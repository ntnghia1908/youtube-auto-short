"""CP9 per-episode functions shared by the web: transcript + Shorts ranges, remaining AI proposals, cut preview,
set / reset the cut points of a Short, add a Short (from a proposal or from caption lines).

Each call reads the episode from the workspace (no state kept), validates, and writes ``work/<id>/review.json``
atomically only when the change is valid. They never call the AI and never render: the web runs the title of an
added Short (:mod:`auto_short.titling.added`) and :func:`auto_short.render.run_render` afterwards. An archived
episode (source video cleaned up, CP8.6) refuses every write with :class:`ArchivedError`.

Canonical contract: docs/decisions/CP8.2-title-override-contract.md T1, T8 (CP9).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .. import hashing
from ..config import Config
from ..workspace import atomic_write_json
from . import cuts as C
from .archive import check_not_archived
from .logic import (ADDED_KEY, CUTS_KEY, MANUAL_CANDIDATE, ORIGIN_ADDED, ORIGIN_AI, PROPOSAL, REJECTED_KEY,
                    REVIEW_NAME, TRANSCRIPT, ReviewError, next_added_id, resolve_cuts, with_added, with_cut,
                    without_cut)
from .titles import _Episode, _load

PROPOSAL_STATUSES = ("overlapped", "over_limit", "ineligible")  # C7: AI proposals not selected, with a candidate
RENDER_MANIFEST = "render_manifest.json"
PUBLISH_NAME = "publish.json"


def _read(path: Path, what: str) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError(f"không đọc được {path.name} ({exc}); chạy lại bước {what}") from exc
    if not isinstance(doc, dict):
        raise ReviewError(f"{path.name} hỏng; chạy lại bước {what}")
    return doc


def _sha(doc: dict) -> str:
    return hashlib.sha256(hashing.canonical_json(doc).encode("utf-8")).hexdigest()


@dataclass
class _Ctx:
    """One episode with the artifacts the range rules need (read-only snapshot)."""

    ep: _Episode
    cand: dict  # candidates.json
    rng: C.Episode
    cuts: dict[str, tuple[float, float]]  # applied manual cuts (C1 key rule)
    cut_warnings: list[str]

    @property
    def episode_id(self) -> str:
        return self.ep.ws.episode_id

    def keys(self) -> list[tuple[str, str]]:
        return [(c["id"], c["candidate_id"]) for c in self.ep.clips] + \
            [(a["clip_id"], a["candidate_id"]) for a in self.ep.added]

    def original(self, clip_id: str) -> tuple[float, float]:
        for c in self.ep.clips:
            if c["id"] == clip_id:
                return c["source_start"], c["source_end"]
        a = self.ep.added_entry(clip_id)
        if a is not None:
            return a["start"], a["end"]
        raise ReviewError(f"không có Short {clip_id!r} trong tập {self.episode_id}")

    def current(self, clip_id: str) -> tuple[float, float]:
        """Range the next render uses: the manual cut, else the original."""
        return self.cuts.get(clip_id) or self.original(clip_id)

    def rejected(self) -> set[str]:
        keys = dict(self.keys())
        return {e["clip_id"] for e in self.ep.review.get(REJECTED_KEY, [])
                if keys.get(e["clip_id"]) == e["candidate_id"]}

    def ranges(self, exclude: str | None = None) -> list[tuple[str, float, float]]:
        """Current range of every Short that will be rendered (deleted ones left out), for overlap warnings."""
        gone = self.rejected()
        return [(cid, *self.current(cid)) for cid, _ in self.keys() if cid != exclude and cid not in gone]


def _context(episode_id: str, config: Config) -> _Ctx:
    ep = _load(episode_id, config)  # titling done, titles.json matches clips.json, review.json valid
    d = ep.ws.dir
    cand = _read(d / "candidates.json", "analysis")
    transcript = _read(d / "transcript.json", "transcript")
    silences = _read(d / "silences.json", "analysis")
    clips_doc = _read(d / "clips.json", "selection")
    if clips_doc.get("candidates_sha256") != _sha(cand):
        raise ReviewError("clips.json không khớp candidates.json; chạy lại bước chọn clip (selection)")
    if cand.get("transcript_sha256") != transcript.get("transcript_sha256") \
            or cand.get("silences_sha256") != _sha(silences):
        raise ReviewError("candidates.json không khớp transcript.json / silences.json; chạy lại bước phân tích")
    try:
        shots = json.loads((d / "shots.json").read_text(encoding="utf-8")).get("changes") or []
    except (OSError, ValueError, AttributeError):
        shots = []  # warnings only
    content = cand.get("content") or {}
    rng = C.Episode(segments=[s for s in transcript.get("segments", []) if isinstance(s, dict)],
                    silences=[(a["start"], a["end"]) for a in silences.get("silences", [])],
                    params=cand.get("params") or {}, content=(content.get("start"), content.get("end")),
                    shot_changes=shots)
    keys = [(c["id"], c["candidate_id"]) for c in ep.clips] + [(a["clip_id"], a["candidate_id"]) for a in ep.added]
    applied, warnings = resolve_cuts(keys, ep.review)
    return _Ctx(ep, cand, rng, applied, warnings)


def _text(ctx: _Ctx, segment_id: str | None) -> str | None:
    if segment_id is None:
        return None
    return ctx.rng.segments[ctx.rng.index(segment_id)]["text"]


def _preview(ctx: _Ctx, r: C.Range, clip_id: str | None) -> dict:
    """What the UI shows for a range: times, durations, first / last line, C4 error, warnings, overlaps."""
    over = C.overlaps(r.start, r.end, ctx.ranges(exclude=clip_id))
    warnings = list(r.warnings)
    if over:
        warnings.insert(0, "chồng lấn " + ", ".join(over))
    out = {"clip_id": clip_id, "start": r.start, "end": r.end, "duration": r.duration,
           "source_duration": r.source_duration, "start_segment": r.start_segment, "end_segment": r.end_segment,
           "start_text": _text(ctx, r.start_segment), "end_text": _text(ctx, r.end_segment),
           "error": r.error, "warnings": warnings, "overlaps": over}
    if clip_id is not None:
        orig, cur = ctx.original(clip_id), ctx.current(clip_id)
        out["original"] = C.ms(r.start) == C.ms(orig[0]) and C.ms(r.end) == C.ms(orig[1])
        out["changed"] = not (C.ms(r.start) == C.ms(cur[0]) and C.ms(r.end) == C.ms(cur[1]))
    return out


def _clip_key(ctx: _Ctx, clip_id: str) -> str:
    keys = dict(ctx.keys())
    if clip_id not in keys:
        raise ReviewError(f"không có Short {clip_id!r} trong tập {ctx.episode_id}")
    return keys[clip_id]


# --- read ----------------------------------------------------------------------------------------------------

def transcript_view(episode_id: str, config: Config) -> dict:
    """``GET /api/episodes/{id}/transcript``: caption lines, content window, duration limits and the range of
    every Short (current range, first / last line, cut or not, deleted or not)."""
    ctx = _context(episode_id, config)
    gone = ctx.rejected()
    shorts = []
    for cid, cand_id in ctx.keys():
        start, end = ctx.current(cid)
        first, last = C.range_segments(ctx.rng, start, end)
        o0, o1 = ctx.original(cid)
        shorts.append({"clip_id": cid, "candidate_id": cand_id,
                       "origin": ORIGIN_ADDED if ctx.ep.added_entry(cid) is not None else ORIGIN_AI,
                       "start": start, "end": end, "start_segment": first, "end_segment": last,
                       "original_start": o0, "original_end": o1, "cut": cid in ctx.cuts, "rejected": cid in gone})
    p = ctx.rng.params
    return {"episode_id": ctx.episode_id,
            "content": {"start": ctx.rng.content[0], "end": ctx.rng.content[1]},
            "min_duration": p.get("min_duration"), "max_duration": p.get("max_duration"),
            "segments": [{"id": s["id"], "start": s["start"], "end": s["end"], "kind": s["kind"], "text": s["text"]}
                         for s in ctx.rng.segments],
            "shorts": shorts, "ignored": ctx.cut_warnings}


def _proposal_range(ctx: _Ctx, p: dict, cand: dict) -> tuple[int, int]:
    """C1 proposal source: the candidate range after the CP5 B11 head cut recorded for the proposal."""
    head = p.get("head_cut")
    start = head["source_start"] if isinstance(head, dict) and head.get("source_start") is not None \
        else cand["source_start"]
    return C.ms(start), C.ms(cand["source_end"])


def list_proposals(episode_id: str, config: Config) -> dict:
    """``GET /api/episodes/{id}/proposals``: AI proposals of ``selection_log.json`` that were not selected
    (``overlapped`` / ``over_limit`` / ``ineligible``) and map to a candidate, with topic, score, reason, the range
    they would get (C1), duration, C4 error, overlaps and the Shorts already added from them."""
    ctx = _context(episode_id, config)
    log_doc = _read(ctx.ep.ws.dir / "selection_log.json", "selection")
    if log_doc.get("candidates_sha256") != _sha(ctx.cand):
        raise ReviewError("selection_log.json không khớp candidates.json; chạy lại bước chọn clip (selection)")
    cands = {c["id"]: c for c in ctx.cand.get("candidates", [])}
    added_from = {}
    for a in ctx.ep.added:
        added_from.setdefault(a["candidate_id"], []).append(a["clip_id"])
    out, seen = [], set()
    for w in log_doc.get("windows", []):
        for p in w.get("proposals", []):
            cid = p.get("candidate_id")
            if p.get("status") not in PROPOSAL_STATUSES or cid not in cands or cid in seen:
                continue
            seen.add(cid)
            r = C.evaluate(ctx.rng, *_proposal_range(ctx, p, cands[cid]))
            prev = _preview(ctx, r, None)
            out.append({"candidate_id": cid, "topic": p.get("topic"), "reason": p.get("reason"),
                        "score": p.get("score"), "status": p.get("status"), "reject_reason": p.get("reject_reason"),
                        **{k: prev[k] for k in ("start", "end", "duration", "start_segment", "end_segment",
                                                "start_text", "end_text", "error", "warnings", "overlaps")},
                        "added_as": added_from.get(cid, [])})
    out.sort(key=lambda x: (x["start"], x["candidate_id"]))
    return {"episode_id": ctx.episode_id, "proposals": out}


def preview_cut(episode_id: str, config: Config, *, clip_id: str | None, start_segment: str, end_segment: str,
                start_nudge: object = 0, end_nudge: object = 0) -> dict:
    """``POST /api/episodes/{id}/cut/preview`` (nothing written): the range of lines ``start_segment`` ..
    ``end_segment`` plus nudges (C3) — for ``clip_id`` relative to its current range, else a new Short from the
    transcript. Malformed input raises ReviewError; a C4 violation is returned in ``error``."""
    ctx = _context(episode_id, config)
    current = None
    if clip_id is not None:
        _clip_key(ctx, clip_id)
        current = ctx.current(clip_id)
    s, e = C.resolve_range(ctx.rng, start_segment, end_segment, start_nudge, end_nudge, current)
    return _preview(ctx, C.evaluate(ctx.rng, s, e), clip_id)


# --- write -----------------------------------------------------------------------------------------------------

def _write(ctx: _Ctx, review: dict) -> None:
    atomic_write_json(ctx.ep.ws.dir / REVIEW_NAME, review)
    ctx.ep.review = review


def set_cut(episode_id: str, config: Config, clip_id: str, *, start_segment: str, end_segment: str,
            start_nudge: object = 0, end_nudge: object = 0) -> dict:
    """Store the manual cut of ``clip_id`` (C1 ``cuts``). Invalid (C4) -> ReviewError, review.json unchanged. A
    range equal to the Short's original drops the cut (file back to what it was without it)."""
    ctx = _context(episode_id, config)
    check_not_archived(ctx.ep.ws.dir, ctx.episode_id)
    cand_id = _clip_key(ctx, clip_id)
    s, e = C.resolve_range(ctx.rng, start_segment, end_segment, start_nudge, end_nudge, ctx.current(clip_id))
    r = C.evaluate(ctx.rng, s, e)
    if r.error:
        raise ReviewError(f"đoạn không hợp lệ: {r.error}")
    preview = _preview(ctx, r, clip_id)
    if preview["original"]:
        review, _ = without_cut(ctx.ep.review, ctx.ep.order, clip_id)
    else:
        review = with_cut(ctx.ep.review, ctx.ep.order, clip_id=clip_id, candidate_id=cand_id, start=r.start,
                          end=r.end)
    if review != ctx.ep.review:
        _write(ctx, review)
    return preview


