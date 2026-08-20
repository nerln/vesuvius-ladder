import hashlib
import json
from pathlib import Path

from ladder_io import canonical_json_sha256


ROOT = Path(__file__).parents[1]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_corpus_release_artifacts_are_immutable():
    snapshot = json.loads((ROOT / "results/corpus_snapshot.json").read_text())
    for name, expected in snapshot["artifacts"].items():
        path = ROOT / "results" / name
        assert path.stat().st_size == expected["size"], name
        assert _sha256(path) == expected["sha256"], name


def test_ray_snapshot_is_bound_to_manifest_and_chunk_bytes():
    manifest = json.loads((ROOT / "data_manifest.json").read_text())
    result = json.loads((ROOT / "results/ray_PHerc0139.json").read_text())
    expected_manifest_sha = "df32a087b57b62d5f415438e3eb8b670063b4cc244d54c507b52055cf62be594"
    assert canonical_json_sha256(manifest) == expected_manifest_sha
    assert result["inputs"]["manifest_sha256"] == expected_manifest_sha
    chunks = result["inputs"]["chunks"]
    assert len(chunks) == 361
    assert sum(row["size"] for row in chunks) == 112892827
    assert all(row["sha256"] and not row["missing"] for row in chunks)
