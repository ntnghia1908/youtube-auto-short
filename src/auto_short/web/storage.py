"""Storage tab (CP8.6 S1, S2, S4): disk usage of the server, size of every episode, clean-up recommendations and
the low-disk warning. Stdlib only; sizes via ``os.scandir`` (no ``du``), cached up to 30 s. Nothing here deletes
anything: the recommendations are only shown, the user runs them (``archive_source`` / ``delete_episode``).

Canonical contract: docs/decisions/CP8.3-web-contract.md W9. Exception to "nothing deletes" (S5): the opt-in-by-default
auto clean-up of a finished video's source (:func:`auto_archive_plan`, run by the web app).
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..review import ReviewError, episode_complete, publish_status, read_archive
from ..review.archive import source_files
from ..post.store import POSTS_NAME, read_posts_quiet
from ..review.publish import PUBLISH_NAME, read_publish
from ..khaithi import SUFFIX as KT_SUFFIX
from ..workspace import DONE, iter_manifests
from . import episodes as ep

GB = 1_000_000_000
OLD_DAYS = 7  # P1: "cũ" = older than 7 days
WARN_BYTES, WARN_RATIO = 10 * GB, 0.10  # P2: warning banner below 10 GB free or below 10 % free
BLOCK_BYTES = 3 * GB  # P2: refuse a new URL below 3 GB free
BLOCK_MESSAGE = ("Ổ đĩa server còn dưới 3 GB trống: không nhận video mới. "
                 "Dọn bớt ở tab Bộ nhớ rồi thử lại.")  # 507 of POST /api/episodes; CP8.10: job failed before ingest
CACHE_SECONDS = 30.0

DiskUsage = Callable[[Path], tuple[int, int, int]]  # shutil.disk_usage-like: (total, used, free)

# Episode states (S1)
PROCESSING, DONE_STATE, FAILED, INCOMPLETE, ARCHIVED, ORPHAN = (
    "processing", "done", "failed", "incomplete", "archived", "orphan")


def tree_size(path: Path) -> int:
    """Apparent size (bytes) of the regular files under ``path``; symlinks are not followed, directories
    themselves are not counted. A missing path is 0."""
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            if cur == path and path.is_file() and not path.is_symlink():
                total += path.stat().st_size
    return total


def tree_links(path: Path) -> dict[tuple[int, int], int]:
    """Regular files under ``path`` with more than one hard link: ``{(st_dev, st_ino): size}``. Only these can be
    shared between two workspaces (e.g. the source of ``<id>`` and ``<id>.kt``, CP8.9)."""
    out: dict[tuple[int, int], int] = {}
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            if st.st_nlink > 1:
                                out[(st.st_dev, st.st_ino)] = st.st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return out


def parse_time(value: object) -> float | None:
    """``YYYY-MM-DDTHH:MM:SSZ`` (manifest / job times) -> epoch seconds."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def disk_info(config: Config, disk_usage: DiskUsage = shutil.disk_usage) -> list[dict]:
    """``shutil.disk_usage`` of the drive holding ``workspace.dir`` and, when it is another drive, ``output_dir``."""
    out, seen = [], set()
    for label, path in (("work", Path(config.workspace.dir)), ("output", Path(config.render.output_dir))):
        probe = path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            dev = probe.stat().st_dev
        except OSError:
            dev = None
        if dev is not None and dev in seen:
            continue
        seen.add(dev)
        total, used, free = disk_usage(probe)
        out.append({"label": label, "path": str(path), "total": total, "used": used, "free": free})
    return out


def warning(disks: list[dict]) -> dict:
    """S4: ``warn`` (red banner) when a drive has < 10 GB or < 10 % free; ``block`` (refuse new URLs) < 3 GB."""
    free = min((d["free"] for d in disks), default=0)
    warn = any(d["free"] < WARN_BYTES or (d["total"] and d["free"] < WARN_RATIO * d["total"]) for d in disks)
    return {"free": free, "warn": warn, "block": free < BLOCK_BYTES,
            "warn_bytes": WARN_BYTES, "warn_ratio": WARN_RATIO, "block_bytes": BLOCK_BYTES}


