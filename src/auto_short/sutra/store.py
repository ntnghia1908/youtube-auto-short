"""Sutra storage S4: ``<root>/<slug>/{sutra.txt, meta.json, recitations.json}`` + recitation counter.

``root`` = ``<workspace dir>/_sutras`` (underscore prefix: the Auto Short episode scans skip it). Contract:
docs/decisions/SR1-sutra-reader-contract.md S4. Only the shared workspace helpers are imported from the host.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from ..workspace import atomic_write_bytes, atomic_write_json
from . import markup

SCHEMA_VERSION = 1
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
MAX_ENTRIES_IN_DETAIL = 400
TEXT_FILE, META_FILE, REC_FILE = "sutra.txt", "meta.json", "recitations.json"


class SutraError(Exception):
    """Base of store errors (``str(e)`` is a Vietnamese message)."""


class SutraNotFound(SutraError):
    pass


class SutraConflict(SutraError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(title: str) -> str:
    """S4: strip diacritics (NFD, ``đ`` -> ``d``), lower-case, ``[a-z0-9]`` joined by ``-``, <= 60 chars."""
    s = unicodedata.normalize("NFD", title.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60].strip("-")
    return s or "kinh"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SutraStore:
    def __init__(self, root: Path, *, clock: Callable[[], datetime] = _now):
        self.root = Path(root)
        self._clock = clock
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    # --- helpers -----------------------------------------------------------------------------------

    def _lock(self, slug: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(slug, threading.Lock())

    def _dir(self, slug: str) -> Path:
        """Directory of an existing sutra: valid slug, direct child of root, not a symlink."""
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            raise SutraNotFound("không có bộ kinh này")
        d = self.root / slug
        if d.is_symlink() or not d.is_dir() or d.resolve().parent != self.root.resolve():
            raise SutraNotFound("không có bộ kinh này")
        if (d / META_FILE).is_symlink() or not (d / META_FILE).is_file():
            raise SutraNotFound("không có bộ kinh này")
        return d

    def exists(self, slug: str) -> bool:
        try:
            self._dir(slug)
            return True
        except SutraNotFound:
            return False

    @staticmethod
    def _read_bytes(path: Path) -> bytes:
        if path.is_symlink():
            raise SutraError(f"{path.name} là liên kết, không đọc")
        return path.read_bytes()

    def _meta(self, d: Path) -> dict:
        return json.loads(self._read_bytes(d / META_FILE).decode("utf-8"))

    def _entries(self, d: Path) -> list[dict]:
        p = d / REC_FILE
        if not p.is_file():
            return []
        try:
            return list(json.loads(self._read_bytes(p).decode("utf-8")).get("entries", []))
        except (ValueError, OSError):
            return []

    def _write_entries(self, d: Path, entries: list[dict]) -> None:
        atomic_write_json(d / REC_FILE, {"schema_version": SCHEMA_VERSION, "entries": entries})

    def _stamp(self) -> str:
        return _iso(self._clock())

    # --- read --------------------------------------------------------------------------------------

    def list(self) -> list[dict]:
        out = []
        if not self.root.is_dir():
            return out
        for d in sorted(self.root.iterdir()):
            if d.name.startswith((".", "_")) or not SLUG_RE.match(d.name):
                continue
            try:
                d = self._dir(d.name)
                meta = self._meta(d)
                sutra = markup.parse(self._read_bytes(d / TEXT_FILE).decode("utf-8"))
            except (SutraError, markup.MarkupError, ValueError, OSError):
                continue
            entries = self._entries(d)
            out.append({"slug": d.name, "title": meta.get("title", sutra.title), "sections": sutra.section_count,
                        "recitations": {"total": len(entries), "last_at": entries[-1]["at"] if entries else None},
                        "updated_at": meta.get("updated_at")})
        out.sort(key=lambda r: r["title"].casefold())
        return out

    def text(self, slug: str) -> dict:
        d = self._dir(slug)
        data = self._read_bytes(d / TEXT_FILE)
        return {"text": data.decode("utf-8"), "sha256": _sha(data)}

    def get(self, slug: str) -> dict:
        d = self._dir(slug)
        data = self._read_bytes(d / TEXT_FILE)
        try:
            sutra = markup.parse(data.decode("utf-8"))
        except markup.MarkupError as e:
            raise SutraError(f"văn bản kinh lỗi: {e}") from e
        entries = self._entries(d)
        doc = sutra.to_json()
        doc.update({"slug": slug, "sha256": _sha(data),
                    "recitations": {"total": len(entries), "entries": entries[-MAX_ENTRIES_IN_DETAIL:]}})
        return doc

    # --- write -------------------------------------------------------------------------------------

    def _claim_slug(self, title: str) -> tuple[str, Path]:
        base = slugify(title)
        self.root.mkdir(parents=True, exist_ok=True)
        n = 1
        while True:
            suffix = "" if n == 1 else f"-{n}"
            slug = base[:60 - len(suffix)].rstrip("-") + suffix
            d = self.root / slug
            try:
                d.mkdir()
                return slug, d
            except FileExistsError:
                n += 1

    def create(self, text: str) -> str:
        """Validate, then store a new sutra; returns its slug. Raises :class:`markup.MarkupError`."""
        norm = markup.normalize(text)
        sutra = markup.parse(norm)
        data = norm.encode("utf-8")
        with self._guard:
            slug, d = self._claim_slug(sutra.title)
        try:
            now = self._stamp()
            atomic_write_bytes(d / TEXT_FILE, data)
            self._write_entries(d, [])
            atomic_write_json(d / META_FILE, {"schema_version": SCHEMA_VERSION, "slug": slug, "title": sutra.title,
                                              "sha256": _sha(data), "created_at": now, "updated_at": now})
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
        return slug

    def update(self, slug: str, text: str, sha256: str) -> dict:
        """Replace the text if ``sha256`` is the stored one (else :class:`SutraConflict`)."""
        norm = markup.normalize(text)
        sutra = markup.parse(norm)
        data = norm.encode("utf-8")
        with self._lock(slug):
            d = self._dir(slug)
            if _sha(self._read_bytes(d / TEXT_FILE)) != sha256:
                raise SutraConflict("bộ kinh đã được sửa ở nơi khác, hãy tải lại")
            meta = self._meta(d)
            atomic_write_bytes(d / TEXT_FILE, data)
            meta.update({"title": sutra.title, "sha256": _sha(data), "updated_at": self._stamp()})
            atomic_write_json(d / META_FILE, meta)
        return {"slug": slug, "sha256": _sha(data)}

    def delete(self, slug: str) -> None:
        with self._lock(slug):
            d = self._dir(slug)
            shutil.rmtree(d)

    # --- recitations -------------------------------------------------------------------------------

    def add_recitation(self, slug: str) -> dict:
        with self._lock(slug):
            d = self._dir(slug)
            entries = self._entries(d)
            entry = {"at": self._stamp()}
            entries.append(entry)
            self._write_entries(d, entries)
            return {"total": len(entries), "entry": entry}

    def undo_recitation(self, slug: str) -> dict:
        with self._lock(slug):
            d = self._dir(slug)
            entries = self._entries(d)
            if not entries:
                raise SutraConflict("chưa có biến nào để hoàn tác")
            entries.pop()
            self._write_entries(d, entries)
            return {"total": len(entries)}
