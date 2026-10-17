"""CP8.33 G3: ``ffprobe`` of the input clips and the "can they be joined by stream copy" check."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .spec import CompilationError

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)
    except FileNotFoundError as exc:
        raise CompilationError(f"không tìm thấy '{cmd[0]}' trên PATH; cài ffmpeg") from exc


def last_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    vcodec: str | None
    width: int | None
    height: int | None
    pix_fmt: str | None
    fps: str | None  # r_frame_rate, e.g. "30000/1001"
    acodec: str | None
    sample_rate: str | None
    channels: int | None

    @property
    def signature(self) -> tuple:
        """What must be equal for the concat demuxer to copy the streams (G3)."""
        return (self.vcodec, self.width, self.height, self.pix_fmt, self.fps,
                self.acodec, self.sample_rate, self.channels)

    @property
    def complete(self) -> bool:
        return self.vcodec is not None and self.acodec is not None and self.duration > 0


def probe(path: Path, runner: Runner = run) -> MediaInfo:
    proc = runner(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if proc.returncode != 0:
        raise CompilationError(f"ffprobe không đọc được {Path(path).name}: {last_line(proc.stderr) or f'exit {proc.returncode}'}")
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        raise CompilationError(f"ffprobe trả về JSON không hợp lệ cho {Path(path).name}") from exc
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return MediaInfo(duration=duration, vcodec=v.get("codec_name"), width=v.get("width"), height=v.get("height"),
                     pix_fmt=v.get("pix_fmt"), fps=v.get("r_frame_rate"), acodec=a.get("codec_name"),
                     sample_rate=a.get("sample_rate"), channels=a.get("channels"))


def compatible(infos: list[MediaInfo]) -> bool:
    """G3: every input has the same codecs, size, fps, sample rate and channel count."""
    return len({i.signature for i in infos}) <= 1
