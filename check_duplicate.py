#!/usr/bin/env python3
"""
check_duplicate.py — the PHerc0139 w045/w046 finding, re-derived from scratch.

Downloads the two surfaces and the two ink maps from the public bucket and
prints every number quoted in README.md.  Nothing is read from disk that this
script did not fetch.  ~60 MB of download, about a minute.

    python3 check_duplicate.py [workdir]
"""
import io, json, os, sys, urllib.request
import numpy as np

S3 = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
W045 = "PHerc0139/segments/20260126000000-w045_2026012619"
W046 = "PHerc0139/segments/20260325000000-w046_20260325"
W044 = "PHerc0139/segments/20260115000000-w044_2026011522"
W047 = "PHerc0139/segments/20260206000001-w047_2026020613"
INK = ("ink-detection/downsampled/PHerc0139-{stamp}-2.399um-0.22m-78keV-volume-"
       "20260102150214-20260417190342-new_canon_autoresearch_recipe-tile256-stride128-ds8.jpg")
STAMPS = {W044: "20260115000000", W045: "20260126000000",
          W046: "20260325000000", W047: "20260206000001"}

work = sys.argv[1] if len(sys.argv) > 1 else "./check_data"
os.makedirs(work, exist_ok=True)

def get(key):
    dest = os.path.join(work, key.replace("/", "_"))
    if not (os.path.exists(dest) and os.path.getsize(dest)):
        with urllib.request.urlopen(f"{S3}/{key}", timeout=300) as r:
            open(dest, "wb").write(r.read())
    return dest

def imread(p):
    try:
        import tifffile
        return np.asarray(tifffile.imread(p))
    except Exception:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        return np.asarray(Image.open(p))

def surface(seg):
    base = f"{seg}/mesh/intermediate/tifxyz_original"
    x, y, z = (imread(get(f"{base}/{c}.tif")).astype(np.float32) for c in "xyz")
    meta = json.load(open(get(f"{base}/meta.json")))
    valid = (z > 0) & np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    valid &= ~((x == -1) & (y == -1) & (z == -1))
    return np.stack([x, y, z], -1), valid, meta

print("=" * 72)
PA, vA, mA = surface(W045)
PB, vB, mB = surface(W046)
print(f"w045 grid {vA.shape}  valid {int(vA.sum())}")
print(f"w046 grid {vB.shape}  valid {int(vB.sum())}")
print(f"bbox identical: {mA['bbox'] == mB['bbox']}")
print(f"w046 meta: mode={mB.get('vc_gsfs_mode')} "
      f"dir={(mB.get('vc_gsfs_params') or {}).get('neighbor_dir')} "
      f"max_gen={mB.get('max_gen')} copy_moved_points={mB.get('copy_moved_points')}")

# w046's grid is w045's padded by 4 on each side; verify by exhaustive search
best = None
for dy in range(-8, 9):
    for dx in range(-8, 9):
        ys, xs = vA.shape
        if not (0 <= dy and dy + ys <= vB.shape[0] and 0 <= dx and dx + xs <= vB.shape[1]):
            continue
        sub = vB[dy:dy + ys, dx:dx + xs]
        n = int((vA & sub).sum())
        if best is None or n > best[0]:
            best = (n, dy, dx, sub)
n, dy, dx, sub = best
print(f"\nbest mask alignment of w045 inside w046: offset ({dy},{dx}), "
      f"cells valid in both = {n}")
print(f"mask XOR at that offset = {int((vA ^ sub).sum())}  (0 means the masks are identical)")

QB = PB[dy:dy + vA.shape[0], dx:dx + vA.shape[1]]
both = vA & sub
d = np.linalg.norm(PA[both] - QB[both], axis=1)
print(f"\nvertices compared: {both.sum()}")
print(f"bit-identical in all three channels: {int((d == 0).sum())} = {(d == 0).mean() * 100:.4f}%")
print(f"displaced: {int((d > 0).sum())}   median displacement of those: "
      f"{np.median(d[d > 0]):.3f} vx   max {d.max():.2f} vx")

# nearest-neighbour ladder, w044..w047
from scipy.spatial import cKDTree
pts = {}
for name, seg in (("w044", W044), ("w045", W045), ("w046", W046), ("w047", W047)):
    P, v, _ = surface(seg)
    pts[name] = P[v].astype(np.float64)
print("\nmedian nearest-neighbour distance between consecutive surfaces:")
for a, b in (("w044", "w045"), ("w045", "w046"), ("w046", "w047")):
    dist, _ = cKDTree(pts[b]).query(pts[a], workers=-1)
    print(f"  {a} -> {b}: median {np.median(dist):8.3f} vx    "
          f"fraction within 2 vx: {(dist < 2).mean():.4f}")

# ink maps
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
from numpy.fft import rfft2, irfft2
def ink(seg):
    return np.asarray(Image.open(get(f"{seg}/{INK.format(stamp=STAMPS[seg])}")).convert("L")).astype(np.float32)
def align_corr(a, b):
    H, W = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    A = np.zeros((H, W), np.float32); B = np.zeros((H, W), np.float32)
    A[:a.shape[0], :a.shape[1]] = a - a.mean(); B[:b.shape[0], :b.shape[1]] = b - b.mean()
    C = irfft2(rfft2(B) * np.conj(rfft2(A)), s=(H, W))
    i, j = np.unravel_index(np.argmax(C), C.shape)
    if i > H // 2: i -= H
    i = int(i); j = int(j)
    if j > W // 2: j -= W
    ay, by = max(0, i), max(0, -i); ax, bx = max(0, j), max(0, -j)
    h = min(a.shape[0] - ay, b.shape[0] - by); w = min(a.shape[1] - ax, b.shape[1] - bx)
    a2 = a[ay:ay + h, ax:ax + w]; b2 = b[by:by + h, bx:bx + w]
    m = (a2 > 0) & (b2 > 0)
    return (i, j), float(np.corrcoef(a2[m], b2[m])[0, 1]), int(m.sum())
print("\npublished ink detections (2.399 um, model 20260417190342), correlation after alignment:")
for na, sa, nb, sb in (("w044", W044, "w045", W045), ("w045", W045, "w046", W046), ("w046", W046, "w047", W047)):

    sh, r, npx = align_corr(ink(sa), ink(sb))
    print(f"  {na} vs {nb}: shift {sh}   r = {r:+.3f}   over {npx/1e6:.2f} Mpx")
print("=" * 72)
