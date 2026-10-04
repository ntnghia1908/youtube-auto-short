"""YouTube download via the ``yt-dlp`` Python library (video only, no captions)."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import IngestConfig

# Subset of yt-dlp info kept in metadata.json.
INFO_KEYS = ("id", "title", "channel", "upload_date", "webpage_url", "duration")


class DownloadError(Exception):
    """Download failed (network, YouTube, format...)."""


class YoutubeBlocked(DownloadError):
    """FIX-youtube-botcheck-wait Y1: YouTube refuses the download for now (bot check "Sign in to confirm you're not a
    bot", HTTP 429 / Too Many Requests): temporary, so the web queue waits and retries instead of failing."""


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_BLOCK_MARKERS = ("confirm you're not a bot", "confirm you are not a bot", "http error 429", "too many requests")


def is_blocked_message(text: str) -> bool:
    """Y1: does a yt-dlp error text say that YouTube blocked this client (bot check / rate limit)?"""
    plain = _ANSI.sub("", str(text)).replace("\u2019", "'").replace("\u2018", "'").lower()
    return any(m in plain for m in _BLOCK_MARKERS)


@dataclass(frozen=True)
class Download:
    path: Path  # downloaded media file inside dest_dir
    info: dict  # yt-dlp info dict (at least INFO_KEYS when available)


class Downloader(Protocol):
    def __call__(self, url: str, dest_dir: Path, config: IngestConfig) -> Download: ...


def youtube_info(info: dict) -> dict:
    out = {k: info.get(k) for k in INFO_KEYS}
    if out["channel"] is None:
        out["channel"] = info.get("uploader")
    return out


def ytdlp_download(url: str, dest_dir: Path, config: IngestConfig) -> Download:
    """Download ``url`` into ``dest_dir/source.<ext>`` (mp4 when merged)."""
    import yt_dlp

    opts = {
        "format": config.youtube_format,
        "merge_output_format": "mp4",
        "outtmpl": {"default": str(dest_dir / "source.%(ext)s")},
        "noplaylist": True,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "js_runtimes": {name: {} for name in config.js_runtimes},
        "noprogress": not sys.stderr.isatty(),
        "quiet": False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=True))
    except yt_dlp.utils.DownloadError as exc:
        if is_blocked_message(str(exc)):
            raise YoutubeBlocked(f"yt-dlp download failed: {exc}") from exc
        raise DownloadError(f"yt-dlp download failed: {exc}") from exc

    files = [Path(d["filepath"]) for d in info.get("requested_downloads", []) if d.get("filepath")]
    files = [f for f in files if f.is_file()] or sorted(dest_dir.glob("source.*"))
    if len(files) != 1:
        raise DownloadError(f"expected one downloaded file in {dest_dir}, found {len(files)}")
    return Download(files[0], info)
