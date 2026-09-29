"""Pure review logic (CP8.2): ``review.json`` v1 schema (T1), manual title form check (T2), override key (T3),
title precedence at render time (T4), deleted Shorts (``rejected``, CP8.5 X2), manual cut points (``cuts``, CP9)
and Shorts added by hand (``added``, CP9). No I/O except :func:`read_review`.

Canonical contract: docs/decisions/CP8.2-title-override-contract.md.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from ..titling.logic import TITLED, form_reject_reason, normalize_title

REVIEW_NAME = "review.json"
SCHEMA_VERSION = 1
AI, MANUAL, ALTERNATIVE = "ai", "manual", "alternative"
ORIGINS = (MANUAL, ALTERNATIVE)  # origins stored in review.json
DOC_KEYS = ("schema_version", "episode_id", "titles")
REJECTED_KEY = "rejected"  # CP8.5 X2: optional key, present only when non-empty
CUTS_KEY = "cuts"  # CP9 C1: optional key after rejected, present only when non-empty
ADDED_KEY = "added"  # CP9 C1: optional last key, present only when non-empty
OPTIONAL_KEYS = (REJECTED_KEY, CUTS_KEY, ADDED_KEY)  # in this order after DOC_KEYS
ENTRY_KEYS = ("clip_id", "candidate_id", "title", "origin")
REJECTED_KEYS = ("clip_id", "candidate_id")
CUT_KEYS = ("clip_id", "candidate_id", "start", "end")
ADDED_KEYS = ("clip_id", "candidate_id", "start", "end", "source", "title", "ai_title", "alternatives")
PROPOSAL, TRANSCRIPT = "proposal", "transcript"  # CP9 C1 ``added[].source``
MANUAL_CANDIDATE = "manual"  # ``candidate_id`` of a Short added from the transcript
ADDED_ID_RE = re.compile(r"^m(\d{2,})$")  # m01, m02, ... (never reused)
ORIGIN_AI, ORIGIN_ADDED = "ai", "added"  # CP9 C5: render_manifest ``shorts[].origin``
MIN_CHARS = 1  # T2: a manual title only needs to be non-empty (no CP6 min_chars)


class ReviewError(Exception):
    """Invalid manual title, unknown clip/alternative, missing inputs or invalid ``review.json``."""


def empty_review(episode_id: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "titles": []}


def check_review(doc: object, episode_id: str) -> dict:
    """T1 schema check of a parsed ``review.json``; returns it unchanged or raises ReviewError."""
    def bad(msg: str) -> ReviewError:
        return ReviewError(f"{REVIEW_NAME}: {msg}")

    extra = list(doc)[len(DOC_KEYS):] if isinstance(doc, dict) else []
    if not isinstance(doc, dict) or list(doc)[:len(DOC_KEYS)] != list(DOC_KEYS) \
            or extra != [k for k in OPTIONAL_KEYS if k in extra]:
        raise bad(f"must be an object with keys {list(DOC_KEYS)} (+ optional {', '.join(map(repr, OPTIONAL_KEYS))}"
                  " in this order)")
    if doc["schema_version"] != SCHEMA_VERSION:
        raise bad(f"unsupported schema_version {doc['schema_version']!r}")
    if doc["episode_id"] != episode_id:
        raise bad(f"episode_id {doc['episode_id']!r} != {episode_id!r}")
    if not isinstance(doc["titles"], list):
        raise bad("titles must be an array")
    seen = set()
    for n, e in enumerate(doc["titles"]):
        if not isinstance(e, dict) or list(e) != list(ENTRY_KEYS):
            raise bad(f"titles[{n}] must be an object with keys {list(ENTRY_KEYS)}")
        if not all(isinstance(e[k], str) and e[k] for k in ENTRY_KEYS):
            raise bad(f"titles[{n}]: every value must be a non-empty string")
        if e["origin"] not in ORIGINS:
            raise bad(f"titles[{n}]: origin {e['origin']!r} not in {list(ORIGINS)}")
        if e["title"] != normalize_title(e["title"]):
            raise bad(f"titles[{n}]: title {e['title']!r} is not normalized (NFC, single spaces, one line)")
        if e["clip_id"] in seen:
            raise bad(f"duplicate clip_id {e['clip_id']!r}")
        seen.add(e["clip_id"])
    rejected = doc.get(REJECTED_KEY, [])
    if not isinstance(rejected, list) or (REJECTED_KEY in doc and not rejected):
        raise bad(f"{REJECTED_KEY} must be a non-empty array when present")
    seen = set()
    for n, e in enumerate(rejected):
        if not isinstance(e, dict) or list(e) != list(REJECTED_KEYS):
            raise bad(f"{REJECTED_KEY}[{n}] must be an object with keys {list(REJECTED_KEYS)}")
        if not all(isinstance(e[k], str) and e[k] for k in REJECTED_KEYS):
            raise bad(f"{REJECTED_KEY}[{n}]: every value must be a non-empty string")
        if e["clip_id"] in seen:
            raise bad(f"duplicate rejected clip_id {e['clip_id']!r}")
        seen.add(e["clip_id"])
    _check_cuts(doc, bad)
    _check_added(doc, bad)
    return doc


def _seconds(value: object) -> bool:
    """A time in seconds as stored (CP9 C1): a finite number >= 0 with at most 3 decimals (not a bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) \
        and value >= 0 and round(value, 3) == value


