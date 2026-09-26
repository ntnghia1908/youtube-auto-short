"""Analysis stage (CP4): transcript done -> ``shots.json``, ``silences.json``, ``candidates.json``.

Canonical contract: docs/decisions/CP4-analysis-contract.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import hashing
from ..config import AnalysisConfig, Config
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
from .candidates import (
    build_units,
    content_trimmed_seconds,
    detect_content_window,
    find_cut_points,
    generate_candidates,
    validate,
)
from .detect import AnalysisError, FfmpegAnalyzer, MediaAnalyzer, normalize_changes, normalize_silences

log = logging.getLogger("auto_short")

STAGE = "analysis"
SCHEMA_VERSION = 1
METADATA_NAME = "metadata.json"
TRANSCRIPT_NAME = "transcript.json"
SHOTS_NAME = "shots.json"
SILENCES_NAME = "silences.json"
CANDIDATES_NAME = "candidates.json"
ARTIFACTS = [SHOTS_NAME, SILENCES_NAME, CANDIDATES_NAME]

# Keys written to candidates.json ``params`` (A10), in this order.
PARAM_KEYS = ("min_boundary_silence", "align_tolerance", "hard_break_silence", "max_pause", "boundary_pad",
              "min_duration", "max_duration", "target_min", "target_max", "shot_guard", "intro_window",
              "intro_min_silence", "outro_window")


@dataclass(frozen=True)
class AnalysisResult:
    episode_id: str
    path: Path  # candidates.json
    ran: bool  # False when skipped as up to date
    candidates: int | None = None


def used_config(config: Config) -> dict:
    """Every ``[analysis]`` key (A11)."""
    return {f"analysis.{k}": v for k, v in asdict(config.analysis).items()}


def _sha(doc: dict) -> str:
    return hashlib.sha256(hashing.canonical_json(doc).encode("utf-8")).hexdigest()


def shots_document(episode_id: str, media_sha256: str, changes: list[float], duration: float,
                   cfg: AnalysisConfig) -> dict:
    bounds = [0.0, *changes, round(duration, 3)]
    return {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "media_sha256": media_sha256,
        "method": {"tool": "ffmpeg", "filter": "scene", "threshold": cfg.scene_threshold,
                   "scale_width": cfg.scale_width},
        "duration": round(duration, 3),
        "changes": changes,
        "shots": [{"id": f"h{n:04d}", "start": a, "end": b} for n, (a, b) in enumerate(zip(bounds, bounds[1:]), 1)],
    }


def silences_document(episode_id: str, media_sha256: str, silences: list[tuple[float, float]],
                      cfg: AnalysisConfig) -> dict:
    total = sum(round(b * 1000) - round(a * 1000) for a, b in silences) / 1000
    return {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "media_sha256": media_sha256,
        "method": {"tool": "ffmpeg", "filter": "silencedetect", "noise_db": cfg.silence_noise_db,
                   "min_seconds": cfg.silence_min},
        "stats": {"count": len(silences), "total_seconds": total},
        "silences": [{"start": a, "end": b} for a, b in silences],
    }


def analyze(episode_id: str, transcript: dict, metadata: dict, changes: list[float],
            silences: list[tuple[float, float]], cfg: AnalysisConfig) -> tuple[dict, dict, dict]:
    """Pure part of the stage: detector output + transcript -> the three validated documents."""
    duration = float(metadata["duration"])
    media_sha256 = metadata["source"]["sha256"]
    changes = normalize_changes(changes, duration)
    silences = normalize_silences(silences, duration)
    shots = shots_document(episode_id, media_sha256, changes, duration, cfg)
    sil_doc = silences_document(episode_id, media_sha256, silences, cfg)

    segments = transcript["segments"]
    window = detect_content_window(segments, silences, duration, cfg)
    cuts = find_cut_points(segments, silences, window, cfg)
    units = build_units(segments, silences, cuts, cfg)
    candidates = generate_candidates(units, silences, changes, shots["shots"], cfg)
    validate(candidates, units, window, silences, changes, shots["shots"], cfg)

    cand_doc = {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "transcript_sha256": transcript["transcript_sha256"],
        "shots_sha256": _sha(shots),
        "silences_sha256": _sha(sil_doc),
        "params": {k: getattr(cfg, k) for k in PARAM_KEYS},
        "content": {"start": window.start, "end": window.end,
                    "start_reason": window.start_reason, "end_reason": window.end_reason},
        "stats": {
            "units": len(units),
            "candidates": len(candidates),
            "in_target": sum(c["in_target"] for c in candidates),
            "content_seconds": (round(window.end * 1000) - round(window.start * 1000)) / 1000,
            "content_seconds_trimmed": content_trimmed_seconds(window, silences, cfg),
        },
        "units": [u.to_json() for u in units],
        "candidates": candidates,
    }
    return shots, sil_doc, cand_doc


def _remove_outputs(ws: Workspace) -> None:
    for name in ARTIFACTS:
        (ws.dir / name).unlink(missing_ok=True)


def _read_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnalysisError(f"cannot read {path}: {exc}; re-run 'auto-short {what}'") from exc


def run_analysis(episode_id: str, config: Config, *, force: bool = False,
                 analyzer: MediaAnalyzer | None = None) -> AnalysisResult:
    try:
        ws = Workspace(config.workspace.dir, validate_episode_id(episode_id))
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise AnalysisError(str(exc)) from exc
    if manifest is None:
        raise AnalysisError(f"no manifest for episode {episode_id!r} in {ws.dir}; run 'auto-short ingest' first")

    transcript_entry = manifest["stages"].get("transcript") or {}
    meta_path, tr_path = ws.dir / METADATA_NAME, ws.dir / TRANSCRIPT_NAME
    if transcript_entry.get("status") != DONE or not tr_path.is_file() or not meta_path.is_file():
        msg = (f"transcript is not done for {episode_id!r} (status: {transcript_entry.get('status', 'pending')}); "
               "run 'auto-short transcript' first")
        _remove_outputs(ws)
        record_failure(ws, manifest, STAGE, msg)
        raise AnalysisError(msg)

    src = manifest["source"]
    media = ws.resolve(src["path"]).absolute()
    try:
        media_fp = hashing.fingerprint(media, ws.source_fingerprint(manifest))
    except OSError as exc:
        raise AnalysisError(f"cannot read source media {media}: {exc}") from exc
    inputs = [
        {"path": ws.relpath(meta_path), "sha256": hashing.sha256_file(meta_path)},
        {"path": ws.relpath(tr_path), "sha256": hashing.sha256_file(tr_path)},
        {"path": ws.relpath(media), "sha256": media_fp.sha256},
    ]
    cfg_hash = hashing.config_hash(used_config(config))
    detector = analyzer or FfmpegAnalyzer()
    cfg = config.analysis
    outcome: dict = {}

    def action() -> list[str]:
        metadata = _read_json(meta_path, "ingest")
        transcript = _read_json(tr_path, "transcript")
        if metadata.get("audio_codec") is None:
            raise AnalysisError(f"source media has no audio stream: {media}")
        duration = float(metadata["duration"])
        log.info("%s: detecting shot changes (scene > %g)", STAGE, cfg.scene_threshold)
        changes = detector.shot_changes(media, threshold=cfg.scene_threshold, scale_width=cfg.scale_width)
        log.info("%s: detecting silences (%gdB, >= %g s)", STAGE, cfg.silence_noise_db, cfg.silence_min)
        silences = detector.silences(media, noise_db=cfg.silence_noise_db, min_seconds=cfg.silence_min,
                                     duration=duration)
        shots, sil_doc, cand_doc = analyze(ws.episode_id, transcript, metadata, changes, silences, cfg)
        try:
            _remove_outputs(ws)
            atomic_write_json(ws.dir / SHOTS_NAME, shots)
            atomic_write_json(ws.dir / SILENCES_NAME, sil_doc)
            atomic_write_json(ws.dir / CANDIDATES_NAME, cand_doc)
        except BaseException:
            _remove_outputs(ws)
            raise
        c, st = cand_doc["content"], cand_doc["stats"]
        log.info("%s: content %s-%s (%s; %s)", STAGE, c["start"], c["end"], c["start_reason"], c["end_reason"])
        log.info("%s: shot_changes=%d silences=%d units=%d candidates=%d in_target=%d "
                 "content_seconds=%s content_seconds_trimmed=%s", STAGE, len(shots["changes"]),
                 sil_doc["stats"]["count"], st["units"], st["candidates"], st["in_target"],
                 st["content_seconds"], st["content_seconds_trimmed"])
        outcome["candidates"] = st["candidates"]
        return list(ARTIFACTS)

    try:
        ran = run_stage(ws, manifest, STAGE, inputs=inputs, cfg_hash=cfg_hash, force=force, action=action)
    except StageError as exc:
        _remove_outputs(ws)
        raise AnalysisError(str(exc)) from exc
    return AnalysisResult(ws.episode_id, ws.dir / CANDIDATES_NAME, ran, outcome.get("candidates"))
