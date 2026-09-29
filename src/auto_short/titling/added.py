"""AI title of one Short added by hand (CP9 C6): the CP6 prompt, validation and retries (G3–G6, ``[titling]`` as
configured) for a single clip, outside the ``titling`` stage (``titles.json`` / manifest untouched).

The result goes to ``review.json`` ``added[]`` (``ai_title``, ``alternatives``, ``title`` when none was typed) via
:func:`auto_short.review.shorts.set_added_ai_title`; every call is appended to ``work/<id>/review_titling_log.json``
(not byte-stable: it keeps a timestamp per entry). All attempts failing -> the Short stays ``untitled`` and waits
for a manual title (like CP7 R2).

Canonical contract: docs/decisions/CP8.2-title-override-contract.md T8 (CP9); prompt / validation:
docs/decisions/CP6-titling-contract.md G3–G6.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..selection.client import ChatClient, OllamaClient, resolve_host
from ..workspace import Workspace, atomic_write_json, validate_episode_id
from .logic import TITLED, UNTITLED, VALID, TitlingError, choose_title
from .prompt import RESPONSE_SCHEMA, prompt_sha256, prompt_texts, render_user_prompt, system_prompt
from .stage import _title_clip, model_block

log = logging.getLogger("auto_short")

LOG_NAME = "review_titling_log.json"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AddedTitle:
    clip_id: str
    status: str  # titled | untitled
    title: str | None
    alternatives: list[dict]
    error: str | None  # no schema-valid response at all (connection, bad JSON...); None otherwise
    stored: bool  # review.json updated


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_log(path: Path, episode_id: str, entry: dict) -> None:
    doc = {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "entries": []}
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(old, dict) and isinstance(old.get("entries"), list) and old.get("episode_id") == episode_id:
            doc = old
    except (OSError, ValueError):
        pass
    doc["entries"].append(entry)
    atomic_write_json(path, doc)


def title_added(episode_id: str, config: Config, clip_id: str, *, client: ChatClient | None = None,
                sleep: Callable[[float], None] = time.sleep) -> AddedTitle:
    """Title the added Short ``clip_id`` with the AI (one clip, CP6 G3–G6) and store the result."""
    from ..review.shorts import added_titling_input, set_added_ai_title

    cfg = config.titling
    try:
        prompt_texts(cfg.prompt_version)
    except ValueError as exc:
        raise TitlingError(f"titling.prompt_version: {exc}") from exc
    ws = Workspace(config.workspace.dir, validate_episode_id(episode_id))
    inp = added_titling_input(episode_id, config, clip_id)
    system = system_prompt(cfg.prompt_version, max_chars=cfg.max_chars, n_options=cfg.n_options)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": render_user_prompt(cfg.prompt_version, title=inp["video_title"],
                                                               duration=inp["duration"], text=inp["text"])}]
    chat = client or OllamaClient(resolve_host(cfg.ollama_host), timeout=cfg.timeout)
    clog = {"clip_id": clip_id, "candidate_id": inp["candidate_id"], "text": inp["text"], "ai_calls": []}
    t0 = time.monotonic()
    error = None
    try:
        records = _title_clip(chat, cfg, messages, clip_id, inp["text"], clog, sleep)
    except TitlingError as exc:
        records, error = None, str(exc)
    chosen, alternatives = choose_title(records) if records else (None, [])
    status = TITLED if chosen else UNTITLED
    _append_log(ws.dir / LOG_NAME, ws.episode_id, {
        "at": _now(), "clip_id": clip_id, "candidate_id": inp["candidate_id"], "source": inp["source"],
        "model": model_block(cfg), "prompt_version": cfg.prompt_version,
        "prompt_sha256": prompt_sha256(cfg.prompt_version), "system_prompt": system,
        "response_format": RESPONSE_SCHEMA, "duration": inp["duration"], "text": inp["text"],
        "ai_calls": clog["ai_calls"], "status": status, "title": chosen["title"] if chosen else None,
        "alternatives": alternatives, "error": error})
    stored = set_added_ai_title(episode_id, config, clip_id, title=chosen["title"] if chosen else None,
                                alternatives=alternatives)
    secs = time.monotonic() - t0
    if chosen:
        log.info("titling: added Short %s: %r (%d/%d options valid, %d call(s), %.1f s)", clip_id, chosen["title"],
                 sum(r["status"] == VALID for r in records), len(records), len(clog["ai_calls"]), secs)
    else:
        log.warning("titling: WARNING: added Short %s untitled after %d attempt(s) (%.1f s)%s; set a title by hand",
                    clip_id, len(clog["ai_calls"]), secs, f": {error}" if error else "")
    return AddedTitle(clip_id, status, chosen["title"] if chosen else None, alternatives, error, stored)
