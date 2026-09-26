"""Titling stage (CP6): selection done -> ``titles.json`` + ``titling_log.json``.

Canonical contract: docs/decisions/CP6-titling-contract.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import hashing
from ..config import Config, TitlingConfig
from ..selection.client import ChatClient, ChatError, OllamaClient, resolve_host
from ..selection.stage import backoff_before
from ..workspace import (
    DONE,
    StageError,
    Workspace,
    WorkspaceError,
    atomic_write_json,
    record_failure,
    run_stage,
    validate_episode_id,
)
from .logic import (
    TITLED,
    UNTITLED,
    VALID,
    ResponseError,
    TitlingError,
    choose_title,
    clip_text,
    parse_response,
    resolve_header,
    validate_options,
    validate_titles,
)
from .prompt import RESPONSE_SCHEMA, prompt_sha256, prompt_texts, render_user_prompt, system_prompt

log = logging.getLogger("auto_short")

STAGE = "titling"
SCHEMA_VERSION = 1
METADATA_NAME = "metadata.json"
CANDIDATES_NAME = "candidates.json"
CLIPS_NAME = "clips.json"
TITLES_NAME = "titles.json"
LOG_NAME = "titling_log.json"
ARTIFACTS = [TITLES_NAME, LOG_NAME]

# [titling] keys in the config hash (G9); ollama_host / timeout / retry_backoff are execution-only.
HASH_KEYS = ("model", "think", "temperature", "seed", "num_ctx", "prompt_version", "n_options", "min_chars",
             "max_chars", "retries")
PARAM_KEYS = ("n_options", "min_chars", "max_chars", "retries")


@dataclass(frozen=True)
class TitlingResult:
    episode_id: str
    path: Path  # titles.json
    ran: bool  # False when skipped as up to date
    titled: int | None = None
    clips: int | None = None


def used_config(config: Config, header_lines: list[str]) -> dict:
    cfg = config.titling
    used = {f"titling.{k}": getattr(cfg, k) for k in HASH_KEYS}
    try:
        used["titling.prompt_sha256"] = prompt_sha256(cfg.prompt_version)
    except ValueError:
        used["titling.prompt_sha256"] = None
    used["titling.header.lines"] = list(header_lines)
    return used


def _sha(doc: dict) -> str:
    return hashlib.sha256(hashing.canonical_json(doc).encode("utf-8")).hexdigest()


def options(cfg: TitlingConfig) -> dict:
    temp = cfg.temperature
    return {"temperature": int(temp) if temp == int(temp) else temp, "seed": cfg.seed, "num_ctx": cfg.num_ctx}


def model_block(cfg: TitlingConfig) -> dict:
    return {"provider": "ollama", "name": cfg.model, "think": cfg.think, "options": options(cfg)}


def _remove_outputs(ws: Workspace) -> None:
    for name in ARTIFACTS:
        (ws.dir / name).unlink(missing_ok=True)


def _read_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TitlingError(f"cannot read {path}: {exc}; re-run 'auto-short {what}'") from exc


def _title_clip(client: ChatClient, cfg: TitlingConfig, messages: list[dict], clip_id: str, text: str,
                clog: dict, sleep: Callable[[float], None]) -> list[dict] | None:
    """Call the model for one clip with retries and backoff (G5/G6). Returns the option records of
    the first attempt with a valid option; None when attempts returned options but none valid (P3).
    Raises TitlingError when no attempt returned a schema-valid response."""
    opts = options(cfg)
    last_error, parsed_any = None, False
    attempts = cfg.retries + 1
    for attempt in range(1, attempts + 1):
        wait = backoff_before(attempt, cfg.retry_backoff)
        if wait > 0:
            log.info("%s: clip %s: waiting %g s before attempt %d", STAGE, clip_id, wait, attempt)
            sleep(wait)
        call = {"attempt": attempt, "backoff_seconds": wait, "seconds": None,
                "request": {"model": cfg.model, "messages": messages, "format": RESPONSE_SCHEMA, "options": opts,
                            "think": cfg.think, "stream": False},
                "response": None, "error": None, "options": []}
        clog["ai_calls"].append(call)
        t0 = time.monotonic()
        try:
            res = client.chat(model=cfg.model, messages=messages, format=RESPONSE_SCHEMA, options=opts,
                              think=cfg.think)
            call["response"] = {"content": res.content, "thinking": res.thinking, "eval_count": res.eval_count,
                                "prompt_eval_count": res.prompt_eval_count, "total_duration": res.total_duration,
                                **res.extra}
            parsed = parse_response(res.content, cfg.n_options)
        except (ChatError, ResponseError) as exc:
            call["seconds"] = round(time.monotonic() - t0, 3)
            call["error"] = str(exc)
            last_error = exc
            log.warning("%s: clip %s attempt %d/%d failed: %s", STAGE, clip_id, attempt, attempts, exc)
            continue
        call["seconds"] = round(time.monotonic() - t0, 3)
        parsed_any = True
        records = validate_options(parsed, text, min_chars=cfg.min_chars, max_chars=cfg.max_chars)
        call["options"] = records
        if any(r["status"] == VALID for r in records):
            return records
        call["error"] = "no valid option"
        last_error = "no valid option"
        log.warning("%s: clip %s attempt %d/%d: no valid option (%s)", STAGE, clip_id, attempt, attempts,
                    "; ".join(f"{r['title']!r}: {r['reject_reason']}" for r in records))
    if parsed_any:
        return None
    raise TitlingError(f"clip {clip_id}: {last_error} (after {attempts} attempts)")


def title_clips(episode_id: str, clips_doc: dict, cand_doc: dict, metadata: dict, header: dict,
                cfg: TitlingConfig, client: ChatClient,
                sleep: Callable[[float], None] = time.sleep) -> tuple[dict, dict]:
    """Stage body without I/O: inputs -> (titles document, titling log document)."""
    system = system_prompt(cfg.prompt_version, max_chars=cfg.max_chars, n_options=cfg.n_options)
    p_sha = prompt_sha256(cfg.prompt_version)
    cands_sha, clips_sha = _sha(cand_doc), _sha(clips_doc)
    if clips_doc.get("candidates_sha256") != cands_sha:
        raise TitlingError("clips.json does not match candidates.json (candidates_sha256); "
                           "re-run 'auto-short selection'")
    units = cand_doc["units"]
    index = {u["id"]: n for n, u in enumerate(units)}
    video_title = metadata.get("title") or ""
    texts = {c["id"]: clip_text(c, units, index) for c in clips_doc["clips"]}

    entries, clogs = [], []
    for clip in clips_doc["clips"]:
        cid, text = clip["id"], texts[clip["id"]]
        clog = {"clip_id": cid, "candidate_id": clip["candidate_id"], "text": text, "ai_calls": []}
        clogs.append(clog)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": render_user_prompt(cfg.prompt_version, title=video_title,
                                                                   duration=clip["duration"], text=text)}]
        t0 = time.monotonic()
        records = _title_clip(client, cfg, messages, cid, text, clog, sleep)
        chosen, alternatives = choose_title(records) if records else (None, [])
        entries.append({"clip_id": cid, "candidate_id": clip["candidate_id"],
                        "title": chosen["title"] if chosen else None,
                        "evidence": chosen["evidence"] if chosen else None,
                        "alternatives": alternatives, "status": TITLED if chosen else UNTITLED})
        secs = time.monotonic() - t0
        if chosen:
            log.info("%s: clip %s: %r (%d/%d options valid, %d call(s), %.1f s)", STAGE, cid, chosen["title"],
                     sum(r["status"] == VALID for r in records), len(records), len(clog["ai_calls"]), secs)
        else:
            log.warning("%s: WARNING: clip %s untitled: no valid option after %d attempts (%.1f s)", STAGE, cid,
                        len(clog["ai_calls"]), secs)

    stats = {"clips": len(entries), "ai_calls": sum(len(c["ai_calls"]) for c in clogs),
             "titled": sum(e["status"] == TITLED for e in entries),
             "untitled": sum(e["status"] == UNTITLED for e in entries)}
    model = model_block(cfg)
    titles_doc = {
        "schema_version": SCHEMA_VERSION, "episode_id": episode_id,
        "clips_sha256": clips_sha, "candidates_sha256": cands_sha,
        "header": header, "model": model,
        "prompt_version": cfg.prompt_version, "prompt_sha256": p_sha,
        "params": {k: getattr(cfg, k) for k in PARAM_KEYS},
        "stats": stats, "titles": entries,
    }
    validate_titles(titles_doc, clips_doc, texts, clips_sha256=clips_sha, candidates_sha256=cands_sha,
                    min_chars=cfg.min_chars, max_chars=cfg.max_chars)
    log_doc = {
        "schema_version": SCHEMA_VERSION, "episode_id": episode_id, "clips_sha256": clips_sha,
        "model": model, "prompt_version": cfg.prompt_version, "prompt_sha256": p_sha,
        "system_prompt": system, "response_format": RESPONSE_SCHEMA, "header": header, "stats": stats,
        "clips": clogs,
    }
    return titles_doc, log_doc


def run_titling(episode_id: str, config: Config, *, force: bool = False, speaker: str | None = None,
                series: str | None = None, episode: str | None = None, client: ChatClient | None = None,
                sleep: Callable[[float], None] = time.sleep) -> TitlingResult:
    cfg = config.titling
    try:
        prompt_texts(cfg.prompt_version)
    except ValueError as exc:
        raise TitlingError(f"titling.prompt_version: {exc}") from exc
    try:
        ws = Workspace(config.workspace.dir, validate_episode_id(episode_id))
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise TitlingError(str(exc)) from exc
    if manifest is None:
        raise TitlingError(f"no manifest for episode {episode_id!r} in {ws.dir}; run 'auto-short ingest' first")

    def fail(msg: str) -> TitlingError:
        _remove_outputs(ws)
        record_failure(ws, manifest, STAGE, msg)
        return TitlingError(msg)

    sel_entry = manifest["stages"].get("selection") or {}
    clips_path, cand_path, meta_path = ws.dir / CLIPS_NAME, ws.dir / CANDIDATES_NAME, ws.dir / METADATA_NAME
    if sel_entry.get("status") != DONE or not all(p.is_file() for p in (clips_path, cand_path, meta_path)):
        raise fail(f"selection is not done for {episode_id!r} (status: {sel_entry.get('status', 'pending')}); "
                   "run 'auto-short selection' first")

    try:
        metadata = _read_json(meta_path, "ingest")
        header = resolve_header(cfg.header, metadata.get("title"),
                                {"speaker": speaker, "series": series, "episode": episode})
    except TitlingError as exc:
        raise fail(str(exc)) from exc

    inputs = [
        {"path": ws.relpath(clips_path), "sha256": hashing.sha256_file(clips_path)},
        {"path": ws.relpath(cand_path), "sha256": hashing.sha256_file(cand_path)},
        {"path": ws.relpath(meta_path), "sha256": hashing.sha256_file(meta_path)},
    ]
    cfg_hash = hashing.config_hash(used_config(config, header["lines"]))
    chat = client or OllamaClient(resolve_host(cfg.ollama_host), timeout=cfg.timeout)
    outcome: dict = {}

    def action() -> list[str]:
        clips_doc = _read_json(clips_path, "selection")
        cand_doc = _read_json(cand_path, "analysis")
        log.info("%s: model %s (think=%s) via %s", STAGE, cfg.model, cfg.think,
                 getattr(chat, "host", type(chat).__name__))
        log.info("%s: header %s (%s)", STAGE, " | ".join(header["lines"]),
                 ", ".join(f"{k}: {v}" for k, v in header["sources"].items() if v))
        titles_doc, log_doc = title_clips(ws.episode_id, clips_doc, cand_doc, metadata, header, cfg, chat, sleep)
        try:
            _remove_outputs(ws)
            atomic_write_json(ws.dir / LOG_NAME, log_doc)
            atomic_write_json(ws.dir / TITLES_NAME, titles_doc)
        except BaseException:
            _remove_outputs(ws)
            raise
        st = titles_doc["stats"]
        log.info("%s: clips=%d ai_calls=%d titled=%d untitled=%d", STAGE, st["clips"], st["ai_calls"],
                 st["titled"], st["untitled"])
        if st["untitled"]:
            log.warning("%s: WARNING: %d clip(s) untitled: %s", STAGE, st["untitled"],
                        ", ".join(e["clip_id"] for e in titles_doc["titles"] if e["status"] == UNTITLED))
        outcome.update(titled=st["titled"], clips=st["clips"])
        return list(ARTIFACTS)

    try:
        ran = run_stage(ws, manifest, STAGE, inputs=inputs, cfg_hash=cfg_hash, force=force, action=action)
    except StageError as exc:
        _remove_outputs(ws)
        raise TitlingError(str(exc)) from exc
    return TitlingResult(ws.episode_id, ws.dir / TITLES_NAME, ran, outcome.get("titled"), outcome.get("clips"))
