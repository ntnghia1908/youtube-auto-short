"""P2 source text: the literal words of a Short's community post, before the AI adds punctuation (P3).

Reads the episode's artifacts directly (``clips.json``, ``candidates.json``, ``transcript.json``, ``silences.json``,
``review.json``) — the same cross-checks :mod:`auto_short.review.shorts` does, kept separate here so this package
does not depend on that module's private helpers:

- A Short from ``clips.json`` (AI-selected) with **no** manual cut (``review.json`` ``cuts``): the full text of its
  candidate's ``unit_ids`` range, **with** the ``head_cut`` drop applied exactly like
  :func:`auto_short.titling.logic.clip_text` (CP6 G3) — a connector word ``head_cut`` removes from the render
  (CP5 B11) is dropped from the post text too, so the text matches what is actually spoken in the Short. Reuses
  ``clip_text`` itself for the drop-and-validate step (identical mismatch error, ORCHESTRATOR review round 1 B1);
  the caption-line-level breakdown below is only for the chunk boundaries of P3.
- A Short with a manual cut, or added by hand (``review.json`` ``added``): the caption lines of its current range
  (:func:`auto_short.review.cuts.lines_in`, the same rule :func:`auto_short.review.shorts.added_titling_input` uses
  for the AI title of an added Short).

Canonical contract: docs/decisions/CP8.15-community-post-contract.md P2.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .. import hashing
from ..config import Config
from ..review import cuts as C
from ..review.logic import ADDED_KEY, read_review, resolve_cuts
from ..titling.logic import TitlingError
from ..titling.logic import clip_text as titling_clip_text
from ..workspace import Workspace, WorkspaceError, validate_episode_id

CANDIDATES_NAME = "candidates.json"
CLIPS_NAME = "clips.json"
TRANSCRIPT_NAME = "transcript.json"
SILENCES_NAME = "silences.json"


class PostSourceError(Exception):
    """The episode's artifacts are missing / inconsistent, or a Short has no text (P2)."""


def _read(path: Path, what: str) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PostSourceError(f"không đọc được {path.name} ({exc}); chạy lại bước {what}") from exc
    if not isinstance(doc, dict):
        raise PostSourceError(f"{path.name} hỏng; chạy lại bước {what}")
    return doc