def reset_cut(episode_id: str, config: Config, clip_id: str) -> dict:
    """"Về như AI chọn": drop the manual cut of ``clip_id`` (an added Short goes back to the range it was added
    with). Returns the preview of the original range with ``changed`` = whether review.json changed."""
    ctx = _context(episode_id, config)
    check_not_archived(ctx.ep.ws.dir, ctx.episode_id)
    _clip_key(ctx, clip_id)
    review, removed = without_cut(ctx.ep.review, ctx.ep.order, clip_id)
    if removed:
        _write(ctx, review)
    ctx.cuts.pop(clip_id, None)
    o0, o1 = ctx.original(clip_id)
    return {**_preview(ctx, C.evaluate(ctx.rng, C.ms(o0), C.ms(o1)), clip_id), "changed": removed}


def _used_ids(ctx: _Ctx, config: Config) -> set[str]:
    """Every clip id the episode ever had in review.json, publish.json or the last render (C1: an added id is
    never reused, so no old tick / title / file can attach to a new Short)."""
    used = set(ctx.ep.order)
    for key in ("titles", REJECTED_KEY, CUTS_KEY, ADDED_KEY):
        used |= {e["clip_id"] for e in ctx.ep.review.get(key, [])}
    for path in (ctx.ep.ws.dir / PUBLISH_NAME, Path(config.render.output_dir) / ctx.episode_id / RENDER_MANIFEST):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            used |= {e.get("clip_id") for e in doc.get("published", []) + doc.get("shorts", [])
                     if isinstance(e, dict) and isinstance(e.get("clip_id"), str)}
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    return used