def _check_range(e: dict, where: str, bad) -> None:
    if not _seconds(e["start"]) or not _seconds(e["end"]) or not e["start"] < e["end"]:
        raise bad(f"{where}: start/end must be seconds (>= 0, 3 decimals) with start < end")


def _check_cuts(doc: dict, bad) -> None:
    if CUTS_KEY not in doc:
        return
    cuts = doc[CUTS_KEY]
    if not isinstance(cuts, list) or not cuts:
        raise bad(f"{CUTS_KEY} must be a non-empty array when present")
    seen = set()
    for n, e in enumerate(cuts):
        where = f"{CUTS_KEY}[{n}]"
        if not isinstance(e, dict) or list(e) != list(CUT_KEYS):
            raise bad(f"{where} must be an object with keys {list(CUT_KEYS)}")
        if not all(isinstance(e[k], str) and e[k] for k in ("clip_id", "candidate_id")):
            raise bad(f"{where}: clip_id / candidate_id must be non-empty strings")
        _check_range(e, where, bad)
        if e["clip_id"] in seen:
            raise bad(f"duplicate cut clip_id {e['clip_id']!r}")
        seen.add(e["clip_id"])


def _check_added(doc: dict, bad) -> None:
    if ADDED_KEY not in doc:
        return
    added = doc[ADDED_KEY]
    if not isinstance(added, list) or not added:
        raise bad(f"{ADDED_KEY} must be a non-empty array when present")
    seen = set()
    for n, e in enumerate(added):
        where = f"{ADDED_KEY}[{n}]"
        if not isinstance(e, dict) or list(e) != list(ADDED_KEYS):
            raise bad(f"{where} must be an object with keys {list(ADDED_KEYS)}")
        if not isinstance(e["clip_id"], str) or not ADDED_ID_RE.match(e["clip_id"]):
            raise bad(f"{where}: clip_id must be m01, m02, ...")
        if not isinstance(e["candidate_id"], str) or not e["candidate_id"]:
            raise bad(f"{where}: candidate_id must be a non-empty string")
        if e["source"] not in (PROPOSAL, TRANSCRIPT):
            raise bad(f"{where}: source {e['source']!r} not in {[PROPOSAL, TRANSCRIPT]}")
        if (e["source"] == TRANSCRIPT) != (e["candidate_id"] == MANUAL_CANDIDATE):
            raise bad(f"{where}: candidate_id {MANUAL_CANDIDATE!r} goes with source {TRANSCRIPT!r} only")
        _check_range(e, where, bad)
        for key in ("title", "ai_title"):
            v = e[key]
            if v is not None and (not isinstance(v, str) or not v or v != normalize_title(v)):
                raise bad(f"{where}: {key} must be null or a normalized non-empty string")
        alts = e["alternatives"]
        if not isinstance(alts, list) or not all(
                isinstance(a, dict) and list(a) == ["title", "evidence"]
                and all(isinstance(a[k], str) and a[k] for k in ("title", "evidence")) for a in alts):
            raise bad(f"{where}: alternatives must be an array of {{\"title\", \"evidence\"}} strings")
        if e["clip_id"] in seen:
            raise bad(f"duplicate added clip_id {e['clip_id']!r}")
        seen.add(e["clip_id"])


