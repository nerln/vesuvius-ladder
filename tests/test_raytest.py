import hashlib
from pathlib import Path

import numpy as np
import pytest

from ladder_io import cache_path
from raytest import (
    S3,
    VolumeReader,
    intervening,
    load_manifest,
    summarize_pair,
    validate_expected,
)


def test_release_manifest_is_internally_consistent():
    manifest = load_manifest(Path(__file__).parents[1] / "data_manifest.json")
    assert set(manifest["ray_experiment"]["meshes"]) == {"45", "46", "47", "48", "49"}


def test_intervening_requires_a_high_island_and_two_low_separators():
    profiles = np.zeros((3, 65), np.float32)
    profiles[0, 0] = profiles[0, -1] = 255
    profiles[0, 32] = 255
    profiles[1] = 255
    profiles[2, 0] = profiles[2, -1] = 255
    assert intervening(profiles).tolist() == [True, False, False]


def test_pair_summary_counts_length_matched_rays():
    profiles = np.zeros((3, 65), np.float32)
    profiles[:, 0] = profiles[:, -1] = 255
    profiles[[0, 2], 32] = 255
    config = {
        "high_threshold": 128,
        "low_threshold": 64,
        "edge_fraction": 0.15,
        "length_match": [40, 55],
    }
    row = summarize_pair("x", "control", profiles, np.array([45.0, 30.0, 50.0]), config)
    assert row["interior_count"] == 2
    assert row["matched_n"] == 2
    assert row["matched_count"] == 2
    assert row["matched_rate"] == 1


def test_volume_reader_samples_validated_offline_chunk(tmp_path):
    metadata = {
        "shape": [2, 2, 2],
        "chunks": [2, 2, 2],
        "dtype": "|u1",
        "fill_value": 0,
        "order": "C",
        "compressor": None,
    }
    zarr = {"path": "volume-a.zarr", "level": 0, "metadata": metadata}
    raw = np.arange(8, dtype=np.uint8).tobytes()
    url = f"{S3}/volume-a.zarr/0/0/0/0"
    path = cache_path(tmp_path, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    reader = VolumeReader(
        zarr,
        tmp_path,
        offline=True,
        expected_chunks={"0/0/0": {"sha256": digest, "size": len(raw)}},
        workers=1,
    )
    values, valid = reader.sample(np.array([[0, 0, 0], [1, 1, 1]], dtype=float))
    assert valid.tolist() == [True, True]
    assert values.tolist() == [0, 7]
    assert reader.observed["0/0/0"]["sha256"] == digest


def test_expected_result_mismatch_is_fatal():
    result = {
        "pairs": [{"name": "gap", "n": 1, "interior_count": 0, "matched_n": 1, "matched_count": 0, "interior_rate": 0.0, "matched_rate": 0.0, "median_length": 1.0}]
    }
    with pytest.raises(AssertionError, match="interior_count"):
        validate_expected(result, {"pairs": {"gap": {"interior_count": 1}}})
