"""HD1 G1 / G2 / G3: confirm an external backup of the HD / vertical file by sha256, then release them on the VM.

``confirm`` records ``work/<owner>/backup.json`` only when the sha256 equals the one of the file the VM holds now
(HD: ``enhance.json`` ``source_hd_sha256`` + size; vertical: the real sha256, computed once and cached by size +
mtime_ns). ``release`` deletes exactly ``work/<owner>/source_hd.mp4`` (+ the khai thị hard link) and
``output/<owner>/full/vertical.mp4`` when every file present was confirmed with its current sha256, and marks
``enhance.json`` ``released: true`` (state ``done`` and the recorded sha256 are kept, so the Shorts rendered from the
HD source stay current). Nothing else is touched. Canonical contract: docs/decisions/HD1-hd-backup-release.md.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..enhance import state as enh
from ..hashing import sha256_file
from ..khaithi import SUFFIX
from ..render import full as render_full
from ..workspace import WorkspaceError, atomic_write_json, utc_now, validate_episode_id
from .logic import ReviewError

log = logging.getLogger("auto_short")

BACKUP_NAME = "backup.json"
SCHEMA_VERSION = 1
KINDS = ("hd", "vertical")
_SHA = re.compile(r"[0-9a-f]{64}")
_LOCK = threading.RLock()


class BackupError(ReviewError):
    """A backup / release request that cannot be done; ``status`` is the HTTP status the API answers with."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ReleaseResult:
    episode_id: str
    changed: bool  # False: already released
    freed: int  # bytes
    removed: list[str]  # paths relative to the workspace root / output dir, for the log


def backup_path(ws_dir: Path) -> Path:
    return Path(ws_dir) / BACKUP_NAME