def _last_activity(manifest: dict, fallback: float) -> float:
    times = []
    for entry in (manifest.get("stages") or {}).values():
        for key in ("started_at", "finished_at"):
            t = parse_time((entry or {}).get(key))
            if t is not None:
                times.append(t)
    return max(times, default=fallback)


def video_id(episode_id: str) -> str:
    """The video an episode belongs to: ``<id>`` (Short) and ``<id>.kt`` (khai thị) are parts of video ``<id>``."""
    return episode_id[:-len(KT_SUFFIX)] if episode_id.endswith(KT_SUFFIX) and len(episode_id) > len(KT_SUFFIX) \
        else episode_id


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def episode_sizes(config: Config, active: set[str] | None = None) -> list[dict]:
    """S1 table: one row per workspace with a manifest (+ output dirs without a workspace: ``orphan``), sorted by
    total size (largest first)."""
    active = active or set()
    work_root, out_root = Path(config.workspace.dir), Path(config.render.output_dir)
    rows, known = [], set()
    for ws, manifest in iter_manifests(work_root):
        eid = ws.episode_id
        known.add(eid)
        src_files = source_files(ws.dir)
        source = sum(p.lstat().st_size for p in src_files)
        work_total = tree_size(ws.dir)
        shorts = tree_size(out_root / eid)
        src_links = {}
        for p in src_files:
            st = p.lstat()
            if st.st_nlink > 1 and not p.is_symlink():
                src_links[(st.st_dev, st.st_ino)] = st.st_size
        links = {**tree_links(ws.dir), **tree_links(out_root / eid)}
        stages = manifest.get("stages") or {}
        statuses = [(stages.get(s) or {}).get("status") for s in ep.PIPELINE_STAGES]
        archive = read_archive(ws.dir)
        rm = ep._render_manifest(config, eid)
        rendered = [s for s in (rm or {}).get("shorts", []) if isinstance(s, dict) and s.get("status") == "rendered"]
        try:
            pub = read_publish(ws.dir / PUBLISH_NAME, eid)
            status = publish_status(pub, rendered)
            complete = rm is not None and episode_complete((stages.get("render") or {}).get("status"),
                                                           rm.get("shorts") or [], pub)
        except ReviewError:
            status, complete = {}, False
        published = sum(1 for s in rendered if status.get(s.get("clip_id"), {}).get("published"))
        # D3: composed community posts not yet ticked "Đã đăng bài" (only for Shorts still rendered)
        rendered_ids = {s.get("clip_id") for s in rendered}
        post_unticked = sum(1 for e in read_posts_quiet(ws.dir / POSTS_NAME, eid)["posts"]
                            if e["posted_at"] is None and e["clip_id"] in rendered_ids)
        # D4: since when the episode has been "Xong" — latest of the ticks, publish.json / render_manifest.json
        # mtimes and render finish (stateless: survives a restart; any later change moves it forward)
        complete_since = None
        if complete:
            ticks = [t for t in (parse_time(e.get("at")) for e in (pub.get("published") or [])) if t is not None]
            finished = parse_time((stages.get("render") or {}).get("finished_at"))
            complete_since = max([*ticks, _mtime(ws.dir / PUBLISH_NAME),
                                  _mtime(out_root / eid / ep.RENDER_MANIFEST),
                                  *([finished] if finished is not None else [])])
        if eid in active or "running" in statuses:
            state = PROCESSING
        elif archive is not None:
            state = ARCHIVED
        elif all(st == DONE for st in statuses):
            state = DONE_STATE
        elif "failed" in statuses:
            state = FAILED
        else:
            state = INCOMPLETE
        try:
            mtime = ws.manifest_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        meta = ep._read_json(ws.dir / "metadata.json") or {}
        rows.append({
            "id": eid, "title": meta.get("title"), "state": state,
            "source_kind": (manifest.get("source") or {}).get("kind"),
            "source": source, "shorts_bytes": shorts, "other": work_total - source, "total": work_total + shorts,
            "shorts": len(rendered), "published": published, "complete": complete,
            "post_unticked": post_unticked, "complete_since": complete_since,
            "links": links, "source_links": src_links,  # hard-linked files, for de-duplicated sums (not in the API)
            "render_finished_at": parse_time((stages.get("render") or {}).get("finished_at"))
            if (stages.get("render") or {}).get("status") == DONE else None,
            "last_activity": _last_activity(manifest, mtime),
            "archived_at": (archive or {}).get("archived_at"),
        })
    if out_root.is_dir():
        for entry in sorted(out_root.iterdir()):
            if entry.name in known or not entry.is_dir() or entry.is_symlink() or not ep.valid_episode_id(entry.name):
                continue
            size = tree_size(entry)
            rows.append({"id": entry.name, "title": None, "state": ORPHAN, "source_kind": None, "source": 0,
                         "shorts_bytes": size, "other": 0, "total": size, "shorts": 0, "published": 0,
                         "complete": False, "post_unticked": 0, "complete_since": None,
                         "render_finished_at": None, "last_activity": entry.stat().st_mtime, "archived_at": None})
    rows.sort(key=lambda r: (-r["total"], r["id"]))
    return rows


