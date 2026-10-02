"""P7 ``work/<id>/posts.json``: schema, validation, read / write. User state (not a stage input, like CP8.5
``publish.json``): a broken file is reported (``post_error``) and never overwritten by a read.

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P7, P8.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..workspace import atomic_write_json

POSTS_NAME = "posts.json"
SCHEMA_VERSION = 1
AI, RAW, MANUAL, DOC = "ai", "raw", "manual", "doc"  # DOC: CP8.19 text taken from the lecture document
ORIGINS = (AI, RAW, MANUAL, DOC)
ENTRY_KEYS = ("clip_id", "candidate_id", "source_sha256", "paragraphs", "origin", "image", "link", "posted_at",
             "updated_at")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PostsError(Exception):
    """``posts.json`` is missing an entry, malformed, or invalid per P7."""


def empty_posts(episode_id: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "posts": []}


def _timestamp(value: object, *, nullable: bool) -> bool:
    if value is None:
        return nullable
    return isinstance(value, str) and bool(_TIMESTAMP_RE.match(value))


def check_posts(doc: object, episode_id: str) -> dict:
    """P7 schema check of a parsed ``posts.json``; returns it unchanged or raises :class:`PostsError`."""
    def bad(msg: str) -> PostsError:
        return PostsError(f"{POSTS_NAME}: {msg}")

    if not isinstance(doc, dict) or list(doc) != ["schema_version", "episode_id", "posts"]:
        raise bad('must be an object with keys "schema_version", "episode_id", "posts" in this order')
    if doc["schema_version"] != SCHEMA_VERSION:
        raise bad(f"unsupported schema_version {doc['schema_version']!r}")
    if doc["episode_id"] != episode_id:
        raise bad(f"episode_id {doc['episode_id']!r} != {episode_id!r}")
    if not isinstance(doc["posts"], list):
        raise bad("posts must be an array")
    seen = set()
    for n, e in enumerate(doc["posts"]):
        where = f"posts[{n}]"
        if not isinstance(e, dict) or list(e) != list(ENTRY_KEYS):
            raise bad(f"{where} must be an object with keys {list(ENTRY_KEYS)}")
        if not isinstance(e["clip_id"], str) or not e["clip_id"]:
            raise bad(f"{where}.clip_id must be a non-empty string")
        if not isinstance(e["candidate_id"], str) or not e["candidate_id"]:
            raise bad(f"{where}.candidate_id must be a non-empty string")
        if not isinstance(e["source_sha256"], str) or not _SHA_RE.match(e["source_sha256"]):
            raise bad(f"{where}.source_sha256 must be a sha256 hex digest")
        if not isinstance(e["paragraphs"], list) or not e["paragraphs"] \
                or not all(isinstance(p, str) and p.strip() for p in e["paragraphs"]):
            raise bad(f"{where}.paragraphs must be a non-empty array of non-empty strings")
        if e["origin"] not in ORIGINS:
            raise bad(f"{where}.origin {e['origin']!r} not in {list(ORIGINS)}")
        if e["image"] is not None and not (isinstance(e["image"], str) and e["image"]):
            raise bad(f"{where}.image must be null or a non-empty string")
        if e["link"] is not None and not (isinstance(e["link"], str) and e["link"]):
            raise bad(f"{where}.link must be null or a non-empty string")
        if not _timestamp(e["posted_at"], nullable=True):
            raise bad(f"{where}.posted_at must be null or an ISO UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)")
        if not _timestamp(e["updated_at"], nullable=False):
            raise bad(f"{where}.updated_at must be an ISO UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)")
        if e["clip_id"] in seen:
            raise bad(f"duplicate clip_id {e['clip_id']!r}")
        seen.add(e["clip_id"])
    return doc


def read_posts(path: Path, episode_id: str) -> dict:
    """``posts.json`` checked against P7; a missing file means no post yet (empty document)."""
    if not path.is_file():
        return empty_posts(episode_id)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PostsError(f"cannot read {path}: {exc}") from exc
    return check_posts(doc, episode_id)


def read_posts_quiet(path: Path, episode_id: str) -> dict:
    """Like :func:`read_posts`, but a broken file is treated as empty (usage counting across every workspace,
    P5: one broken ``posts.json`` must not stop image assignment for every other episode)."""
    try:
        return read_posts(path, episode_id)
    except PostsError:
        return empty_posts(episode_id)


def _order(doc: dict, clip_order: list[str]) -> dict:
    """Canonical document: entries sorted by ``clip_order`` (render_manifest.json order, P7); unknown ids
    (a Short deleted since) last, by id."""
    pos = {cid: n for n, cid in enumerate(clip_order)}
    posts = sorted(doc["posts"], key=lambda e: (pos.get(e["clip_id"], len(pos)), e["clip_id"]))
    return {"schema_version": SCHEMA_VERSION, "episode_id": doc["episode_id"], "posts": posts}


def find(doc: dict, clip_id: str) -> dict | None:
    return next((e for e in doc["posts"] if e["clip_id"] == clip_id), None)


def with_compose(doc: dict, clip_order: list[str], *, clip_id: str, candidate_id: str, source_sha256: str,
                 paragraphs: list[str], origin: str, image: str | None, now: str) -> dict:
    """P7: store an AI / raw compose result. A re-compose (an entry for ``clip_id`` already exists) keeps its
    ``image``, ``link``, ``posted_at``; a brand new entry gets ``image`` (the caller resolves P5's "least used")."""
    old = find(doc, clip_id)
    if old is not None:
        entry = {**old, "candidate_id": candidate_id, "source_sha256": source_sha256, "paragraphs": list(paragraphs),
                 "origin": origin, "updated_at": now}
    else:
        entry = {"clip_id": clip_id, "candidate_id": candidate_id, "source_sha256": source_sha256,
                 "paragraphs": list(paragraphs), "origin": origin, "image": image, "link": None, "posted_at": None,
                 "updated_at": now}
    rest = [e for e in doc["posts"] if e["clip_id"] != clip_id]
    return _order({**doc, "posts": rest + [entry]}, clip_order)


def with_fields(doc: dict, clip_order: list[str], clip_id: str, changes: dict, *, now: str) -> dict:
    """P9 ``PUT``: merge ``changes`` (``paragraphs`` / ``image`` / ``link``) into the existing entry of ``clip_id``;
    raises :class:`PostsError` when there is no post yet (soạn bài trước)."""
    old = find(doc, clip_id)
    if old is None:
        raise PostsError(f"chưa có bài đăng cho {clip_id!r}; bấm \"Soạn bài\" trước")
    entry = {**old, **changes, "updated_at": now}
    rest = [e for e in doc["posts"] if e["clip_id"] != clip_id]
    return _order({**doc, "posts": rest + [entry]}, clip_order)


def with_posted(doc: dict, clip_order: list[str], clip_id: str, value: bool, *, now: str) -> dict:
    """P8: tick / untick "Đã đăng bài" (``posted_at``); raises :class:`PostsError` when there is no post yet."""
    return with_fields(doc, clip_order, clip_id, {"posted_at": now if value else None}, now=now)


def write(path: Path, doc: dict) -> None:
    atomic_write_json(path, doc)
