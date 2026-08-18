"""Is there a papyrus sheet in the gap between two traced windings?

Samples the published surface-prediction volume along the straight segment
joining each vertex of one winding to its nearest vertex on another, and asks
whether a distinct predicted sheet lies strictly between them.
"""
import os, json, hashlib, urllib.request, numpy as np, concurrent.futures as cf
from PIL import Image
from scipy.spatial import cKDTree
import numcodecs
Image.MAX_IMAGE_PIXELS = None

S3 = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
VOL = ("PHerc0139/representations/predictions/surfaces/"
       "20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr")
CACHE = "predcache"; os.makedirs(CACHE, exist_ok=True)
ZA = json.loads(urllib.request.urlopen(f"{S3}/{VOL}/0/.zarray", timeout=60).read())
SHAPE = tuple(ZA["shape"]); CH = tuple(ZA["chunks"])
CODEC = numcodecs.get_codec(ZA["compressor"])

def get_chunk(cz, cy, cx):
    key = f"{cz}/{cy}/{cx}"
    f = os.path.join(CACHE, hashlib.sha1(key.encode()).hexdigest())
    if os.path.exists(f):
        raw = open(f, "rb").read()
    else:
        try:
            raw = urllib.request.urlopen(f"{S3}/{VOL}/0/{key}", timeout=180).read()
        except Exception:
            raw = b""
        open(f, "wb").write(raw)
    if not raw:
        return np.zeros(CH, np.uint8)          # fill_value 0 = absent chunk
    return np.frombuffer(CODEC.decode(raw), np.uint8).reshape(CH)

def sample(points):
    """points: (N,3) in (z,y,x) voxel coords. Nearest-voxel sampling."""
    p = np.rint(points).astype(np.int64)
    ok = np.all((p >= 0) & (p < np.array(SHAPE)), axis=1)
    out = np.zeros(len(p), np.uint8)
    idx = np.where(ok)[0]
    if not len(idx): return out, ok
    c = p[idx] // np.array(CH)
    keys = [tuple(v) for v in c]
    uniq = sorted(set(keys))
    with cf.ThreadPoolExecutor(12) as ex:
        chunks = dict(zip(uniq, ex.map(lambda k: get_chunk(*k), uniq)))
    loc = p[idx] % np.array(CH)
    for n, i in enumerate(idx):
        out[i] = chunks[keys[n]][loc[n, 0], loc[n, 1], loc[n, 2]]
    return out, ok

def load(w):
    d = f"frame9362/w{w:03d}"
    x, y, z = (np.asarray(Image.open(f"{d}/{c}.tif")).astype(np.float32) for c in "xyz")
    v = (z > 0) & np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    v &= ~((x == -1) & (y == -1) & (z == -1))
    return np.stack([z, y, x], -1)[v].astype(np.float64)     # (z,y,x) order

def ray_profiles(A, B, n_rays=400, n_samples=65, zlo=None, zhi=None, seed=0):
    """For a sample of A's vertices, the prediction profile along the straight
    segment to the nearest vertex of B."""
    rng = np.random.default_rng(seed)
    if zlo is not None:
        A = A[(A[:, 0] >= zlo) & (A[:, 0] <= zhi)]
    tree = cKDTree(B)
    d, j = tree.query(A, workers=-1)
    keep = np.where(np.isfinite(d))[0]
    sel = rng.choice(keep, min(n_rays, len(keep)), replace=False)
    a = A[sel]; b = B[j[sel]]; dist = d[sel]
    u = np.linspace(0, 1, n_samples)
    pts = a[:, None, :] + (b - a)[:, None, :] * u[None, :, None]
    vals, ok = sample(pts.reshape(-1, 3))
    return vals.reshape(len(sel), n_samples).astype(np.float32), dist, u

def intervening(prof, u, hi=128, lo=64, edge=0.15):
    """A distinct sheet strictly between the endpoints: some interior sample
    above `hi`, separated from BOTH endpoints by a sample below `lo`."""
    n = prof.shape[1]
    inner = (u > edge) & (u < 1 - edge)
    out = np.zeros(len(prof), bool); pos = np.full(len(prof), np.nan)
    for k, p in enumerate(prof):
        cand = np.where(inner & (p > hi))[0]
        for c in cand:
            if p[:c].min() < lo and p[c + 1:].min() < lo:
                out[k] = True; pos[k] = u[c]; break
    return out, pos
