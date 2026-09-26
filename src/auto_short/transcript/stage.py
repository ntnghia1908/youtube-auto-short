"""Transcript stage (CP3): episode after ingest -> ``work/<id>/transcript.json``.

Canonical contract: docs/decisions/CP3-transcript-contract.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import hashing
from ..config import Config
from ..workspace import (
    DONE,
    StageError,
    Workspace,
    WorkspaceError,
    atomic_write_bytes,
    atomic_write_json,
    record_failure,
    run_stage,
    validate_episode_id,
)
from .normalize import normalize, stats, validate
from .parsers import FORMATS, ParseError
from .providers import (
    LOCAL_SUBTITLE,
    ORDER,
    WHISPER,
    YOUTUBE,
    Candidate,
    Context,
    LocalSubtitleProvider,
    ProviderUnavailable,
    TranscriptProvider,
    WhisperProvider,
    YouTubeCaptionProvider,
)
from .whisper import FasterWhisperBackend, WhisperBackend
from .youtube import CaptionFetcher, YtDlpCaptionFetcher

log = logging.getLogger("auto_short")

STAGE = "transcript"
TRANSCRIPT_NAME = "transcript.json"
RAW_DIR = "transcript"
TRANSCRIPT_SCHEMA_VERSION = 1
METADATA_NAME = "metadata.json"
# Sidecar subtitle suffixes next to a local video, in priority order (T3).
SIDECAR_SUFFIXES = (".vi.srt", ".vi.vtt", ".vi.json3", ".srt", ".vtt", ".json3")

ACCEPTED, REJECTED, UNAVAILABLE, ERROR = "accepted", "rejected", "unavailable", "error"


class TranscriptError(Exception):
    """Transcript could not run; message is user-facing."""


@dataclass(frozen=True)
class TranscriptResult:
    episode_id: str
    path: Path  # transcript.json
    ran: bool  # False when skipped as up to date
    source: str | None = None
    method: str | None = None


def used_config(config: Config) -> dict:
    """Every ``[transcript]`` key except execution-only settings (T8)."""
    t, p, w = config.transcript, config.transcript.providers, config.transcript.whisper
    return {
        "transcript.language": t.language,
        "transcript.min_vietnamese_ratio": t.min_vietnamese_ratio,
        "transcript.min_coverage": t.min_coverage,
        "transcript.min_words_per_minute": t.min_words_per_minute,
        "transcript.providers.youtube": p.youtube,
        "transcript.providers.local_subtitle": p.local_subtitle,
        "transcript.providers.whisper": p.whisper,
        "transcript.whisper.model": w.model,
        "transcript.whisper.device": w.device,
        "transcript.whisper.compute_type": w.compute_type,
        "transcript.whisper.vad_filter": w.vad_filter,
        "transcript.whisper.word_timestamps": w.word_timestamps,
    }


def _check_subtitle(path: Path) -> Path:
    path = path.expanduser().absolute()
    if not path.is_file():
        raise TranscriptError(f"subtitle file not found: {path}")
    if path.suffix.lower() not in FORMATS:
        raise TranscriptError(f"unsupported subtitle format {path.suffix!r} (use .srt, .vtt or .json3)")
    return path


def find_sidecar(media: Path) -> Path | None:
    for suffix in SIDECAR_SUFFIXES:
        candidate = media.with_name(media.stem + suffix)
        if candidate.is_file():
            return candidate.absolute()
    return None


def _enabled(config: Config, name: str) -> bool:
    return getattr(config.transcript.providers, name)


def _attempt(provider: TranscriptProvider, ctx: Context, duration: float) -> tuple[dict, Candidate | None, list]:
    """Run one provider; return (attempt record, accepted candidate or None, segments)."""
    name = provider.name
    try:
        cand = provider.fetch(ctx)
    except ProviderUnavailable as exc:
        return {"provider": name, "status": UNAVAILABLE, "reason": str(exc)}, None, []
    except ParseError as exc:
        return {"provider": name, "status": REJECTED, "reason": f"parse error: {exc}"}, None, []
    except Exception as exc:  # network, model, IO...
        return {"provider": name, "status": ERROR, "reason": str(exc) or type(exc).__name__}, None, []
    segments = normalize(cand.segments)
    reason = validate(segments, duration=duration, language=cand.language, cfg=ctx.config.transcript)
    if reason is not None:
        return {"provider": name, "status": REJECTED, "reason": reason}, None, []
    return {"provider": name, "status": ACCEPTED, "reason": None}, cand, segments


def _document(ctx: Context, media_sha256: str, cand: Candidate, attempts: list[dict], segments: list[dict]) -> dict:
    return {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "episode_id": ctx.episode_id,
        "source": cand.source,
        "method": cand.method,
        "language": ctx.config.transcript.language,
        "media_sha256": media_sha256,
        "raw": cand.raw,
        "provider": cand.provider,
        "attempts": attempts,
        "stats": stats(segments, ctx.duration),
        "transcript_sha256": hashlib.sha256(hashing.canonical_json(segments).encode("utf-8")).hexdigest(),
        "segments": segments,
    }


def _remove_outputs(ws: Workspace) -> None:
    (ws.dir / TRANSCRIPT_NAME).unlink(missing_ok=True)
    shutil.rmtree(ws.dir / RAW_DIR, ignore_errors=True)


def run_transcript(
    episode_id: str,
    config: Config,
    *,
    subtitle: Path | None = None,
    force: bool = False,
    fetcher: CaptionFetcher | None = None,
    backend: WhisperBackend | None = None,
) -> TranscriptResult:
    try:
        ws = Workspace(config.workspace.dir, validate_episode_id(episode_id))
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise TranscriptError(str(exc)) from exc
    if manifest is None:
        raise TranscriptError(f"no manifest for episode {episode_id!r} in {ws.dir}; run 'auto-short ingest' first")

    ingest = manifest["stages"].get("ingest") or {}
    meta_path = ws.dir / METADATA_NAME
    if ingest.get("status") != DONE or not meta_path.is_file():
        msg = f"ingest is not done for {episode_id!r} (status: {ingest.get('status', 'pending')}); run 'auto-short ingest' first"
        record_failure(ws, manifest, STAGE, msg)
        raise TranscriptError(msg)

    explicit = _check_subtitle(subtitle) if subtitle is not None else None
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    src = manifest["source"]
    media = ws.resolve(src["path"]).absolute()
    sub = explicit or (find_sidecar(media) if src.get("kind") == "local" else None)

    inputs = [{"path": ws.relpath(meta_path), "sha256": hashing.sha256_file(meta_path)}]
    if sub is not None:
        inputs.append({"path": str(sub), "sha256": hashing.sha256_file(sub)})
    cfg_hash = hashing.config_hash(used_config(config))

    ctx = Context(
        episode_id=ws.episode_id,
        source_kind=src.get("kind"),
        source_uri=src.get("uri"),
        media_path=media,
        duration=float(metadata["duration"]),
        subtitle=sub,
        config=config,
    )
    providers: dict[str, TranscriptProvider] = {
        YOUTUBE: YouTubeCaptionProvider(fetcher or YtDlpCaptionFetcher(config.ingest.js_runtimes)),
        LOCAL_SUBTITLE: LocalSubtitleProvider(),
        WHISPER: WhisperProvider(backend or FasterWhisperBackend()),
    }
    outcome: dict = {}

    def action() -> list[str]:
        attempts: list[dict] = []
        accepted = None
        for name in ORDER:  # fixed order; first accepted wins, later providers not called
            if not _enabled(config, name):
                attempt = {"provider": name, "status": UNAVAILABLE, "reason": "disabled by config"}
            else:
                log.info("%s: trying %s", STAGE, name)
                attempt, cand, segments = _attempt(providers[name], ctx, ctx.duration)
                if cand is not None:
                    accepted = (cand, segments)
            attempts.append(attempt)
            log.info("%s: %s %s%s", STAGE, name, attempt["status"],
                     f" ({attempt['reason']})" if attempt["reason"] else "")
            if accepted:
                break
        if accepted is None:
            summary = "; ".join(f"{a['provider']}: {a['status']} ({a['reason']})" for a in attempts)
            raise TranscriptError(f"no acceptable transcript: {summary}")

        cand, segments = accepted
        try:
            _remove_outputs(ws)
            artifacts = [TRANSCRIPT_NAME]
            if cand.raw_file is not None:
                rel, data = cand.raw_file
                atomic_write_bytes(ws.dir / rel, data)
                artifacts.append(rel)
            doc = _document(ctx, metadata["source"]["sha256"], cand, attempts, segments)
            atomic_write_json(ws.dir / TRANSCRIPT_NAME, doc)
        except BaseException:
            _remove_outputs(ws)
            raise
        outcome.update(source=cand.source, method=cand.method, stats=doc["stats"])
        log.info("%s: %s/%s %s", STAGE, cand.source, cand.method,
                 " ".join(f"{k}={v}" for k, v in doc["stats"].items()))
        return artifacts

    try:
        ran = run_stage(ws, manifest, STAGE, inputs=inputs, cfg_hash=cfg_hash, force=force, action=action)
    except StageError as exc:
        _remove_outputs(ws)
        raise TranscriptError(str(exc)) from exc
    return TranscriptResult(ws.episode_id, ws.dir / TRANSCRIPT_NAME, ran, outcome.get("source"), outcome.get("method"))
