"""SHO1a: verify every rendered Short, durably record its location, then release VM bytes."""
from __future__ import annotations

import os
import re
import tempfile
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

from ..config import Config
from ..render.stage import RENDER_MANIFEST_NAME
from ..web import episodes as ep
from ..web.storage import episode_sizes, short_offload_plan
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import index_cache
from .backup import _destination, _matches
from .client import StoreClient, StoreError, StoreMismatch, StoreUnavailable
from .offload import _check_stop, _sha256_file


def fetch_released(config: Config, short: ep.StoredShort, dest: Path, *, client=None) -> Path:
    """Use the shared verified/resumable fetch and restore the original ARC1 timestamp."""
    if not config.store.enabled:
        raise StoreUnavailable("Short của tập đang ở kho 3090; bật [store] để sửa")
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = client or StoreClient.from_config(config.store)
    client.fetch(short.episode_id, "short", dest, short.sha256, clip=short.clip)
    os.utime(dest, ns=(short.mtime_ns, short.mtime_ns))
    return dest


def restore_released(config: Config, episode_id: str, *, client=None) -> None:
    """Restore just this part before render; local files win and successful downloads survive retries."""
    from ..render.stage import RenderError, StoreWait
    from .borrow import WAIT_PREFIX

    record = Path(config.render.output_dir) / episode_id / "store.json"
    released = (read_json_dict(record) or {}).get("released")
    if not released:
        return
    if not config.store.enabled:
        raise RenderError("Short của tập đang ở kho 3090; bật [store] để sửa")
    locations = {cid: p for cid, p, _ in ep.short_locations(config, episode_id) or []}
    try:
        if not isinstance(released, dict):
            raise StoreMismatch("hồ sơ Short đã giải phóng không hợp lệ")
        for cid in released:
            location = locations.get(cid)
            if isinstance(location, Path):
                continue
            if not isinstance(location, ep.StoredShort):
                raise StoreMismatch(f"không biết sha256 của Short đã giải phóng ({episode_id}/{cid})")
            fetch_released(config, location, record.parent / "shorts" / location.clip, client=client)
    except StoreError as exc:
        raise StoreWait(f"{WAIT_PREFIX}: {exc}") from exc
    record.unlink()


@contextmanager
def borrow_short(config: Config, location: Path | ep.StoredShort, folder: Path, *, client=None):
    """A private copy per compilation; borrow tracking protects active copies from the temp sweeper."""
    from .borrow import _BORROWED, _LOCK

    if isinstance(location, Path):
        yield location
        return
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".store-shorts-", dir=folder) as tmp:
        dest = Path(tmp) / location.clip
        part = dest.with_name(dest.name + ".part")
        with _LOCK:
            _BORROWED[dest] += 1
            _BORROWED[part] += 1
        try:
            try:
                fetch_released(config, location, dest, client=client)
            except StoreError as exc:
                raise StoreUnavailable(f"Short {location.episode_id}/{location.clip} đang ở kho 3090, "
                                       "3090 không trả lời — bấm Ghép lại sau") from exc
            yield dest
        finally:
            with _LOCK:
                del _BORROWED[dest]
                del _BORROWED[part]


def offload_snapshot(config: Config, *, busy=None, now: float | None = None,
                     failed=(), last_error=None) -> dict:
    """G7: stat/release metadata only, including grace waiters; never query the store."""
    now = time.time() if now is None else now
    rows = episode_sizes(config)
    local, released = set(), {}
    for row in rows:
        for _cid, location, _name in ep.short_locations(config, row["id"]) or []:
            if isinstance(location, Path):
                local.add(row["id"])
            elif isinstance(location, ep.StoredShort):
                released[row["id"]] = released.get(row["id"], 0) + location.size
    grace = config.storage.auto_archive_grace_minutes * 60
    ready = short_offload_plan(rows, now, grace, local)
    all_done = short_offload_plan(rows, now, 0, local)
    eligible = {r["video_id"] for r in ready if busy is None or not busy(r["video_id"])}
    errors = eligible.intersection(failed)
    return dict(enabled=config.store.offload_shorts, episodes=len(released), bytes=sum(released.values()),
                eligible=len(eligible - errors), waiting_days=len(all_done) - len(ready), failed=len(errors),
                last_error=last_error if errors else None)


def candidates(config: Config, *, busy=None, now: float | None = None, stop=None) -> list[dict]:
    """Stat-only selection; no store request or content hashing. A busy part excludes its whole video."""
    _check_stop(stop)
    rows = episode_sizes(config)
    local = set()
    for row in rows:
        _check_stop(stop)
        if ep.short_files(config, row["id"]):
            local.add(row["id"])
    plan = short_offload_plan(rows, time.time() if now is None else now,
                              config.storage.auto_archive_grace_minutes * 60, local)
    return [item for item in plan if busy is None or not busy(item["video_id"])]


