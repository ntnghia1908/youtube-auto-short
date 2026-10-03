"""The "Đã xem" (watched) state of Shorts / khai thị videos (CP8.21 D4): ``work/<episode_id>/watched.json``.

User state like ``publish.json`` (CP8.5 X4), in its own file so the "Đã đăng" file keeps its schema: no stage reads
it, so ticking never makes the render stale and needs no job. A missing file = nothing watched. Entry
``(clip_id, candidate_id, sha256, at)``: ``sha256`` = the video file at tick time, so a later re-render shows
"đã xem bản cũ".
Canonical contract: docs/decisions/CP8.3-web-contract.md § Đã xem (watched.json).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import Config
from ..workspace import atomic_write_json
from .logic import ReviewError
from .publish import (_AT_RE, _SHA_RE, _paths, _render_shorts, _tickable, publish_status, utc_now)

WATCHED_NAME = "watched.json"
SCHEMA_VERSION = 1
DOC_KEYS = ("schema_version", "episode_id", "watched")
ENTRY_KEYS = ("clip_id", "candidate_id", "sha256", "at")


def empty_watched(episode_id: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "watched": []}


def check_watched(doc: object, episode_id: str) -> dict:
    def bad(msg: str) -> ReviewError:
        return ReviewError(f"{WATCHED_NAME}: {msg}")

    if not isinstance(doc, dict) or list(doc) != list(DOC_KEYS):
        raise bad(f"must be an object with keys {list(DOC_KEYS)}")
    if doc["schema_version"] != SCHEMA_VERSION:
        raise bad(f"unsupported schema_version {doc['schema_version']!r}")
    if doc["episode_id"] != episode_id:
        raise bad(f"episode_id {doc['episode_id']!r} != {episode_id!r}")
    if not isinstance(doc["watched"], list):
        raise bad("watched must be an array")
    seen = set()
    for n, e in enumerate(doc["watched"]):
        if not isinstance(e, dict) or list(e) != list(ENTRY_KEYS):
            raise bad(f"watched[{n}] must be an object with keys {list(ENTRY_KEYS)}")
        if not all(isinstance(e[k], str) and e[k] for k in ENTRY_KEYS):
            raise bad(f"watched[{n}]: every value must be a non-empty string")
        if not _SHA_RE.match(e["sha256"]) or not _AT_RE.match(e["at"]):
            raise bad(f"watched[{n}]: sha256 must be 64 hex chars, at UTC ISO-8601 (YYYY-MM-DDTHH:MM:SSZ)")
        if e["clip_id"] in seen:
            raise bad(f"duplicate clip_id {e['clip_id']!r}")
        seen.add(e["clip_id"])
    return doc


def read_watched(path: Path, episode_id: str) -> dict:
    """``watched.json`` checked; a missing file means nothing watched."""
    if not path.is_file():
        return empty_watched(episode_id)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError(f"cannot read {path}: {exc}") from exc
    return check_watched(doc, episode_id)


def watched_status(doc: dict, shorts: list[dict]) -> dict[str, dict]:
    """Per clip of the render manifest: ``{"watched": bool, "stale": bool, "at": str | None}`` (same rules as
    :func:`publish_status`)."""
    st = publish_status({"published": doc["watched"]}, shorts)
    return {cid: {"watched": v["published"], "stale": v["stale"], "at": v["at"]} for cid, v in st.items()}


def set_watched(episode_id: str, config: Config, clip_id: str, value: bool, *, at: str | None = None) -> dict:
    """Tick (``value`` True) or untick "Đã xem" of ``clip_id``. A tick records the ``candidate_id`` and ``sha256`` of
    the video in the last committed ``render_manifest.json`` and needs a rendered file; ticking the same file again
    changes nothing (keeps ``at``), a new file replaces the tick; unticking always works. Returns
    ``{"clip_id", "watched", "stale", "at"}``. Never touches review.json / render / publish.json."""
    if not isinstance(value, bool):
        raise ReviewError("value must be true or false")
    ws, rm_path = _paths(episode_id, config)
    if ws.load_manifest() is None:
        raise ReviewError(f"no episode {episode_id!r}")
    shorts = _render_shorts(ws, rm_path)
    order = [s.get("clip_id") for s in shorts]
    short = next((s for s in shorts if s.get("clip_id") == clip_id), None)
    path = ws.dir / WATCHED_NAME
    doc = read_watched(path, ws.episode_id)
    rest = [e for e in doc["watched"] if e["clip_id"] != clip_id]
    if value:
        if not _tickable(short):
            raise ReviewError(f"Short {clip_id} has no rendered file to mark as watched")
        old = next((e for e in doc["watched"] if e["clip_id"] == clip_id), None)
        if old is not None and old["candidate_id"] == short["candidate_id"] and old["sha256"] == short["sha256"]:
            new = doc
        else:
            entry = {"clip_id": clip_id, "candidate_id": short["candidate_id"], "sha256": short["sha256"],
                     "at": at or utc_now()}
            new = {**doc, "watched": rest + [entry]}
    else:
        new = {**doc, "watched": rest}
    pos = {cid: n for n, cid in enumerate(order)}
    new = {"schema_version": SCHEMA_VERSION, "episode_id": doc["episode_id"],
           "watched": sorted(new["watched"], key=lambda e: (pos.get(e["clip_id"], len(pos)), e["clip_id"]))}
    if new != doc:
        atomic_write_json(path, new)
    status = watched_status(new, [short] if short is not None else [])
    return {"clip_id": clip_id, **status.get(clip_id, {"watched": False, "stale": False, "at": None})}