def read_review(path: Path, episode_id: str) -> dict:
    """``review.json`` checked against T1; a missing file means no override (empty document)."""
    if not path.is_file():
        return empty_review(episode_id)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError(f"cannot read {path}: {exc}") from exc
    return check_review(doc, episode_id)


def manual_title_error(text: str, *, max_chars: int) -> str | None:
    """T2 form rules for a human title (CP6 G5 rules 1-8 with ``min_chars`` = 1, no evidence rule): None when
    valid, else the reason. Glyph coverage and fit (CP7 R5) are checked by the caller with the font."""
    return form_reject_reason(text, min_chars=MIN_CHARS, max_chars=max_chars)


@dataclass(frozen=True)
class ResolvedTitle:
    """Title a clip is rendered with (T4): ``title`` None = nothing to render (untitled, no override)."""

    clip_id: str
    candidate_id: str
    title: str | None
    origin: str | None  # ai | manual | alternative | None
    rejected: bool = False  # CP8.5 X2: deleted in review -> not rendered (skip_reason "rejected")


def resolve_titles(titles: list[dict], review: dict) -> tuple[list[ResolvedTitle], list[str]]:
    """T3/T4: for each ``titles.json`` entry, an override with the same ``(clip_id, candidate_id)`` wins over the
    AI title; untitled clips with an override are rendered. Overrides whose clip is gone or whose
    ``candidate_id`` differs (selection re-run) are ignored; one warning message each is returned. A clip in
    ``rejected`` with the same ``(clip_id, candidate_id)`` (CP8.5 X2) is flagged ``rejected`` (its title is still
    resolved, to be shown and restored); a stale ``rejected`` entry is ignored the same way as an override."""
    by_clip = {e["clip_id"]: e for e in review["titles"]}
    rej = {e["clip_id"]: e for e in review.get(REJECTED_KEY, [])}
    out, warnings = [], []
    for t in titles:
        o = by_clip.pop(t["clip_id"], None)
        r = rej.pop(t["clip_id"], None)
        rejected = r is not None and r["candidate_id"] == t["candidate_id"]
        if r is not None and not rejected:
            warnings.append(f"deleted Short {r['clip_id']} ignored: deleted as candidate {r['candidate_id']}, "
                            f"the clip is now candidate {t['candidate_id']} (selection re-run)")
        if o is not None and o["candidate_id"] == t["candidate_id"]:
            out.append(ResolvedTitle(t["clip_id"], t["candidate_id"], o["title"], o["origin"], rejected))
            continue
        if o is not None:
            warnings.append(f"title override for clip {o['clip_id']} ignored: made for candidate "
                            f"{o['candidate_id']}, the clip is now candidate {t['candidate_id']} (selection re-run)")
        ai = t.get("title") if t.get("status") == TITLED else None
        # CP9: a Short added by hand carries its own title and the origin derived from it (added_entries)
        origin = (t.get("origin") or AI) if ai is not None else None
        out.append(ResolvedTitle(t["clip_id"], t["candidate_id"], ai, origin, rejected))
    for o in by_clip.values():
        warnings.append(f"title override for clip {o['clip_id']} ignored: no such clip in clips.json")
    for r in rej.values():
        warnings.append(f"deleted Short {r['clip_id']} ignored: no such clip in clips.json")
    return out, warnings


