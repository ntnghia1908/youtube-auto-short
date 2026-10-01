"""Typed runtime configuration loaded from TOML (stdlib ``tomllib``)."""

from __future__ import annotations

import os
import re
import string
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
    # CP8.9 A3.1: a non_speech label no longer than this is not a hard break (A4 a). Never read from [analysis];
    # set only by ``khaithi.effective_config`` for a khai thị episode (None = Short: not in the hash / params).
    soft_label_max_seconds: float | None = None


# B11: pure connectors cut from the start of a clip (docs/decisions/CP5-selection-contract.md).
DEFAULT_HEAD_CUT_WORDS = ("cho nên", "vì vậy", "thế nên", "thế là", "do đó", "và", "nhưng", "mà", "rồi", "còn",
                          "thì")


@dataclass(frozen=True)
class SelectionConfig:
    """AI clip selection via Ollama (docs/decisions/CP5-selection-contract.md)."""

    model: str = "qwen3:30b"
    think: bool = True
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 32768
    prompt_version: str = "v3"
    max_clips: int = 25
    min_score: int = 7
    max_window_words: int = 2500
    retries: int = 2
    head_cut_words: tuple[str, ...] = DEFAULT_HEAD_CUT_WORDS  # empty = no head cut
    head_cut_pad: float = 0.1
    # Execution-only settings (not part of the config hash); env OLLAMA_HOST overrides ollama_host.
    ollama_host: str = "http://127.0.0.1:11437"
    timeout: float = 600.0
    retry_backoff: tuple[float, ...] = (5.0, 15.0)  # wait before attempt 2, 3 (last value repeats)
    # CP8.9 K3: (min, max) minutes filled into a khai thị prompt; never read from TOML, set only by
    # ``khaithi.effective_config`` for a khai thị episode (None = Short: not in the config hash).
    duration_minutes: tuple[int, int] | None = None


# G2: header fields and template (docs/decisions/CP6-titling-contract.md).
HEADER_FIELDS = ("speaker", "series", "episode")
DEFAULT_TITLE_PATTERN = r"^(?:Phật Thuyết\s+)?(?P<series>.+?)\s+tập\s+(?P<episode>\d+)\b"
# CP8.11 D2: ordered, the first pattern that matches the title wins (the CP6 pattern first: unchanged results).
DEFAULT_TITLE_PATTERNS = (
    DEFAULT_TITLE_PATTERN,
    r'^Tập\s+(?P<episode>\d+)(?:\s*/\s*\d+)?\s*:\s*(?:Giảng\s+)?["“](?P<series>[^"”]+?)\s*["”]',
)


@dataclass(frozen=True)
class TitlingHeaderConfig:
    """Deterministic header (G2): CLI flag > these values (non-empty) > groups of the first matching
    ``title_patterns`` entry > the "Tên bộ kinh" of a stored bộ kinh (CP8.11 D5)."""

    speaker: str = "HT.Tịnh Không"
    series: str = ""
    episode: str = ""
    title_patterns: tuple[str, ...] = DEFAULT_TITLE_PATTERNS  # regexes on metadata.title, in order; () = off
    lines: tuple[str, ...] = ("{speaker}", "{series} (tập {episode})")


@dataclass(frozen=True)
class TitlingConfig:
    """AI title / hook generation via Ollama (docs/decisions/CP6-titling-contract.md)."""

    model: str = "qwen3:14b"  # chosen by HUMAN LEAD 2026-09-26 (CP1 §11)
    think: bool = False
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 16384
    prompt_version: str = "v2"
    n_options: int = 3
    min_chars: int = 10
    max_chars: int = 60
    retries: int = 2
    header: TitlingHeaderConfig = field(default_factory=TitlingHeaderConfig)
    # Execution-only settings (not part of the config hash); env OLLAMA_HOST overrides ollama_host.
    ollama_host: str = "http://127.0.0.1:11437"
    timeout: float = 600.0
    retry_backoff: tuple[float, ...] = (5.0, 15.0)


