"""HD2b G6: send current verticals to the store, confirm exact bytes, then apply HD1 release rules."""
from __future__ import annotations

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


def candidates(config: Config, *, busy=None, errors: dict | None = None) -> list[dict]:
    """D1: include old files too. Cache each digest in backup.json; caller runs this in a thread."""
    owners = {enh.owner_for(config, ws.episode_id) for ws, _ in iter_manifests(Path(config.workspace.dir))}
    rows = []
    for owner in sorted(owners):
        d = Path(config.workspace.dir) / owner
        if backup.lease_active(d) or (busy is not None and busy(owner)):
            continue
        path = full.ready_file(config, owner)
        if path is None or not full.current(config, owner):
            continue
        try:
            with backup._LOCK:
                doc = backup.read_backup(d)
                before = doc.get("vertical_sha")
                got = backup.vertical_sha(config, owner, doc)
                if got is None:
                    continue
                if doc.get("vertical_sha") != before:
                    atomic_write_json(backup.backup_path(d), doc)
                sha, size, mtime_ns = got
                if _matches((doc.get("confirmed") or {}).get("vertical") or {}, sha, size):
                    continue
        except (OSError, backup.BackupError) as exc:
            if errors is not None:
                errors[owner] = str(exc)
            continue  # one unreadable / changing file must not block the rest of the inventory
        rows.append(dict(owner=owner, path=path, sha256=sha, size=size, mtime_ns=mtime_ns,
                         has_hd=enh.has_hd(d)))
    return sorted(rows, key=lambda row: (row["has_hd"], -row["size"], row["owner"]))


def push_vertical(config: Config, owner: str, *, client=None, busy=None, lock=None) -> dict:
    """D2: HEAD + unchanged stat authorize confirm; a missing HD confirmation only postpones release."""
    if not config.store.enabled or not config.store.offload:
        return {"owner": owner, "pushed": False, "released": False}
    owner = enh.owner_for(config, owner)
    d = Path(config.workspace.dir) / owner
    if backup.lease_active(d) or (busy is not None and busy(owner)):
        return {"owner": owner, "pushed": False, "released": False, "busy": True}
    path = full.ready_file(config, owner)
    if path is None or not full.current(config, owner):
        raise StoreMismatch("bản dọc không còn hiện hành")
    with backup._LOCK:
        doc = backup.read_backup(d)
        got = backup.vertical_sha(config, owner, doc)
        if got is None:
            raise StoreMismatch("không còn bản dọc trên VM")
        atomic_write_json(backup.backup_path(d), doc)
    sha, size, mtime_ns = got
    series, source_name = _destination(config, enh.owner_id(owner))
    name = "[HD Mobile] " + source_name.removeprefix("[Goc] ")
    client = client or StoreClient.from_config(config.store)
    client.put(enh.owner_id(owner), "vertical", series, name, path, sha)
    index_cache.invalidate()
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
        backup.confirm(config, owner, "vertical", sha)
        try:
            released = backup.release(config, owner)
        except backup.BackupError as exc:
            return dict(owner=owner, pushed=True, released=False, sha256=sha, size=size,
                        status="đã xác nhận, chưa giải phóng", reason=str(exc))
    return dict(owner=owner, pushed=True, released=released.changed, sha256=sha, size=size,
                freed=released.freed, status="đã xác nhận, đã giải phóng")
