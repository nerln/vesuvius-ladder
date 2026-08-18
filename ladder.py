#!/usr/bin/env python3
"""
ladder — find traced surfaces that occupy the same papyrus.

Two traced surfaces from one scroll may share an edge, may lie on neighbouring
wraps, or may be the same physical sheet published twice.  The last case is a
defect: it duplicates text and hides a wrap that was never traced.  It is
invisible in any single segment and only shows up when the segments are held
together.

The check is scale-free.  Within one scroll the median nearest-neighbour
distance between two surfaces that share support is, for genuinely distinct
wraps, on the order of the local sheet spacing.  `ladder` measures that
distance for every pair, takes the scroll's own median over pairs as the unit,
and reports pairs that come in far below it.  No absolute threshold in voxels
is needed and none is used for the verdict.

Input is the public open-data bucket (anonymous) or a local directory of
tifxyz surfaces.  Nothing but geometry is read: no volume, no model, no GPU.

  python3 ladder.py scan --sample PHerc0139
  python3 ladder.py scan --dir /path/to/tifxyz_dirs
  python3 ladder.py scan --sample PHerc0139 --json out.json --collection dup.json
"""
import argparse, json, os, re, sys, urllib.request, gzip, io, hashlib
import concurrent.futures as cf
import numpy as np

S3 = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
CATALOG = f"{S3}/metadata.json"

# ---------------------------------------------------------------- data access

def _fetch(url, timeout=180):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()

def load_catalog(cache=None):
    if cache and os.path.exists(cache):
        raw = open(cache, "rb").read()
    else:
        raw = _fetch(CATALOG)
        if cache:
            open(cache, "wb").write(raw)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)

def catalog_surfaces(cat, sample):
    """[(segment_long_id, s3 prefix of a tifxyz dir)] for one sample."""
    out = []
    segs = cat["samples"][sample]["segments"]
    for _, seg in segs.items():
        for item in (seg.get("data") or []):
            if item["type"] == "tifxyz":
                out.append((seg["long_id"], item["origins"][0]["path"]))
                break
    return sorted(out)

def download_tifxyz(prefix, dest, timeout=300):
    os.makedirs(dest, exist_ok=True)
    for f in ("meta.json", "x.tif", "y.tif", "z.tif"):
        p = os.path.join(dest, f)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            continue
        try:
            open(p, "wb").write(_fetch(f"{S3}/{prefix}{f}", timeout))
        except Exception:
            if os.path.exists(p):
                os.remove(p)
            if f != "meta.json":
                raise
    return dest

# ---------------------------------------------------------------- tifxyz read

def _imread(path):
    """Read one coordinate plane.

    tifffile is the natural reader, but some imagecodecs builds *segfault* on
    these LZW float32 TIFFs — and a segfault is not an exception, so no
    try/except can rescue it.  Set LADDER_TIFF_READER=pil to use Pillow, which
    decodes them correctly, if the process dies while loading.
    """
    if os.environ.get("LADDER_TIFF_READER", "").lower() == "pil":
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        return np.asarray(Image.open(path))
    try:
        import tifffile
        return np.asarray(tifffile.imread(path))
    except Exception:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        return np.asarray(Image.open(path))


def read_tifxyz(d):
    x = _imread(os.path.join(d, "x.tif")).astype(np.float32)
    y = _imread(os.path.join(d, "y.tif")).astype(np.float32)
    z = _imread(os.path.join(d, "z.tif")).astype(np.float32)
    # villa's own rule: a cell is invalid when z <= 0, or any channel is
    # non-finite, or all three are exactly -1 (QuadSurface.cpp).
    valid = (z > 0) & np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    valid &= ~((x == -1) & (y == -1) & (z == -1))
    P = np.stack([x, y, z], -1)
    meta = {}
    mp = os.path.join(d, "meta.json")
    if os.path.exists(mp):
        try:
            meta = json.load(open(mp))
        except Exception:
            pass
    return P, valid, meta

# ---------------------------------------------------------------- the measure

TAUS = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0)

