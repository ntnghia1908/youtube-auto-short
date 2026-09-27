"""AI enrichment of lesson lines (CL1 C7): batches of ``{id, zh}`` -> ``{id: (pinyin, vi)}``.

Only ``pinyin`` and ``vi`` are taken from the model; every other field it returns (including
``zh``/``start``/``end``) is ignored. A batch is rejected on the first failing check and retried
up to ``retries`` times; a :class:`ChatError` also counts as a failed attempt.
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from collections.abc import Callable

from ..config import LearningConfig
from ..selection.client import ChatClient, ChatError
from .prompt import OUTPUT_SCHEMA, messages, prompt_sha256
from .subtitle import is_han

log = logging.getLogger("auto_short")

LOG_SCHEMA_VERSION = 1


class EnrichmentError(Exception):
    """A batch still failed after every attempt; ``log`` is the full enrichment log document."""

    def __init__(self, batch: int, ids: list[str], reason: str, attempts: int, log_doc: dict):
        span = f"{ids[0]}..{ids[-1]}" if ids else "-"
        super().__init__(f"batch {batch} ({span}): {reason} (after {attempts} attempts)")
        self.batch, self.reason, self.log = batch, reason, log_doc


def options(cfg: LearningConfig) -> dict:
    temp = cfg.temperature
    return {"temperature": int(temp) if temp == int(temp) else temp, "seed": cfg.seed, "num_ctx": cfg.num_ctx}


def backoff_before(attempt: int, backoff: tuple[float, ...]) -> float:
    """Seconds to wait before ``attempt`` (1-based): none before the first, then ``backoff`` in order
    (its last value repeats)."""
    if attempt <= 1 or not backoff:
        return 0.0
    return backoff[min(attempt - 2, len(backoff) - 1)]


def batches(lines: list[dict], size: int) -> list[list[dict]]:
    return [lines[i:i + size] for i in range(0, len(lines), size)]


def pinyin_problem(pinyin: str) -> str | None:
    """Han characters or non-Latin letters; digits, spaces, punctuation and marks are allowed."""
    for ch in pinyin:
        if is_han(ch):
            return f"contains Han character {ch!r}"
        if ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN"):
            return f"contains non-Latin letter {ch!r}"
    return None


def validate_batch(submitted_ids: list[str], content: str) -> dict[str, tuple[str, str]] | str:
    """``{id: (pinyin, vi)}`` (stripped) when the response is acceptable, else the first reason."""
    try:
        data = json.loads(content)
    except ValueError as exc:
        return f"response is not JSON: {exc}"
    items = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return 'response is not an object with a "lines" array'
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("id", "pinyin", "vi")):
            return f'lines[{i}] is not an object with string "id", "pinyin" and "vi"'
    ids = [item["id"] for item in items]
    seen, dup = set(), []
    for x in ids:
        if x in seen and x not in dup:
            dup.append(x)
        seen.add(x)
    if dup:
        return f"duplicate id: {', '.join(dup)}"
    missing = [x for x in submitted_ids if x not in seen]
    if missing:
        return f"missing id: {', '.join(missing)}"
    extra = [x for x in ids if x not in set(submitted_ids)]
    if extra:
        return f"unexpected id: {', '.join(extra)}"
    by_id = {item["id"]: item for item in items}
    out = {}
    for x in submitted_ids:
        pinyin, vi = by_id[x]["pinyin"].strip(), by_id[x]["vi"].strip()
        if not pinyin:
            return f"{x}: empty pinyin"
        problem = pinyin_problem(pinyin)
        if problem:
            return f"{x}: pinyin {problem}"
        if not vi:
            return f"{x}: empty vi"
        out[x] = (pinyin, vi)
    return out


def log_document(episode_id: str, cfg: LearningConfig) -> dict:
    return {
        "schema_version": LOG_SCHEMA_VERSION,
        "episode_id": episode_id,
        "model": cfg.model,
        "prompt_version": cfg.prompt_version,
        "prompt_sha256": prompt_sha256(cfg.prompt_version),
        "options": options(cfg),
        "think": cfg.think,
        "batches": [],
    }


def enrich(episode_id: str, lines: list[dict], cfg: LearningConfig, client: ChatClient,
           sleep: Callable[[float], None] = time.sleep) -> tuple[dict[str, tuple[str, str]], dict]:
    """Enrich every line; returns (``{id: (pinyin, vi)}``, log document).

    Raises :class:`EnrichmentError` (carrying the log) when a batch fails every attempt.
    """
    log_doc = log_document(episode_id, cfg)
    opts = options(cfg)
    result: dict[str, tuple[str, str]] = {}
    groups = batches(lines, cfg.batch_lines)
    for index, group in enumerate(groups, start=1):
        ids = [ln["id"] for ln in group]
        msgs = messages(cfg.prompt_version, group)
        blog = {"index": index, "ids": ids, "attempts": [], "accepted_attempt": None}
        log_doc["batches"].append(blog)
        reason = None
        t_batch = time.monotonic()
        for attempt in range(1, cfg.retries + 2):
            wait = backoff_before(attempt, cfg.retry_backoff)
            if wait > 0:
                log.info("lesson: batch %d/%d: waiting %g s before attempt %d", index, len(groups), wait, attempt)
                sleep(wait)
            entry: dict = {"attempt": attempt,
                           "request": {"messages": msgs, "format": OUTPUT_SCHEMA, "options": opts},
                           "response": None}
            blog["attempts"].append(entry)
            t0 = time.monotonic()
            try:
                res = client.chat(model=cfg.model, messages=msgs, format=OUTPUT_SCHEMA, options=opts,
                                  think=cfg.think)
            except ChatError as exc:
                entry["error"] = reason = str(exc)
            else:
                entry["response"] = res.content
                checked = validate_batch(ids, res.content)
                if isinstance(checked, str):
                    entry["rejection"] = reason = checked
                else:
                    reason = None
            entry["duration_s"] = round(time.monotonic() - t0, 3)
            if reason is None:
                blog["accepted_attempt"] = attempt
                result.update(checked)
                break
            log.warning("lesson: batch %d/%d attempt %d/%d failed: %s", index, len(groups), attempt,
                        cfg.retries + 1, reason)
        if reason is not None:
            raise EnrichmentError(index, ids, reason, cfg.retries + 1, log_doc)
        log.info("lesson: batch %d/%d: %d lines in %.1f s (attempt %d)", index, len(groups), len(group),
                 time.monotonic() - t_batch, blog["accepted_attempt"])
    return result, log_doc
