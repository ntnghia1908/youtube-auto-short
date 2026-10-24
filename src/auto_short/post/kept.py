"""CP8.38: immutable post snapshots kept independently of episode tombstones.

Only the posted tick can change. A second deletion appends distinct versions of a
clip, so an optional array index disambiguates ticks for repeated clip ids.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..review.logic import ReviewError
from ..review.names import hashtags
from ..review.tombstone import tombstone_dir
from ..review.titles import list_titles
from ..workspace import WorkspaceError, atomic_write_json, read_json_dict, validate_episode_id
from . import logic, store

log = logging.getLogger("auto_short")
CopyText = Callable[[dict], str]
ENTRY_KEYS = {"clip_id", "short_title", "paragraphs", "image", "link", "copy_text", "posted_at"}


class KeptPostsError(ReviewError):
    """An existing snapshot is unreadable; never overwrite it with a fallback."""


def kept_path(config: Config, episode_id: str) -> Path:
    return tombstone_dir(config) / f"{validate_episode_id(episode_id)}.posts.json"


def check(doc: object, episode_id: str) -> dict:
    def nullable_text(value):
        return value is None or isinstance(value, str)

    def timestamp(value):
        try:
            return isinstance(value, str) and datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ") is not None
        except ValueError:
            return False

    valid = isinstance(doc, dict) and set(doc) == {"schema_version", "episode_id", "title", "deleted_at", "posts"}
    if not valid or type(doc["schema_version"]) is not int or doc["schema_version"] != 1 \
            or doc["episode_id"] != episode_id or not nullable_text(doc["title"]) \
            or not timestamp(doc["deleted_at"]) or not isinstance(doc["posts"], list):
        raise KeptPostsError(f"invalid kept posts for {episode_id}")
    for e in doc["posts"]:
        if not isinstance(e, dict) or set(e) != ENTRY_KEYS \
                or not isinstance(e["clip_id"], str) or not e["clip_id"] \
                or not nullable_text(e["short_title"]) \
                or not isinstance(e["paragraphs"], list) or not e["paragraphs"] \
                or not all(isinstance(p, str) and p.strip() for p in e["paragraphs"]) \
                or not all(nullable_text(e[k]) for k in ("image", "link")) \
                or not isinstance(e["copy_text"], str) or not e["copy_text"] \
                or (e["posted_at"] is not None and not timestamp(e["posted_at"])):
            raise KeptPostsError(f"invalid kept post entry for {episode_id}")
    return doc


def read(config: Config, episode_id: str) -> dict | None:
    path = kept_path(config, episode_id)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KeptPostsError(f"cannot read {path}: {exc}") from exc
    return check(doc, episode_id)


def build(episode_id: str, config: Config, *, copy_text: CopyText | None = None,
          now: str | None = None) -> dict | None:
    """Snapshot every unticked entry, including clips no longer rendered.

    The web supplies its Posts-tab view for exact current custom hashtags. Other
    callers use the same P4 composer with the config's default hashtags.
    """
    ws = Path(config.workspace.dir) / validate_episode_id(episode_id)
    try:
        entries = store.read_posts(ws / store.POSTS_NAME, episode_id)["posts"]
    except store.PostsError as exc:
        log.warning("delete episode %s: skipping broken posts.json: %s", episode_id, exc)
        return None
    entries = [e for e in entries if e["posted_at"] is None and e["paragraphs"]]
    if not entries:
        return None
    rm = read_json_dict(Path(config.render.output_dir) / episode_id / "render_manifest.json") or {}
    titles = {s.get("clip_id"): s.get("title") for s in rm.get("shorts", []) if isinstance(s, dict)} \
        if rm.get("episode_id") == episode_id else {}
    if copy_text is None:
        try:
            tab_titles = {c["clip_id"]: c["title"] for c in list_titles(episode_id, config)["clips"]}
        except ReviewError:
            tab_titles = {}
        fields = ((read_json_dict(ws / "titles.json") or {}).get("header") or {}).get("fields")
        tags = hashtags(fields.get("series") if fields else None, config.web.hashtags)

        def copy_text(entry):
            return logic.compose_copy_text(title=tab_titles.get(entry["clip_id"]), paragraphs=entry["paragraphs"],
                                           header_fields=fields, link=entry["link"], hashtags=tags)

    meta = read_json_dict(ws / "metadata.json") or {}
    return check({"schema_version": 1, "episode_id": episode_id, "title": meta.get("title"),
                  "deleted_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "posts": [{"clip_id": e["clip_id"], "short_title": titles.get(e["clip_id"]),
                             "paragraphs": list(e["paragraphs"]), "image": e["image"], "link": e["link"],
                             "copy_text": copy_text(e), "posted_at": None} for e in entries]}, episode_id)


def write_kept(episode_id: str, config: Config, *, copy_text: CopyText | None = None,
               now: str | None = None) -> dict | None:
    new = build(episode_id, config, copy_text=copy_text, now=now)
    if new is None:
        return None
    old = read(config, episode_id)
    posts = list(old["posts"]) if old else []
    for entry in new["posts"]:
        if not any(e["clip_id"] == entry["clip_id"] and e["paragraphs"] == entry["paragraphs"] for e in posts):
            posts.append(entry)
    doc = {**new, "posts": posts}
    atomic_write_json(kept_path(config, episode_id), check(doc, episode_id))
    return doc


def list_kept(config: Config) -> list[dict]:
    out = []
    for path in tombstone_dir(config).glob("*.posts.json"):
        episode_id = path.name.removesuffix(".posts.json")
        try:
            doc = read(config, episode_id)
        except (KeptPostsError, WorkspaceError) as exc:
            log.warning("skipping kept posts %s: %s", path, exc)
            continue
        if doc is not None:
            out.append(doc)
    return sorted(out, key=lambda d: (d["deleted_at"], d["episode_id"]), reverse=True)


def set_posted(config: Config, episode_id: str, clip_id: str, value: bool, *, index: int | None = None,
               now: str | None = None) -> dict | None:
    doc = read(config, episode_id)
    if doc is None:
        return None
    entry = next((e for n, e in enumerate(doc["posts"]) if e["clip_id"] == clip_id
                  and (index is None or n == index)), None)
    if entry is None:
        return None
    entry["posted_at"] = (now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")) if value else None
    atomic_write_json(kept_path(config, episode_id), check(doc, episode_id))
    return entry


def remove(config: Config, episode_id: str) -> bool:
    path = kept_path(config, episode_id)
    if not path.is_file():
        return False
    path.unlink()
    return True
