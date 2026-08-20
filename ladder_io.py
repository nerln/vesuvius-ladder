"""Small, dependency-free I/O helpers shared by ladder's command-line tools.

Downloads are atomic, caches are keyed by the complete URL, and cached bytes
are checked against either a release-manifest digest or a digest sidecar.  A
404 may be an expected absent Zarr chunk; every other HTTP or transport error
is fatal and is never converted into data.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


class DownloadError(RuntimeError):
    """A remote object could not be fetched."""


class IntegrityError(RuntimeError):
    """Downloaded or cached bytes do not match their declared identity."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: os.PathLike[str] | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(raw)


def cache_path(cache_dir: os.PathLike[str] | str, url: str) -> Path:
    """Return a cache path whose identity includes the complete remote URL."""
    suffix = Path(urllib.parse.urlparse(url).path).suffix
    name = hashlib.sha256(url.encode()).hexdigest() + suffix
    return Path(cache_dir) / name


def _validate(
    data: bytes,
    *,
    source: str,
    expected_sha256: str | None,
    expected_size: int | None,
    validator: Callable[[bytes], None] | None,
) -> str:
    if expected_size is not None and len(data) != expected_size:
        raise IntegrityError(
            f"size mismatch for {source}: got {len(data)}, expected {expected_size}"
        )
    digest = sha256_bytes(data)
    if expected_sha256 is not None and digest != expected_sha256:
        raise IntegrityError(
            f"SHA-256 mismatch for {source}: got {digest}, expected {expected_sha256}"
        )
    if validator is not None:
        validator(data)
    return digest


def fetch_bytes(
    url: str,
    *,
    timeout: float = 180,
    allow_404: bool = False,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    validator: Callable[[bytes], None] | None = None,
) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": "vesuvius-ladder/0.2"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and allow_404:
            return None
        raise DownloadError(f"HTTP {exc.code} while fetching {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DownloadError(f"transport error while fetching {url}: {exc}") from exc

    _validate(
        data,
        source=url,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
        validator=validator,
    )
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def read_validated(
    path: os.PathLike[str] | str,
    *,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    validator: Callable[[bytes], None] | None = None,
    require_sidecar: bool = False,
) -> bytes:
    target = Path(path)
    data = target.read_bytes()
    declared = expected_sha256
    sidecar = _sidecar(target)
    if declared is None and sidecar.exists():
        declared = sidecar.read_text(encoding="ascii").strip().split()[0]
    elif declared is None and require_sidecar:
        raise IntegrityError(f"cache digest sidecar is missing for {target}")
    digest = _validate(
        data,
        source=str(target),
        expected_sha256=declared,
        expected_size=expected_size,
        validator=validator,
    )
    if not sidecar.exists():
        _atomic_write(sidecar, (digest + "\n").encode("ascii"))
    return data


def fetch_to_path(
    url: str,
    path: os.PathLike[str] | str,
    *,
    timeout: float = 180,
    offline: bool = False,
    refresh: bool = False,
    allow_404: bool = False,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    validator: Callable[[bytes], None] | None = None,
) -> Path | None:
    """Return a validated local object, downloading and replacing atomically.

    If a cached object fails a declared digest and networking is available, a
    fresh copy is attempted.  In offline mode the integrity error is surfaced.
    Expected 404s return ``None`` and are deliberately not cached.
    """
    target = Path(path)
    if target.exists() and not refresh:
        try:
            read_validated(
                target,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                validator=validator,
            )
            return target
        except IntegrityError:
            if offline:
                raise
    elif offline:
        raise DownloadError(f"offline cache miss for {url} ({target})")

    data = fetch_bytes(
        url,
        timeout=timeout,
        allow_404=allow_404,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
        validator=validator,
    )
    if data is None:
        return None
    _atomic_write(target, data)
    digest = sha256_bytes(data)
    _atomic_write(_sidecar(target), (digest + "\n").encode("ascii"))
    return target


def fetch_cached(
    url: str,
    cache_dir: os.PathLike[str] | str,
    **kwargs: Any,
) -> Path | None:
    return fetch_to_path(url, cache_path(cache_dir, url), **kwargs)


def json_validator(data: bytes) -> None:
    try:
        json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"invalid JSON: {exc}") from exc


def write_json_atomic(path: os.PathLike[str] | str, value: Any, *, indent: int = 2) -> None:
    raw = (json.dumps(value, indent=indent, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(Path(path), raw)