@dataclass(frozen=True)
class Added:
    clip_id: str
    preview: dict


def add_short(episode_id: str, config: Config, *, candidate_id: str | None = None,
              start_segment: str | None = None, end_segment: str | None = None, start_nudge: object = 0,
              end_nudge: object = 0) -> Added:
    """C1: add a Short from a remaining AI proposal (``candidate_id``) or from caption lines (``start_segment`` ..
    ``end_segment`` + nudges). It gets the next ``m<NN>`` id and no title yet (the AI titles it next, C6); invalid
    range (C4) -> ReviewError, nothing written."""
    ctx = _context(episode_id, config)
    check_not_archived(ctx.ep.ws.dir, ctx.episode_id)
    if (candidate_id is None) == (start_segment is None or end_segment is None):
        raise ReviewError("cần candidate_id (đề xuất AI) hoặc start_segment + end_segment (phụ đề)")
    if candidate_id is not None:
        found = next((p for p in list_proposals(episode_id, config)["proposals"]
                      if p["candidate_id"] == candidate_id), None)
        if found is None:
            raise ReviewError(f"không có đề xuất AI {candidate_id!r} còn lại trong tập {ctx.episode_id}")
        r = C.evaluate(ctx.rng, C.ms(found["start"]), C.ms(found["end"]))
        source, cand = PROPOSAL, candidate_id
    else:
        s, e = C.resolve_range(ctx.rng, start_segment, end_segment, start_nudge, end_nudge)
        r = C.evaluate(ctx.rng, s, e)
        source, cand = TRANSCRIPT, MANUAL_CANDIDATE
    if r.error:
        raise ReviewError(f"đoạn không hợp lệ: {r.error}")
    clip_id = next_added_id(_used_ids(ctx, config))
    entry = {"clip_id": clip_id, "candidate_id": cand, "start": r.start, "end": r.end, "source": source,
             "title": None, "ai_title": None, "alternatives": []}
    preview = _preview(ctx, r, None)
    _write(ctx, with_added(ctx.ep.review, ctx.ep.order + [clip_id], entry))
    return Added(clip_id, {**preview, "clip_id": clip_id})


