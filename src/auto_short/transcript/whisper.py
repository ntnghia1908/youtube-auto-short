"""Whisper fallback (T4): ``faster-whisper`` behind a small backend protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..config import WhisperConfig
from .parsers import RawSegment, RawWord


class WhisperBackend(Protocol):
    version: str  # faster-whisper version recorded in transcript.json

    def transcribe(self, media: Path, *, language: str, config: WhisperConfig) -> list[RawSegment]: ...


class FasterWhisperBackend:
    """Real backend; ``faster_whisper`` is imported only when a transcription runs."""

    def __init__(self) -> None:
        self._models: dict[tuple, object] = {}

    @property
    def version(self) -> str:
        from importlib.metadata import version

        return version("faster-whisper")

    def _model(self, config: WhisperConfig):
        key = (config.model, config.device, config.compute_type, config.effective_cpu_threads, config.models_dir)
        if key not in self._models:
            from faster_whisper import WhisperModel

            config.models_dir.mkdir(parents=True, exist_ok=True)
            self._models[key] = WhisperModel(
                config.model,
                device=config.device,
                compute_type=config.compute_type,
                cpu_threads=config.effective_cpu_threads,
                download_root=str(config.models_dir),
            )
        return self._models[key]

    def transcribe(self, media: Path, *, language: str, config: WhisperConfig) -> list[RawSegment]:
        segments, _info = self._model(config).transcribe(
            str(media),
            language=language,
            vad_filter=config.vad_filter,
            word_timestamps=config.word_timestamps,
        )
        out = []
        for seg in segments:
            words = [RawWord(w.start, w.word.strip(), w.end) for w in (seg.words or []) if w.word.strip()]
            out.append(RawSegment(seg.start, seg.end, seg.text, words))
        return out
