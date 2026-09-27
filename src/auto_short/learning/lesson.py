"""Stage ``lesson`` (CL1 C7, C8, C9): normalized subtitle lines + AI Pinyin/meaning -> ``lesson.json``.

``id``, ``start``, ``end`` and ``zh`` always come from ``normalize(parse_json3(subtitle.json3))``
(speech segments starting inside the window); only ``pinyin`` and ``vi`` come from the model.
``lesson.json`` has a fixed key order and no creation time (byte-stable). The AI log goes to
``lesson_log.json``, never into ``lesson.json``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from .. import hashing
from ..config import Config
from ..selection.client import ChatClient
from ..transcript.normalize import normalize
from ..transcript.parsers import ParseError, parse_json3
from ..workspace import Workspace, atomic_write_json
from .enrich import EnrichmentError, enrich
from .media import CLIP_NAME, MEDIA_NAME
from .prompt import prompt_sha256
from .subtitle import SOURCE_NAME, SUBTITLE_NAME, in_window, is_han

log = logging.getLogger("auto_short")

STAGE = "lesson"
LESSON_NAME = "lesson.json"
LOG_NAME = "lesson_log.json"
LESSON_SCHEMA_VERSION = 1
DOWNSTREAM: tuple[str, ...] = ()
ARTIFACTS = [LESSON_NAME, LOG_NAME]

# [learning] keys in the config hash (C9); ollama_host / timeout / retries / retry_backoff are execution-only.
HASH_KEYS = ("model", "think", "temperature", "seed", "num_ctx", "prompt_version")


class LessonError(Exception):
    """The lesson could not be built; the message is user-facing."""


def used_config(config: Config) -> dict:
    cfg = config.learning
    used = {f"learning.{k}": getattr(cfg, k) for k in HASH_KEYS}
    try:
        used["learning.prompt_sha256"] = prompt_sha256(cfg.prompt_version)
    except ValueError:
        used["learning.prompt_sha256"] = None
    used["learning.batch_lines"] = cfg.batch_lines
    used["learning.window_seconds"] = cfg.window_seconds
    return used


def inputs(ws: Workspace) -> list[dict]:
    """``subtitle.json3`` + ``source.json`` (+ ``clip.mp4`` when present), with their sha256."""
    names = [SUBTITLE_NAME, SOURCE_NAME] + ([CLIP_NAME] if (ws.dir / CLIP_NAME).is_file() else [])
    return [{"path": name, "sha256": hashing.sha256_file(ws.dir / name)} for name in names]


def lesson_lines(data: bytes, window: float) -> list[dict]:
    """``[{id, start, end, zh}]`` of the speech segments starting before ``window``."""
    return [{"id": s["id"], "start": s["start"], "end": s["end"], "zh": s["text"]}
            for s in in_window(normalize(parse_json3(data)), window)]


def lines_sha256(lines: list[dict]) -> str:
    base = [{"id": ln["id"], "start": ln["start"], "end": ln["end"], "zh": ln["zh"]} for ln in lines]
    return hashlib.sha256(hashing.canonical_json(base).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LessonError(f"cannot read {path.name}: {exc}") from exc


def media_block(ws: Workspace) -> dict | None:
    clip = ws.dir / CLIP_NAME
    if not clip.is_file():
        return None
    window = _read_json(ws.dir / MEDIA_NAME).get("window") or {}
    if not isinstance(window, dict) or "start" not in window or "end" not in window:
        raise LessonError(f"{MEDIA_NAME} has no window")
    return {"path": CLIP_NAME, "sha256": hashing.sha256_file(clip), "start": window["start"], "end": window["end"]}


def lesson_document(episode_id: str, config: Config, source: dict, subtitle_sha256: str, media: dict | None,
                    lines: list[dict], enrichment: dict[str, tuple[str, str]]) -> dict:
    cfg = config.learning
    video = source.get("video") or {}
    selected = source.get("selected") or {}
    return {
        "schema_version": LESSON_SCHEMA_VERSION,
        "episode_id": episode_id,
        "video": {"id": video.get("id", episode_id), "title": video.get("title"), "channel": video.get("channel"),
                  "duration": video.get("duration"), "url": f"https://youtu.be/{episode_id}"},
        "window": {"start": 0.0, "end": cfg.window_seconds},
        "subtitle": {"path": SUBTITLE_NAME, "sha256": subtitle_sha256, "track": selected.get("key"),
                     "auto": selected.get("auto")},
        "media": media,
        "enrichment": {"model": cfg.model, "prompt_version": cfg.prompt_version, "think": cfg.think,
                       "temperature": cfg.temperature, "seed": cfg.seed},
        "lines_sha256": lines_sha256(lines),
        "stats": {"lines": len(lines), "han_chars": sum(1 for ln in lines for c in ln["zh"] if is_han(c))},
        "lines": [{"id": ln["id"], "start": ln["start"], "end": ln["end"], "zh": ln["zh"],
                   "pinyin": enrichment[ln["id"]][0], "vi": enrichment[ln["id"]][1]} for ln in lines],
    }


def remove_outputs(ws: Workspace) -> None:
    for name in ARTIFACTS:
        (ws.dir / name).unlink(missing_ok=True)


def produce(ws: Workspace, config: Config, client: ChatClient, sleep: Callable[[float], None] = time.sleep,
            failure: dict | None = None) -> list[str]:
    """The stage action. On an enrichment failure its log is put in ``failure["log"]`` (written by the
    orchestrator after ``record_failure``) and the error is raised."""
    cfg = config.learning
    sub_path = ws.dir / SUBTITLE_NAME
    try:
        data = sub_path.read_bytes()
    except OSError as exc:
        raise LessonError(f"cannot read {SUBTITLE_NAME}: {exc}") from exc
    source = _read_json(ws.dir / SOURCE_NAME)
    try:
        lines = lesson_lines(data, cfg.window_seconds)
    except ParseError as exc:
        raise LessonError(f"{SUBTITLE_NAME}: parse error: {exc}") from exc
    if not lines:
        raise LessonError(f"no speech line starts before {cfg.window_seconds} s")
    media = media_block(ws)
    log.info("%s: %d lines, model %s (think=%s) via %s", STAGE, len(lines), cfg.model, cfg.think,
             getattr(client, "host", type(client).__name__))
    remove_outputs(ws)
    try:
        enrichment, log_doc = enrich(ws.episode_id, lines, cfg, client, sleep)
    except EnrichmentError as exc:
        if failure is not None:
            failure["log"] = exc.log
        raise
    doc = lesson_document(ws.episode_id, config, source, hashlib.sha256(data).hexdigest(), media, lines,
                          enrichment)
    try:
        atomic_write_json(ws.dir / LOG_NAME, log_doc)
        atomic_write_json(ws.dir / LESSON_NAME, doc)
    except BaseException:
        remove_outputs(ws)
        raise
    log.info("%s: %d lines, %d Han characters, %d AI calls", STAGE, doc["stats"]["lines"],
             doc["stats"]["han_chars"], sum(len(b["attempts"]) for b in log_doc["batches"]))
    return list(ARTIFACTS)