def _sha(doc: dict) -> str:
    return hashlib.sha256(hashing.canonical_json(doc).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceEpisode:
    """Everything :func:`source_lines` needs for one episode (read-only snapshot)."""

    ws: Workspace
    clips: list[dict]  # clips.json clips
    units: list[dict]  # candidates.json units
    index: dict[str, int]  # unit id -> position in ``units``
    rng: C.Episode  # transcript segments + silences + params + content window (CP9 C3-C5)
    cuts: dict[str, tuple[float, float]]  # applied manual cuts (CP9 C1 key rule)
    added: list[dict]  # review.json "added" (CP9 C1)

    def added_entry(self, clip_id: str) -> dict | None:
        return next((e for e in self.added if e["clip_id"] == clip_id), None)

    def clip(self, clip_id: str) -> dict | None:
        return next((c for c in self.clips if c["id"] == clip_id), None)


def load(episode_id: str, config: Config) -> SourceEpisode:
    """Read + cross-check one episode's artifacts (P2); raises :class:`PostSourceError` when a stage needs
    re-running. Works on an archived episode (CP8.6): no video file is touched."""
    try:
        ws = Workspace(Path(config.workspace.dir), validate_episode_id(episode_id))
    except WorkspaceError as exc:
        raise PostSourceError(str(exc)) from exc
    d = ws.dir
    clips_doc = _read(d / CLIPS_NAME, "selection")
    cand = _read(d / CANDIDATES_NAME, "analysis")
    if clips_doc.get("candidates_sha256") != _sha(cand):
        raise PostSourceError("clips.json không khớp candidates.json; chạy lại bước chọn clip (selection)")
    transcript = _read(d / TRANSCRIPT_NAME, "transcript")
    silences = _read(d / SILENCES_NAME, "analysis")
    if cand.get("transcript_sha256") != transcript.get("transcript_sha256") \
            or cand.get("silences_sha256") != _sha(silences):
        raise PostSourceError("candidates.json không khớp transcript.json / silences.json; chạy lại bước phân tích")
    review = read_review(d / "review.json", ws.episode_id)
    content = cand.get("content") or {}
    rng = C.Episode(segments=[s for s in transcript.get("segments", []) if isinstance(s, dict)],
                    silences=[(a["start"], a["end"]) for a in silences.get("silences", [])],
                    params=cand.get("params") or {}, content=(content.get("start"), content.get("end")))
    units = cand.get("units") or []
    index = {u["id"]: n for n, u in enumerate(units)}
    clips = clips_doc.get("clips") or []
    added = list(review.get(ADDED_KEY, []))
    keys = [(c["id"], c["candidate_id"]) for c in clips] + [(a["clip_id"], a["candidate_id"]) for a in added]
    cuts, _warnings = resolve_cuts(keys, review)
    return SourceEpisode(ws, clips, units, index, rng, cuts, added)


def _full_clip_lines(clip: dict, units: list[dict], index: dict[str, int]) -> list[str]:
    """P2: the candidate's text like CP6 G3 ``clip_text`` (``head_cut`` dropped when present), one entry per
    unit for the chunk boundaries of P3. Delegates the drop-and-validate step to ``clip_text`` itself (identical
    mismatch error); rebuilds the per-unit breakdown by removing the same number of leading tokens so joining the
    result reproduces ``clip_text``'s string exactly."""
    first, last = clip["unit_ids"]
    if first not in index or last not in index or index[first] > index[last]:
        raise PostSourceError(f"Short {clip['id']}: unit_ids {clip['unit_ids']} không có trong candidates.json")
    lines = [u["text"] for u in units[index[first]:index[last] + 1]]
    cut = clip.get("head_cut")
    if not cut:
        return lines
    try:
        titling_clip_text(clip, units, index)  # validates the drop; raises on mismatch (same message as titling)
    except TitlingError as exc:
        raise PostSourceError(str(exc)) from exc
    remaining = len(cut["words"].split())
    out: list[str] = []
    for line in lines:
        tokens = line.split()
        if remaining >= len(tokens):
            remaining -= len(tokens)
            continue
        out.append(" ".join(tokens[remaining:]))
        remaining = 0
    return out


def source_lines(ep: SourceEpisode, clip_id: str) -> list[str]:
    """P2: the caption-line-like pieces of ``clip_id``'s literal text, in order (chunk boundaries for P3)."""
    clip = ep.clip(clip_id)
    added = ep.added_entry(clip_id)
    if clip is None and added is None:
        raise PostSourceError(f"không có Short {clip_id!r}")
    if clip is not None and clip_id not in ep.cuts:
        lines = _full_clip_lines(clip, ep.units, ep.index)
    else:
        start, end = ep.cuts.get(clip_id) or (added["start"], added["end"])
        idx = C.lines_in(ep.rng, start, end)
        if not idx:
            raise PostSourceError(f"Short {clip_id}: không tìm được dòng phụ đề trong khoảng {start:.3f}-{end:.3f}")
        lines = [ep.rng.segments[n]["text"] for n in idx]
    lines = [" ".join(unicodedata.normalize("NFC", t).split()) for t in lines]
    if not any(line for line in lines):
        raise PostSourceError(f"Short {clip_id}: text nguồn rỗng")
    return [line for line in lines if line]


def source_text(ep: SourceEpisode, clip_id: str) -> str:
    """P2: ``source_lines`` joined by one space (what ``source_sha256`` hashes)."""
    return " ".join(source_lines(ep, clip_id))


def source_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