def added_titling_input(episode_id: str, config: Config, clip_id: str) -> dict:
    """What the AI titles an added Short with (C6, CP6 G3 on a manual range): the caption lines of the range it
    was added with, its duration after trims and the video title."""
    ctx = _context(episode_id, config)
    a = ctx.ep.added_entry(clip_id)
    if a is None:
        raise ReviewError(f"không có Short thêm {clip_id!r} trong tập {ctx.episode_id}")
    r = C.evaluate(ctx.rng, C.ms(a["start"]), C.ms(a["end"]))
    s0, s1 = C.ms(a["start"]), C.ms(a["end"])
    text = " ".join(s["text"] for s in ctx.rng.segments
                    if s["kind"] == "speech" and s0 <= (C.ms(s["start"]) + C.ms(s["end"])) // 2 <= s1)
    try:
        meta = json.loads((ctx.ep.ws.dir / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    return {"clip_id": clip_id, "candidate_id": a["candidate_id"], "source": a["source"], "text": text,
            "duration": r.duration, "video_title": (meta or {}).get("title") or ""}


def set_added_ai_title(episode_id: str, config: Config, clip_id: str, *, title: str | None,
                       alternatives: list[dict]) -> bool:
    """Store the AI result of an added Short (C6): ``ai_title`` + ``alternatives``, and ``title`` = the AI title
    when no title was set meanwhile. Returns False when the Short is gone or was already titled by the AI."""
    ep = _load(episode_id, config)
    a = ep.added_entry(clip_id)
    if a is None or a["ai_title"] is not None:
        return False
    new = {**a, "ai_title": title, "alternatives": [{"title": x["title"], "evidence": x["evidence"]}
                                                     for x in alternatives],
           "title": a["title"] if a["title"] is not None else title}
    if new == a:
        return False
    atomic_write_json(ep.ws.dir / REVIEW_NAME, with_added(ep.review, ep.order, new))
    return True