def _sum(parts: list[dict], field: str, links_field: str) -> int:
    """Bytes freed by acting on ``parts``: ``sum(field)`` counting a hard-linked file (same ``(st_dev, st_ino)``
    in several parts, e.g. the source of ``<id>`` and ``<id>.kt``) once."""
    total, seen = sum(r[field] for r in parts), set()
    for r in parts:
        for key, size in (r.get(links_field) or {}).items():
            if key in seen:
                total -= size
            seen.add(key)
    return total


def _can_archive(r: dict) -> bool:
    return r["state"] == DONE_STATE and r["source_kind"] == "youtube" and r["source"] > 0


def _videos(rows: list[dict]) -> dict[str, list[dict]]:
    """D1: rows grouped by video id (videos in first-row order, the Short before its khai thị inside a video;
    ``orphan`` rows are not parts of a video)."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        if r["state"] != ORPHAN:
            out.setdefault(video_id(r["id"]), []).append(r)
    return {vid: sorted(parts, key=lambda r: r["id"] != vid) for vid, parts in out.items()}


def recommend(rows: list[dict], now: float, *, old_days: int = OLD_DAYS) -> list[dict]:
    """S2 (priority order; one recommendation per **video** — Short ``<id>`` and khai thị ``<id>.kt`` are its
    parts; the first rule that applies; a video with a part that is processing is skipped). Each action names the
    bytes it frees and the episodes it applies to (``episodes``):

    1. every part is "Xong" (CP8.7 L4, ``complete``) -> ``delete`` (all parts) and, while a source can be cleaned
       up, ``archive``;
    2. every part with a cleanable source finished its render more than ``old_days`` ago -> ``archive``;
    3. every part failed / unfinished with no activity for ``old_days`` -> ``delete``.

    Every recommendation also carries ``post_unticked`` (D3): composed posts of the video not yet ticked.
    """
    limit = now - old_days * 86400
    out = []
    for vid, parts in _videos(rows).items():
        if any(r["state"] == PROCESSING for r in parts):
            continue
        title = next((r["title"] for r in parts if r["title"]), None)
        base = {"episode_id": parts[0]["id"], "episodes": [r["id"] for r in parts], "video_id": vid, "title": title,
                "post_unticked": sum(r.get("post_unticked", 0) for r in parts)}
        arch = [r for r in parts if _can_archive(r)]
        if all(r.get("complete") for r in parts):
            actions = [{"action": "delete", "frees": _sum(parts, "total", "links"),
                        "episodes": [r["id"] for r in parts]}]
            if arch:
                actions.insert(0, {"action": "archive", "frees": _sum(arch, "source", "source_links"),
                                   "episodes": [r["id"] for r in arch]})
            out.append({**base, "rule": "all_published", "actions": actions})
        elif arch and all(r["render_finished_at"] is not None and r["render_finished_at"] < limit for r in arch):
            out.append({**base, "rule": "old_source",
                        "age_days": min(int((now - r["render_finished_at"]) // 86400) for r in arch),
                        "actions": [{"action": "archive", "frees": _sum(arch, "source", "source_links"),
                                     "episodes": [r["id"] for r in arch]}]})
        elif all(r["state"] in (FAILED, INCOMPLETE) and r["last_activity"] < limit for r in parts):
            out.append({**base, "rule": "stale_unfinished",
                        "age_days": min(int((now - r["last_activity"]) // 86400) for r in parts),
                        "actions": [{"action": "delete", "frees": _sum(parts, "total", "links"),
                                     "episodes": [r["id"] for r in parts]}]})
    return out


def auto_archive_plan(rows: list[dict], now: float, grace_seconds: float) -> list[dict]:
    """S5 / D4 (pure): videos whose source is to be cleaned up automatically. A video qualifies when it has at
    least one part with a cleanable source, no part is processing, **every** part is "Xong" and the state has
    held for ``grace_seconds`` (``complete_since`` of the latest part). Returns
    ``[{"video_id", "episodes": [ids to archive], "freed": bytes, "since": epoch}]`` in row order."""
    plan = []
    for vid, parts in _videos(rows).items():
        if any(r["state"] == PROCESSING for r in parts) or not all(r.get("complete") for r in parts):
            continue
        arch = [r for r in parts if _can_archive(r)]
        since = max((r.get("complete_since") or now for r in parts), default=now)
        if arch and now - since >= grace_seconds:
            plan.append({"video_id": vid, "episodes": [r["id"] for r in arch],
                         "freed": _sum(arch, "source", "source_links"), "since": since})
    return plan


def _models_dir(config: Config) -> Path:
    """The folder the transcript stage uses (``faster-whisper`` ``download_root``): a relative ``models_dir``
    is relative to the server's working directory, exactly like the stage; shown absolute."""
    return Path(config.transcript.whisper.models_dir).absolute()


