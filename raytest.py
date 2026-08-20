#!/usr/bin/env python3
"""End-to-end, manifest-pinned surface-prediction ray experiment.

The command downloads five PHerc0139 meshes in the surface-prediction frame,
samples the pinned public Zarr, writes a machine-readable result/snapshot, and
renders the figure used in the evidence report.  A 404 means an absent Zarr
chunk and therefore the declared fill value; timeouts, 5xx responses, corrupt
cache entries, and decode failures are fatal.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

from ladder_io import (
    DownloadError,
    IntegrityError,
    cache_path,
    canonical_json_sha256,
    fetch_bytes,
    fetch_cached,
    fetch_to_path,
    read_validated,
    sha256_bytes,
    sha256_file,
    write_json_atomic,
)


S3 = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
DEFAULT_MANIFEST = Path(__file__).with_name("data_manifest.json")


def load_manifest(path: os.PathLike[str] | str) -> dict:
    with open(path, encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("schema_version") != 1:
        raise ValueError(f"unsupported manifest schema in {path}")
    experiment = manifest.get("ray_experiment")
    if not isinstance(experiment, dict):
        raise ValueError("manifest has no ray_experiment")
    zarr = experiment.get("zarr")
    if canonical_json_sha256(zarr["metadata"]) != zarr["metadata_sha256"]:
        raise IntegrityError("manifest Zarr metadata digest is internally inconsistent")
    if not experiment.get("meshes") or not experiment.get("pairs"):
        raise ValueError("manifest ray experiment has no meshes or pairs")
    return manifest


def _verify_live_zarray(experiment: dict, *, offline: bool) -> None:
    if offline:
        return
    zarr = experiment["zarr"]
    url = f"{S3}/{zarr['path'].rstrip('/')}/{zarr['level']}/.zarray"
    raw = fetch_bytes(url, timeout=60)
    assert raw is not None
    try:
        live = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"invalid live .zarray at {url}: {exc}") from exc
    if canonical_json_sha256(live) != zarr["metadata_sha256"]:
        raise IntegrityError(
            "the public Zarr metadata no longer matches data_manifest.json; "
            "make a reviewed snapshot update instead of silently continuing"
        )


def materialize_meshes(
    experiment: dict,
    work: os.PathLike[str] | str,
    *,
    offline: bool,
    mesh_dir: os.PathLike[str] | str | None = None,
) -> tuple[dict[int, Path], list[dict[str, Any]]]:
    root = Path(mesh_dir) if mesh_dir else Path(work) / "meshes"
    result: dict[int, Path] = {}
    observed = []
    for winding_text, mesh in sorted(experiment["meshes"].items()):
        winding = int(winding_text)
        destination = root / f"w{winding:03d}"
        destination.mkdir(parents=True, exist_ok=True)
        for filename, spec in mesh["files"].items():
            local = destination / filename
            if mesh_dir:
                read_validated(
                    local,
                    expected_sha256=spec["sha256"],
                    expected_size=spec["size"],
                )
            else:
                fetched = fetch_to_path(
                    f"{S3}/{mesh['path'].rstrip('/')}/{filename}",
                    local,
                    timeout=300,
                    offline=offline,
                    expected_sha256=spec["sha256"],
                    expected_size=spec["size"],
                )
                assert fetched is not None
            observed.append(
                {
                    "winding": winding,
                    "file": filename,
                    "size": local.stat().st_size,
                    "sha256": sha256_file(local),
                    "source": f"{mesh['path'].rstrip('/')}/{filename}",
                }
            )
        result[winding] = destination
    return result, observed


def load_mesh(path: os.PathLike[str] | str) -> np.ndarray:
    Image.MAX_IMAGE_PIXELS = None
    directory = Path(path)
    x, y, z = (
        np.asarray(Image.open(directory / f"{channel}.tif"), dtype=np.float32)
        for channel in "xyz"
    )
    valid = (z > 0) & np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    valid &= ~((x == -1) & (y == -1) & (z == -1))
    # Prediction arrays and ray coordinates are both indexed (z, y, x).
    return np.stack([z, y, x], -1)[valid].astype(np.float64)


def chunk_snapshot(path: os.PathLike[str] | str | None) -> dict[str, dict]:
    if path is None or not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    return {row["key"]: row for row in value.get("inputs", {}).get("chunks", [])}


class VolumeReader:
    def __init__(
        self,
        zarr: dict,
        cache_dir: os.PathLike[str] | str,
        *,
        offline: bool = False,
        expected_chunks: dict[str, dict] | None = None,
        legacy_cache: os.PathLike[str] | str | None = None,
        workers: int = 12,
    ):
        import numcodecs

        self.path = zarr["path"].rstrip("/")
        self.level = str(zarr["level"])
        self.metadata = zarr["metadata"]
        self.shape = tuple(self.metadata["shape"])
        self.chunks = tuple(self.metadata["chunks"])
        self.dtype = np.dtype(self.metadata["dtype"])
        self.fill_value = self.metadata.get("fill_value", 0)
        compressor = self.metadata.get("compressor")
        self.codec = numcodecs.get_codec(compressor) if compressor is not None else None
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.expected_chunks = expected_chunks or {}
        self.legacy_cache = Path(legacy_cache) if legacy_cache else None
        self.workers = workers
        self.observed: dict[str, dict[str, Any]] = {}

    def _key(self, index: tuple[int, int, int]) -> str:
        return "/".join(str(int(value)) for value in index)

    def _url(self, key: str) -> str:
        return f"{S3}/{self.path}/{self.level}/{key}"

    def _decode(self, raw: bytes, key: str) -> np.ndarray:
        try:
            decoded = self.codec.decode(raw) if self.codec is not None else raw
            array = np.frombuffer(decoded, dtype=self.dtype)
            expected = math.prod(self.chunks)
            if array.size != expected:
                raise IntegrityError(
                    f"decoded Zarr chunk {key} has {array.size} values, expected {expected}"
                )
            return array.reshape(self.chunks, order=self.metadata.get("order", "C"))
        except IntegrityError:
            raise
        except Exception as exc:
            raise IntegrityError(f"cannot decode Zarr chunk {key}: {exc}") from exc

    def _legacy_bytes(self, key: str) -> bytes | None:
        if self.legacy_cache is None:
            return None
        path = self.legacy_cache / hashlib.sha1(key.encode()).hexdigest()
        if not path.exists():
            return None
        raw = path.read_bytes()
        if not raw:
            raise IntegrityError(f"legacy cache contains an ambiguous empty chunk for {key}")
        return raw

    def get_chunk(self, index: tuple[int, int, int]) -> np.ndarray:
        key = self._key(index)
        url = self._url(key)
        expected = self.expected_chunks.get(key, {})
        raw = self._legacy_bytes(key)
        missing = False
        if raw is None:
            path = fetch_cached(
                url,
                self.cache_dir,
                timeout=180,
                offline=self.offline,
                allow_404=True,
                expected_sha256=expected.get("sha256"),
                expected_size=expected.get("size"),
            )
            if path is None:
                if expected and not expected.get("missing", False):
                    raise IntegrityError(f"snapshot expected a present chunk, but {key} is now 404")
                raw = None
                missing = True
            else:
                raw = Path(path).read_bytes()
        if raw is None:
            chunk = np.full(self.chunks, self.fill_value, dtype=self.dtype)
            digest = None
            size = 0
        else:
            digest = sha256_bytes(raw)
            size = len(raw)
            if expected.get("sha256") and digest != expected["sha256"]:
                raise IntegrityError(f"chunk {key} differs from the reference snapshot")
            chunk = self._decode(raw, key)
        self.observed[key] = {
            "key": key,
            "url": url,
            "missing": missing,
            "size": size,
            "sha256": digest,
        }
        return chunk

    def sample(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rounded = np.rint(points).astype(np.int64)
        valid = np.all((rounded >= 0) & (rounded < np.asarray(self.shape)), axis=1)
        output = np.full(len(rounded), self.fill_value, self.dtype)
        indices = np.where(valid)[0]
        if not len(indices):
            return output, valid
        chunk_indices = rounded[indices] // np.asarray(self.chunks)
        keys = [tuple(int(x) for x in row) for row in chunk_indices]
        unique = sorted(set(keys))
        with cf.ThreadPoolExecutor(self.workers) as executor:
            chunks = dict(zip(unique, executor.map(self.get_chunk, unique)))
        local = rounded[indices] % np.asarray(self.chunks)
        grouped: dict[tuple[int, int, int], list[int]] = {}
        for position, key in enumerate(keys):
            grouped.setdefault(key, []).append(position)
        for key, positions in grouped.items():
            pos = np.asarray(positions)
            coords = local[pos]
            output[indices[pos]] = chunks[key][coords[:, 0], coords[:, 1], coords[:, 2]]
        return output, valid


def ray_profiles(
    surface_a: np.ndarray,
    surface_b: np.ndarray,
    reader: VolumeReader,
    *,
    n_rays: int = 400,
    n_samples: int = 65,
    zlo: float | None = None,
    zhi: float | None = None,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    a = surface_a
    if zlo is not None:
        a = a[(a[:, 0] >= zlo) & (a[:, 0] <= zhi)]
    if not len(a):
        raise ValueError("no source vertices remain after the z-band filter")
    distance, neighbor = cKDTree(surface_b).query(a, workers=-1)
    available = np.where(np.isfinite(distance))[0]
    selected = rng.choice(available, min(n_rays, len(available)), replace=False)
    start = a[selected]
    end = surface_b[neighbor[selected]]
    distance = distance[selected]
    position = np.linspace(0, 1, n_samples)
    points = start[:, None, :] + (end - start)[:, None, :] * position[None, :, None]
    values, valid = reader.sample(points.reshape(-1, 3))
    if not valid.all():
        raise ValueError("a ray left the declared prediction volume")
    return values.reshape(len(selected), n_samples).astype(np.float32), distance


def intervening(
    profiles: np.ndarray,
    *,
    hi: float = 128,
    lo: float = 64,
    edge: float = 0.15,
) -> np.ndarray:
    """Classify a distinct model-predicted surface strictly inside each ray."""
    positions = np.linspace(0, 1, profiles.shape[1])
    interior = (positions > edge) & (positions < 1 - edge)
    result = np.zeros(len(profiles), bool)
    for row_index, profile in enumerate(profiles):
        for candidate in np.where(interior & (profile > hi))[0]:
            if profile[:candidate].min() < lo and profile[candidate + 1 :].min() < lo:
                result[row_index] = True
                break
    return result


def summarize_pair(
    name: str,
    label: str,
    profiles: np.ndarray,
    distances: np.ndarray,
    config: dict,
) -> dict[str, Any]:
    detected = intervening(
        profiles,
        hi=config["high_threshold"],
        lo=config["low_threshold"],
        edge=config["edge_fraction"],
    )
    low, high = config["length_match"]
    matched = (distances >= low) & (distances <= high)
    return {
        "name": name,
        "label": label,
        "n": int(len(distances)),
        "median_length": float(np.median(distances)),
        "interior_count": int(detected.sum()),
        "interior_rate": float(detected.mean()),
        "matched_range": [low, high],
        "matched_n": int(matched.sum()),
        "matched_count": int(detected[matched].sum()),
        "matched_rate": float(detected[matched].mean()) if matched.any() else None,
    }


def frame_check(
    surface: np.ndarray,
    reader: VolumeReader,
    config: dict,
) -> dict[str, Any]:
    points = surface[
        (surface[:, 0] >= config["z_band"][0])
        & (surface[:, 0] <= config["z_band"][1])
    ]
    rng = np.random.default_rng(config["seed"])
    selected = points[rng.choice(len(points), min(config["n_rays"], len(points)), replace=False)]
    own, valid = reader.sample(selected)
    if not valid.all():
        raise ValueError("frame-check surface vertices leave the prediction volume")
    direction_rng = np.random.default_rng(config["seed"] + 7919)
    directions = direction_rng.normal(size=selected.shape)
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    displaced, displaced_valid = reader.sample(selected + 200 * directions)
    return {
        "n": int(len(selected)),
        "own_median": float(np.median(own)),
        "own_above_128": float((own > 128).mean()),
        "displaced_valid_n": int(displaced_valid.sum()),
        "displaced_median": float(np.median(displaced[displaced_valid])),
        "displaced_above_128": float((displaced[displaced_valid] > 128).mean()),
    }


def validate_expected(result: dict, expected: dict) -> None:
    rows = {row["name"]: row for row in result["pairs"]}
    tolerance = expected.get("rate_tolerance", 1e-12)
    for name, wanted in expected.get("pairs", {}).items():
        actual = rows[name]
        for field in ("n", "interior_count", "matched_n", "matched_count"):
            if field in wanted and actual[field] != wanted[field]:
                raise AssertionError(f"{name} {field}: got {actual[field]}, expected {wanted[field]}")
        for field in ("interior_rate", "matched_rate", "median_length"):
            if field in wanted and not math.isclose(actual[field], wanted[field], abs_tol=tolerance):
                raise AssertionError(f"{name} {field}: got {actual[field]}, expected {wanted[field]}")


def render_figure(path: os.PathLike[str] | str, rows: list[dict], distances: dict[str, np.ndarray]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {
        "46-47": "#c43b2f",
        "47-48": "#4c72b0",
        "48-49": "#7aa6dc",
        "47-49": "#2f7f33",
        "45-47": "#6aa16d",
    }
    figure, axes = plt.subplots(1, 2, figsize=(15.6, 5.4))
    bins = np.linspace(0, 90, 37)
    for row in rows:
        axes[0].hist(
            distances[row["name"]],
            bins=bins,
            histtype="step",
            linewidth=1.4,
            color=colors.get(row["name"]),
            label=f"w{row['name'].replace('-', ' → w')}  {row['label']}",
        )
    axes[0].axvspan(40, 55, color="0.7", alpha=0.25, label="length-matched band")
    axes[0].set_title("The w046→w047 gap has the length distribution of a two-sheet step")
    axes[0].set_xlabel("distance to nearest vertex on the other winding (voxels)")
    axes[0].set_ylabel("rays")
    axes[0].legend(fontsize=8)

    shown = [row for row in rows if row["name"] in ("46-47", "47-48", "47-49", "45-47")]
    rates = [100 * row["matched_rate"] for row in shown]
    bars = axes[1].bar(range(len(shown)), rates, color=[colors[row["name"]] for row in shown])
    axes[1].set_xticks(
        range(len(shown)),
        [f"w{row['name'].replace('-', '→w')}\n{row['label']}" for row in shown],
    )
    axes[1].set_ylim(0, 110)
    axes[1].set_ylabel("rays crossing a distinct model-predicted surface (%)")
    axes[1].set_title("Length-matched rays, 40–55 voxels")
    for bar, row in zip(bars, shown):
        axes[1].text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1,
            f"{100 * row['matched_rate']:.1f}%\nn={row['matched_n']}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    figure.suptitle(
        "PHerc0139 winding 46: evidence from the published surface-prediction model\n"
        "400 rays per pair, z=4000–4600; model evidence, not physical ground truth"
    )
    figure.tight_layout(rect=(0, 0, 1, 0.9))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def run_experiment(
    manifest: dict,
    *,
    work: os.PathLike[str] | str,
    offline: bool,
    mesh_dir: os.PathLike[str] | str | None,
    legacy_cache: os.PathLike[str] | str | None,
    expected_chunks: dict[str, dict],
    profiles_dir: os.PathLike[str] | str | None,
) -> tuple[dict, dict[str, np.ndarray]]:
    experiment = manifest["ray_experiment"]
    _verify_live_zarray(experiment, offline=offline)
    mesh_paths, mesh_inputs = materialize_meshes(
        experiment, work, offline=offline, mesh_dir=mesh_dir
    )
    surfaces = {winding: load_mesh(path) for winding, path in mesh_paths.items()}
    reader = VolumeReader(
        experiment["zarr"],
        Path(work) / "chunks",
        offline=offline,
        expected_chunks=expected_chunks,
        legacy_cache=legacy_cache,
        workers=experiment["config"].get("workers", 12),
    )
    config = experiment["config"]
    rows = []
    distances_by_name = {}
    profile_root = Path(profiles_dir) if profiles_dir else None
    if profile_root:
        profile_root.mkdir(parents=True, exist_ok=True)
    for pair in experiment["pairs"]:
        profiles, distances = ray_profiles(
            surfaces[pair["from"]],
            surfaces[pair["to"]],
            reader,
            n_rays=config["n_rays"],
            n_samples=config["n_samples"],
            zlo=config["z_band"][0],
            zhi=config["z_band"][1],
            seed=config["seed"],
        )
        rows.append(summarize_pair(pair["name"], pair["label"], profiles, distances, config))
        distances_by_name[pair["name"]] = distances
        if profile_root:
            np.savez_compressed(profile_root / f"pair_{pair['name']}.npz", profiles=profiles, distances=distances)

    result = {
        "schema_version": 1,
        "experiment": "PHerc0139 missing-winding ray test",
        "config": config,
        "inputs": {
            "manifest_sha256": canonical_json_sha256(manifest),
            "zarr": {
                "path": experiment["zarr"]["path"],
                "level": experiment["zarr"]["level"],
                "metadata_sha256": experiment["zarr"]["metadata_sha256"],
            },
            "meshes": mesh_inputs,
            "chunks": [],
        },
        "frame_check": frame_check(surfaces[47], reader, config),
        "pairs": rows,
        "interpretation": (
            "These rates are evidence from the named surface-prediction model. "
            "They are not direct observation or physical ground truth."
        ),
    }
    result["inputs"]["chunks"] = [reader.observed[key] for key in sorted(reader.observed)]
    validate_expected(result, experiment.get("expected", {}))
    return result, distances_by_name


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--work", default="./ray_data")
    parser.add_argument("--output", default="./results/ray_PHerc0139.json")
    parser.add_argument("--figure", default="./fig_gap.png")
    parser.add_argument("--profiles-dir")
    parser.add_argument("--mesh-dir", help="validated local w045..w049 directories")
    parser.add_argument("--legacy-cache", help=argparse.SUPPRESS)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--no-figure", action="store_true")
    parser.add_argument("--reference", help="prior result whose chunk digests must match")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    reference = args.reference
    if reference is None:
        candidate = Path(args.manifest).parent / manifest["ray_experiment"].get(
            "reference_result", ""
        )
        if candidate.is_file():
            reference = str(candidate)
    expected_chunks = chunk_snapshot(reference)
    result, distances = run_experiment(
        manifest,
        work=args.work,
        offline=args.offline,
        mesh_dir=args.mesh_dir,
        legacy_cache=args.legacy_cache,
        expected_chunks=expected_chunks,
        profiles_dir=args.profiles_dir,
    )
    write_json_atomic(args.output, result)
    if not args.no_figure:
        render_figure(args.figure, result["pairs"], distances)
    print(f"wrote {args.output} ({len(result['inputs']['chunks'])} pinned chunks)")
    if not args.no_figure:
        print(f"wrote {args.figure}")
    for row in result["pairs"]:
        print(
            f"{row['name']}: rate={row['interior_rate']:.4f}; "
            f"40-55 vx={row['matched_count']}/{row['matched_n']} "
            f"({row['matched_rate']:.4f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
