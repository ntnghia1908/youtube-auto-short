"""YouTube download via the ``yt-dlp`` Python library (video only, no captions)."""

from __future__ import annotations

import json
import re
import tempfile
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from ..config import IngestConfig
from ..store.cancellation import current_stop, run_process

# Subset of yt-dlp info kept in metadata.json.
INFO_KEYS = ("id", "title", "channel", "upload_date", "webpage_url", "duration")


class DownloadError(Exception):
    """Download failed (network, YouTube, format...)."""


class YoutubeBlocked(DownloadError):
    """Y1: bot check, rate limit or temporary network failure during download.

    The web queue waits and retries instead of failing.
    """


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_BLOCK_MARKERS = (
    "confirm you're not a bot", "confirm you are not a bot", "http error 429", "too many requests",
    "the read operation timed out", "read timed out", "connection reset by peer", "connection aborted",
    "remote end closed connection", "incompleteread", "incomplete read",
    "broken pipe", "handshake operation timed out",
)


def is_blocked_message(text: str) -> bool:
    """Y1: does a yt-dlp error indicate a bot check, rate limit or temporary network failure?"""
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
    if current_stop() is not None:
        return _ytdlp_process(url, dest_dir, config)
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


def _ytdlp_process(url: str, dest_dir: Path, config: IngestConfig) -> Download:
    # The existing library downloader still owns options, metadata and error classification.
    # Only background redownloads need a separate process, including yt-dlp's ffmpeg children.
    with tempfile.TemporaryDirectory(prefix=".ytdlp-", dir=dest_dir) as temporary:
        result = Path(temporary) / "result.json"
        args = json.dumps([url, str(dest_dir), asdict(config), str(result)])
        code = run_process([sys.executable, "-c",
                            "from auto_short.ingest.youtube import _download_worker; _download_worker()", args])
        if code != 0 or not result.is_file():
            raise DownloadError(f"yt-dlp download failed: exit {code}")
        doc = json.loads(result.read_text(encoding="utf-8"))
        if doc.get("blocked"):
            raise YoutubeBlocked(doc["error"])
        if doc.get("error"):
            raise DownloadError(doc["error"])
        return Download(Path(doc["path"]), doc["info"])


def _download_worker():
    url, dest, config, result = json.loads(sys.argv[1])
    try:
        got = ytdlp_download(url, Path(dest), IngestConfig(**config))
        doc = {"path": str(got.path), "info": got.info}
    except DownloadError as exc:
        doc = {"error": str(exc), "blocked": isinstance(exc, YoutubeBlocked)}
    Path(result).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
