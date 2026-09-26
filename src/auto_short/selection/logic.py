"""Pure selection logic: windows (B2), response parsing, mapping to candidates (B4),
final deterministic choice (B6) and validation (B8).

Canonical contract: docs/decisions/CP5-selection-contract.md.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from ..analysis.candidates import plan_trims

SILENCE = "silence"

# Proposal statuses (B7).
VALID, REJECTED, INELIGIBLE, SELECTED, OVERLAPPED, OVER_LIMIT = (
    "valid", "rejected", "ineligible", "selected", "overlapped", "over_limit")

PROPOSAL_KEYS = ("first_unit", "last_unit", "topic", "reason", "start_complete", "end_complete", "score")
CLIP_COPY_KEYS = ("source_start", "source_end", "source_duration", "duration", "in_target", "unit_ids",
                  "segment_ids")


class SelectionError(Exception):
    """The selection stage cannot complete (bad input, AI failure, validation error)."""


class ResponseError(ValueError):
    """The AI response is not JSON or does not match the response schema (B5: retry)."""


def _ms(x: float) -> int:
    return round(x * 1000)


# --- unit durations (B3) --------------------------------------------------------------------

def unit_durations(units: list[dict], silences: list[tuple[float, float]], max_pause: float) -> dict[str, float]:
    """Unit length after silence trimming, computed exactly like CP4 A8 trims on ``[start, end]``."""
    out = {}
    for u in units:
        trims = plan_trims(u["start"], u["end"], silences, max_pause)
        out[u["id"]] = (_ms(u["end"]) - _ms(u["start"]) - sum(_ms(b) - _ms(a) for a, b in trims)) / 1000
    return out


# --- B2 windows -----------------------------------------------------------------------------

@dataclass
class Window:
    id: str
    parent: str  # top-level window id (== id when not split)
    units: list[dict]
    candidates: list[dict] = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(u["words"] for u in self.units)

    @property
    def unit_ids(self) -> list[str]:
        return [self.units[0]["id"], self.units[-1]["id"]]


def _split(lo: int, hi: int, spans: list[tuple[int, int]], words: list[int], max_words: int,
           wid: str) -> list[tuple[int, int]]:
    """Split unit indexes ``[lo, hi)`` into overlapping ranges of <= ``max_words`` words such that
    every candidate span ``(i, j)`` (inclusive unit indexes) lies inside at least one range."""
    ranges, s = [], lo
    while True:
        e, total = s, words[s]
        while e + 1 < hi and total + words[e + 1] <= max_words:
            e += 1
            total += words[e]
        ranges.append((s, e))
        if e == hi - 1:
            return ranges
        pending = [i for i, j in spans if i >= s and j > e]
        nxt = min(pending) if pending else e + 1
        if nxt <= s:
            raise SelectionError(f"window {wid}: a candidate starting at unit index {s} has more than "
                                 f"max_window_words={max_words} words")
        s = nxt


def build_windows(units: list[dict], candidates: list[dict], max_window_words: int) -> list[Window]:
    """Runs of units between two non-``silence`` boundaries (hard break / content edge).

    Windows longer than ``max_window_words`` are split into overlapping sub-windows
    ``<id>.<k>``; windows without candidates are kept (no AI call is made for them).
    """
    index = {u["id"]: n for n, u in enumerate(units)}
    words = [u["words"] for u in units]
    bounds = [n for n, u in enumerate(units) if n == 0 or u["break_before"]["kind"] != SILENCE] + [len(units)]
    spans = sorted((index[c["unit_ids"][0]], index[c["unit_ids"][1]], c["id"]) for c in candidates)
    windows = []
    for k, (lo, hi) in enumerate(zip(bounds, bounds[1:]), 1):
        wid = f"w{k:02d}"
        inside = [(i, j) for i, j, _ in spans if lo <= i < hi]
        for i, j in inside:
            if j >= hi:
                raise SelectionError(f"candidate spans beyond window {wid} (unit index {i}..{j})")
        ranges = [(lo, hi - 1)] if sum(words[lo:hi]) <= max_window_words else \
            _split(lo, hi, inside, words, max_window_words, wid)
        for n, (a, b) in enumerate(ranges, 1):
            win = Window(wid if len(ranges) == 1 else f"{wid}.{n}", wid, units[a:b + 1])
            win.candidates = [c for c in candidates if a <= index[c["unit_ids"][0]] and index[c["unit_ids"][1]] <= b]
            windows.append(win)
    return windows


# --- response parsing (B3/B5) ---------------------------------------------------------------

_TYPES = {"first_unit": str, "last_unit": str, "topic": str, "reason": str,
          "start_complete": bool, "end_complete": bool, "score": int}


def parse_response(content: str) -> list[dict]:
    """Parse ``{"clips": [...]}``; any deviation from the response schema raises ResponseError."""
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise ResponseError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("clips"), list):
        raise ResponseError('response must be an object with a "clips" array')
    out = []
    for n, item in enumerate(data["clips"]):
        if not isinstance(item, dict):
            raise ResponseError(f"clips[{n}] is not an object")
        for key, typ in _TYPES.items():
            value = item.get(key)
            if key not in item or not isinstance(value, typ) or (typ is int and isinstance(value, bool)):
                raise ResponseError(f"clips[{n}].{key} missing or not {typ.__name__}")
        if not 1 <= item["score"] <= 10:
            raise ResponseError(f"clips[{n}].score {item['score']} not in 1..10")
        out.append({k: item[k] for k in PROPOSAL_KEYS})
    return out


# --- B4 map to candidates -------------------------------------------------------------------

def estimate_seconds(units: list[dict], durations: dict[str, float], max_pause: float, pad: float) -> float:
    """Rough Short length of a unit run (for reject reasons only; candidates are the truth)."""
    gaps = sum(min(u["break_after"]["seconds"] or 0.0, max_pause) for u in units[:-1])
    return round(sum(durations[u["id"]] for u in units) + gaps + 2 * pad, 1)


def map_proposals(proposals: list[dict], window: Window, by_units: dict[tuple[str, str], dict],
                  durations: dict[str, float], params: dict) -> list[dict]:
    """Attach ``status``/``candidate_id``/``reject_reason`` to each proposal of ``window``.

    A proposal is valid iff exactly one candidate has ``unit_ids == [first_unit, last_unit]``
    and it lies in the window; otherwise it is rejected as is (never repaired or widened)."""
    pos = {u["id"]: n for n, u in enumerate(window.units)}
    in_window = {c["id"] for c in window.candidates}
    records = []
    for p in proposals:
        rec = dict(p, window=window.id, status=REJECTED, candidate_id=None, reject_reason=None)
        a, b = p["first_unit"], p["last_unit"]
        cand = by_units.get((a, b))
        if a not in pos or b not in pos:
            missing = ", ".join(x for x in (a, b) if x not in pos)
            rec["reject_reason"] = f"unit not in window {window.id}: {missing}"
        elif pos[a] > pos[b]:
            rec["reject_reason"] = "last_unit before first_unit"
        elif cand is None or cand["id"] not in in_window:
            est = estimate_seconds(window.units[pos[a]:pos[b] + 1], durations, params["max_pause"],
                                   params["boundary_pad"])
            rec["reject_reason"] = (f"no candidate with unit_ids [{a}, {b}] (~{est} s; must be "
                                    f"{params['min_duration']:g}-{params['max_duration']:g} s after trims "
                                    "and pass the shot guard)")
        else:
            rec.update(status=VALID, candidate_id=cand["id"])
        records.append(rec)
    return records


def dedupe(records: list[dict]) -> None:
    """Keep one valid proposal per candidate (highest score, then first proposed)."""
    best: dict[str, dict] = {}
    for rec in records:
        if rec["status"] != VALID:
            continue
        cur = best.get(rec["candidate_id"])
        if cur is None or rec["score"] > cur["score"]:
            if cur is not None:
                cur.update(status=REJECTED, reject_reason=f"duplicate of proposal in {rec['window']}")
            best[rec["candidate_id"]] = rec
        else:
            rec.update(status=REJECTED, reject_reason=f"duplicate of proposal in {cur['window']}")


# --- B11 opening-connector filter ----------------------------------------------------------

def normalize_text(text: str) -> str:
    """NFC, lowercase, collapse whitespace."""
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def start_connector(text: str, blocklist: tuple[str, ...] | list[str]) -> str | None:
    """The (normalized) blocklist phrase that ``text`` starts with as whole words, else None.
    Longest phrase wins so the reason names the most specific match."""
    t = normalize_text(text)
    for phrase in sorted((normalize_text(p) for p in blocklist), key=len, reverse=True):
        if phrase and re.match(re.escape(phrase) + r"(?!\w)", t):
            return phrase
    return None


def filter_start(records: list[dict], cand_by_id: dict[str, dict], units_by_id: dict[str, dict],
                 blocklist: tuple[str, ...] | list[str]) -> int:
    """Mark valid proposals whose first unit opens with a blocked connector ``ineligible``
    (B11); runs after mapping/dedupe and before the final choice. Returns how many."""
    n = 0
    for rec in records:
        if rec["status"] != VALID or not blocklist:
            continue
        first = cand_by_id[rec["candidate_id"]]["unit_ids"][0]
        phrase = start_connector(units_by_id[first]["text"], blocklist)
        if phrase is not None:
            rec.update(status=INELIGIBLE, reject_reason=f"start connector: {phrase}")
            n += 1
    return n


# --- B6 final choice ------------------------------------------------------------------------

def _overlaps(a: dict, b: dict) -> bool:
    return max(_ms(a["source_start"]), _ms(b["source_start"])) < min(_ms(a["source_end"]), _ms(b["source_end"]))


def select_clips(records: list[dict], cand_by_id: dict[str, dict], *, max_clips: int, min_score: int) -> list[dict]:
    """Greedy non-overlapping choice; updates each valid record's status. Returns clips (B7)."""
    eligible = []
    for rec in records:
        if rec["status"] != VALID:
            continue
        if rec["start_complete"] and rec["end_complete"] and rec["score"] >= min_score:
            eligible.append(rec)
        else:
            why = [w for w, bad in (("start not complete", not rec["start_complete"]),
                                    ("end not complete", not rec["end_complete"]),
                                    (f"score < {min_score}", rec["score"] < min_score)) if bad]
            rec.update(status=INELIGIBLE, reject_reason=", ".join(why))

    def key(rec):
        c = cand_by_id[rec["candidate_id"]]
        return (-rec["score"], not c["in_target"], _ms(c["source_start"]), _ms(c["source_end"]), c["id"])

    chosen: list[tuple[dict, dict]] = []
    for rec in sorted(eligible, key=key):
        c = cand_by_id[rec["candidate_id"]]
        if len(chosen) >= max_clips:
            rec.update(status=OVER_LIMIT, reject_reason=f"max_clips={max_clips} reached")
            continue
        clash = next((o for o, _ in chosen if _overlaps(o, c)), None)
        if clash is not None:
            rec.update(status=OVERLAPPED, reject_reason=f"overlaps selected {clash['id']}")
            continue
        rec["status"] = SELECTED
        chosen.append((c, rec))

    chosen.sort(key=lambda x: (_ms(x[0]["source_start"]), x[0]["id"]))
    clips = []
    for n, (c, rec) in enumerate(chosen, 1):
        clip = {"id": f"k{n:02d}", "candidate_id": c["id"]}
        clip.update({k: c[k] for k in CLIP_COPY_KEYS})
        clip.update(score=rec["score"], start_complete=rec["start_complete"], end_complete=rec["end_complete"],
                    topic=rec["topic"], reason=rec["reason"], window=rec["window"])
        rec["clip_id"] = clip["id"]
        clips.append(clip)
    return clips