@dataclass(frozen=True)
class RenderConfig:
    """Short composition / renderer (docs/decisions/CP7-render-contract.md). Ratios are fractions of the
    frame width W = 1080 (CP1 §4); layout V16 (CP8.14)."""

    title_source: str = "titles"  # P1: AI titles from titles.json (auto-approve until CP9 review)
    font_file: str = "fonts/BeVietnamPro-Regular.ttf"  # inside the auto_short.render package (P2)
    header_panel_width: float = 0.85
    header_panel_height: float = 0.17
    video_height: float = 1.16
    title_panel_width: float = 0.75
    title_panel_height: float = 0.21  # minimum; grows upwards for a 3rd title line (P3)
    title_bottom: float = 1.4815  # 1600 px: bottom edge of the title panel (above the YouTube Shorts UI)
    gap_header_video: float = 0.005
    panel_radius: float = 0.055
    min_frame_margin: float = 0.02  # top margin of the header panel
    header_font_size: float = 0.045  # 49 px
    title_font_size: float = 0.065  # 70 px
    line_spacing: float = 1.05  # baseline pitch / font size
    panel_padding_x: float = 0.03
    panel_padding_y: float = 0.035
    min_font_scale: float = 0.6
    crf: int = 22  # P4 amended by HUMAN LEAD 2026-09-27 (was 18)
    preset: str = "medium"
    audio_bitrate: str = "192k"
    dissolve: float = 0.15  # s, video dissolve at silence-trim junctions; 0 = hard cut (CP8.1 V1)
    # Execution-only settings (not part of the config hash):
    output_dir: Path = Path("output")
    threads: int = 0  # 0 = ffmpeg/x264 default
    jobs: int = 1  # Shorts encoded at once (CP11-R1)


@dataclass(frozen=True)
class WebConfig:
    """Web MVP server (docs/decisions/CP8.3-web-contract.md). Execution-only: no stage uses it."""

    host: str = "0.0.0.0"
    port: int = 8080
    session_days: int = 30  # login cookie lifetime
    # CP8.7: hashtags appended to the copied title (after #<series>); written without "#"
    hashtags: tuple[str, ...] = ("TịnhKhông", "LờiPhậtDạy", "TịnhĐộ", "NiệmPhật")
    # CP8.10: "lanes" = prepare / ai / render lanes run in parallel (one job per lane); "serial" = one job at a
    # time through all six stages (W5 before CP8.10)
    queue_mode: str = "lanes"


WEB_QUEUE_MODES = ("lanes", "serial")


@dataclass(frozen=True)
class KhaithiConfig:
    """Khai thị videos (docs/decisions/CP8.9-khai-thi-contract.md K9). Only the effective values derived from
    these (K2-K4) enter the config hash; the defaults and the limit are execution-only."""

    default_min_minutes: int = 4
    default_max_minutes: int = 7
    max_minutes_limit: int = 15
    prompt_version: str = "kt2"  # A3.2 (kt1 before)
    window_words_per_minute: int = 400
    soft_label_max_seconds: float = 5.0  # A3.1: shorter non_speech labels are no hard break (khai thị only)


@dataclass(frozen=True)
class PostConfig:
    """Community post text of a Short (docs/decisions/CP8.15-community-post-contract.md P11): AI punctuation /
    paragraphs via Ollama (P3), the image library (P5) and link fetching (P5b)."""

    model: str = "qwen3:14b"  # chosen by HUMAN LEAD 2026-09-29 (Q4)
    think: bool = False
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 8192
    prompt_version: str = "v2"  # free-form AI + deterministic projection (P3 amendment, HUMAN LEAD 2026-09-29)
    retries: int = 2
    chunk_words: int = 400  # P3: text longer than this (words) is punctuated in several AI calls
    # P5: outside the repo, not committed.
    image_dir: Path = field(default_factory=lambda: Path("~/.local/share/auto-short/post-images").expanduser())
    image_sources: tuple[str, ...] = ()  # P5b: quick-link buttons ([] = none)
    # Execution-only settings (not part of any hash; posts.json is not a stage artifact); env OLLAMA_HOST overrides.
    ollama_host: str = "http://127.0.0.1:11437"
    timeout: float = 600.0
    retry_backoff: tuple[float, ...] = (5.0, 15.0)


