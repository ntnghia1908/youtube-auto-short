"""Selection stage (CP5): analysis done -> ``clips.json`` + ``selection_log.json``.

Canonical contract: docs/decisions/CP5-selection-contract.md.
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
from ..config import Config, SelectionConfig
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
from .client import ChatClient, ChatError, OllamaClient, resolve_host
from .logic import (
    SELECTED,
    VALID,
    ResponseError,
    SelectionError,
    Window,
    build_windows,
    apply_head_cuts,
    dedupe,
    map_proposals,
    parse_response,
    select_clips,
    unit_durations,
    validate_clips,
)
from .prompt import RESPONSE_SCHEMA, prompt_sha256, prompt_texts, render_user_prompt, system_prompt

log = logging.getLogger("auto_short")

STAGE = "selection"
SCHEMA_VERSION = 1
METADATA_NAME = "metadata.json"
CANDIDATES_NAME = "candidates.json"
SILENCES_NAME = "silences.json"
TRANSCRIPT_NAME = "transcript.json"
CLIPS_NAME = "clips.json"
LOG_NAME = "selection_log.json"
ARTIFACTS = [CLIPS_NAME, LOG_NAME]

# [selection] keys in the config hash (B9); ollama_host / timeout are execution-only.
HASH_KEYS = ("model", "think", "temperature", "seed", "num_ctx", "prompt_version", "max_clips", "min_score",
             "max_window_words", "retries", "head_cut_words", "head_cut_pad")
PARAM_KEYS = ("max_clips", "min_score", "max_window_words", "retries", "head_cut_words", "head_cut_pad")


@dataclass(frozen=True)
class SelectionResult:
    episode_id: str
    path: Path  # clips.json
    ran: bool  # False when skipped as up to date
    clips: int | None = None


def used_config(config: Config) -> dict:
    cfg = config.selection
    used = {f"selection.{k}": getattr(cfg, k) for k in HASH_KEYS}
    used["selection.head_cut_words"] = list(cfg.head_cut_words)
    try:
        used["selection.prompt_sha256"] = prompt_sha256(cfg.prompt_version)
    except ValueError:
        used["selection.prompt_sha256"] = None
    return used


def _sha(doc: dict) -> str:
    return hashlib.sha256(hashing.canonical_json(doc).encode("utf-8")).hexdigest()


def model_block(cfg: SelectionConfig) -> dict:
    return {"provider": "ollama", "name": cfg.model, "think": cfg.think, "options": options(cfg)}


def options(cfg: SelectionConfig) -> dict:
    temp = cfg.temperature
    return {"temperature": int(temp) if temp == int(temp) else temp, "seed": cfg.seed, "num_ctx": cfg.num_ctx}


def _remove_outputs(ws: Workspace) -> None:
    for name in ARTIFACTS:
        (ws.dir / name).unlink(missing_ok=True)


def _read_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SelectionError(f"cannot read {path}: {exc}; re-run 'auto-short {what}'") from exc


def backoff_before(attempt: int, backoff: tuple[float, ...]) -> float:
    """Seconds to wait before ``attempt`` (1-based): none before the first; then the backoff
    list in order, repeating its last value (B5)."""
    if attempt <= 1 or not backoff:
        return 0.0
    return backoff[min(attempt - 2, len(backoff) - 1)]


def _call_window(client: ChatClient, cfg: SelectionConfig, messages: list[dict], window: Window,
                 wlog: dict, sleep: Callable[[float], None]) -> list[dict]:
    """Call the model for one window with retries and backoff (B5); returns parsed proposals."""
    opts = options(cfg)
    last_error = None
    for attempt in range(1, cfg.retries + 2):
        wait = backoff_before(attempt, cfg.retry_backoff)
        if wait > 0:
            log.info("%s: window %s: waiting %g s before attempt %d", STAGE, window.id, wait, attempt)
            sleep(wait)
        call = {"attempt": attempt, "backoff_seconds": wait, "seconds": None,
                "request": {"model": cfg.model, "messages": messages, "format": RESPONSE_SCHEMA, "options": opts,
                            "think": cfg.think, "stream": False},
                "response": None, "error": None}
        wlog["ai_calls"].append(call)
        t0 = time.monotonic()
        try:
            res = client.chat(model=cfg.model, messages=messages, format=RESPONSE_SCHEMA, options=opts,
                              think=cfg.think)
            call["response"] = {"content": res.content, "thinking": res.thinking, "eval_count": res.eval_count,
                                "prompt_eval_count": res.prompt_eval_count, "total_duration": res.total_duration,
                                **res.extra}
            proposals = parse_response(res.content)
        except (ChatError, ResponseError) as exc:
            call["seconds"] = round(time.monotonic() - t0, 3)
            call["error"] = str(exc)
            last_error = exc
            log.warning("%s: window %s attempt %d/%d failed: %s", STAGE, window.id, attempt, cfg.retries + 1, exc)
            continue
        call["seconds"] = round(time.monotonic() - t0, 3)
        return proposals
    raise SelectionError(f"window {window.id}: {last_error} (after {cfg.retries + 1} attempts)")


def select(episode_id: str, cand_doc: dict, metadata: dict, silences_doc: dict, transcript: dict,
           cfg: SelectionConfig, client: ChatClient,
           sleep: Callable[[float], None] = time.sleep) -> tuple[dict, dict]:
    """Stage body without I/O: inputs -> (clips document, selection log document)."""
    system = system_prompt(cfg.prompt_version, cfg.head_cut_words)
    p_sha = prompt_sha256(cfg.prompt_version)
    cands_sha = _sha(cand_doc)
    if _sha(silences_doc) != cand_doc.get("silences_sha256"):
        raise SelectionError("silences.json does not match candidates.json silences_sha256; "
                             "re-run 'auto-short analysis'")
    if transcript.get("transcript_sha256") != cand_doc.get("transcript_sha256"):
        raise SelectionError("transcript.json does not match candidates.json transcript_sha256; "
                             "re-run 'auto-short analysis'")
    seg_by_id = {sg["id"]: sg for sg in transcript["segments"]}
    params = cand_doc["params"]
    units, candidates = cand_doc["units"], cand_doc["candidates"]
    silences = [(s["start"], s["end"]) for s in silences_doc["silences"]]
    durations = unit_durations(units, silences, params["max_pause"])
    by_units: dict[tuple[str, str], dict] = {}
    for c in candidates:
        key = (c["unit_ids"][0], c["unit_ids"][1])
        if key in by_units:
            raise SelectionError(f"candidates {by_units[key]['id']} and {c['id']} share unit_ids {list(key)}")
        by_units[key] = c
    cand_by_id = {c["id"]: c for c in candidates}
    windows = build_windows(units, candidates, cfg.max_window_words)
    title = metadata.get("title") or ""

    wlogs, records = [], []
    for win in windows:
        wlog = {"id": win.id, "parent": win.parent, "unit_ids": win.unit_ids, "units": len(win.units),
                "words": win.words, "candidates": len(win.candidates), "ai_calls": [], "proposals": []}
        wlogs.append(wlog)
        if not win.candidates:
            log.info("%s: window %s: %d units, no candidates -> no AI call", STAGE, win.id, len(win.units))
            continue
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": render_user_prompt(
                        cfg.prompt_version, title=title, window_id=win.id, units=win.units, durations=durations,
                        max_pause=params["max_pause"], pad=params["boundary_pad"])}]
        t0 = time.monotonic()
        proposals = _call_window(client, cfg, messages, win, wlog, sleep)
        recs = map_proposals(proposals, win, by_units, durations, params)
        wlog["proposals"] = recs
        records.extend(recs)
        log.info("%s: window %s: %d units, %d words, %d candidates -> %d proposals (%d valid) in %.1f s",
                 STAGE, win.id, len(win.units), win.words, len(win.candidates), len(recs),
                 sum(r["status"] == VALID for r in recs), time.monotonic() - t0)

    dedupe(records)
    valid = sum(r["status"] == VALID for r in records)
    effective = apply_head_cuts(records, cand_by_id, seg_by_id, silences, params, cfg.head_cut_words,
                                cfg.head_cut_pad)
    for r in records:
        cut = r.get("head_cut")
        if cut:
            log.info("%s: head cut %s: drop '%s', %s -> %s (%s)%s", STAGE, r["candidate_id"], cut["words"],
                     cut["original_start"], cut["source_start"], cut["method"],
                     f"; {r['reject_reason']}" if r["status"] == "ineligible" else "")
        elif r.get("head_cut_note"):
            log.info("%s: head cut %s skipped: %s", STAGE, r["candidate_id"], r["head_cut_note"])
    clips = select_clips(records, effective, max_clips=cfg.max_clips, min_score=cfg.min_score)
    validate_clips(clips, cand_doc, max_clips=cfg.max_clips, min_score=cfg.min_score)
    eligible = sum(r["status"] not in ("rejected", "ineligible") for r in records)
    stats = {
        "windows": len({w.parent for w in windows}),
        "ai_calls": sum(len(w["ai_calls"]) for w in wlogs),
        "proposals": len(records),
        "valid": valid,
        "eligible": eligible,
        "selected": sum(r["status"] == SELECTED for r in records),
        "selected_seconds": sum(round(c["duration"] * 1000) for c in clips) / 1000,
        "head_cut": sum(c["head_cut"] is not None for c in clips),
    }
    head = {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "candidates_sha256": cands_sha,
        "model": model_block(cfg),
        "prompt_version": cfg.prompt_version,
        "prompt_sha256": p_sha,
    }
    params_doc = {k: getattr(cfg, k) for k in PARAM_KEYS}
    params_doc["head_cut_words"] = list(cfg.head_cut_words)
    clips_doc = dict(head, params=params_doc, stats=stats, clips=clips)
    log_doc = dict(head, system_prompt=system, response_format=RESPONSE_SCHEMA, stats=stats,
                   unit_seconds=durations, windows=wlogs)
    return clips_doc, log_doc


def run_selection(episode_id: str, config: Config, *, force: bool = False,
                  client: ChatClient | None = None,
                  sleep: Callable[[float], None] = time.sleep) -> SelectionResult:
    cfg = config.selection
    try:
        prompt_texts(cfg.prompt_version)
    except ValueError as exc:
        raise SelectionError(f"selection.prompt_version: {exc}") from exc
    try:
        ws = Workspace(config.workspace.dir, validate_episode_id(episode_id))
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise SelectionError(str(exc)) from exc
    if manifest is None:
        raise SelectionError(f"no manifest for episode {episode_id!r} in {ws.dir}; run 'auto-short ingest' first")

    analysis_entry = manifest["stages"].get("analysis") or {}
    meta_path, cand_path, sil_path = ws.dir / METADATA_NAME, ws.dir / CANDIDATES_NAME, ws.dir / SILENCES_NAME
    tr_path = ws.dir / TRANSCRIPT_NAME
    if analysis_entry.get("status") != DONE or \
            not all(p.is_file() for p in (cand_path, sil_path, meta_path, tr_path)):
        msg = (f"analysis is not done for {episode_id!r} (status: {analysis_entry.get('status', 'pending')}); "
               "run 'auto-short analysis' first")
        _remove_outputs(ws)
        record_failure(ws, manifest, STAGE, msg)
        raise SelectionError(msg)

    inputs = [
        {"path": ws.relpath(cand_path), "sha256": hashing.sha256_file(cand_path)},
        {"path": ws.relpath(meta_path), "sha256": hashing.sha256_file(meta_path)},
        {"path": ws.relpath(tr_path), "sha256": hashing.sha256_file(tr_path)},
    ]
    cfg_hash = hashing.config_hash(used_config(config))
    chat = client or OllamaClient(resolve_host(cfg.ollama_host), timeout=cfg.timeout)
    outcome: dict = {}

    def action() -> list[str]:
        cand_doc = _read_json(cand_path, "analysis")
        metadata = _read_json(meta_path, "ingest")
        silences_doc = _read_json(sil_path, "analysis")
        transcript = _read_json(tr_path, "transcript")
        log.info("%s: model %s (think=%s) via %s", STAGE, cfg.model, cfg.think,
                 getattr(chat, "host", type(chat).__name__))
        clips_doc, log_doc = select(ws.episode_id, cand_doc, metadata, silences_doc, transcript, cfg, chat, sleep)
        try:
            _remove_outputs(ws)
            atomic_write_json(ws.dir / LOG_NAME, log_doc)
            atomic_write_json(ws.dir / CLIPS_NAME, clips_doc)
        except BaseException:
            _remove_outputs(ws)
            raise
        st = clips_doc["stats"]
        log.info("%s: windows=%d ai_calls=%d proposals=%d valid=%d eligible=%d selected=%d selected_seconds=%s "
                 "head_cut=%d", STAGE, st["windows"], st["ai_calls"], st["proposals"], st["valid"],
                 st["eligible"], st["selected"], st["selected_seconds"], st["head_cut"])
        if not clips_doc["clips"]:
            log.warning("%s: WARNING: no clip met the criteria (complete start/end, score >= %d); "
                        "clips.json has no clips", STAGE, cfg.min_score)
        outcome["clips"] = len(clips_doc["clips"])
        return list(ARTIFACTS)

    try:
        ran = run_stage(ws, manifest, STAGE, inputs=inputs, cfg_hash=cfg_hash, force=force, action=action)
    except StageError as exc:
        _remove_outputs(ws)
        raise SelectionError(str(exc)) from exc
    return SelectionResult(ws.episode_id, ws.dir / CLIPS_NAME, ran, outcome.get("clips"))
