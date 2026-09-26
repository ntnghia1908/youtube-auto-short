"""Media probing via the system ``ffprobe`` binary."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path


class ProbeError(Exception):
    """ffprobe is missing, failed, or the file has no video stream."""


def _fps(stream: dict) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        try:
            fps = Fraction(value)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if fps > 0:
            return round(float(fps), 3)
    return None


def probe(path: Path, ffprobe: str = "ffprobe") -> dict:
    """Return duration, width, height, fps and codecs of a video file."""
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise ProbeError(f"'{ffprobe}' not found on PATH; install ffmpeg") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit {proc.returncode}"
        raise ProbeError(f"ffprobe cannot read {path} (not a media file?): {detail}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned invalid JSON for {path}") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise ProbeError(f"no video stream in {path}: not a video file")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = data.get("format", {}).get("duration") or video.get("duration")
    try:
        duration = round(float(duration), 3)
    except (TypeError, ValueError):
        raise ProbeError(f"ffprobe reports no duration for {path}") from None

    return {
        "duration": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": _fps(video),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
    }
