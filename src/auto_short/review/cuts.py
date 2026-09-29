"""Pure cut-point logic of CP9: a Short's range from caption lines (C3), its validity (C4) and its kept segments
(C5). No I/O; all arithmetic in integer milliseconds like CP4.

- C3: from the first line ``a`` and the last line ``b`` (``transcript.json`` segments), ``start`` = the speech edge
  before ``a`` by the CP4 A6 rule (end of the silence nearest ``a.start`` within ``align_tolerance``, minus
  ``boundary_pad``, never into the line before), ``end`` likewise around ``b.end``. A nudge of ±0.2 s steps (at
  most ±2.0 s) is added on top; nudging never leaves the content window nor cuts more than 2.0 s into the next
  line. Editing an existing Short keeps its current start / end while its first / last line is unchanged.
- C4: inside the content window, no ``non_speech`` label (hard break, CP4 A4; the short labels of a khai thị
  episode, CP8.9 A3.1, are pauses) nor hard-break silence inside, duration after trimming silences in
  ``[min_duration, max_duration]`` of the episode's ``candidates.json``. Overlap with other Shorts and shot
  changes near an edge are warnings only.
- C5: trims = CP4 A8 on ``silences.json`` for ``[start, end]`` (never the candidate's trims).

Canonical contract: docs/decisions/CP8.2-title-override-contract.md T8 (CP9).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from ..analysis.candidates import plan_trims
from ..transcript.normalize import NON_SPEECH, SPEECH
from .logic import ReviewError

NUDGE_STEP_MS = 200  # C3: ±0.2 s
MAX_NUDGE_MS = 2000  # C3: at most ±2.0 s from the base point
MAX_INTO_LINE_MS = 2000  # C3: never more than 2.0 s into the neighbouring line


def ms(seconds: float) -> int:
    return round(seconds * 1000)


def sec(value_ms: int) -> float:
    return value_ms / 1000


@dataclass(frozen=True)
class Episode:
    """What the range rules need from one episode (built by the caller from its artifacts)."""

    segments: list[dict]  # transcript.json segments (id, start, end, kind, text), time order
    silences: list[tuple[float, float]]  # silences.json
    params: dict  # candidates.json params
    content: tuple[float, float]  # candidates.json content window
    shot_changes: list[float] = field(default_factory=list)  # shots.json changes (warnings only)

    def index(self, segment_id: str) -> int:
        for n, s in enumerate(self.segments):
            if s["id"] == segment_id:
                return n
        raise ReviewError(f"không có dòng phụ đề {segment_id!r}")

    def speech(self, segment_id: str) -> int:
        n = self.index(segment_id)
        if self.segments[n]["kind"] != SPEECH:
            raise ReviewError(f"dòng {segment_id} không phải lời nói ({self.segments[n]['text']})")
        return n


@dataclass(frozen=True)
class Range:
    """A candidate Short range with everything the UI shows (C3/C4/C5)."""

    start: float
    end: float
    source_duration: float
    duration: float  # after trimming silences (C5)
    trims: list[list[float]]
    start_segment: str | None  # first / last caption line (midpoint rule, see range_segments)
    end_segment: str | None
    error: str | None  # C4 violation (the range cannot be saved), None when valid
    warnings: list[str]  # shot change near an edge (overlaps are added by the caller)


def check_nudge(value: object, what: str) -> int:
    """A nudge in seconds (multiple of 0.2, |x| <= 2.0) -> milliseconds; anything else -> ReviewError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReviewError(f"{what} phải là số giây")
    steps = value * 1000 / NUDGE_STEP_MS
    if abs(steps - round(steps)) > 1e-6 or abs(round(steps) * NUDGE_STEP_MS) > MAX_NUDGE_MS:
        raise ReviewError(f"{what} phải là bội của 0.2 s trong khoảng ±2.0 s")
    return round(steps) * NUDGE_STEP_MS


