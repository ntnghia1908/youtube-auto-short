"""CP8.30 P5d: re-deal library images to the posts that are not ticked "Đã đăng bài".

A post with ``posted_at`` keeps its image. Every other post (in every episode workspace) gets, one after the other,
the image used least so far (the posted posts count, the posts being re-dealt count as they are dealt), never one
already used by another post of the same video (the Short episode and its ``<id>.kt`` khai thị episode), ties broken by
a stable hash of (episode, clip, image) so the result is shuffled yet reproducible. Only ``image`` changes (``stale``,
``updated_at`` and every other field stay as they are). ``posts.json`` is backed up before it is written.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P5d.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import store
from .store import PostsError

BACKUP_DIR = "_post-backups"
KEEP_BACKUPS = 5
_EP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def base_id(episode_id: str) -> str:
    return episode_id[:-3] if episode_id.endswith(".kt") else episode_id


@dataclass
class Plan:
    changes: dict[str, dict[str, str | None]] = field(default_factory=dict)  # episode -> {clip_id: new image}
    old: dict[str, dict[str, str | None]] = field(default_factory=dict)
    unposted: int = 0
    posted: int = 0
    episodes: int = 0
    skipped_broken: list[str] = field(default_factory=list)
    counts_after: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> int:
        return sum(len(v) for v in self.changes.values())

    def spread(self) -> int:
        """max - min posts per library image after the plan (0 / 1 = even)."""
        return (max(self.counts_after.values()) - min(self.counts_after.values())) if self.counts_after else 0


def _tie(episode_id: str, clip_id: str, image: str) -> str:
    return hashlib.sha256(f"{episode_id}|{clip_id}|{image}".encode()).hexdigest()


def plan(work_dir: Path, library: list[str]) -> Plan:
    """Pure: what :func:`apply` would change. ``library`` = image names (an empty library changes nothing)."""
    result = Plan()
    docs: dict[str, dict] = {}
    if work_dir.is_dir():
        for d in sorted(work_dir.iterdir()):
            if not d.is_dir() or not _EP_RE.match(d.name) or not (d / store.POSTS_NAME).is_file():
                continue
            try:
                docs[d.name] = store.read_posts(d / store.POSTS_NAME, d.name)
            except PostsError:
                result.skipped_broken.append(d.name)
    result.episodes = len(docs)
    if not library:
        return result
    lib = set(library)
    counts = {name: 0 for name in library}
    video_used: dict[str, set[str]] = {}
    todo: list[tuple[str, dict]] = []
    for eid, doc in docs.items():
        for entry in doc["posts"]:
            if entry["posted_at"] is not None:
                result.posted += 1
                img = entry["image"]
                if img in lib:
                    counts[img] += 1
                if img:
                    video_used.setdefault(base_id(eid), set()).add(img)
            else:
                todo.append((eid, entry))
    result.unposted = len(todo)
    for eid, entry in todo:
        used = video_used.setdefault(base_id(eid), set())
        pool = [n for n in library if n not in used] or list(library)  # library smaller than the video: allow repeats
        pick = min(pool, key=lambda n: (counts[n], _tie(eid, entry["clip_id"], n)))
        counts[pick] += 1
        used.add(pick)
        if entry["image"] != pick:
            result.changes.setdefault(eid, {})[entry["clip_id"]] = pick
            result.old.setdefault(eid, {})[entry["clip_id"]] = entry["image"]
    result.counts_after = counts
    return result


def apply(work_dir: Path, the_plan: Plan, *, now: datetime | None = None) -> Path | None:
    """Write the plan: back up each affected ``posts.json`` to ``<work>/_post-backups/<timestamp>/<episode>.json``
    (the last :data:`KEEP_BACKUPS` backup folders are kept), then set the new images. Returns the backup folder.
    The caller holds the posts lock."""
    if not the_plan.changes:
        return None
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    root = work_dir / BACKUP_DIR
    bdir = root / stamp
    bdir.mkdir(parents=True, exist_ok=True)
    for eid, per_clip in the_plan.changes.items():
        path = work_dir / eid / store.POSTS_NAME
        doc = store.read_posts(path, eid)
        shutil.copy2(path, bdir / f"{eid}.json")
        for entry in doc["posts"]:
            if entry["clip_id"] in per_clip and entry["posted_at"] is None:
                entry["image"] = per_clip[entry["clip_id"]]
        store.write(path, doc)
    for old in sorted(p for p in root.iterdir() if p.is_dir())[:-KEEP_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)
    return bdir