@dataclass(frozen=True)
class LearningConfig:
    """Chinese Learning application (docs/decisions/CL1-chinese-learning-contract.md C6, C7, C10)."""

    window_seconds: float = 300.0  # only [0, window) of the video: subtitle segments and clip
    min_han_ratio: float = 0.5  # Han characters / letters in the window's subtitle text
    media_format: str = "bv*[height<=720]+ba/b[height<=720]"  # yt-dlp format of the clip
    # C7 AI enrichment (stage ``lesson``) via Ollama; G6 model not final until HUMAN LEAD reviews a sample.
    model: str = "qwen3:14b"
    think: bool = False
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 8192
    prompt_version: str = "v1"  # checked against learning/prompt.py by run_learning
    batch_lines: int = 20
    retries: int = 2
    # Execution-only settings (not part of the config hash); env OLLAMA_HOST overrides ollama_host.
    ollama_host: str = "http://127.0.0.1:11437"
    timeout: float = 600.0
    retry_backoff: tuple[float, ...] = (5.0, 15.0)


@dataclass(frozen=True)
class Config:
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    transcript: TranscriptConfig = field(default_factory=TranscriptConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    titling: TitlingConfig = field(default_factory=TitlingConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    web: WebConfig = field(default_factory=WebConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    khaithi: KhaithiConfig = field(default_factory=KhaithiConfig)
    post: PostConfig = field(default_factory=PostConfig)


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


def _int(section: dict, key: str, default: int, where: str, *, lo: int, hi: int | None = None) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < lo or (hi is not None and value > hi):
        bound = f"between {lo} and {hi}" if hi is not None else f">= {lo}"
        raise ConfigError(f"{where}.{key} must be an integer {bound}")
    return value


def _selection(data: dict) -> SelectionConfig:
    se = _section(data, "selection")
    d, w = SelectionConfig(), "selection"
    cut_words = se.get("head_cut_words", list(d.head_cut_words))
    if not isinstance(cut_words, list) or not all(isinstance(x, str) and x.strip() for x in cut_words):
        raise ConfigError(f"{w}.head_cut_words must be a list of non-empty strings")
    backoff = se.get("retry_backoff", list(d.retry_backoff))
    if not isinstance(backoff, list) or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 3600 for x in backoff):
        raise ConfigError(f"{w}.retry_backoff must be a list of numbers between 0 and 3600 (seconds)")
    return SelectionConfig(
        model=_str(se, "model", d.model, w),
        think=_bool(se, "think", d.think, w),
        temperature=_number(se, "temperature", d.temperature, w, lo=0, hi=2),
        seed=_int(se, "seed", d.seed, w, lo=0),
        num_ctx=_int(se, "num_ctx", d.num_ctx, w, lo=512),
        prompt_version=_str(se, "prompt_version", d.prompt_version, w),
        max_clips=_int(se, "max_clips", d.max_clips, w, lo=1, hi=99),
        min_score=_int(se, "min_score", d.min_score, w, lo=1, hi=10),
        max_window_words=_int(se, "max_window_words", d.max_window_words, w, lo=1),
        retries=_int(se, "retries", d.retries, w, lo=0),
        head_cut_words=tuple(cut_words),
        head_cut_pad=_number(se, "head_cut_pad", d.head_cut_pad, w, lo=0, hi=1),
        ollama_host=_str(se, "ollama_host", d.ollama_host, w),
        timeout=_number(se, "timeout", d.timeout, w, lo=1),
        retry_backoff=tuple(float(x) for x in backoff),
    )


def _template_fields(line: str) -> list[str]:
    try:
        return [name for _, name, _, _ in string.Formatter().parse(line) if name is not None]
    except ValueError as exc:
        raise ConfigError(f"titling.header.lines: invalid template {line!r}: {exc}") from exc


def _title_patterns(he: dict, d: TitlingHeaderConfig, w: str) -> tuple[str, ...]:
    """CP8.11 D3: ``title_patterns`` (list of regexes, ``[]`` = off) or the legacy ``title_pattern`` (one regex,
    ``""`` = off); both -> error."""
    if "title_patterns" in he and "title_pattern" in he:
        raise ConfigError(f"{w}: set title_patterns or title_pattern, not both")
    if "title_pattern" in he:
        pattern = he["title_pattern"]
        if not isinstance(pattern, str):
            raise ConfigError(f"{w}.title_pattern must be a string (empty = off)")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"{w}.title_pattern is not a valid regex: {exc}") from exc
        return (pattern,) if pattern else ()
    patterns = he.get("title_patterns", list(d.title_patterns))
    if not isinstance(patterns, list):
        raise ConfigError(f"{w}.title_patterns must be a list of regex strings ([] = off)")
    for n, pattern in enumerate(patterns):
        if not isinstance(pattern, str) or not pattern:
            raise ConfigError(f"{w}.title_patterns[{n}] must be a non-empty string")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"{w}.title_patterns[{n}] is not a valid regex: {exc}") from exc
    return tuple(patterns)