def push_video(config: Config, video_id: str, *, client=None, busy=None, lock=None, stop=None,
               clock=time.time) -> dict:
    """No deletion until ALL current files (both parts) pass HEAD and every release record is durable.

    Submission uses the web's existing lock only for the final recheck/commit; hashing and uploads yield
    to jobs via busy/stop checks. An interrupted commit is safe: local files take precedence on reads.
    """
    result = {"video_id": video_id, "released": False}
    if not config.store.enabled or not config.store.offload_shorts:
        return result
    _check_stop(stop)
    item = next((r for r in candidates(config, busy=busy, now=clock(), stop=stop)
                 if r["video_id"] == video_id), None)
    if item is None:
        return result
    client = client or StoreClient.from_config(config.store)
    snapshots, documents, released = [], {}, {}
    # Validate the entire video first. Missing/stale records cannot authorize a partial release.
    for eid in item["episodes"]:
        out = Path(config.render.output_dir) / eid
        doc = read_json_dict(out / RENDER_MANIFEST_NAME)
        documents[eid] = doc
        locations = {cid: p for cid, p, _ in ep.short_locations(config, eid) or []}
        released[eid] = {}
        for short in (doc or {}).get("shorts", []):
            if short.get("status") != "rendered":
                continue
            _check_stop(stop)
            if busy is not None and busy(video_id):
                return result
            cid, sha = short.get("clip_id"), short.get("sha256")
            if (not isinstance(cid, str) or not ep.valid_clip_id(cid)
                    or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)
                    or short.get("file") != f"shorts/{cid}.mp4"):
                raise StoreMismatch("manifest Short không hợp lệ")
            location = locations.get(cid)
            if isinstance(location, Path):
                st = location.stat()
                record = dict(sha256=sha, size=st.st_size, mtime_ns=st.st_mtime_ns)
                if _sha256_file(location, stop) != sha:
                    raise StoreMismatch("file Short trên VM lệch sha256 manifest")
            elif isinstance(location, ep.StoredShort):
                record = dict(sha256=sha, size=location.size, mtime_ns=location.mtime_ns)
            else:
                raise StoreMismatch("thiếu file Short chưa được giải phóng")
            released[eid][cid] = record
            snapshots.append((eid, cid, location, record))
    series, source_name = _destination(config, video_id)
    stem = source_name.removeprefix("[Goc] ").removesuffix(".mp4")
    for eid, cid, location, record in snapshots:
        _check_stop(stop)
        if busy is not None and busy(video_id):
            return result
        if isinstance(location, Path):
            prefix = "KhaiThi" if eid.endswith(".kt") else "Short"
            client.put(eid, "short", series, f"[{prefix}] {stem} - {cid}.mp4", location,
                       record["sha256"], clip=cid + ".mp4")
            index_cache.invalidate()
        _check_stop(stop)
        if not _matches(client.head(eid, "short", clip=cid + ".mp4"), record["sha256"], record["size"]):
            raise StoreMismatch("kho xác nhận Short khác sha256 / kích thước")
    with lock if lock is not None else nullcontext():
        _check_stop(stop)
        # Recheck grace, all publish ticks and jobs too: a user can edit while uploads run.
        if not any(r["video_id"] == video_id and r["episodes"] == item["episodes"]
                   for r in candidates(config, busy=busy, now=clock(), stop=stop)):
            return result
        for eid, doc in documents.items():
            if read_json_dict(Path(config.render.output_dir) / eid / RENDER_MANIFEST_NAME) != doc:
                raise StoreMismatch("manifest Short đã đổi trong lúc đẩy")
        for _eid, _cid, location, record in snapshots:
            if isinstance(location, Path):
                st = location.stat()
                if (st.st_size, st.st_mtime_ns) != (record["size"], record["mtime_ns"]):
                    raise StoreMismatch("file Short đã đổi trong lúc đẩy")
        at = utc_now()
        for eid, records in released.items():
            _check_stop(stop)
            atomic_write_json(Path(config.render.output_dir) / eid / "store.json", {"released": records, "at": at})
        for _eid, _cid, location, _record in snapshots:
            _check_stop(stop)
            if isinstance(location, Path):
                location.unlink()
    return {"video_id": video_id, "released": True,
            "freed": sum(r["size"] for _, _, p, r in snapshots if isinstance(p, Path))}
