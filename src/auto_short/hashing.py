"""sha256 helpers: file hashing with a (path, size, mtime) cache and config hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class FileFingerprint:
    path: Path  # absolute, resolved
    size: int
    mtime_ns: int
    sha256: str


def fingerprint(path: Path, cache: Iterable[FileFingerprint] = ()) -> FileFingerprint:
    """Return size/mtime/sha256 of ``path``, reusing a cached sha256 when
    (path, size, mtime_ns) match an entry in ``cache``; otherwise hash the file."""
    path = path.resolve()
    st = path.stat()
    for entry in cache:
        if entry.path == path and entry.size == st.st_size and entry.mtime_ns == st.st_mtime_ns:
            return entry
    return FileFingerprint(path, st.st_size, st.st_mtime_ns, sha256_file(path))


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def config_hash(used_config: dict) -> str:
    """sha256 of the canonical JSON of the config keys a stage uses."""
    return hashlib.sha256(canonical_json(used_config).encode("utf-8")).hexdigest()