def pair_stats(A, treeB, radius):
    """A: (N,3) points of surface A. treeB: cKDTree over surface B.

    Returns the coverage (what fraction of A has any B vertex within the
    support window), the median nearest-neighbour distance over that support,
    and the fraction of ALL of A's vertices within each radius in TAUS.  The
    fractions are over all of A, not over the support, so they are comparable
    across pairs with different coverage."""
    dist, _ = treeB.query(A, distance_upper_bound=radius, workers=-1)
    sup = np.isfinite(dist)
    n = int(sup.sum())
    if n == 0:
        return dict(cover=0.0, n_support=0, d_med=None, taus={})
    d = dist[sup]
    return dict(cover=float(n) / len(A), n_support=n,
                d_med=float(np.median(d)),
                taus={str(t): float((dist < t).mean()) for t in TAUS})


def coincident_fraction(row, radius):
    """Fraction of A's vertices within `radius` of B, interpolated from the
    tabulated radii."""
    if not row.get("taus"):
        return 0.0
    xs = np.array([float(k) for k in row["taus"]])
    o = np.argsort(xs); xs = xs[o]
    ys = np.array([row["taus"][k] for k in row["taus"]])[o]
    return float(np.interp(radius, xs, ys))

def scan(dirs, names, max_query=20000, radius=None, seed=0):
    """Trees are built on the FULL vertex set of each surface; only the query
    side is subsampled.  Subsampling the tree side would inflate every
    nearest-neighbour distance and is the one shortcut that would bias the
    verdict."""
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    full, query, spacing = {}, {}, {}
    for n, d in zip(names, dirs):
        P, v, meta = read_tifxyz(d)
        p = P[v].astype(np.float64)
        full[n] = p
        sc = meta.get("scale")
        spacing[n] = (1.0 / sc[0]) if sc else 20.0
        query[n] = p if len(p) <= max_query else p[rng.choice(len(p), max_query, replace=False)]
    step = float(np.median(list(spacing.values())))
    if radius is None:
        radius = 20 * step          # only sets the shared-support window
    # One tree at a time: full point sets are large (a scroll-scale corpus can
    # be tens of millions of vertices) and holding every tree at once is what
    # makes this run out of memory on a laptop.
    rows = []
    for b in names:
        tree = cKDTree(full[b])
        for a in names:
            if a == b:
                continue
            st = pair_stats(query[a], tree, radius)
            st.update(A=a, B=b, nQ=len(query[a]), nA_full=len(full[a]), nB_full=len(full[b]))
            rows.append(st)
        del tree
    return rows, step, radius


def classify(rows, min_cover=0.02, dup_frac=0.5, coin_ratio=0.1):
    """Self-calibrating verdict.

    For each surface, its closest companion surface (smallest median
    nearest-neighbour distance over shared support) is a sample of the local
    sheet spacing: the nearest other traced surface in a scroll is, normally,
    the neighbouring wrap.  The median of those per-surface minima is the unit.

    A pair is called a duplicate when more than `dup_frac` of one surface's
    vertices lie within `coin_ratio` of that unit of the other surface —
    "over half of this sheet is sitting on top of that one, a tenth of a sheet
    spacing away".  Both directions are considered; the verdict is symmetric.

    The median-distance ratio is reported too, but it is a diagnostic: it is
    diluted by whatever part of the surfaces do not coincide, so it separates
    duplicates from near-misses less sharply than the coincident fraction.
    """
    have = [r for r in rows if r["d_med"] is not None and r["cover"] >= min_cover]
    if not have:
        for r in rows:
            r["verdict"] = "no-shared-support"; r["ratio"] = None
            r["unit"] = None; r["coincident"] = None
        return rows, None
    per_surface_min = {}
    for r in have:
        cur = per_surface_min.get(r["A"])
        if cur is None or r["d_med"] < cur:
            per_surface_min[r["A"]] = r["d_med"]
    unit = float(np.median(list(per_surface_min.values())))
    coin_r = max(1.0, coin_ratio * unit)
    for r in rows:
        r["unit"] = unit; r["coin_radius"] = coin_r
        r["ratio"] = (r["d_med"] / unit) if (r["d_med"] is not None and unit > 0) else None
        r["coincident"] = coincident_fraction(r, coin_r)
    # symmetric verdict: a pair is a duplicate if either direction qualifies
    bykey = {}
    for r in rows:
        bykey.setdefault(tuple(sorted((r["A"], r["B"]))), []).append(r)
    for key, pair in bykey.items():
        dup = any(x["cover"] >= min_cover and x["coincident"] > dup_frac for x in pair)
        for x in pair:
            if x["d_med"] is None or x["cover"] < min_cover:
                x["verdict"] = "DUPLICATE" if dup else "no-shared-support"
            else:
                x["verdict"] = "DUPLICATE" if dup else "distinct"
    return rows, unit


