#!/usr/bin/env python3
"""Re-derive the PHerc0139 w045/w046 duplicate from pinned public assets."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import numpy as np

from ladder_io import fetch_to_path


S3 = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
W045 = "PHerc0139/segments/20260126000000-w045_2026012619"
W046 = "PHerc0139/segments/20260325000000-w046_20260325"
W044 = "PHerc0139/segments/20260115000000-w044_2026011522"
W047 = "PHerc0139/segments/20260206000001-w047_2026020613"
INK = (
    "ink-detection/downsampled/PHerc0139-{stamp}-2.399um-0.22m-78keV-volume-"
    "20260102150214-20260417190342-new_canon_autoresearch_recipe-"
    "tile256-stride128-ds8.jpg"
)
STAMPS = {
    W044: "20260115000000",
    W045: "20260126000000",
    W046: "20260325000000",
    W047: "20260206000001",
}
DEFAULT_MANIFEST = Path(__file__).with_name("data_manifest.json")


def _manifest(path: os.PathLike[str] | str) -> dict:
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    if value.get("schema_version") != 1:
        raise ValueError(f"unsupported manifest schema in {path}")
    return value


class Assets:
    def __init__(self, work: os.PathLike[str] | str, manifest: dict, offline: bool):
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.specs = manifest["duplicate_check"]["assets"]
        self.offline = offline

    def get(self, key: str) -> Path:
        destination = self.work / key.replace("/", "_")
        spec = self.specs.get(key)
        if spec is None:
            raise KeyError(f"asset is not pinned in the release manifest: {key}")
        result = fetch_to_path(
            f"{S3}/{key}",
            destination,
            timeout=300,
            offline=self.offline,
            expected_sha256=spec["sha256"],
            expected_size=spec["size"],
        )
        assert result is not None
        return result


def imread(path: os.PathLike[str] | str) -> np.ndarray:
    if os.environ.get("LADDER_TIFF_READER", "").lower() != "pil":
        try:
            import tifffile

            return np.asarray(tifffile.imread(path))
        except Exception:
            pass
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    return np.asarray(Image.open(path))


def surface(assets: Assets, segment: str):
    base = f"{segment}/mesh/intermediate/tifxyz_original"
    x, y, z = (
        imread(assets.get(f"{base}/{channel}.tif")).astype(np.float32)
        for channel in "xyz"
    )
    with open(assets.get(f"{base}/meta.json"), encoding="utf-8") as stream:
        meta = json.load(stream)
    valid = (z > 0) & np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    valid &= ~((x == -1) & (y == -1) & (z == -1))
    return np.stack([x, y, z], -1), valid, meta


def ink(assets: Assets, segment: str) -> np.ndarray:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    key = f"{segment}/{INK.format(stamp=STAMPS[segment])}"
    return np.asarray(Image.open(assets.get(key)).convert("L")).astype(np.float32)


def align_corr(a: np.ndarray, b: np.ndarray):
    from numpy.fft import irfft2, rfft2

    height = max(a.shape[0], b.shape[0])
    width = max(a.shape[1], b.shape[1])
    aa = np.zeros((height, width), np.float32)
    bb = np.zeros((height, width), np.float32)
    aa[: a.shape[0], : a.shape[1]] = a - a.mean()
    bb[: b.shape[0], : b.shape[1]] = b - b.mean()
    corr = irfft2(rfft2(bb) * np.conj(rfft2(aa)), s=(height, width))
    row, col = np.unravel_index(np.argmax(corr), corr.shape)
    if row > height // 2:
        row -= height
    if col > width // 2:
        col -= width
    row, col = int(row), int(col)
    ay, by = max(0, row), max(0, -row)
    ax, bx = max(0, col), max(0, -col)
    overlap_h = min(a.shape[0] - ay, b.shape[0] - by)
    overlap_w = min(a.shape[1] - ax, b.shape[1] - bx)
    a2 = a[ay : ay + overlap_h, ax : ax + overlap_w]
    b2 = b[by : by + overlap_h, bx : bx + overlap_w]
    mask = (a2 > 0) & (b2 > 0)
    return (row, col), float(np.corrcoef(a2[mask], b2[mask])[0, 1]), int(mask.sum())


def run(assets: Assets) -> dict:
    from scipy.ndimage import label
    from scipy.spatial import cKDTree

    pa, va, ma = surface(assets, W045)
    pb, vb, mb = surface(assets, W046)
    best = None
    for dy in range(-8, 9):
        for dx in range(-8, 9):
            rows, cols = va.shape
            if not (0 <= dy and dy + rows <= vb.shape[0] and 0 <= dx and dx + cols <= vb.shape[1]):
                continue
            sub = vb[dy : dy + rows, dx : dx + cols]
            common = int((va & sub).sum())
            if best is None or common > best[0]:
                best = (common, dy, dx, sub)
    assert best is not None
    common, dy, dx, sub = best
    qb = pb[dy : dy + va.shape[0], dx : dx + va.shape[1]]
    both = va & sub
    displacement = np.linalg.norm(pa[both] - qb[both], axis=1)
    moved = np.zeros(va.shape, dtype=bool)
    moved[both] = displacement > 0
    components, component_count = label(moved, structure=np.ones((3, 3), dtype=np.uint8))
    component_sizes = np.bincount(components.ravel())[1:]
    rows, cols = np.where(moved)

    points = {}
    for name, segment in (("w044", W044), ("w045", W045), ("w046", W046), ("w047", W047)):
        coords, valid, _ = surface(assets, segment)
        points[name] = coords[valid].astype(np.float64)
    ladder_rows = []
    for a, b in (("w044", "w045"), ("w045", "w046"), ("w046", "w047")):
        distance, _ = cKDTree(points[b]).query(points[a], workers=-1)
        ladder_rows.append(
            {"pair": f"{a}->{b}", "median": float(np.median(distance)), "within_2": float((distance < 2).mean())}
        )

    correlations = []
    for a, sa, b, sb in (
        ("w044", W044, "w045", W045),
        ("w045", W045, "w046", W046),
        ("w046", W046, "w047", W047),
    ):
        shift, coefficient, pixels = align_corr(ink(assets, sa), ink(assets, sb))
        correlations.append(
            {"pair": f"{a}/{b}", "shift": shift, "r": coefficient, "pixels": pixels}
        )

    return {
        "shape_045": va.shape,
        "shape_046": vb.shape,
        "valid_045": int(va.sum()),
        "valid_046": int(vb.sum()),
        "bbox_identical": ma["bbox"] == mb["bbox"],
        "mode": mb.get("vc_gsfs_mode"),
        "neighbor_dir": (mb.get("vc_gsfs_params") or {}).get("neighbor_dir"),
        "max_gen": mb.get("max_gen"),
        "copy_moved_points": mb.get("copy_moved_points"),
        "alignment": (dy, dx),
        "common": common,
        "mask_xor": int((va ^ sub).sum()),
        "bit_identical": int((displacement == 0).sum()),
        "bit_identical_fraction": float((displacement == 0).mean()),
        "displaced": int((displacement > 0).sum()),
        "displaced_median": float(np.median(displacement[displacement > 0])),
        "displaced_max": float(displacement.max()),
        "displaced_components": int(component_count),
        "largest_component": int(component_sizes.max()),
        "displaced_bbox": [int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())],
        "ladder": ladder_rows,
        "correlations": correlations,
    }


def validate_expected(result: dict, expected: dict) -> None:
    """Fail if pinned inputs no longer produce the release headline."""
    tolerance = expected.get("float_tolerance", 1e-9)
    scalar_fields = (
        "shape_045", "shape_046", "valid_045", "valid_046",
        "bbox_identical", "mode", "neighbor_dir", "max_gen",
        "copy_moved_points", "alignment", "common", "mask_xor",
        "bit_identical", "bit_identical_fraction", "displaced",
        "displaced_median", "displaced_components", "largest_component",
        "displaced_bbox",
    )
    for field in scalar_fields:
        wanted = expected[field]
        actual = result[field]
        if isinstance(wanted, float):
            matches = math.isclose(actual, wanted, rel_tol=0, abs_tol=tolerance)
        elif isinstance(wanted, list):
            matches = list(actual) == wanted
        else:
            matches = actual == wanted
        if not matches:
            raise AssertionError(f"{field}: got {actual!r}, expected {wanted!r}")

    for group in ("ladder", "correlations"):
        actual_rows = {row["pair"]: row for row in result[group]}
        for pair, wanted in expected[group].items():
            actual = actual_rows[pair]
            for field, value in wanted.items():
                got = actual[field]
                if isinstance(value, float):
                    matches = math.isclose(got, value, rel_tol=0, abs_tol=tolerance)
                elif isinstance(value, list):
                    matches = list(got) == value
                else:
                    matches = got == value
                if not matches:
                    raise AssertionError(
                        f"{group} {pair} {field}: got {got!r}, expected {value!r}"
                    )


def print_report(result: dict) -> None:
    print("=" * 72)
    print(f"w045 grid {tuple(result['shape_045'])}  valid {result['valid_045']}")
    print(f"w046 grid {tuple(result['shape_046'])}  valid {result['valid_046']}")
    print(f"bbox identical: {result['bbox_identical']}")
    print(
        f"w046 meta: mode={result['mode']} dir={result['neighbor_dir']} "
        f"max_gen={result['max_gen']} copy_moved_points={result['copy_moved_points']}"
    )
    dy, dx = result["alignment"]
    print(
        f"\nbest mask alignment of w045 inside w046: offset ({dy},{dx}), "
        f"cells valid in both = {result['common']}"
    )
    print(f"mask XOR at that offset = {result['mask_xor']}  (0 means the masks are identical)")
    print(f"\nvertices compared: {result['common']}")
    print(
        f"bit-identical in all three channels: {result['bit_identical']} = "
        f"{result['bit_identical_fraction'] * 100:.4f}%"
    )
    print(
        f"displaced: {result['displaced']}   median displacement of those: "
        f"{result['displaced_median']:.3f} vx   max {result['displaced_max']:.2f} vx"
    )
    print(
        f"displaced components (8-connected): {result['displaced_components']}   "
        f"largest {result['largest_component']}   bbox rows/cols {result['displaced_bbox']}"
    )
    print("\nmedian nearest-neighbour distance between consecutive surfaces:")
    for row in result["ladder"]:
        print(
            f"  {row['pair']}: median {row['median']:8.3f} vx    "
            f"fraction within 2 vx: {row['within_2']:.4f}"
        )
    print("\npublished ink detections (2.399 um, model 20260417190342), correlation after alignment:")
    for row in result["correlations"]:
        print(
            f"  {row['pair']}: shift {tuple(row['shift'])}   r = {row['r']:+.3f}   "
            f"over {row['pixels'] / 1e6:.2f} Mpx"
        )
    print("=" * 72)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workdir", nargs="?", default="./check_data")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    manifest = _manifest(args.manifest)
    result = run(Assets(args.workdir, manifest, args.offline))
    validate_expected(result, manifest["duplicate_check"]["expected"])
    print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
