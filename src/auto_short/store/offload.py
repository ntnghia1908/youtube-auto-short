"""HD2b G6: send current verticals to the store, confirm exact bytes, then apply HD1 release rules."""
from __future__ import annotations

import hashlib
import threading
from contextlib import nullcontext
from pathlib import Path

from ..config import Config
from ..enhance import state as enh
from ..render import full
from ..review import backup
from ..workspace import atomic_write_json, iter_manifests
from . import index_cache
from .backup import _destination, _matches
from .client import StoreClient, StoreMismatch


class OffloadStopped(Exception):
    """The web lifespan requested a cooperative stop; this is not an upload failure."""


def _check_stop(stop: threading.Event | None) -> None:
    if stop is not None and stop.is_set():
        raise OffloadStopped()


def _sha256_file(path: Path, stop: threading.Event | None) -> str:
    """Bound cancellation latency to one read, including the final block."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            _check_stop(stop)
            chunk = fh.read(1024 * 1024)
            _check_stop(stop)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _vertical_snapshot(config: Config, owner: str, *, stop=None) -> tuple[tuple[str, int, int], dict] | None:
    """Hash outside the backup lock, then merge only an unchanged file's cache into the latest document."""
    _check_stop(stop)
    d = Path(config.workspace.dir) / owner
    path = full.vertical_path(config, owner)
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    with backup._LOCK:
        doc = backup.read_backup(d)
    cache = doc.get("vertical_sha")
    if isinstance(cache, dict) and (cache.get("size"), cache.get("mtime_ns")) == (st.st_size, st.st_mtime_ns) \
            and isinstance(cache.get("sha256"), str):
        sha = cache["sha256"]
    else:
        sha = _sha256_file(path, stop)
    size, mtime_ns = st.st_size, st.st_mtime_ns
    with backup._LOCK:
        _check_stop(stop)
        st = path.stat()
        if (st.st_size, st.st_mtime_ns) != (size, mtime_ns):
            raise backup.BackupError("bản dọc đã đổi trong lúc tính sha256; thử lại sau", 409)
        doc = backup.read_backup(d)
        cache = dict(sha256=sha, size=size, mtime_ns=mtime_ns)
        if doc.get("vertical_sha") != cache:
            doc["vertical_sha"] = cache
            atomic_write_json(backup.backup_path(d), doc)
    return (sha, size, mtime_ns), doc


def candidates(config: Config, *, busy=None, errors: dict | None = None, stop=None) -> list[dict]:
    """Stat-only pending inventory; an uncached identity stays pending until selection verifies it."""
    owners = {enh.owner_for(config, ws.episode_id) for ws, _ in iter_manifests(Path(config.workspace.dir))}
    rows = []
    for owner in sorted(owners):
        _check_stop(stop)
        d = Path(config.workspace.dir) / owner
        if backup.lease_active(d) or (busy is not None and busy(owner)):
            continue
        try:
            path = full.ready_file(config, owner)
            if path is None or not full.current(config, owner):
                continue
            st = path.stat()
            doc = backup.read_backup(d)
            cache = doc.get("vertical_sha")
            if isinstance(cache, dict) and (cache.get("size"), cache.get("mtime_ns")) == (st.st_size, st.st_mtime_ns) \
                    and _matches((doc.get("confirmed") or {}).get("vertical") or {},
                                 cache.get("sha256"), st.st_size):
                continue
        except (OSError, backup.BackupError) as exc:
            if errors is not None:
                errors[owner] = str(exc)
            continue
        rows.append(dict(owner=owner, path=path, size=st.st_size, mtime_ns=st.st_mtime_ns,
                         has_hd=enh.has_hd(d)))
    return sorted(rows, key=lambda row: (row["has_hd"], -row["size"], row["owner"]))


def next_candidate(config: Config, rows: list[dict], *, errors: dict, stop=None) -> dict | None:
    """Hash in priority order, stopping at the first unconfirmed file; skip unreadable owners."""
    for row in rows:
        _check_stop(stop)
        if row["owner"] in errors:
            continue
        try:
            snapshot = _vertical_snapshot(config, row["owner"], stop=stop)
            if snapshot is None:
                continue
            (sha, size, _), doc = snapshot
            if not _matches((doc.get("confirmed") or {}).get("vertical") or {}, sha, size):
                return row
        except (OSError, backup.BackupError) as exc:
            errors[row["owner"]] = str(exc)
    return None


def push_vertical(config: Config, owner: str, *, client=None, busy=None, lock=None, stop=None) -> dict:
    """D2: HEAD + unchanged stat authorize confirm; a missing HD confirmation only postpones release."""
    if not config.store.enabled or not config.store.offload:
        return {"owner": owner, "pushed": False, "released": False}
    _check_stop(stop)
    owner = enh.owner_for(config, owner)
    d = Path(config.workspace.dir) / owner
    if backup.lease_active(d) or (busy is not None and busy(owner)):
        return {"owner": owner, "pushed": False, "released": False, "busy": True}
    path = full.ready_file(config, owner)
    if path is None or not full.current(config, owner):
        raise StoreMismatch("bản dọc không còn hiện hành")
    snapshot = _vertical_snapshot(config, owner, stop=stop)
    if snapshot is None:
        raise StoreMismatch("không còn bản dọc trên VM")
    (sha, size, mtime_ns), _ = snapshot
    if backup.lease_active(d) or (busy is not None and busy(owner)):
        return {"owner": owner, "pushed": False, "released": False, "busy": True}
    series, source_name = _destination(config, enh.owner_id(owner))
    name = "[HD Mobile] " + source_name.removeprefix("[Goc] ")
    client = client or StoreClient.from_config(config.store)
    _check_stop(stop)
    client.put(enh.owner_id(owner), "vertical", series, name, path, sha)
    index_cache.invalidate()
    _check_stop(stop)
    if not _matches(client.head(enh.owner_id(owner), "vertical"), sha, size):
        raise StoreMismatch("kho xác nhận bản dọc khác sha256 / kích thước")
    with lock if lock is not None else nullcontext():
        if backup.lease_active(d) or (busy is not None and busy(owner)):
            return {"owner": owner, "pushed": False, "released": False, "busy": True}
        try:
            st = path.stat()
        except OSError:
            raise StoreMismatch("bản dọc đã đổi trong lúc đẩy") from None
        if (st.st_size, st.st_mtime_ns) != (size, mtime_ns) or not full.current(config, owner):
            raise StoreMismatch("bản dọc đã đổi trong lúc đẩy; không xác nhận")
        _check_stop(stop)
        backup.confirm(config, owner, "vertical", sha)
        try:
            _check_stop(stop)
            released = backup.release(config, owner)
        except backup.BackupError as exc:
            return dict(owner=owner, pushed=True, released=False, sha256=sha, size=size,
                        status="đã xác nhận, chưa giải phóng", reason=str(exc))
    return dict(owner=owner, pushed=True, released=released.changed, sha256=sha, size=size,
                freed=released.freed, status="đã xác nhận, đã giải phóng")