def _titling_header(ti: dict) -> TitlingHeaderConfig:
    he = _section(ti, "header") if "header" in ti else {}
    d, w = TitlingHeaderConfig(), "titling.header"
    values = {}
    for key in HEADER_FIELDS:
        value = he.get(key, getattr(d, key))
        if isinstance(value, int) and not isinstance(value, bool) and key == "episode":
            value = str(value)
        if not isinstance(value, str):
            raise ConfigError(f"{w}.{key} must be a string (empty = not set)")
        values[key] = value.strip()
    patterns = _title_patterns(he, d, w)
    lines = he.get("lines", list(d.lines))
    if not isinstance(lines, list) or not 1 <= len(lines) <= 3 or \
            not all(isinstance(x, str) and x.strip() for x in lines):
        raise ConfigError(f"{w}.lines must be a list of 1-3 non-empty strings")
    for line in lines:
        for name in _template_fields(line):
            if name not in HEADER_FIELDS:
                raise ConfigError(f"{w}.lines: unknown field {{{name}}} in {line!r} "
                                  f"(allowed: {', '.join('{' + f + '}' for f in HEADER_FIELDS)})")
    return TitlingHeaderConfig(title_patterns=patterns, lines=tuple(lines), **values)


def _titling(data: dict) -> TitlingConfig:
    ti = _section(data, "titling")
    d, w = TitlingConfig(), "titling"
    backoff = ti.get("retry_backoff", list(d.retry_backoff))
    if not isinstance(backoff, list) or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 3600 for x in backoff):
        raise ConfigError(f"{w}.retry_backoff must be a list of numbers between 0 and 3600 (seconds)")
    cfg = TitlingConfig(
        model=_str(ti, "model", d.model, w),
        think=_bool(ti, "think", d.think, w),
        temperature=_number(ti, "temperature", d.temperature, w, lo=0, hi=2),
        seed=_int(ti, "seed", d.seed, w, lo=0),
        num_ctx=_int(ti, "num_ctx", d.num_ctx, w, lo=512),
        prompt_version=_str(ti, "prompt_version", d.prompt_version, w),
        n_options=_int(ti, "n_options", d.n_options, w, lo=1, hi=10),
        min_chars=_int(ti, "min_chars", d.min_chars, w, lo=1),
        max_chars=_int(ti, "max_chars", d.max_chars, w, lo=1),
        retries=_int(ti, "retries", d.retries, w, lo=0),
        header=_titling_header(ti),
        ollama_host=_str(ti, "ollama_host", d.ollama_host, w),
        timeout=_number(ti, "timeout", d.timeout, w, lo=1),
        retry_backoff=tuple(float(x) for x in backoff),
    )
    if cfg.min_chars > cfg.max_chars:
        raise ConfigError(f"{w}.min_chars must be <= {w}.max_chars")
    return cfg


TITLE_SOURCES = ("titles",)  # CP9 adds "review"
X264_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow",
                "placebo")