def added_number(clip_id: str) -> int | None:
    """``m07`` -> 7; None for any other id."""
    m = ADDED_ID_RE.match(clip_id or "")
    return int(m.group(1)) if m else None


def _order(review: dict, clip_order: list[str]) -> dict:
    """Canonical document: entries sorted by clip order (clips.json then the added Shorts; unknown ids last, by
    id); ``rejected`` / ``cuts`` / ``added`` only when non-empty, so a file without them keeps the CP8.2 shape
    (CP8.5, CP9 C1). ``added`` stays in creation order (id number)."""
    pos = {cid: n for n, cid in enumerate(clip_order)}

    def key(e: dict) -> tuple:
        return pos.get(e["clip_id"], len(pos)), e["clip_id"]

    doc = {"schema_version": SCHEMA_VERSION, "episode_id": review["episode_id"],
           "titles": sorted(review["titles"], key=key)}
    for name in (REJECTED_KEY, CUTS_KEY):
        entries = sorted(review.get(name, []), key=key)
        if entries:
            doc[name] = entries
    added = sorted(review.get(ADDED_KEY, []), key=lambda e: (added_number(e["clip_id"]) or 0, e["clip_id"]))
    if added:
        doc[ADDED_KEY] = added
    return doc


def with_override(review: dict, clip_order: list[str], *, clip_id: str, candidate_id: str, title: str,
                  origin: str) -> dict:
    """New document with the override of ``clip_id`` set (replacing any older one), sorted by ``clip_order``
    (clips.json order; ids not in it last)."""
    if origin not in ORIGINS:
        raise ReviewError(f"invalid origin {origin!r}")
    entry = {"clip_id": clip_id, "candidate_id": candidate_id, "title": title, "origin": origin}
    rest = [e for e in review["titles"] if e["clip_id"] != clip_id]
    return _order({**review, "titles": rest + [entry]}, clip_order)


def without_override(review: dict, clip_order: list[str], clip_id: str) -> tuple[dict, bool]:
    """New document without the override of ``clip_id``; the flag tells whether one existed."""
    rest = [e for e in review["titles"] if e["clip_id"] != clip_id]
    return _order({**review, "titles": rest}, clip_order), len(rest) != len(review["titles"])


def with_rejected(review: dict, clip_order: list[str], *, clip_id: str, candidate_id: str) -> dict:
    """CP8.5 X2: new document with ``clip_id`` deleted (``rejected``; replaces an older entry of the clip). Title
    overrides are kept, so restoring gives back the same title."""
    rest = [e for e in review.get(REJECTED_KEY, []) if e["clip_id"] != clip_id]
    entry = {"clip_id": clip_id, "candidate_id": candidate_id}
    return _order({**review, REJECTED_KEY: rest + [entry]}, clip_order)


def without_rejected(review: dict, clip_order: list[str], clip_id: str) -> tuple[dict, bool]:
    """CP8.5 X2: new document with ``clip_id`` restored; the flag tells whether it was deleted."""
    old = review.get(REJECTED_KEY, [])
    rest = [e for e in old if e["clip_id"] != clip_id]
    return _order({**review, REJECTED_KEY: rest}, clip_order), len(rest) != len(old)


# --- CP9: manual cut points (``cuts``) and Shorts added by hand (``added``) ----------------------------------

def added_ids(review: dict) -> list[str]:
    return [e["clip_id"] for e in review.get(ADDED_KEY, [])]


def added_origin(entry: dict) -> str | None:
    """Title origin of an added Short (C1: ``title`` = title in use, origin as CP8.2): None when untitled, ``ai``
    when it is the AI title, ``alternative`` when it is one of the AI alternatives, else ``manual``."""
    title = entry["title"]
    if title is None:
        return None
    if title == entry["ai_title"]:
        return AI
    if any(a["title"] == title for a in entry["alternatives"]):
        return ALTERNATIVE
    return MANUAL


