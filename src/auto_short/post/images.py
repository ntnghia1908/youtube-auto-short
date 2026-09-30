"""P5 image library, P5a upload: JPEG/PNG only, top level of ``[post] image_dir`` (outside the repo), served whole
(no resize / crop / text overlay). Dimensions come from the file header (no Pillow): stdlib only (CP1 §10).

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P5, P5a.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..workspace import atomic_write_bytes

MAX_BYTES = 15 * 1024 * 1024
MIN_SHORT_EDGE = 600
EXTS = {".jpg", ".jpeg", ".png"}
CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class ImageError(Exception):
    """Invalid image data (magic bytes, size, dimensions) — P5a."""


@dataclass(frozen=True)
class ImageInfo:
    name: str
    width: int
    height: int
    bytes: int


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(data)
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:  # SOI / EOI / RSTn: no length
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in sof:
            if i + 9 > n:
                return None
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        if seg_len < 2:
            return None
        i += 2 + seg_len
    return None


def sniff(data: bytes) -> tuple[str, int, int] | None:
    """(extension, width, height) from magic bytes + header; None when neither JPEG nor PNG matches."""
    dim = _png_size(data)
    if dim is not None:
        return ".png", *dim
    dim = _jpeg_size(data)
    if dim is not None:
        return ".jpg", *dim
    return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate(data: bytes) -> tuple[str, int, int]:
    """P5a checks: size, magic bytes, short edge; raises :class:`ImageError`, else (ext, width, height)."""
    if len(data) > MAX_BYTES:
        raise ImageError(f"ảnh lớn hơn {MAX_BYTES // (1024 * 1024)} MB")
    sniffed = sniff(data)
    if sniffed is None:
        raise ImageError("không phải ảnh JPEG/PNG hợp lệ (sai magic bytes)")
    ext, w, h = sniffed
    if w <= 0 or h <= 0:
        raise ImageError("không đọc được kích thước ảnh")
    if min(w, h) < MIN_SHORT_EDGE:
        raise ImageError(f"ảnh nhỏ hơn {MIN_SHORT_EDGE} px (cạnh ngắn {min(w, h)} px)")
    return ext, w, h


def clean_name(name: str, ext: str) -> str:
    """Sanitised base name (letters, digits, ``-``, ``_``, ``.``) + the canonical extension (P5a)."""
    stem = Path(unicodedata.normalize("NFKD", name or "")).stem
    stem = "".join(c for c in stem if not unicodedata.combining(c))
    stem = _NAME_UNSAFE.sub("-", stem).strip("-_.") or "image"
    return f"{stem[:80]}{ext}"


def safe_name(name: str) -> bool:
    return bool(_SAFE_NAME.match(name or "")) and Path(name).suffix.lower() in EXTS and ".." not in name


def resolve(image_dir: Path, name: str) -> Path | None:
    """The library file ``name``, or None for an unknown / unsafe name (path traversal, AC 4 / AC 12 -> 404)."""
    if not safe_name(name):
        return None
    path = image_dir / name
    try:
        if not image_dir.is_dir() or path.resolve().parent != image_dir.resolve():
            return None
    except OSError:
        return None
    return path if path.is_file() else None


def list_images(image_dir: Path) -> list[ImageInfo]:
    """Every valid ``.jpg``/``.jpeg``/``.png`` directly inside ``image_dir`` (top level only, name order); a file
    that fails to sniff is skipped (not a valid image)."""
    if not image_dir.is_dir():
        return []
    out = []
    for path in sorted(image_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in EXTS:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        dim = sniff(data)
        if dim is None:
            continue
        _, w, h = dim
        out.append(ImageInfo(path.name, w, h, len(data)))
    return out


def find_by_sha256(image_dir: Path, digest: str) -> str | None:
    for info in list_images(image_dir):
        try:
            data = (image_dir / info.name).read_bytes()
        except OSError:
            continue
        if sha256_bytes(data) == digest:
            return info.name
    return None


def unique_name(image_dir: Path, base: str) -> str:
    """``base`` (already :func:`clean_name`d) when free, else ``<stem>-2<ext>``, ``-3``... (P5a)."""
    stem, ext = Path(base).stem, Path(base).suffix
    name, n = base, 2
    while (image_dir / name).exists():
        name = f"{stem}-{n}{ext}"
        n += 1
    return name


def save_image(image_dir: Path, data: bytes, *, original_name: str) -> tuple[str, bool]:
    """P5a: validate, dedup by sha256 (returns the existing name, ``duplicate=True``), else save under a cleaned /
    unique name (atomic write). Raises :class:`ImageError`."""
    ext, _w, _h = validate(data)
    image_dir.mkdir(parents=True, exist_ok=True)
    existing = find_by_sha256(image_dir, sha256_bytes(data))
    if existing is not None:
        return existing, True
    name = unique_name(image_dir, clean_name(original_name, ext))
    atomic_write_bytes(image_dir / name, data)
    return name, False


def delete_image(image_dir: Path, name: str) -> bool:
    """Removes the library file ``name``; False when it did not exist. Caller resolves/validates the name first
    (:func:`resolve`)."""
    path = resolve(image_dir, name)
    if path is None:
        return False
    path.unlink()
    return True


def usage_counts(work_dir: Path) -> dict[str, int]:
    """Image name -> number of ``posts.json`` entries using it, across every episode workspace directly inside
    ``work_dir`` (P5: "ít dùng nhất trong mọi posts.json của workspace")."""
    from .store import read_posts_quiet

    counts: dict[str, int] = {}
    if not work_dir.is_dir():
        return counts
    for ep_dir in work_dir.iterdir():
        if not ep_dir.is_dir() or ep_dir.name.startswith("_"):
            continue
        doc = read_posts_quiet(ep_dir / "posts.json", ep_dir.name)
        for entry in doc.get("posts", []):
            image = entry.get("image")
            if isinstance(image, str):
                counts[image] = counts.get(image, 0) + 1
    return counts


def least_used(image_dir: Path, work_dir: Path) -> str | None:
    """P5: the library image used least across every workspace's ``posts.json`` (ties -> file name); None = the
    library is empty ("thiếu ảnh")."""
    images = list_images(image_dir)
    if not images:
        return None
    counts = usage_counts(work_dir)
    return min((i.name for i in images), key=lambda n: (counts.get(n, 0), n))