def _render(data: dict) -> RenderConfig:
    re_ = _section(data, "render")
    d, w = RenderConfig(), "render"

    def num(key: str, lo: float, hi: float) -> float:
        return _number(re_, key, getattr(d, key), w, lo=lo, hi=hi)

    title_source = _str(re_, "title_source", d.title_source, w)
    if title_source not in TITLE_SOURCES:
        raise ConfigError(f"{w}.title_source must be one of: {', '.join(TITLE_SOURCES)}")
    font_file = _str(re_, "font_file", d.font_file, w)
    if Path(font_file).is_absolute() or ".." in Path(font_file).parts:
        raise ConfigError(f"{w}.font_file must be a path inside the auto_short.render package (e.g. {d.font_file})")
    preset = _str(re_, "preset", d.preset, w)
    if preset not in X264_PRESETS:
        raise ConfigError(f"{w}.preset must be one of: {', '.join(X264_PRESETS)}")
    bitrate = _str(re_, "audio_bitrate", d.audio_bitrate, w)
    if not re.fullmatch(r"[1-9][0-9]{1,3}k", bitrate):
        raise ConfigError(f"{w}.audio_bitrate must look like '192k'")
    return RenderConfig(
        title_source=title_source,
        font_file=font_file,
        header_panel_width=num("header_panel_width", 0.1, 1),
        header_panel_height=num("header_panel_height", 0.05, 1),
        video_height=num("video_height", 0.1, 1.7),
        title_panel_width=num("title_panel_width", 0.1, 1),
        title_panel_height=num("title_panel_height", 0.05, 1),
        title_bottom=num("title_bottom", 0.1, 2),
        gap_header_video=num("gap_header_video", 0, 0.2),
        panel_radius=num("panel_radius", 0, 0.2),
        min_frame_margin=num("min_frame_margin", 0, 0.2),
        header_font_size=num("header_font_size", 0.01, 0.2),
        title_font_size=num("title_font_size", 0.01, 0.2),
        line_spacing=num("line_spacing", 0.8, 2),
        panel_padding_x=num("panel_padding_x", 0, 0.2),
        panel_padding_y=num("panel_padding_y", 0, 0.2),
        min_font_scale=num("min_font_scale", 0.1, 1),
        crf=_int(re_, "crf", d.crf, w, lo=0, hi=51),
        preset=preset,
        audio_bitrate=bitrate,
        dissolve=num("dissolve", 0, 1),
        output_dir=Path(_str(re_, "output_dir", str(d.output_dir), w)),
        threads=_int(re_, "threads", d.threads, w, lo=0, hi=256),
        jobs=_int(re_, "jobs", d.jobs, w, lo=1, hi=16),
    )


def _web(data: dict) -> WebConfig:
    we = _section(data, "web")
    d, w = WebConfig(), "web"
    return WebConfig(
        host=_str(we, "host", d.host, w),
        port=_int(we, "port", d.port, w, lo=1, hi=65535),
        session_days=_int(we, "session_days", d.session_days, w, lo=1, hi=365),
        hashtags=_hashtags(we, d.hashtags),
        queue_mode=_queue_mode(we, d.queue_mode),
    )


def _queue_mode(section: dict, default: str) -> str:
    value = section.get("queue_mode", default)
    if value not in WEB_QUEUE_MODES:
        raise ConfigError(f"web.queue_mode must be one of: {', '.join(repr(m) for m in WEB_QUEUE_MODES)}")
    return value


