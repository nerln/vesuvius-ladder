import gzip
import json

import numpy as np
from scipy.spatial import cKDTree

from ladder import _catalog_validator, classify, pair_stats, winding_of
from ladder_io import IntegrityError


def _plane(z):
    y, x = np.mgrid[:10, :10]
    return np.column_stack([x.ravel(), y.ravel(), np.full(x.size, z, dtype=float)])


def test_duplicate_is_separated_from_neighboring_planes():
    surfaces = {
        "a-w045": _plane(0),
        "b-w046": _plane(0),
        "c-w047": _plane(10),
        "d-w048": _plane(20),
        "e-w049": _plane(30),
        "f-w050": _plane(40),
    }
    rows = []
    for name_b, points_b in surfaces.items():
        tree = cKDTree(points_b)
        for name_a, points_a in surfaces.items():
            if name_a == name_b:
                continue
            row = pair_stats(points_a, tree, radius=100)
            row.update(A=name_a, B=name_b)
            rows.append(row)
    rows, unit = classify(rows)
    duplicates = {
        tuple(sorted((row["A"], row["B"])))
        for row in rows
        if row["verdict"] == "DUPLICATE"
    }
    assert unit == 10
    assert duplicates == {("a-w045", "b-w046")}


def test_one_voxel_floor_is_explicit():
    rows = [
        {"A": "a", "B": "b", "d_med": 0.5, "cover": 1.0, "taus": {"0.25": 0.0, "0.5": 0.0, "1.0": 1.0}},
        {"A": "b", "B": "a", "d_med": 0.5, "cover": 1.0, "taus": {"0.25": 0.0, "0.5": 0.0, "1.0": 1.0}},
    ]
    rows, unit = classify(rows)
    assert unit == 0.5
    assert all(row["coin_radius"] == 1.0 for row in rows)


def test_winding_parser():
    assert winding_of("20260325000000-w046_20260325") == 46
    assert winding_of("prefix_w128-extra") == 128
    assert winding_of("title-strip") is None


def test_catalog_validator_accepts_plain_and_gzip_json():
    raw = json.dumps({"samples": {}}).encode()
    _catalog_validator(raw)
    _catalog_validator(gzip.compress(raw))


def test_catalog_validator_rejects_broken_gzip():
    with np.testing.assert_raises(IntegrityError):
        _catalog_validator(b"\x1f\x8bnot-a-gzip-stream")
