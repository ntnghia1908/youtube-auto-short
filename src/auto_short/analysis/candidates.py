"""Deterministic content window, cut points, speech units and candidates (A4–A9).

Canonical contract: docs/decisions/CP4-analysis-contract.md. Pure functions: input is
``transcript.json`` segments, silences and shot changes (seconds, 3 decimals); all
arithmetic is done in integer milliseconds so durations and trims are exact.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from ..config import AnalysisConfig
from ..transcript.normalize import NON_SPEECH, SPEECH, speech_tokens
from .detect import AnalysisError

SILENCE, HARD_BREAK, CONTENT_EDGE = "silence", "hard_break", "content_edge"


def _ms(x: float) -> int:
    return round(x * 1000)


def _s(ms: int) -> float:
    return ms / 1000


# --- A5 content window ----------------------------------------------------------------------

@dataclass(frozen=True)
class ContentWindow:
    start: float
    end: float
    start_reason: str
    end_reason: str


def detect_content_window(segments: list[dict], silences: list[tuple[float, float]], duration: float,
                          cfg: AnalysisConfig) -> ContentWindow:
    """Exclude intro music + announcement and everything from the outro music on (A5)."""
    intro = [s for s in segments if s["kind"] == NON_SPEECH and s["start"] < cfg.intro_window]
    if intro:
        last = max(intro, key=lambda s: (s["end"], s["start"]))
        m = last["end"]
        after = [(a, b) for a, b in silences
                 if a >= m and a < cfg.intro_window and _ms(b) - _ms(a) >= _ms(cfg.intro_min_silence)]
        if after:
            a, b = after[0]
            start, start_reason = b, f"intro: non_speech {last['id']} + silence {a!r}-{b!r}"
        else:
            start = m
            start_reason = (f"intro: non_speech {last['id']} (no silence >= {cfg.intro_min_silence!r} s "
                            f"before {cfg.intro_window!r} s)")
    else:
        start, start_reason = 0.0, "no intro detected"

    outro = [s for s in segments
             if s["kind"] == NON_SPEECH and s["end"] > duration - cfg.outro_window and s["start"] >= start]
    if outro:
        end, end_reason = outro[0]["start"], f"outro: non_speech {outro[0]['id']}"
    else:
        end, end_reason = duration, "no outro detected"
    return ContentWindow(float(start), float(end), start_reason, end_reason)


# --- A6 cut points ----------------------------------------------------------------------------

@dataclass
class Cut:
    """A boundary between speech units, as a region ``[lo, hi]`` in ms.

    ``exact`` cuts are audio silences: the unit before ends at ``lo`` and the unit after
    starts at ``hi``; clip padding may extend into the silence. Other cuts (content edges,
    ``non_speech`` labels) take their speech edge from the nearest silence and clip
    padding never crosses them.
    """

    kind: str
    lo: int
    hi: int
    seconds: float | None
    exact: bool
    split: int | None = None  # segments with midpoint before split belong to the unit before

    def __post_init__(self):
        if self.split is None:
            self.split = (self.lo + self.hi) // 2

    @property
    def brk(self) -> dict:
        return {"kind": self.kind, "seconds": self.seconds}


def _aligned(sil: tuple[int, int], starts: list[int], tol: int) -> bool:
    i = bisect.bisect_left(starts, sil[0] - tol)
    return i < len(starts) and starts[i] <= sil[1] + tol


def find_cut_points(segments: list[dict], silences: list[tuple[float, float]], window: ContentWindow,
                    cfg: AnalysisConfig) -> list[Cut]:
    """Content edges, hard breaks (A4) and aligned boundary silences (A6), in time order."""
    cs, ce = _ms(window.start), _ms(window.end)
    tol = _ms(cfg.align_tolerance)
    starts = sorted(_ms(s["start"]) for s in segments if s["kind"] == SPEECH)
    regions: list[Cut] = []
    for s in segments:
        a, b = _ms(s["start"]), _ms(s["end"])
        if s["kind"] == NON_SPEECH and cs <= a < ce:
            regions.append(Cut(HARD_BREAK, a, min(b, ce), None, exact=False))
    for a_s, b_s in silences:
        a, b = _ms(a_s), _ms(b_s)
        if not (cs <= a and b <= ce):
            continue
        length = b - a
        if length >= _ms(cfg.hard_break_silence):
            regions.append(Cut(HARD_BREAK, a, b, _s(length), exact=True))
        elif length >= _ms(cfg.min_boundary_silence) and _aligned((a, b), starts, tol):
            regions.append(Cut(SILENCE, a, b, _s(length), exact=True))

    # A silence that overlaps a non_speech label joins it as one hard break.
    regions.sort(key=lambda c: (c.lo, c.hi))
    merged: list[Cut] = []
    for c in regions:
        prev = merged[-1] if merged else None
        if prev is not None and c.lo < prev.hi and not (prev.exact and c.exact):
            merged[-1] = Cut(HARD_BREAK, prev.lo, max(prev.hi, c.hi), None, exact=False)
        else:
            merged.append(c)
    return ([Cut(CONTENT_EDGE, cs, cs, None, exact=False, split=cs)] + merged
            + [Cut(CONTENT_EDGE, ce, ce, None, exact=False, split=ce)])


# --- A7 speech units --------------------------------------------------------------------------

@dataclass
class Unit:
    start: int
    end: int
    min_start: int  # clip start may not go before this (A6 padding bound)
    max_end: int  # clip end may not go after this
    segments: list[dict]
    before: Cut
    after: Cut
    id: str = ""
    words: int = 0
    text: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id, "start": _s(self.start), "end": _s(self.end),
            "segment_ids": [self.segments[0]["id"], self.segments[-1]["id"]],
            "text": self.text, "words": self.words,
            "break_before": self.before.brk, "break_after": self.after.brk,
        }


def _start_edge(t0: int, bound: int, limit: int, sils: list[tuple[int, int]], tol: int) -> int:
    """Speech start near caption time ``t0``: end of the nearest silence around it, else ``t0``."""
    near = [b for a, b in sils if a <= t0 + tol and b >= t0 - tol and b < limit]
    edge = min(near, key=lambda b: (abs(b - t0), b)) if near else t0
    return max(edge, bound)


def _end_edge(t1: int, bound: int, limit: int, sils: list[tuple[int, int]], tol: int) -> int:
    """Speech end near caption time ``t1``: start of the nearest silence around it, else ``t1``."""
    near = [a for a, b in sils if a <= t1 + tol and b >= t1 - tol and a > limit]
    edge = min(near, key=lambda a: (abs(a - t1), a)) if near else t1
    return min(edge, bound)


def _make_unit(p: Cut, q: Cut, speech: list[dict], mids: list[int], sils: list[tuple[int, int]],
               tol: int) -> Unit | None:
    segs = speech[bisect.bisect_left(mids, p.split):bisect.bisect_left(mids, q.split)]
    if not segs:
        return None
    start = p.hi if p.exact else _start_edge(_ms(segs[0]["start"]), p.hi, q.lo, sils, tol)
    end = q.lo if q.exact else _end_edge(_ms(segs[-1]["end"]), q.lo, start, sils, tol)
    if end <= start:
        return None
    return Unit(start, end, p.lo if p.exact else p.hi, q.hi if q.exact else q.lo, segs, p, q)


def build_units(segments: list[dict], silences: list[tuple[float, float]], cuts: list[Cut],
                cfg: AnalysisConfig) -> list[Unit]:
    """One unit between consecutive cut points (A7).

    A stretch without a speech segment is not a unit: when it touches a ``silence`` cut
    that cut is dropped (the stretch joins its neighbour); between two hard breaks /
    content edges it is skipped.
    """
    speech = sorted((s for s in segments if s["kind"] == SPEECH), key=lambda s: (s["start"], s["end"]))
    mids = [(_ms(s["start"]) + _ms(s["end"])) // 2 for s in speech]
    sils = [(_ms(a), _ms(b)) for a, b in silences]
    tol = _ms(cfg.align_tolerance)
    cuts = list(cuts)
    while True:
        units: list[Unit] = []
        removed = False
        for i in range(len(cuts) - 1):
            p, q = cuts[i], cuts[i + 1]
            unit = _make_unit(p, q, speech, mids, sils, tol)
            if unit is not None:
                units.append(unit)
                continue
            removable = [c for c in (p, q) if c.kind == SILENCE]
            if removable:
                # Drop the shorter boundary silence (the later one on a tie).
                drop = min(removable, key=lambda c: (c.seconds, -c.lo))
                cuts.remove(drop)
                removed = True
                break
        if not removed:
            break
    for n, u in enumerate(units, 1):
        u.id = f"u{n:04d}"
        u.text = " ".join(s["text"] for s in u.segments)
        u.words = len(speech_tokens(u.segments))
    return units


# --- A8 candidates ----------------------------------------------------------------------------

def plan_trims(start: float, end: float, silences: list[tuple[float, float]], max_pause: float) -> list[list[float]]:
    """Silence spans to cut from ``[start, end]``: each silence (its part inside the clip)
    longer than ``max_pause`` keeps ``max_pause / 2`` at each end (A8)."""
    return [[_s(a), _s(b)] for a, b in _trims_ms(_ms(start), _ms(end), [(_ms(a), _ms(b)) for a, b in silences],
                                                 _ms(max_pause))]


def _trims_ms(start: int, end: int, sils: list[tuple[int, int]], max_pause: int,
              sil_ends: list[int] | None = None) -> list[tuple[int, int]]:
    ends = sil_ends if sil_ends is not None else [b for _, b in sils]
    half = max_pause // 2
    out = []
    for a, b in sils[bisect.bisect_right(ends, start):]:
        if a >= end:
            break
        a, b = max(a, start), min(b, end)
        if b - a > max_pause:
            out.append((a + half, b - (max_pause - half)))
    return out


def generate_candidates(units: list[Unit], silences: list[tuple[float, float]], changes: list[float],
                        shots: list[dict], cfg: AnalysisConfig) -> list[dict]:
    """Every run of consecutive units without a hard break whose trimmed duration is in
    ``[min_duration, max_duration]`` and whose edges pass the shot guard (A8, A9)."""
    sils = [(_ms(a), _ms(b)) for a, b in silences]
    sil_ends = [b for _, b in sils]
    chg = [_ms(c) for c in changes]
    pad, guard, mp = _ms(cfg.boundary_pad), _ms(cfg.shot_guard), _ms(cfg.max_pause)
    lo_d, hi_d = _ms(cfg.min_duration), _ms(cfg.max_duration)
    t_lo, t_hi = _ms(cfg.target_min), _ms(cfg.target_max)
    shot_ms = [(_ms(h["start"]), _ms(h["end"]), h["id"]) for h in shots]

    def guarded(t0: int, t1: int) -> bool:  # a shot change strictly inside (t0, t1)
        k = bisect.bisect_right(chg, t0)
        return k < len(chg) and chg[k] < t1

    found = []
    for i, ui in enumerate(units):
        ss = max(ui.start - pad, ui.min_start)
        for j in range(i, len(units)):
            uj = units[j]
            if j > i and not (units[j - 1].after is uj.before and uj.before.kind == SILENCE):
                break  # hard break / content edge / skipped stretch between units
            se = min(uj.end + pad, uj.max_end)
            trims = _trims_ms(ss, se, sils, mp, sil_ends)
            dur = se - ss - sum(b - a for a, b in trims)
            if dur > hi_d:
                break  # duration only grows with j
            if dur < lo_d:
                continue
            if guarded(ss, min(ss + guard, se)) or guarded(max(se - guard, ss), se):
                continue
            run = units[i:j + 1]
            found.append({
                "source_start": ss, "source_end": se, "duration": dur, "trims": trims,
                "units": run, "shot_ids": [h for a, b, h in shot_ms if a < se and b > ss],
                "shot_changes": [c for c in chg if ss < c < se],
                "in_target": t_lo <= dur <= t_hi,
            })
    found.sort(key=lambda c: (c["source_start"], c["source_end"]))
    out = []
    for n, c in enumerate(found, 1):
        run = c["units"]
        out.append({
            "id": f"c{n:05d}",
            "source_start": _s(c["source_start"]), "source_end": _s(c["source_end"]),
            "source_duration": _s(c["source_end"] - c["source_start"]),
            "duration": _s(c["duration"]), "in_target": c["in_target"],
            "unit_ids": [run[0].id, run[-1].id],
            "segment_ids": [run[0].segments[0]["id"], run[-1].segments[-1]["id"]],
            "words": sum(u.words for u in run),
            "trims": [[_s(a), _s(b)] for a, b in c["trims"]],
            "boundary": {"start": run[0].before.brk, "end": run[-1].after.brk},
            "shot_ids": c["shot_ids"], "shot_changes": [_s(x) for x in c["shot_changes"]],
        })
    return out


def content_trimmed_seconds(window: ContentWindow, silences: list[tuple[float, float]], cfg: AnalysisConfig) -> float:
    """Content window length after shortening every silence to ``max_pause``."""
    cs, ce = _ms(window.start), _ms(window.end)
    sils = [(_ms(a), _ms(b)) for a, b in silences]
    return _s(ce - cs - sum(b - a for a, b in _trims_ms(cs, ce, sils, _ms(cfg.max_pause))))


# --- validation (before any artifact is written) ------------------------------------------------

def validate(candidates: list[dict], units: list[Unit], window: ContentWindow, silences: list[tuple[float, float]],
             changes: list[float], shots: list[dict], cfg: AnalysisConfig) -> None:
    """Re-check every candidate against A5–A8; a violation is a code bug -> AnalysisError."""
    by_id = {u.id: (k, u) for k, u in enumerate(units)}
    shot_ids = {h["id"] for h in shots}
    sils = [(_ms(a), _ms(b)) for a, b in silences]
    cs, ce = _ms(window.start), _ms(window.end)
    pad, guard = _ms(cfg.boundary_pad), _ms(cfg.shot_guard)
    seen, prev_key = set(), None

    def fail(c: dict, msg: str):
        raise AnalysisError(f"candidate validation failed: {c.get('id')}: {msg}")

    for u in units:
        if not (cs <= u.min_start <= u.start < u.end <= u.max_end <= ce):
            raise AnalysisError(f"unit validation failed: {u.id}: edges outside the content window")
    for c in candidates:
        if c["id"] in seen:
            fail(c, "duplicate id")
        seen.add(c["id"])
        ss, se = _ms(c["source_start"]), _ms(c["source_end"])
        key = (ss, se)
        if prev_key is not None and key <= prev_key:
            fail(c, "ids not in (source_start, source_end) order")
        prev_key = key
        if not (cs <= ss < se <= ce):
            fail(c, "outside the content window")
        if c["unit_ids"][0] not in by_id or c["unit_ids"][1] not in by_id:
            fail(c, "unknown unit id")
        i, ui = by_id[c["unit_ids"][0]]
        j, uj = by_id[c["unit_ids"][1]]
        if j < i:
            fail(c, "unit range reversed")
        for k in range(i, j):
            if units[k].after is not units[k + 1].before or units[k].after.kind != SILENCE:
                fail(c, f"contains a {units[k].after.kind} between {units[k].id} and {units[k + 1].id}")
        if ss != max(ui.start - pad, ui.min_start) or se != min(uj.end + pad, uj.max_end):
            fail(c, "edges are not at A6 cut points")
        for brk in (ui.before, uj.after):
            if brk.kind == SILENCE and (brk.seconds is None or _ms(brk.seconds) < _ms(cfg.min_boundary_silence)):
                fail(c, "edge at a silence shorter than min_boundary_silence")
        if c["segment_ids"] != [ui.segments[0]["id"], uj.segments[-1]["id"]]:
            fail(c, "segment_ids do not match units")
        trims = [(_ms(a), _ms(b)) for a, b in c["trims"]]
        last = ss
        for a, b in trims:
            if not (last <= a < b <= se):
                fail(c, "trims overlap or leave the clip")
            last = b
        if trims != _trims_ms(ss, se, sils, _ms(cfg.max_pause)):
            fail(c, "trims do not match A8")
        dur = se - ss - sum(b - a for a, b in trims)
        if _ms(c["duration"]) != dur or _ms(c["source_duration"]) != se - ss:
            fail(c, "duration != source_duration - sum(trims)")
        if not _ms(cfg.min_duration) <= dur <= _ms(cfg.max_duration):
            fail(c, "duration outside [min_duration, max_duration]")
        if c["in_target"] != (_ms(cfg.target_min) <= dur <= _ms(cfg.target_max)):
            fail(c, "in_target wrong")
        for x in changes:
            t = _ms(x)
            if ss < t < min(ss + guard, se) or max(se - guard, ss) < t < se:
                fail(c, f"shot change {x} within shot_guard of an edge")
        if not set(c["shot_ids"]) <= shot_ids or not c["shot_ids"]:
            fail(c, "invalid shot_ids")