def _learning(data: dict) -> LearningConfig:
    le = _section(data, "learning")
    d, w = LearningConfig(), "learning"
    backoff = le.get("retry_backoff", list(d.retry_backoff))
    if not isinstance(backoff, list) or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 3600 for x in backoff):
        raise ConfigError(f"{w}.retry_backoff must be a list of numbers between 0 and 3600 (seconds)")
    return LearningConfig(
        window_seconds=_number(le, "window_seconds", d.window_seconds, w, lo=1, hi=86400),
        min_han_ratio=_number(le, "min_han_ratio", d.min_han_ratio, w, lo=0, hi=1),
        media_format=_str(le, "media_format", d.media_format, w),
        model=_str(le, "model", d.model, w),
        think=_bool(le, "think", d.think, w),
        temperature=_number(le, "temperature", d.temperature, w, lo=0, hi=2),
        seed=_int(le, "seed", d.seed, w, lo=0),
        num_ctx=_int(le, "num_ctx", d.num_ctx, w, lo=512),
        prompt_version=_str(le, "prompt_version", d.prompt_version, w),
        batch_lines=_int(le, "batch_lines", d.batch_lines, w, lo=1),
        retries=_int(le, "retries", d.retries, w, lo=0),
        ollama_host=_str(le, "ollama_host", d.ollama_host, w),
        timeout=_number(le, "timeout", d.timeout, w, lo=1),
        retry_backoff=tuple(float(x) for x in backoff),
    )


KHAITHI_MAX_MINUTES = 15  # CP8.9: videos longer than 15 minutes are out of scope


def _khaithi(data: dict) -> KhaithiConfig:
    kt = _section(data, "khaithi")
    d, w = KhaithiConfig(), "khaithi"
    limit = _int(kt, "max_minutes_limit", d.max_minutes_limit, w, lo=2, hi=KHAITHI_MAX_MINUTES)
    cfg = KhaithiConfig(
        default_min_minutes=_int(kt, "default_min_minutes", d.default_min_minutes, w, lo=1, hi=limit - 1),
        default_max_minutes=_int(kt, "default_max_minutes", d.default_max_minutes, w, lo=2, hi=limit),
        max_minutes_limit=limit,
        prompt_version=_str(kt, "prompt_version", d.prompt_version, w),
        window_words_per_minute=_int(kt, "window_words_per_minute", d.window_words_per_minute, w, lo=1),
        soft_label_max_seconds=_number(kt, "soft_label_max_seconds", d.soft_label_max_seconds, w, lo=0, hi=60),
    )
    if not cfg.default_min_minutes < cfg.default_max_minutes:
        raise ConfigError(f"{w}.default_min_minutes must be < {w}.default_max_minutes")
    return cfg


def _post(data: dict) -> PostConfig:
    po = _section(data, "post")
    d, w = PostConfig(), "post"
    backoff = po.get("retry_backoff", list(d.retry_backoff))
    if not isinstance(backoff, list) or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 3600 for x in backoff):
        raise ConfigError(f"{w}.retry_backoff must be a list of numbers between 0 and 3600 (seconds)")
    sources = po.get("image_sources", list(d.image_sources))
    if not isinstance(sources, list) or not all(isinstance(x, str) and x for x in sources):
        raise ConfigError(f"{w}.image_sources must be a list of non-empty strings")
    return PostConfig(
        model=_str(po, "model", d.model, w),
        think=_bool(po, "think", d.think, w),
        temperature=_number(po, "temperature", d.temperature, w, lo=0, hi=2),
        seed=_int(po, "seed", d.seed, w, lo=0),
        num_ctx=_int(po, "num_ctx", d.num_ctx, w, lo=512),
        prompt_version=_str(po, "prompt_version", d.prompt_version, w),
        retries=_int(po, "retries", d.retries, w, lo=0),
        chunk_words=_int(po, "chunk_words", d.chunk_words, w, lo=20, hi=5000),
        image_dir=Path(_str(po, "image_dir", str(d.image_dir), w)).expanduser(),
        image_sources=tuple(sources),
        ollama_host=_str(po, "ollama_host", d.ollama_host, w),
        timeout=_number(po, "timeout", d.timeout, w, lo=1),
        retry_backoff=tuple(float(x) for x in backoff),
    )


def _hashtags(section: dict, default: tuple[str, ...]) -> tuple[str, ...]:
    value = section.get("hashtags", list(default))
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ConfigError("web.hashtags must be a list of strings")
    return tuple(value)


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
        selection=_selection(data),
        titling=_titling(data),
        render=_render(data),
        web=_web(data),
        learning=_learning(data),
        khaithi=_khaithi(data),
        post=_post(data),
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