# ---------------------------------------------------------------- winding ladder

WRE = re.compile(r"[-_]w(\d{2,3})(?:[-_]|$)")

def winding_of(name):
    m = WRE.search(name)
    return int(m.group(1)) if m else None

def ladder_report(rows, names):
    """When segment names carry winding numbers, check that consecutive
    windings are one step apart on the ladder."""
    w = {n: winding_of(n) for n in names}
    idx = {(r["A"], r["B"]): r for r in rows}
    known = sorted([n for n in names if w[n] is not None], key=lambda n: w[n])
    out = []
    for a, b in zip(known, known[1:]):
        if w[b] - w[a] != 1:
            continue
        r = idx.get((a, b))
        if r is None:
            continue
        out.append(dict(w_from=w[a], w_to=w[b], A=a, B=b,
                        d_med=r["d_med"], ratio=r["ratio"],
                        coincident=r["coincident"],
                        cover=r["cover"], verdict=r["verdict"]))
    return out

def duplicate_sites(dirs, names, dups, tau=2.0, max_sites=2000, seed=0):
    """3-D positions where two surfaces coincide, for inspection in VC3D."""
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    byname = dict(zip(names, dirs))
    sites, seen = [], set()
    for r in dups:
        key = tuple(sorted((r["A"], r["B"])))
        if key in seen:
            continue
        seen.add(key)
        PA, vA, _ = read_tifxyz(byname[r["A"]]); a = PA[vA].astype(np.float64)
        PB, vB, _ = read_tifxyz(byname[r["B"]]); b = PB[vB].astype(np.float64)
        d, _ = cKDTree(b).query(a, distance_upper_bound=tau, workers=-1)
        hit = a[np.isfinite(d)]
        if len(hit) > max_sites:
            hit = hit[rng.choice(len(hit), max_sites, replace=False)]
        sites.append((key, hit))
    return sites