class StorageCache:
    """``report()`` recomputed at most every ``CACHE_SECONDS`` (``invalidate()`` after a delete / clean-up)."""

    def __init__(self, config: Config, *, disk_usage: DiskUsage = shutil.disk_usage,
                 clock: Callable[[], float] = time.time, monotonic: Callable[[], float] = time.monotonic):
        self._config, self._disk_usage, self._clock, self._mono = config, disk_usage, clock, monotonic
        self._lock = threading.Lock()
        self._cached: tuple[float, frozenset, dict] | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    def status(self) -> dict:
        """S4 banner / block (cheap, not cached)."""
        disks = disk_info(self._config, self._disk_usage)
        return {"disks": disks, **warning(disks)}

    def block_message(self) -> str | None:
        """:data:`BLOCK_MESSAGE` when a drive is below the block threshold (W9 507, CP8.10 check before ingest)."""
        return BLOCK_MESSAGE if self.status()["block"] else None

    def report(self, active: set[str] | None = None) -> dict:
        key = frozenset(active or ())
        with self._lock:
            if self._cached and self._cached[1] == key and self._mono() - self._cached[0] < CACHE_SECONDS:
                return self._cached[2]
        now = self._clock()
        rows = episode_sizes(self._config, set(key))
        disks = disk_info(self._config, self._disk_usage)
        models = _models_dir(self._config)
        report = {
            "computed_at": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "disks": disks, **warning(disks),
            "episodes": [{k: v for k, v in r.items() if k not in ("links", "source_links")} for r in rows],
            "totals": {"source": sum(r["source"] for r in rows), "shorts": sum(r["shorts_bytes"] for r in rows),
                       "other": sum(r["other"] for r in rows), "episodes": sum(r["total"] for r in rows)},
            "caches": [{"name": "Model Whisper", "path": str(models), "bytes": tree_size(models),
                        "exists": models.is_dir()}],
            "recommendations": recommend(rows, now),
            "old_days": OLD_DAYS,
        }
        with self._lock:
            self._cached = (self._mono(), key, report)
        return report