# --- B8 validation --------------------------------------------------------------------------

def validate_clips(clips: list[dict], cand_doc: dict, *, max_clips: int, min_score: int) -> None:
    """Raise SelectionError when ``clips`` violates B8 (a code bug, never an AI mistake)."""
    cand_by_id = {c["id"]: c for c in cand_doc["candidates"]}
    unit_ids = {u["id"] for u in cand_doc["units"]}
    params = cand_doc["params"]

    def fail(clip: dict, msg: str):
        raise SelectionError(f"clip {clip.get('id')} ({clip.get('candidate_id')}): {msg}")

    if len(clips) > max_clips:
        raise SelectionError(f"{len(clips)} clips > max_clips={max_clips}")
    prev = None
    for n, clip in enumerate(clips, 1):
        if clip["id"] != f"k{n:02d}":
            fail(clip, f"id must be k{n:02d}")
        cand = cand_by_id.get(clip["candidate_id"])
        if cand is None:
            fail(clip, "candidate does not exist")
        for k in CLIP_COPY_KEYS:
            if clip[k] != cand[k]:
                fail(clip, f"{k} does not match the candidate")
        if not params["min_duration"] <= clip["duration"] <= params["max_duration"]:
            fail(clip, f"duration {clip['duration']} outside {params['min_duration']}-{params['max_duration']} s")
        if not set(clip["unit_ids"]) <= unit_ids:
            fail(clip, "unknown unit id")
        if not (clip["start_complete"] and clip["end_complete"] and min_score <= clip["score"] <= 10):
            fail(clip, "not eligible (complete flags / score)")
        if prev is not None:
            if _ms(clip["source_start"]) < _ms(prev["source_start"]):
                fail(clip, "clips not ordered by source_start")
            if _overlaps(prev, clip):
                fail(clip, f"overlaps {prev['id']}")
        prev = clip  # sorted by source_start: checking neighbours covers every pair
