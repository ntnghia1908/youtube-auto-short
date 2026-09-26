"""Transcript providers (T1–T4): YouTube caption, local subtitle, faster-whisper."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import Config
from .parsers import FORMATS, RawSegment, parse
from .whisper import WhisperBackend
from .youtube import CaptionFetcher, pick_track

YOUTUBE, LOCAL_SUBTITLE, WHISPER = "youtube", "local_subtitle", "whisper"
ORDER = (YOUTUBE, LOCAL_SUBTITLE, WHISPER)  # fixed (T1)


class ProviderUnavailable(Exception):
    """The provider has nothing to offer for this episode (not an error)."""


@dataclass(frozen=True)
class Context:
    episode_id: str
    source_kind: str  # local | youtube
    source_uri: str
    media_path: Path  # absolute
    duration: float
    subtitle: Path | None  # resolved local subtitle (explicit or sidecar), absolute
    config: Config


@dataclass
class Candidate:
    source: str
    method: str
    language: str | None  # language metadata of the track/provider (T5)
    segments: list[RawSegment]
    provider: dict
    raw: dict | None = None  # {"path", "sha256"} written to transcript.json
    raw_file: tuple[str, bytes] | None = None  # (path relative to episode dir, bytes) to store


class TranscriptProvider(Protocol):
    name: str

    def fetch(self, ctx: Context) -> Candidate: ...


class YouTubeCaptionProvider:
    name = YOUTUBE

    def __init__(self, fetcher: CaptionFetcher):
        self.fetcher = fetcher

    def fetch(self, ctx: Context) -> Candidate:
        if ctx.source_kind != "youtube":
            raise ProviderUnavailable("source is not YouTube")
        track = pick_track(self.fetcher.tracks(ctx.source_uri))
        if track is None:
            raise ProviderUnavailable("no Vietnamese caption track (manual vi, auto vi-orig, auto vi)")
        lang, auto = track
        data = self.fetcher.download(ctx.source_uri, lang, auto)
        rel = f"transcript/youtube.{lang}.json3"
        return Candidate(
            source=YOUTUBE,
            method="youtube_auto_caption" if auto else "youtube_manual_caption",
            language=lang,
            segments=parse(data, "json3"),
            provider={"track": lang, "auto": auto},
            raw={"path": rel, "sha256": hashlib.sha256(data).hexdigest()},
            raw_file=(rel, data),
        )


class LocalSubtitleProvider:
    name = LOCAL_SUBTITLE

    def fetch(self, ctx: Context) -> Candidate:
        if ctx.subtitle is None:
            raise ProviderUnavailable("no subtitle file (--subtitle or sidecar next to the local video)")
        fmt = FORMATS[ctx.subtitle.suffix.lower()]
        data = ctx.subtitle.read_bytes()
        return Candidate(
            source=LOCAL_SUBTITLE,
            method=f"subtitle_{fmt}",
            language=ctx.config.transcript.language,
            segments=parse(data, fmt),
            provider={"path": str(ctx.subtitle), "format": fmt},
            raw={"path": str(ctx.subtitle), "sha256": hashlib.sha256(data).hexdigest()},
        )


class WhisperProvider:
    name = WHISPER

    def __init__(self, backend: WhisperBackend):
        self.backend = backend

    def fetch(self, ctx: Context) -> Candidate:
        wc = ctx.config.transcript.whisper
        if not ctx.media_path.is_file():
            raise ProviderUnavailable(f"media file not found: {ctx.media_path}")
        segments = self.backend.transcribe(ctx.media_path, language=ctx.config.transcript.language, config=wc)
        return Candidate(
            source=WHISPER,
            method="faster_whisper",
            language=ctx.config.transcript.language,
            segments=segments,
            provider={
                "model": wc.model,
                "device": wc.device,
                "compute_type": wc.compute_type,
                "vad_filter": wc.vad_filter,
                "faster_whisper_version": self.backend.version,
            },
        )