def write_collection(path, sites):
    """VC3D point-collection JSON (PointCollections::saveToJSON, version "1")."""
    cols, cid = {}, 1
    for (a, b), pts in sites:
        points = {str(i + 1): {"p": [float(v) for v in p],
                               "creation_time": 0, "wind_a": None}
                  for i, p in enumerate(pts)}
        cols[str(cid)] = {"name": f"duplicate {a} == {b}"[:120],
                          "points": points,
                          "metadata": {"winding_is_absolute": True},
                          "color": [1.0, 0.1, 0.1]}
        cid += 1
    json.dump({"vc_pointcollections_json_version": "1", "collections": cols},
              open(path, "w"), indent=4)


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--sample", help="catalog sample id, e.g. PHerc0139")
    s.add_argument("--dir", help="local directory containing tifxyz subdirectories")
    s.add_argument("--work", default="./ladder_data", help="download cache")
    s.add_argument("--json", help="write the full pair table here")
    s.add_argument("--collection", help="write duplicate sites as a VC3D point collection")
    s.add_argument("--max-query", type=int, default=20000)
    s.add_argument("--dup-frac", type=float, default=0.5,
                   help="coincident-fraction threshold for the duplicate verdict")
    s.add_argument("--min-cover", type=float, default=0.02)
    s.add_argument("--catalog-cache", default="./metadata.json")
    a = ap.parse_args()

    if a.cmd == "scan":
        if a.dir:
            names, dirs = [], []
            for e in sorted(os.listdir(a.dir)):
                d = os.path.join(a.dir, e)
                if os.path.isdir(d) and os.path.exists(os.path.join(d, "x.tif")):
                    names.append(e); dirs.append(d)
        else:
            if not a.sample:
                ap.error("give --sample or --dir")
            cat = load_catalog(a.catalog_cache)
            surf = catalog_surfaces(cat, a.sample)
            print(f"{a.sample}: {len(surf)} published tifxyz surfaces", file=sys.stderr)
            root = os.path.join(a.work, a.sample)
            names, dirs = [], []
            with cf.ThreadPoolExecutor(8) as ex:
                futs = {ex.submit(download_tifxyz, pre, os.path.join(root, lid)): lid
                        for lid, pre in surf}
                for f in cf.as_completed(futs):
                    lid = futs[f]
                    try:
                        f.result(); names.append(lid); dirs.append(os.path.join(root, lid))
                    except Exception as e:
                        print(f"  skip {lid}: {e}", file=sys.stderr)
            order = np.argsort(names)
            names = [names[i] for i in order]; dirs = [dirs[i] for i in order]

        if len(names) < 2:
            print("need at least two surfaces", file=sys.stderr); return 1
        rows, step, radius = scan(dirs, names, max_query=a.max_query)
        rows, unit = classify(rows, a.min_cover, a.dup_frac)
        lad = ladder_report(rows, names)

        print(f"\nsurfaces: {len(names)}   nominal grid step: {step:.1f} vx")
        if unit:
            print(f"sheet-spacing unit (median over surfaces of the distance to their nearest companion surface): {unit:.2f} vx")
        if lad:
            print(f"\nwinding ladder ({len(lad)} consecutive pairs)")
            print(f"{'pair':>12} {'d_med(vx)':>10} {'ratio':>7} {'coincid.':>9} {'cover':>7}  verdict")
            for L in lad:
                mark = "  <<<<" if L["verdict"] == "DUPLICATE" else ""
                print(f"  w{L['w_from']:03d}-w{L['w_to']:03d} {L['d_med']:10.2f} "
                      f"{L['ratio']:7.3f} {L['coincident']:9.3f} {L['cover']:7.3f}  "
                      f"{L['verdict']}{mark}")
        dups = sorted([r for r in rows if r["verdict"] == "DUPLICATE"],
                      key=lambda r: -(r["coincident"] or 0))
        seen, uniq = set(), []
        for r in dups:
            k = tuple(sorted((r["A"], r["B"])))
            if k in seen:
                continue
            seen.add(k); uniq.append(r)
        print(f"\nduplicate pairs: {len(uniq)}"
              f"   (coincident fraction > {a.dup_frac} within {rows[0].get('coin_radius', 0):.2f} vx)")
        for r in uniq:
            print(f"  coincident={r['coincident']:.3f}  d_med={r['d_med']:.2f}vx  "
                  f"ratio={r['ratio']:.3f}  cover={r['cover']:.3f}"
                  f"   {r['A']}  ==  {r['B']}")
        near = sorted([r for r in rows if r["verdict"] == "distinct"],
                      key=lambda r: -(r["coincident"] or 0))[:1]
        for r in near:
            print(f"\nclosest non-duplicate pair: coincident={r['coincident']:.3f} "
                  f"d_med={r['d_med']:.2f}vx ratio={r['ratio']:.3f}"
                  f"   {r['A']}  ==  {r['B']}")
        if a.collection and dups:
            sites = duplicate_sites(dirs, names, uniq)
            write_collection(a.collection, sites)
            print(f"wrote {a.collection} ({sum(len(p) for _, p in sites)} sites)")
        if a.json:
            json.dump(dict(sample=a.sample, names=names, unit=unit, step=step,
                           radius=radius, pairs=rows, ladder=lad),
                      open(a.json, "w"), indent=1)
            print(f"\nwrote {a.json}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
