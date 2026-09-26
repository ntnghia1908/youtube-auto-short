"""Typed runtime configuration loaded from TOML (stdlib ``tomllib``)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_FILE = "config.toml"


class ConfigError(Exception):
    """Raised when a config file is missing or invalid."""


@dataclass(frozen=True)
class WorkspaceConfig:
    dir: Path = Path("work")


@dataclass(frozen=True)
class IngestConfig:
    youtube_format: str = "bv*+ba/b"
    js_runtimes: tuple[str, ...] = ("node",)


@dataclass(frozen=True)
class ProvidersConfig:
    """Which transcript providers may run; the order is fixed (T1), config only disables."""

    youtube: bool = True
    local_subtitle: bool = True
    whisper: bool = True


@dataclass(frozen=True)
class WhisperConfig:
    model: str = "large-v3-turbo"
    device: str = "cpu"
    compute_type: str = "int8"
    vad_filter: bool = True
    word_timestamps: bool = True
    # Execution-only settings (not part of the config hash):
    cpu_threads: int = 0  # 0 = os.cpu_count()
    models_dir: Path = Path("models")

    @property
    def effective_cpu_threads(self) -> int:
        return self.cpu_threads or os.cpu_count() or 1


@dataclass(frozen=True)
class TranscriptConfig:
    language: str = "vi"
    min_vietnamese_ratio: float = 0.3
    min_coverage: float = 0.5
    min_words_per_minute: float = 30.0
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)


@dataclass(frozen=True)
class AnalysisConfig:
    """Shot/silence detection and candidate parameters (docs/decisions/CP4-analysis-contract.md)."""

    # Detection (A2, A3)
    scene_threshold: float = 0.3
    scale_width: int = 320
    silence_noise_db: float = -45.0
    silence_min: float = 0.3
    # Candidate parameters (A4–A8), written to candidates.json ``params``
    min_boundary_silence: float = 3.0
    align_tolerance: float = 0.5
    hard_break_silence: float = 10.0
    max_pause: float = 1.0
    boundary_pad: float = 0.3
    min_duration: float = 30.0
    max_duration: float = 180.0
    target_min: float = 60.0
    target_max: float = 90.0
    shot_guard: float = 1.0
    intro_window: float = 60.0
    intro_min_silence: float = 1.0
    outro_window: float = 180.0


@dataclass(frozen=True)
class Config:
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    transcript: TranscriptConfig = field(default_factory=TranscriptConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _str(section: dict, key: str, default: str, where: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}.{key} must be a non-empty string")
    return value


def _bool(section: dict, key: str, default: bool, where: str) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{where}.{key} must be true or false")
    return value


def _number(section: dict, key: str, default: float, where: str, *, lo: float, hi: float | None = None) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < lo or (hi is not None and value > hi):
        bound = f"between {lo} and {hi}" if hi is not None else f">= {lo}"
        raise ConfigError(f"{where}.{key} must be a number {bound}")
    return float(value)


def _transcript(data: dict) -> TranscriptConfig:
    tr = _section(data, "transcript")
    prov = _section(tr, "providers") if "providers" in tr else {}
    wh = _section(tr, "whisper") if "whisper" in tr else {}
    d, dp, dw = TranscriptConfig(), ProvidersConfig(), WhisperConfig()
    where, wp, ww = "transcript", "transcript.providers", "transcript.whisper"

    threads = wh.get("cpu_threads", dw.cpu_threads)
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 0:
        raise ConfigError(f"{ww}.cpu_threads must be an integer >= 0 (0 = number of CPUs)")

    return TranscriptConfig(
        language=_str(tr, "language", d.language, where),
        min_vietnamese_ratio=_number(tr, "min_vietnamese_ratio", d.min_vietnamese_ratio, where, lo=0, hi=1),
        min_coverage=_number(tr, "min_coverage", d.min_coverage, where, lo=0, hi=1),
        min_words_per_minute=_number(tr, "min_words_per_minute", d.min_words_per_minute, where, lo=0),
        providers=ProvidersConfig(
            youtube=_bool(prov, "youtube", dp.youtube, wp),
            local_subtitle=_bool(prov, "local_subtitle", dp.local_subtitle, wp),
            whisper=_bool(prov, "whisper", dp.whisper, wp),
        ),
        whisper=WhisperConfig(
            model=_str(wh, "model", dw.model, ww),
            device=_str(wh, "device", dw.device, ww),
            compute_type=_str(wh, "compute_type", dw.compute_type, ww),
            vad_filter=_bool(wh, "vad_filter", dw.vad_filter, ww),
            word_timestamps=_bool(wh, "word_timestamps", dw.word_timestamps, ww),
            cpu_threads=threads,
            models_dir=Path(_str(wh, "models_dir", str(dw.models_dir), ww)),
        ),
    )


def _analysis(data: dict) -> AnalysisConfig:
    an = _section(data, "analysis")
    d, w = AnalysisConfig(), "analysis"

    width = an.get("scale_width", d.scale_width)
    if isinstance(width, bool) or not isinstance(width, int) or width < 2:
        raise ConfigError(f"{w}.scale_width must be an integer >= 2")

    def num(key: str, lo: float, hi: float | None = None) -> float:
        return _number(an, key, getattr(d, key), w, lo=lo, hi=hi)

    cfg = AnalysisConfig(
        scene_threshold=num("scene_threshold", 0, 1),
        scale_width=width,
        silence_noise_db=num("silence_noise_db", -120, 0),
        silence_min=num("silence_min", 0.01),
        min_boundary_silence=num("min_boundary_silence", 0),
        align_tolerance=num("align_tolerance", 0),
        hard_break_silence=num("hard_break_silence", 0),
        max_pause=num("max_pause", 0),
        boundary_pad=num("boundary_pad", 0),
        min_duration=num("min_duration", 0),
        max_duration=num("max_duration", 0),
        target_min=num("target_min", 0),
        target_max=num("target_max", 0),
        shot_guard=num("shot_guard", 0),
        intro_window=num("intro_window", 0),
        intro_min_silence=num("intro_min_silence", 0),
        outro_window=num("outro_window", 0),
    )
    if not cfg.min_duration <= cfg.max_duration:
        raise ConfigError(f"{w}.min_duration must be <= {w}.max_duration")
    if not cfg.target_min <= cfg.target_max:
        raise ConfigError(f"{w}.target_min must be <= {w}.target_max")
    if not cfg.min_boundary_silence <= cfg.hard_break_silence:
        raise ConfigError(f"{w}.min_boundary_silence must be <= {w}.hard_break_silence")
    return cfg


def from_dict(data: dict) -> Config:
    ws = _section(data, "workspace")
    ing = _section(data, "ingest")
    defaults = IngestConfig()

    runtimes = ing.get("js_runtimes", list(defaults.js_runtimes))
    if not isinstance(runtimes, list) or not all(isinstance(x, str) and x for x in runtimes):
        raise ConfigError("ingest.js_runtimes must be a list of strings")

    return Config(
        workspace=WorkspaceConfig(dir=Path(_str(ws, "dir", "work", "workspace"))),
        ingest=IngestConfig(
            youtube_format=_str(ing, "youtube_format", defaults.youtube_format, "ingest"),
            js_runtimes=tuple(runtimes),
        ),
        transcript=_transcript(data),
        analysis=_analysis(data),
    )


def load(path: Path | None = None) -> Config:
    """Load config from ``path``; without a path use ./config.toml if present, else defaults."""
    if path is None:
        path = Path(DEFAULT_CONFIG_FILE)
        if not path.is_file():
            return Config()
    elif not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    return from_dict(data)
