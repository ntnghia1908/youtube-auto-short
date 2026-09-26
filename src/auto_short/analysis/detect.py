"""Shot and silence detection with ffmpeg (A2, A3) and parsers for its log output.

Canonical contract: docs/decisions/CP4-analysis-contract.md.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Protocol

# Two silences closer than this are one silence (A3).
MERGE_GAP = 0.05

_SHOWINFO_RE = re.compile(r"Parsed_showinfo.*?\bpts_time:\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")
_SIL_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")
_SIL_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")


class AnalysisError(Exception):
    """Analysis could not run or produced invalid output; message is user-facing."""


def _r(x: float) -> float:
    return round(x, 3)


def parse_showinfo(text: str) -> list[float]:
    """``pts_time`` of every frame printed by the ``showinfo`` filter, in log order."""
    return [float(m.group(1)) for m in _SHOWINFO_RE.finditer(text)]


def normalize_changes(changes: list[float], duration: float) -> list[float]:
    """Shot changes rounded to 3 decimals, strictly inside ``(0, duration)``, sorted, unique."""
    return sorted({_r(c) for c in changes if 0 < _r(c) < _r(duration)})


def normalize_silences(intervals: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """Clip to ``[0, duration]``, sort, merge silences < 0.05 s apart, round to 3 decimals."""
    clipped = sorted((max(0.0, a), min(duration, b)) for a, b in intervals)
    merged: list[list[float]] = []
    for a, b in clipped:
        if b <= a:
            continue
        if merged and a - merged[-1][1] < MERGE_GAP - 1e-9:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out = [(_r(a), _r(b)) for a, b in merged]
    return [(a, b) for a, b in out if b > a]


def parse_silencedetect(text: str, duration: float) -> list[tuple[float, float]]:
    """``silencedetect`` log -> silences; an unterminated silence ends at ``duration`` (A3)."""
    events = sorted(
        [(m.start(), "start", float(m.group(1))) for m in _SIL_START_RE.finditer(text)]
        + [(m.start(), "end", float(m.group(1))) for m in _SIL_END_RE.finditer(text)]
    )
    intervals: list[tuple[float, float]] = []
    open_start: float | None = None
    for _, kind, value in events:
        if kind == "start":
            open_start = value
        elif open_start is not None:
            intervals.append((open_start, value))
            open_start = None
    if open_start is not None:
        intervals.append((open_start, duration))
    return normalize_silences(intervals, duration)


class MediaAnalyzer(Protocol):
    """Detects shot changes and silences in a media file (fakeable in tests)."""

    def shot_changes(self, media: Path, *, threshold: float, scale_width: int) -> list[float]:
        """Timestamps (s) of frames whose scene score exceeds ``threshold``."""
        ...

    def silences(self, media: Path, *, noise_db: float, min_seconds: float, duration: float) -> list[tuple[float, float]]:
        """``(start, end)`` of audio silences (s)."""
        ...


def _ffmpeg(args: list[str]) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)
    except FileNotFoundError as exc:
        raise AnalysisError("ffmpeg not found on PATH") from exc
    if proc.returncode != 0:
        tail = [line for line in proc.stderr.strip().splitlines() if line.strip()][-1:] or ["no output"]
        raise AnalysisError(f"ffmpeg failed (exit {proc.returncode}): {tail[0]}")
    return proc.stderr


class FfmpegAnalyzer:
    """Real detector: ``ffmpeg`` system binary via ``subprocess`` (CP1 §10)."""

    def shot_changes(self, media: Path, *, threshold: float, scale_width: int) -> list[float]:
        vf = f"scale={scale_width}:-2,select='gt(scene,{threshold:g})',showinfo"
        return parse_showinfo(_ffmpeg(["-i", str(media), "-an", "-vf", vf, "-f", "null", "-"]))

    def silences(self, media: Path, *, noise_db: float, min_seconds: float, duration: float) -> list[tuple[float, float]]:
        af = f"silencedetect=noise={noise_db:g}dB:d={min_seconds:g}"
        return parse_silencedetect(_ffmpeg(["-i", str(media), "-vn", "-af", af, "-f", "null", "-"]), duration)
