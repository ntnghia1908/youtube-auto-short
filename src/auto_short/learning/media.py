"""Stage ``media`` (CL1 C10, G5 = B): the first ``window_seconds`` of the video -> ``clip.mp4``.

Only ``[0, window]`` is retrieved (yt-dlp ``download_ranges``; the whole video is never
downloaded). The download goes to ``.media-tmp/``, is probed, and only then renamed to
``clip.mp4``; ``.media-tmp/`` is removed in every case.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .. import hashing
from ..config import Config
from ..ingest.probe import ProbeError, probe
from ..workspace import Workspace, atomic_write_json

log = logging.getLogger("auto_short")

STAGE = "media"
CLIP_NAME = "clip.mp4"
MEDIA_NAME = "media.json"
TMP_DIR = ".media-tmp"
MEDIA_SCHEMA_VERSION = 1
METHOD = "yt-dlp download_ranges"
DOWNSTREAM: tuple[str, ...] = ()
DURATION_TOLERANCE = 2.0  # s, around min(window, video duration) .. window


class MediaError(Exception):
    """The clip could not be retrieved or is not acceptable; the message is user-facing."""


@dataclass(frozen=True)
class ClipDownload:
    path: Path  # the downloaded file inside dest_dir
    format_id: str | None  # yt-dlp format id, e.g. "398+251"
    video_duration: float | None  # duration of the whole video (yt-dlp info)


class ClipDownloader(Protocol):
    def __call__(self, url: str, dest_dir: Path, *, end: float, media_format: str,
                 js_runtimes: tuple[str, ...]) -> ClipDownload: ...


def used_config(config: Config) -> dict:
    return {
        "learning.window_seconds": config.learning.window_seconds,
        "learning.media_format": config.learning.media_format,
    }


def ytdlp_clip(url: str, dest_dir: Path, *, end: float, media_format: str,
               js_runtimes: tuple[str, ...]) -> ClipDownload:
    """Download ``[0, end]`` of ``url`` into ``dest_dir/clip.<ext>`` (partial retrieval)."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    opts = {
        "format": media_format,
        "merge_output_format": "mp4",
        "outtmpl": {"default": str(dest_dir / "clip.%(ext)s")},
        "download_ranges": download_range_func(None, [(0, end)]),
        "force_keyframes_at_cuts": True,
        "noplaylist": True,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "js_runtimes": {name: {} for name in js_runtimes},
        "noprogress": not sys.stderr.isatty(),
        "quiet": False,
        "logtostderr": True,  # stdout carries only the command's result lines
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=True))
    except yt_dlp.utils.DownloadError as exc:
        raise MediaError(f"yt-dlp clip download failed: {exc}") from exc

    files = [Path(d["filepath"]) for d in info.get("requested_downloads", []) if d.get("filepath")]
    files = [f for f in files if f.is_file()] or sorted(p for p in dest_dir.glob("clip.*") if p.is_file())
    if len(files) != 1:
        raise MediaError(f"expected one downloaded clip in {dest_dir}, found {len(files)}")
    duration = info.get("duration")
    return ClipDownload(files[0], info.get("format_id"), float(duration) if duration is not None else None)


def check_clip(meta: dict, *, window: float, video_duration: float | None) -> str | None:
    """C10 acceptance of the probed clip; the reason, else None."""
    if not meta.get("audio_codec"):
        return "clip has no audio stream"
    expected = min(window, video_duration) if video_duration is not None else window
    lo, hi = expected - DURATION_TOLERANCE, window + DURATION_TOLERANCE
    if not lo <= meta["duration"] <= hi:
        return f"clip duration {meta['duration']} s outside [{lo:g}, {hi:g}] s"
    return None


def media_document(episode_id: str, clip: Path, meta: dict, *, window: float, format_id: str | None) -> dict:
    return {
        "schema_version": MEDIA_SCHEMA_VERSION,
        "episode_id": episode_id,
        "path": CLIP_NAME,
        "sha256": hashing.sha256_file(clip),
        "size": clip.stat().st_size,
        "window": {"start": 0.0, "end": window},
        "duration": meta["duration"],
        "width": meta["width"],
        "height": meta["height"],
        "video_codec": meta["video_codec"],
        "audio_codec": meta["audio_codec"],
        "format_id": format_id,
        "method": METHOD,
    }


def remove_outputs(ws: Workspace) -> None:
    for name in (CLIP_NAME, MEDIA_NAME):
        (ws.dir / name).unlink(missing_ok=True)


def produce(ws: Workspace, url: str, config: Config, downloader: ClipDownloader) -> list[str]:
    """The stage action: download ``[0, window]``, probe, validate, keep; returns the artifacts."""
    window = config.learning.window_seconds
    tmp = ws.dir / TMP_DIR
    try:
        remove_outputs(ws)
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        dl = downloader(url, tmp, end=window, media_format=config.learning.media_format,
                        js_runtimes=config.ingest.js_runtimes)
        if dl.path.suffix.lower() != ".mp4":
            raise MediaError(f"downloaded clip is {dl.path.suffix or 'without extension'}, expected .mp4")
        try:
            meta = probe(dl.path)
        except ProbeError as exc:
            raise MediaError(str(exc)) from exc
        reason = check_clip(meta, window=window, video_duration=dl.video_duration)
        if reason is not None:
            raise MediaError(reason)
        clip = ws.dir / CLIP_NAME
        os.replace(dl.path, clip)
        doc = media_document(ws.episode_id, clip, meta, window=window, format_id=dl.format_id)
        atomic_write_json(ws.dir / MEDIA_NAME, doc)
    except BaseException:
        remove_outputs(ws)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log.info("%s: %s %.3f s %sx%s %s/%s %d bytes (format %s)", STAGE, CLIP_NAME, doc["duration"], doc["width"],
             doc["height"], doc["video_codec"], doc["audio_codec"], doc["size"], doc["format_id"])
    return [CLIP_NAME, MEDIA_NAME]