def range_segments(ep: Episode, start: float, end: float) -> tuple[str | None, str | None]:
    """First / last speech line of ``[start, end]``: speech segments whose midpoint lies inside (caption timing is
    approximate and consecutive captions touch, so the midpoint is the robust test)."""
    s0, s1 = ms(start), ms(end)
    inside = [s["id"] for s in ep.segments
              if s["kind"] == SPEECH and s0 <= (ms(s["start"]) + ms(s["end"])) // 2 <= s1]
    return (inside[0], inside[-1]) if inside else (None, None)


def _silences_ms(ep: Episode) -> list[tuple[int, int]]:
    return [(ms(a), ms(b)) for a, b in ep.silences]


def base_start(ep: Episode, n: int) -> int:
    """C3 start for first line ``segments[n]`` (CP4 A6 "đầu unit" + ``boundary_pad``)."""
    t0 = ms(ep.segments[n]["start"])
    tol, pad = ms(ep.params["align_tolerance"]), ms(ep.params["boundary_pad"])
    near = [(a, b) for a, b in _silences_ms(ep) if a <= t0 + tol and b >= t0 - tol]
    if near:
        a, b = min(near, key=lambda s: (abs(s[1] - t0), s[1]))
        edge, lower = b, a  # speech starts at the silence end; padding stays inside the silence
    else:
        edge, lower = t0, min(ms(ep.segments[n - 1]["end"]), t0) if n > 0 else 0
    return max(edge - pad, lower, ms(ep.content[0]))


def base_end(ep: Episode, n: int) -> int:
    """C3 end for last line ``segments[n]`` (CP4 A6 "cuối unit" + ``boundary_pad``)."""
    t1 = ms(ep.segments[n]["end"])
    tol, pad = ms(ep.params["align_tolerance"]), ms(ep.params["boundary_pad"])
    near = [(a, b) for a, b in _silences_ms(ep) if a <= t1 + tol and b >= t1 - tol]
    if near:
        a, b = min(near, key=lambda s: (abs(s[0] - t1), s[0]))
        edge, upper = a, b
    else:
        nxt = ep.segments[n + 1]["start"] if n + 1 < len(ep.segments) else ep.content[1]
        edge, upper = t1, max(ms(nxt), t1)
    return min(edge + pad, upper, ms(ep.content[1]))


def resolve_range(ep: Episode, start_segment: str, end_segment: str, start_nudge: object = 0,
                  end_nudge: object = 0, current: tuple[float, float] | None = None) -> tuple[int, int]:
    """C3: (start, end) in ms. ``current`` = the Short's range now (cut or original) when editing it: a line that
    is still its first / last line keeps the current point as base, a new line starts from the C3 point.
    Nudges beyond the limits raise ReviewError (the UI disables the button before)."""
    a, b = ep.speech(start_segment), ep.speech(end_segment)
    if b < a:
        raise ReviewError("dòng cuối đứng trước dòng đầu")
    dn0, dn1 = check_nudge(start_nudge, "start_nudge"), check_nudge(end_nudge, "end_nudge")
    cur0 = cur1 = None
    if current is not None:
        cur0, cur1 = range_segments(ep, *current)
    s0 = ms(current[0]) if current is not None and cur0 == start_segment else base_start(ep, a)
    s1 = ms(current[1]) if current is not None and cur1 == end_segment else base_end(ep, b)
    start, end = s0 + dn0, s1 + dn1
    c0, c1 = ms(ep.content[0]), ms(ep.content[1])
    if dn0 and start < c0:
        raise ReviewError("điểm đầu ra ngoài phần nội dung của video")
    if dn1 and end > c1:
        raise ReviewError("điểm cuối ra ngoài phần nội dung của video")
    if dn0 < 0 and a > 0 and start < ms(ep.segments[a - 1]["end"]) - MAX_INTO_LINE_MS:
        raise ReviewError("điểm đầu lấn vào dòng trước quá 2 s; thêm một dòng thay vì lùi tiếp")
    if dn1 > 0 and b + 1 < len(ep.segments) and end > ms(ep.segments[b + 1]["start"]) + MAX_INTO_LINE_MS:
        raise ReviewError("điểm cuối lấn vào dòng sau quá 2 s; thêm một dòng thay vì kéo tiếp")
    if end <= start:
        raise ReviewError("điểm cuối phải sau điểm đầu")
    return start, end


def _fmt(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def evaluate(ep: Episode, start_ms: int, end_ms: int) -> Range:
    """C4 validity + C5 trims / duration of ``[start, end]``."""
    start, end = sec(start_ms), sec(end_ms)
    trims = plan_trims(start, end, ep.silences, ep.params["max_pause"])
    dur_ms = end_ms - start_ms - sum(ms(b) - ms(a) for a, b in trims)
    p = ep.params
    error = None
    c0, c1 = ms(ep.content[0]), ms(ep.content[1])
    soft = p.get("soft_label_max_seconds")
    if start_ms < c0 or end_ms > c1:
        error = (f"nằm ngoài phần nội dung của video ({_fmt(ep.content[0])}–{_fmt(ep.content[1])}; "
                 "phần giới thiệu / kết thúc bị loại)")
    if error is None:
        for s in ep.segments:
            a, b = ms(s["start"]), ms(s["end"])
            if s["kind"] != NON_SPEECH or not (a < end_ms and b > start_ms):
                continue
            if soft is not None and b - a <= ms(soft):
                continue  # CP8.9 A3.1: a short label of a khai thị episode is a pause
            error = f"chứa đoạn không phải lời nói {s['text']} ở {_fmt(s['start'])} (không ghép qua chỗ ngắt)"
            break
    if error is None:
        hard = ms(p["hard_break_silence"])
        for a, b in _silences_ms(ep):
            if b - a >= hard and a > start_ms and b < end_ms:
                error = f"chứa khoảng lặng dài {sec(b - a):g} s ở {_fmt(sec(a))} (không ghép qua chỗ ngắt)"
                break
    lo, hi = ms(p["min_duration"]), ms(p["max_duration"])
    if error is None and not lo <= dur_ms <= hi:
        error = (f"dài {sec(dur_ms):.1f} s sau khi rút khoảng lặng, cần {sec(lo):g}–{sec(hi):g} s")
    warnings = []
    guard = ms(p.get("shot_guard", 1.0))
    changes = [ms(c) for c in ep.shot_changes]
    k = bisect.bisect_right(changes, start_ms)
    if k < len(changes) and changes[k] < min(start_ms + guard, end_ms):
        warnings.append(f"có chuyển cảnh trong {sec(guard):g} s đầu")
    k = bisect.bisect_right(changes, max(end_ms - guard, start_ms))
    if k < len(changes) and changes[k] < end_ms:
        warnings.append(f"có chuyển cảnh trong {sec(guard):g} s cuối")
    first, last = range_segments(ep, start, end)
    return Range(start, end, sec(end_ms - start_ms), sec(dur_ms), trims, first, last, error, warnings)


def overlaps(start: float, end: float, others: list[tuple[str, float, float]]) -> list[str]:
    """Ids of the ranges in ``others`` (``(clip_id, start, end)``) that overlap ``[start, end]`` (touching is not
    overlapping, like CP5 B6)."""
    s0, s1 = ms(start), ms(end)
    return [cid for cid, a, b in others if ms(a) < s1 and ms(b) > s0]


def kept_segments_ms(start: float, end: float, silences: list[tuple[float, float]],
                     max_pause: float) -> list[tuple[int, int]]:
    """C5: the render's kept segments of a manual range (CP7 R3 with the recomputed trims)."""
    from ..render.plan import kept_segments

    return kept_segments(start, end, plan_trims(start, end, silences, max_pause))
