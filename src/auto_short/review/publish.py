"""The "Đã đăng" (published) state of Shorts (CP8.5 X4): ``work/<episode_id>/publish.json``.

User state, not a pipeline input: no stage reads it, so ticking never makes the render stale and needs no job.
Key ``(clip_id, candidate_id)`` like ``review.json`` (CP8.2 T3); ``sha256`` = the Short file at tick time, so a
later re-render (e.g. new title) shows "đã đăng bản cũ".
Canonical contract: docs/decisions/CP8.3-web-contract.md § Đã đăng (publish.json).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..workspace import Workspace, WorkspaceError, atomic_write_json, validate_episode_id
from .logic import ReviewError

PUBLISH_NAME = "publish.json"
SCHEMA_VERSION = 1
DOC_KEYS = ("schema_version", "episode_id", "published")
ENTRY_KEYS = ("clip_id", "candidate_id", "sha256", "at")
RENDER_MANIFEST = "render_manifest.json"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# --- pure ------------------------------------------------------------------------------------------------------

def empty_publish(episode_id: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "published": []}


def check_publish(doc: object, episode_id: str) -> dict:
    """Schema check of a parsed ``publish.json``; returns it unchanged or raises ReviewError."""
    def bad(msg: str) -> ReviewError:
        return ReviewError(f"{PUBLISH_NAME}: {msg}")

    if not isinstance(doc, dict) or list(doc) != list(DOC_KEYS):
        raise bad(f"must be an object with keys {list(DOC_KEYS)}")
    if doc["schema_version"] != SCHEMA_VERSION:
        raise bad(f"unsupported schema_version {doc['schema_version']!r}")
    if doc["episode_id"] != episode_id:
        raise bad(f"episode_id {doc['episode_id']!r} != {episode_id!r}")
    if not isinstance(doc["published"], list):
        raise bad("published must be an array")
    seen = set()
    for n, e in enumerate(doc["published"]):
        if not isinstance(e, dict) or list(e) != list(ENTRY_KEYS):
            raise bad(f"published[{n}] must be an object with keys {list(ENTRY_KEYS)}")
        if not all(isinstance(e[k], str) and e[k] for k in ENTRY_KEYS):
            raise bad(f"published[{n}]: every value must be a non-empty string")
        if not _SHA_RE.match(e["sha256"]) or not _AT_RE.match(e["at"]):
            raise bad(f"published[{n}]: sha256 must be 64 hex chars, at UTC ISO-8601 (YYYY-MM-DDTHH:MM:SSZ)")
        if e["clip_id"] in seen:
            raise bad(f"duplicate clip_id {e['clip_id']!r}")
        seen.add(e["clip_id"])
    return doc


def with_published(doc: dict, clip_order: list[str], *, clip_id: str, candidate_id: str, sha256: str,
                   at: str) -> dict:
    """New document with ``clip_id`` ticked (replacing an older tick), sorted by ``clip_order``."""
    rest = [e for e in doc["published"] if e["clip_id"] != clip_id]
    entry = {"clip_id": clip_id, "candidate_id": candidate_id, "sha256": sha256, "at": at}
    return _order({**doc, "published": rest + [entry]}, clip_order)


def without_published(doc: dict, clip_order: list[str], clip_id: str) -> tuple[dict, bool]:
    rest = [e for e in doc["published"] if e["clip_id"] != clip_id]
    return _order({**doc, "published": rest}, clip_order), len(rest) != len(doc["published"])


def _order(doc: dict, clip_order: list[str]) -> dict:
    pos = {cid: n for n, cid in enumerate(clip_order)}
    entries = sorted(doc["published"], key=lambda e: (pos.get(e["clip_id"], len(pos)), e["clip_id"]))
    return {"schema_version": SCHEMA_VERSION, "episode_id": doc["episode_id"], "published": entries}


def publish_status(doc: dict, shorts: list[dict]) -> dict[str, dict]:
    """Per clip of the render manifest ``shorts``: ``{"published": bool, "stale": bool, "at": str | None}``.
    A tick counts only for the same ``(clip_id, candidate_id)``; ``stale`` = ticked but the current file differs
    from the one ticked (``sha256``); a deleted Short (no file) keeps its tick and is not stale."""
    ticks = {e["clip_id"]: e for e in doc["published"]}
    out = {}
    for s in shorts:
        t = ticks.get(s.get("clip_id"))
        if t is None or t["candidate_id"] != s.get("candidate_id"):
            out[s.get("clip_id")] = {"published": False, "stale": False, "at": None}
            continue
        current = s.get("sha256") if s.get("status") == "rendered" else None
        out[s.get("clip_id")] = {"published": True, "stale": current is not None and current != t["sha256"],
                                 "at": t["at"]}
    return out


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- episode -----------------------------------------------------------------------------------------------------

def _paths(episode_id: str, config: Config) -> tuple[Workspace, Path]:
    try:
        ws = Workspace(Path(config.workspace.dir), validate_episode_id(episode_id))
    except WorkspaceError as exc:
        raise ReviewError(str(exc)) from exc
    return ws, Path(config.render.output_dir) / ws.episode_id / RENDER_MANIFEST


def read_publish(path: Path, episode_id: str) -> dict:
    """``publish.json`` checked; a missing file means nothing ticked."""
    if not path.is_file():
        return empty_publish(episode_id)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError(f"cannot read {path}: {exc}") from exc
    return check_publish(doc, episode_id)


def load_published(episode_id: str, config: Config) -> list[dict]:
    """Ticks of the episode (entries ``{"clip_id", "candidate_id", "sha256", "at"}``); ``[]`` without a file."""
    ws, _ = _paths(episode_id, config)
    return list(read_publish(ws.dir / PUBLISH_NAME, ws.episode_id)["published"])


def set_published(episode_id: str, config: Config, clip_id: str, value: bool, *, at: str | None = None) -> dict:
    """Tick (``value`` True) or untick the Short ``clip_id``. A tick records the ``candidate_id`` and ``sha256`` of
    the Short in the last committed ``render_manifest.json`` and needs a rendered file; unticking always works.
    Returns the new status ``{"clip_id", "published", "stale", "at"}``. Never touches review.json / render."""
    if not isinstance(value, bool):
        raise ReviewError("value must be true or false")
    ws, rm_path = _paths(episode_id, config)
    if ws.load_manifest() is None:
        raise ReviewError(f"no episode {episode_id!r}")
    try:
        rm = json.loads(rm_path.read_text(encoding="utf-8"))
        shorts = [s for s in rm["shorts"] if isinstance(s, dict)] if rm.get("episode_id") == ws.episode_id else []
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        shorts = []
    order = [s.get("clip_id") for s in shorts]
    short = next((s for s in shorts if s.get("clip_id") == clip_id), None)
    path = ws.dir / PUBLISH_NAME
    doc = read_publish(path, ws.episode_id)
    if value:
        if short is None or short.get("status") != "rendered" or not isinstance(short.get("sha256"), str) \
                or not isinstance(short.get("candidate_id"), str):
            raise ReviewError(f"Short {clip_id} has no rendered file to mark as published")
        new = with_published(doc, order, clip_id=clip_id, candidate_id=short["candidate_id"],
                             sha256=short["sha256"], at=at or utc_now())
    else:
        new, removed = without_published(doc, order, clip_id)
        if not removed:
            new = doc
    if new != doc:
        atomic_write_json(path, new)
    status = publish_status(new, [short] if short is not None else [])
    return {"clip_id": clip_id, **status.get(clip_id, {"published": False, "stale": False, "at": None})}