def added_entries(review: dict) -> list[dict]:
    """The added Shorts as ``titles.json``-like entries for :func:`resolve_titles` (plus ``origin``)."""
    return [{"clip_id": e["clip_id"], "candidate_id": e["candidate_id"], "title": e["title"],
             "status": TITLED if e["title"] is not None else "untitled", "origin": added_origin(e)}
            for e in review.get(ADDED_KEY, [])]


def resolve_cuts(clips: list[tuple[str, str]], review: dict) -> tuple[dict[str, tuple[float, float]], list[str]]:
    """CP9 C1: manual cut of each ``(clip_id, candidate_id)`` in ``clips`` (clips.json then added Shorts). A cut
    whose clip is gone or whose ``candidate_id`` differs (selection re-run) is ignored with a warning, like a
    title override (CP8.2 T3)."""
    by_clip = {e["clip_id"]: e for e in review.get(CUTS_KEY, [])}
    out, warnings = {}, []
    for clip_id, candidate_id in clips:
        c = by_clip.pop(clip_id, None)
        if c is None:
            continue
        if c["candidate_id"] == candidate_id:
            out[clip_id] = (c["start"], c["end"])
        else:
            warnings.append(f"cut of clip {clip_id} ignored: made for candidate {c['candidate_id']}, the clip is now "
                            f"candidate {candidate_id} (selection re-run)")
    for c in by_clip.values():
        warnings.append(f"cut of clip {c['clip_id']} ignored: no such clip")
    return out, warnings


def with_cut(review: dict, clip_order: list[str], *, clip_id: str, candidate_id: str, start: float,
             end: float) -> dict:
    rest = [e for e in review.get(CUTS_KEY, []) if e["clip_id"] != clip_id]
    entry = {"clip_id": clip_id, "candidate_id": candidate_id, "start": start, "end": end}
    return _order({**review, CUTS_KEY: rest + [entry]}, clip_order)


def without_cut(review: dict, clip_order: list[str], clip_id: str) -> tuple[dict, bool]:
    old = review.get(CUTS_KEY, [])
    rest = [e for e in old if e["clip_id"] != clip_id]
    return _order({**review, CUTS_KEY: rest}, clip_order), len(rest) != len(old)


def with_added(review: dict, clip_order: list[str], entry: dict) -> dict:
    """New document with the added Short ``entry`` (C1 keys; replaces an entry with the same id)."""
    if list(entry) != list(ADDED_KEYS):
        raise ReviewError(f"added entry must have keys {list(ADDED_KEYS)}")
    rest = [e for e in review.get(ADDED_KEY, []) if e["clip_id"] != entry["clip_id"]]
    return _order({**review, ADDED_KEY: rest + [entry]}, clip_order)


def without_added(review: dict, clip_order: list[str], clip_id: str) -> tuple[dict, bool]:
    """New document without the added Short ``clip_id`` (and its cut / deletion); the flag tells whether it
    existed. Not reachable from the web (a Short is deleted with ``rejected``); kept for tests and tools."""
    old = review.get(ADDED_KEY, [])
    rest = [e for e in old if e["clip_id"] != clip_id]
    doc = {**review, ADDED_KEY: rest,
           CUTS_KEY: [e for e in review.get(CUTS_KEY, []) if e["clip_id"] != clip_id],
           REJECTED_KEY: [e for e in review.get(REJECTED_KEY, []) if e["clip_id"] != clip_id],
           "titles": [e for e in review["titles"] if e["clip_id"] != clip_id]}
    return _order(doc, clip_order), len(rest) != len(old)


def next_added_id(used: set[str] | list[str]) -> str:
    """``m<NN>`` one above every added id ever seen (C1: never reused, even after a deletion)."""
    top = max((n for n in (added_number(c) for c in used) if n is not None), default=0)
    return f"m{top + 1:02d}"
