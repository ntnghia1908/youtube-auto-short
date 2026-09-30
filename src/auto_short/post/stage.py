"""P1/P3 orchestration: preflight, compose (or recompose) the community post of one or more Shorts of an episode,
``post_log.json`` (one entry per Short per compose call, append-only, not byte-stable — like CP9 C6
``review_titling_log.json``).

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P1, P3, P7.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config, PostConfig
from ..pipeline import PreflightError
from ..selection.client import ChatClient, ChatError, OllamaClient, resolve_host
from ..workspace import atomic_write_json
from . import images, source, store
from .logic import chunk_lines
from .prompt import prompt_sha256, render_user_prompt, system_prompt
from .validate import project_response, raw_fallback

MATCH_RATIO_THRESHOLD = 0.9  # P3 amendment (ORCHESTRATOR review round 1)

log = logging.getLogger("auto_short")

LOG_NAME = "post_log.json"
RENDER_MANIFEST = "render_manifest.json"
SCHEMA_VERSION = 1
PREFLIGHT_TIMEOUT = 10.0


class PostComposeError(Exception):
    """The compose job cannot complete (no rendered Short, unknown clip id, every Short's source unreadable)."""


class _NullLock(AbstractContextManager):
    """Default ``lock`` of :func:`compose_posts` when the caller does not serialize writes itself (tests, scripts;
    the web layer passes its own lock, like CP8.5 ``publish_lock``)."""

    def __enter__(self) -> "_NullLock":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def backoff_before(attempt: int, backoff: tuple[float, ...]) -> float:
    """Seconds to wait before ``attempt`` (1-based): none before the first; then ``backoff`` in order, repeating
    its last value (like CP5 B5)."""
    if attempt <= 1 or not backoff:
        return 0.0
    return backoff[min(attempt - 2, len(backoff) - 1)]


def options(cfg: PostConfig) -> dict:
    temp = cfg.temperature
    return {"temperature": int(temp) if temp == int(temp) else temp, "seed": cfg.seed, "num_ctx": cfg.num_ctx}


def model_block(cfg: PostConfig) -> dict:
    return {"provider": "ollama", "name": cfg.model, "think": cfg.think, "options": options(cfg)}


# --- preflight (P1: "như W4", but only the [post] model at its own host) ---------------------------------------

def preflight(config: Config, *, opener: Callable[..., object] | None = None,
             timeout: float = PREFLIGHT_TIMEOUT) -> None:
    """Check the ``[post]`` model is listed at its Ollama host; raises :class:`auto_short.pipeline.PreflightError`
    (the same type W4 raises, so the web layer's existing 503 mapping applies unchanged)."""
    cfg = config.post
    host = resolve_host(cfg.ollama_host)
    open_ = opener or urllib.request.urlopen
    url = f"{host}/api/tags"
    try:
        with open_(urllib.request.Request(url, method="GET"), timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise PreflightError(f"HTTP {exc.code} from {url}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise PreflightError(f"timeout after {timeout:g} s calling {url}") from exc
    except urllib.error.URLError as exc:
        raise PreflightError(f"cannot reach Ollama at {host}: {exc.reason}") from exc
    except (OSError, ValueError) as exc:
        raise PreflightError(f"error calling {url}: {exc}") from exc
    names = [m.get("name") for m in (data.get("models") or []) if isinstance(m, dict)]
    model = cfg.model
    if not (model in names or (":" not in model and f"{model}:latest" in names)):
        raise PreflightError(f"model {model!r} ([post] model) is not available at {host} (ollama pull {model})")
    log.info("post: ollama %s ok (%s)", host, model)


# --- P3 (amended, ORCHESTRATOR review round 1): free-form AI + deterministic projection, with retries -----------

def _punctuate_chunk(client: ChatClient, cfg: PostConfig, chunk_text: str, clog: dict,
                     sleep: Callable[[float], None]) -> tuple[list[str], float] | None:
    """One chunk with retries (P3): returns ``(paragraphs, match_ratio)`` of the first attempt whose projection
    matches at least :data:`MATCH_RATIO_THRESHOLD`, or None when every attempt either failed (HTTP/timeout/empty
    output) or stayed below the threshold."""
    messages = [{"role": "system", "content": system_prompt(cfg.prompt_version)},
                {"role": "user", "content": render_user_prompt(cfg.prompt_version, text=chunk_text)}]
    opts = options(cfg)
    attempts = cfg.retries + 1
    for attempt in range(1, attempts + 1):
        wait = backoff_before(attempt, cfg.retry_backoff)
        if wait > 0:
            sleep(wait)
        call: dict = {"attempt": attempt, "backoff_seconds": wait, "seconds": None,
                     "request": {"model": cfg.model, "messages": messages, "options": opts, "think": cfg.think,
                                 "stream": False},
                     "response": None, "error": None, "raw_output": None, "match_ratio": None, "paragraphs": None,
                     "valid": False}
        clog["ai_calls"].append(call)
        t0 = time.monotonic()
        try:
            res = client.chat(model=cfg.model, messages=messages, format=None, options=opts, think=cfg.think)
            call["response"] = {"content": res.content, "thinking": res.thinking, "eval_count": res.eval_count,
                                "prompt_eval_count": res.prompt_eval_count, "total_duration": res.total_duration,
                                **res.extra}
        except ChatError as exc:
            call["seconds"] = round(time.monotonic() - t0, 3)
            call["error"] = str(exc)
            log.warning("post: chunk attempt %d/%d failed: %s", attempt, attempts, exc)
            continue
        call["seconds"] = round(time.monotonic() - t0, 3)
        raw_output = res.content or ""
        call["raw_output"] = raw_output
        if not raw_output.strip():
            call["error"] = "output rỗng"
            log.warning("post: chunk attempt %d/%d: output rỗng", attempt, attempts)
            continue
        paragraphs, ratio = project_response(chunk_text, raw_output)
        call["paragraphs"], call["match_ratio"] = paragraphs, round(ratio, 4)
        if ratio >= MATCH_RATIO_THRESHOLD:
            call["valid"] = True
            return paragraphs, ratio
        call["error"] = f"tỉ lệ khớp {ratio:.2f} < {MATCH_RATIO_THRESHOLD:g}"
        log.warning("post: chunk attempt %d/%d: tỉ lệ khớp %.2f < %.2g", attempt, attempts, ratio,
                    MATCH_RATIO_THRESHOLD)
    return None


@dataclass(frozen=True)
class ComposeResult:
    clip_id: str
    candidate_id: str
    origin: str  # store.AI | store.RAW
    paragraphs: list[str]
    source_text: str
    chunks: int
    attempts: int  # total AI calls used (every chunk)
    first_try: bool  # every chunk validated on its first attempt (Q4)
    match_ratio: float | None  # origin ai: average over chunks; raw: the last failing attempt's ratio (or None)


def compose_clip(client: ChatClient, cfg: PostConfig, clip_id: str, candidate_id: str, lines: list[str],
                 clog: dict, sleep: Callable[[float], None] = time.sleep) -> ComposeResult:
    """One Short: chunk its source lines at caption-line boundaries (P3 ``chunk_words``), punctuate each chunk,
    fall back to ``raw`` (P3) when any chunk exhausts its retries."""
    text = " ".join(lines)
    chunks = chunk_lines(lines, cfg.chunk_words)
    all_paragraphs: list[str] = []
    ratios: list[float] = []
    ok = True
    for chunk in chunks:
        result = _punctuate_chunk(client, cfg, " ".join(chunk), clog, sleep)
        if result is None:
            ok = False
            break
        paragraphs, ratio = result
        all_paragraphs += paragraphs
        ratios.append(ratio)
    attempts = len(clog["ai_calls"])
    if ok:
        avg_ratio = sum(ratios) / len(ratios) if ratios else None
        return ComposeResult(clip_id, candidate_id, store.AI, all_paragraphs, text, len(chunks), attempts,
                             attempts == len(chunks), avg_ratio)
    last_ratio = clog["ai_calls"][-1]["match_ratio"] if clog["ai_calls"] else None
    return ComposeResult(clip_id, candidate_id, store.RAW, raw_fallback(text), text, len(chunks), attempts, False,
                         last_ratio)


def _append_log(path: Path, episode_id: str, entry: dict) -> None:
    doc: dict = {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "entries": []}
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(old, dict) and isinstance(old.get("entries"), list) and old.get("episode_id") == episode_id:
            doc = old
    except (OSError, ValueError):
        pass
    doc["entries"].append(entry)
    atomic_write_json(path, doc)


def rendered_clip_ids(config: Config, episode_id: str) -> list[tuple[str, str]]:
    """(clip_id, candidate_id) of every ``rendered`` (not deleted) Short, in ``render_manifest.json`` order
    (P1 scope, P7 entry order)."""
    path = Path(config.render.output_dir) / episode_id / RENDER_MANIFEST
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict) or doc.get("episode_id") != episode_id or not isinstance(doc.get("shorts"), list):
        return []
    out = []
    for s in doc["shorts"]:
        if isinstance(s, dict) and s.get("status") == "rendered" and isinstance(s.get("clip_id"), str) \
                and isinstance(s.get("candidate_id"), str):
            out.append((s["clip_id"], s["candidate_id"]))
    return out


def compute_stale(ep: "source.SourceEpisode", entry: dict) -> bool:
    """P8: the stored ``source_sha256`` no longer matches the Short's current text (edited cut, re-selection...);
    True too when the current text cannot be computed (the Short is gone)."""
    try:
        text = source.source_text(ep, entry["clip_id"])
    except source.PostSourceError:
        return True
    return source.source_sha256(text) != entry["source_sha256"]


def auto_clips(ep: "source.SourceEpisode", doc: dict, order: list[str]) -> list[str]:
    """CP8.16 R4 (``clips: "auto"``): every ``rendered`` Short in ``order`` that (i) has no post yet, or (ii) has a
    ``stale`` post that is not ticked "Đã đăng bài" and whose ``origin`` is not ``manual`` (hand-edited text is kept).
    Pure: reads only ``ep`` and ``doc``."""
    out = []
    for cid in order:
        entry = store.find(doc, cid)
        if entry is None:
            out.append(cid)
        elif entry["posted_at"] is None and entry["origin"] != store.MANUAL and compute_stale(ep, entry):
            out.append(cid)
    return out


def merge_clips(a: "list[str] | str", b: "list[str] | str") -> "list[str] | str":
    """CP8.16 R3 (merge of requests into one ``post`` job): union of two ``clips`` specs (each ``"all"`` / ``"auto"`` /
    a list of clip ids, or a list mixing those tokens with ids), order-preserving, no duplicates. A single token comes
    back as the plain string."""
    out: list[str] = []
    for item in ([a] if isinstance(a, str) else list(a)) + ([b] if isinstance(b, str) else list(b)):
        if item not in out:
            out.append(item)
    return out[0] if len(out) == 1 and out[0] in ("all", "auto") else out


def resolve_todo(ep: "source.SourceEpisode", doc: dict, order: list[str], clips: "list[str] | str") -> list[str]:
    """The clip ids a ``clips`` spec selects, in ``order`` (``render_manifest`` order), each once: ``"all"`` = the
    CP8.15 rule (no post yet or stale), ``"auto"`` = :func:`auto_clips` (R4), any other item = that clip id (composed
    even when its post is still valid). Ids not in ``order`` are left out (the caller reports them)."""
    want: set[str] = set()
    for item in ([clips] if isinstance(clips, str) else clips):
        if item == "all":
            want |= {cid for cid in order if store.find(doc, cid) is None or compute_stale(ep, store.find(doc, cid))}
        elif item == "auto":
            want |= set(auto_clips(ep, doc, order))
        else:
            want.add(item)
    return [cid for cid in order if cid in want]


@dataclass
class ComposeSummary:
    clip_ids: list[str]
    ai: int = 0
    raw: int = 0
    errors: dict[str, str] = field(default_factory=dict)  # clip_id -> reason its source text was not readable


def compose_posts(episode_id: str, config: Config, clips: "list[str] | str", *, client: ChatClient | None = None,
                  sleep: Callable[[float], None] = time.sleep,
                  lock: AbstractContextManager | None = None) -> ComposeSummary:
    """P1: compose (or recompose) the post of ``clips`` (a list of clip ids) or every eligible Short that has no
    valid, non-stale post yet (``clips == "all"``, "bỏ qua Short đã có bài còn hợp lệ"), or the CP8.16 R4 set
    (``clips == "auto"``, :func:`auto_clips`). Each clip's AI work runs
    outside ``lock``; only the read-modify-write of ``posts.json`` for that one clip is serialized by ``lock`` (a
    no-op by default) so a concurrent manual edit of another clip is never lost."""
    cfg = config.post
    ws_dir = Path(config.workspace.dir) / episode_id
    posts_path = ws_dir / store.POSTS_NAME
    order_pairs = rendered_clip_ids(config, episode_id)
    order = [cid for cid, _ in order_pairs]
    cand_by_clip = dict(order_pairs)
    if not order:
        raise PostComposeError(f"tập {episode_id} chưa có Short nào dựng xong")
    try:
        ep = source.load(episode_id, config)
    except source.PostSourceError as exc:
        raise PostComposeError(str(exc)) from exc

    tokens = [clips] if isinstance(clips, str) else list(clips)
    if any(t in ("all", "auto") for t in tokens):
        try:
            doc = store.read_posts(posts_path, episode_id)
        except store.PostsError:
            doc = store.empty_posts(episode_id)
        # a merged request (R3): an unknown explicit id is dropped with a warning, not a failure of the whole job
        for cid in [t for t in tokens if t not in ("all", "auto") and t not in cand_by_clip]:
            log.warning("post: [%s] bỏ qua clip %s: không có Short đã dựng", episode_id, cid)
        todo = resolve_todo(ep, doc, order, tokens)
    else:
        todo = list(clips)
        unknown = [c for c in todo if c not in cand_by_clip]
        if unknown:
            raise PostComposeError(f"không có Short đã dựng: {', '.join(unknown)}")

    chat = client or OllamaClient(resolve_host(cfg.ollama_host), timeout=cfg.timeout)
    guard = lock if lock is not None else _NullLock()
    summary = ComposeSummary(list(todo))
    for cid in todo:
        try:
            lines = source.source_lines(ep, cid)
        except source.PostSourceError as exc:
            summary.errors[cid] = str(exc)
            log.warning("post: %s [%s]: source text not ready: %s", cid, episode_id, exc)
            continue
        clog: dict = {"clip_id": cid, "candidate_id": cand_by_clip[cid], "text": " ".join(lines), "ai_calls": []}
        t0 = time.monotonic()
        result = compose_clip(chat, cfg, cid, cand_by_clip[cid], lines, clog, sleep)
        secs = time.monotonic() - t0
        if result.origin == store.AI:
            summary.ai += 1
        else:
            summary.raw += 1
        _append_log(ws_dir / LOG_NAME, episode_id, {
            "at": _now(), "clip_id": cid, "candidate_id": cand_by_clip[cid], "model": model_block(cfg),
            "prompt_version": cfg.prompt_version, "prompt_sha256": prompt_sha256(cfg.prompt_version),
            "chunks": result.chunks, "attempts": result.attempts, "first_try": result.first_try,
            "match_ratio": result.match_ratio, "seconds": round(secs, 3), "origin": result.origin,
            "text": result.source_text, "paragraphs": result.paragraphs, "ai_calls": clog["ai_calls"]})
        with guard:
            doc = store.read_posts(posts_path, episode_id)
            image = images.least_used(cfg.image_dir, Path(config.workspace.dir)) if store.find(doc, cid) is None \
                else None
            doc = store.with_compose(doc, order, clip_id=cid, candidate_id=cand_by_clip[cid],
                                     source_sha256=source.source_sha256(result.source_text),
                                     paragraphs=result.paragraphs, origin=result.origin, image=image, now=_now())
            store.write(posts_path, doc)
        valid_first = sum(1 for c in clog["ai_calls"] if c["valid"])
        log.info("post: %s [%s]: %s (%d/%d call(s) valid, %.1f s)", cid, episode_id, result.origin, valid_first,
                 len(clog["ai_calls"]), secs)
    if todo and summary.errors and not summary.ai and not summary.raw:
        raise PostComposeError("; ".join(f"{c}: {e}" for c, e in summary.errors.items()))
    return summary
