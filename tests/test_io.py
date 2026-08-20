import hashlib
import io
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from ladder_io import (
    DownloadError,
    IntegrityError,
    cache_path,
    fetch_bytes,
    fetch_to_path,
    read_validated,
)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_only_explicit_404_can_be_absent():
    missing = urllib.error.HTTPError("https://example/x", 404, "missing", {}, None)
    with patch("urllib.request.urlopen", side_effect=missing):
        assert fetch_bytes("https://example/x", allow_404=True) is None
    with patch("urllib.request.urlopen", side_effect=missing):
        with pytest.raises(DownloadError, match="HTTP 404"):
            fetch_bytes("https://example/x")


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_other_http_errors_are_fatal(status):
    error = urllib.error.HTTPError("https://example/x", status, "bad", {}, None)
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(DownloadError, match=f"HTTP {status}"):
            fetch_bytes("https://example/x", allow_404=True)


def test_transport_errors_are_fatal():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        with pytest.raises(DownloadError, match="transport error"):
            fetch_bytes("https://example/x", allow_404=True)


def test_full_url_is_part_of_cache_identity(tmp_path):
    a = cache_path(tmp_path, "https://bucket/volume-a/0/1/2/3")
    b = cache_path(tmp_path, "https://bucket/volume-b/0/1/2/3")
    assert a != b


def test_declared_digest_repairs_online_and_fails_offline(tmp_path):
    target = tmp_path / "asset.bin"
    target.write_bytes(b"corrupt")
    good = b"release bytes"
    digest = hashlib.sha256(good).hexdigest()
    with patch("urllib.request.urlopen", return_value=Response(good)):
        fetch_to_path(
            "https://example/asset.bin",
            target,
            expected_sha256=digest,
            expected_size=len(good),
        )
    assert read_validated(target, expected_sha256=digest) == good
    target.write_bytes(b"corrupt again")
    with pytest.raises(IntegrityError, match="SHA-256 mismatch"):
        fetch_to_path(
            "https://example/asset.bin",
            target,
            offline=True,
            expected_sha256=digest,
            expected_size=len(good),
        )


def test_download_writes_digest_sidecar(tmp_path):
    target = tmp_path / "asset"
    with patch("urllib.request.urlopen", return_value=Response(b"abc")):
        fetch_to_path("https://example/asset", target)
    assert Path(str(target) + ".sha256").read_text().strip() == hashlib.sha256(b"abc").hexdigest()