def read_backup(ws_dir: Path) -> dict:
    try:
        doc = json.loads(backup_path(ws_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        return {"schema_version": SCHEMA_VERSION, "confirmed": {}, "vertical_sha": None, "released": None}
    for key, default in (("confirmed", {}), ("vertical_sha", None), ("released", None)):
        doc.setdefault(key, default)
    return doc


def _owner_dir(config: Config, episode_id: str) -> tuple[str, Path]:
    try:
        eid = validate_episode_id(episode_id)
    except WorkspaceError as exc:
        raise BackupError(f"không có tập {episode_id!r}", 404) from exc
    owner = enh.owner_for(config, eid)
    d = Path(config.workspace.dir) / owner
    if not (d / "manifest.json").is_file():
        raise BackupError(f"không có tập {owner!r}", 404)
    return owner, d


def vertical_sha(config: Config, owner: str, doc: dict) -> tuple[str, int, int] | None:
    """``(sha256, size, mtime_ns)`` of ``output/<owner>/full/vertical.mp4``, hashed once and cached in ``doc``
    (``vertical_sha``) by size + mtime_ns; None when there is no file. The caller saves ``doc`` when it changed."""
    path = render_full.vertical_path(config, owner)
    try:
        st = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    cache = doc.get("vertical_sha")
    if isinstance(cache, dict) and cache.get("size") == st.st_size and cache.get("mtime_ns") == st.st_mtime_ns \
            and isinstance(cache.get("sha256"), str):
        return cache["sha256"], st.st_size, st.st_mtime_ns
    sha = sha256_file(path)
    doc["vertical_sha"] = {"sha256": sha, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    return sha, st.st_size, st.st_mtime_ns


def _current_hd(d: Path) -> tuple[str, int] | None:
    fp = enh.hd_fingerprint(d)
    return (fp.sha256, fp.size) if fp is not None else None


def confirm(config: Config, episode_id: str, kind: str, sha256: str, *, now: str | None = None) -> dict:
    """G1: record that the external copy of ``kind`` (``hd`` | ``vertical``) with this sha256 exists. Only the sha256
    of the file the VM holds now is accepted (no file / another sha256 -> :class:`BackupError`, nothing written)."""
    if kind not in KINDS:
        raise BackupError("kind phải là 'hd' hoặc 'vertical'")
    sha = (sha256 or "").strip().lower()
    if not _SHA.fullmatch(sha):
        raise BackupError("sha256 không hợp lệ (64 ký tự hex)")
    owner, d = _owner_dir(config, episode_id)
    with _LOCK:
        doc = read_backup(d)
        if doc.get("released"):
            raise BackupError(f"{enh.RELEASED_MESSAGE}: không còn file trên VM để xác nhận")
        if kind == "hd":
            cur = _current_hd(d)
            if cur is None:
                raise BackupError("VM không có bản HD hợp lệ của tập này (enhance chưa xong hoặc file không khớp)")
            have, size = cur
            mtime_ns = None
        else:
            got = vertical_sha(config, owner, doc)
            if got is None:
                raise BackupError("VM không có bản dọc của tập này")
            have, size, mtime_ns = got
        if sha != have:
            raise BackupError("sha256 không khớp file hiện có trên VM; không ghi xác nhận")
        entry = {"sha256": have, "size": size, "confirmed_at": now or utc_now()}
        doc.update(episode_id=owner)
        doc["confirmed"][kind] = entry
        atomic_write_json(backup_path(d), doc)
    log.info("backup: confirmed %s [%s] %s", kind, owner, have[:12])
    return {"episode_id": owner, "kind": kind, **entry}


def view(config: Config, episode_id: str) -> dict:
    """Fields for the web views: ``released`` / ``released_at`` + the confirmations (read-only; no hashing)."""
    owner = enh.owner_for(config, episode_id)
    d = Path(config.workspace.dir) / owner
    edoc = enh.read(d) or {}
    doc = read_backup(d)
    return {"released": bool(edoc.get("released")) and not enh.hd_path(d).is_file(),
            "released_at": edoc.get("released_at"),
            "confirmed": {k: {"confirmed_at": v.get("confirmed_at"), "size": v.get("size")}
                          for k, v in (doc.get("confirmed") or {}).items() if isinstance(v, dict)}}


def release(config: Config, episode_id: str, *, allow_no_vertical: bool = False, now: str | None = None,
            clock=time.time) -> ReleaseResult:
    """G2 / G3: delete ``source_hd.mp4`` (and its khai thị hard link) + ``full/vertical.mp4`` when each file present
    was confirmed with its current sha256. Records first (``enhance.json`` released, ``backup.json``), deletes
    after, so a crash never leaves a deleted file without the record. The caller checks running jobs (409)."""
    owner, d = _owner_dir(config, episode_id)
    with _LOCK:
        edoc = enh.read(d)
        hd_file = enh.hd_path(d)
        if edoc is not None and edoc.get("released") and not hd_file.is_file() \
                and not render_full.vertical_path(config, owner).is_file():
            return ReleaseResult(owner, False, 0, [])
        if edoc is None or edoc.get("state") != enh.DONE:
            raise BackupError("tập chưa có bản HD hoàn tất (enhance chưa xong); không có gì để giải phóng")
        lease = edoc.get("lease")
        exp = enh.parse_iso((lease or {}).get("expires_at")) if lease else None
        if exp is not None and exp > clock():
            raise BackupError("tập đang có lease enhance; giải phóng sau khi xong", 409)
        cur_hd = _current_hd(d)
        if cur_hd is None:
            raise BackupError("không có file HD khớp enhance.json (sha256) để giải phóng")
        doc = read_backup(d)
        conf = doc.get("confirmed") or {}
        problems = []
        c = conf.get("hd") or {}
        if not c:
            problems.append("chưa xác nhận bản HD")
        elif c.get("sha256") != cur_hd[0] or c.get("size") != cur_hd[1]:
            problems.append("sha bản HD không khớp file hiện tại")
        vpath = render_full.vertical_path(config, owner)
        vgot = vertical_sha(config, owner, doc)
        if vgot is None:
            if not allow_no_vertical:
                problems.append("chưa có bản dọc (tạo bản dọc trước để giữ chất lượng HD, hoặc gửi allow_no_vertical)")
        else:
            c = conf.get("vertical") or {}
            if not c:
                problems.append("chưa xác nhận bản dọc")
            elif c.get("sha256") != vgot[0] or c.get("size") != vgot[1]:
                problems.append("sha bản dọc không khớp file hiện tại")
        if problems:
            raise BackupError("; ".join(problems))
        stamp = now or utc_now()
        removed_doc = {"hd": {"sha256": cur_hd[0], "size": cur_hd[1]}}
        if vgot is not None:
            removed_doc["vertical"] = {"sha256": vgot[0], "size": vgot[1]}
        doc.update(episode_id=owner, released={"released_at": stamp, **removed_doc})
        atomic_write_json(backup_path(d), doc)
        edoc.update(released=True, released_at=stamp)
        enh.write(d, edoc)
        targets = [hd_file]
        if not owner.endswith(SUFFIX):  # a ``.kt``-only video has no further khai thị mirror / hard link
            enh.mirror(config, owner)
            targets.append(enh.hd_path(d.parent / (owner + SUFFIX)))
        if vgot is not None:
            targets.append(vpath)
        freed = cur_hd[1] + (vgot[1] if vgot is not None else 0)
        removed = []
        for p in targets:
            if p.is_file() or p.is_symlink():
                p.unlink()
                removed.append(str(p))
    log.warning("backup: released %s: %s (%d bytes)", owner, ", ".join(removed), freed)
    return ReleaseResult(owner, True, freed, removed)
