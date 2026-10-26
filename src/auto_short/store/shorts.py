"""SHO1a: verify every rendered Short, durably record its location, then release VM bytes."""
from __future__ import annotations

import re
import time
from contextlib import nullcontext
from pathlib import Path

from ..config import Config
from ..render.stage import RENDER_MANIFEST_NAME
from ..web import episodes as ep
from ..web.storage import episode_sizes, short_offload_plan
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import index_cache
from .backup import _destination, _matches
from .client import StoreClient, StoreMismatch
from .offload import _check_stop, _sha256_file


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
