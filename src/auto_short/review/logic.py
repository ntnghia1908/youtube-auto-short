"""Pure review logic (CP8.2): ``review.json`` v1 schema (T1), manual title form check (T2), override key (T3),
title precedence at render time (T4) and deleted Shorts (``rejected``, CP8.5 X2). No I/O except
:func:`read_review`.

Canonical contract: docs/decisions/CP8.2-title-override-contract.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..titling.logic import TITLED, form_reject_reason, normalize_title

REVIEW_NAME = "review.json"
SCHEMA_VERSION = 1
AI, MANUAL, ALTERNATIVE = "ai", "manual", "alternative"
ORIGINS = (MANUAL, ALTERNATIVE)  # origins stored in review.json
DOC_KEYS = ("schema_version", "episode_id", "titles")
REJECTED_KEY = "rejected"  # CP8.5 X2: optional last key, present only when non-empty
ENTRY_KEYS = ("clip_id", "candidate_id", "title", "origin")
REJECTED_KEYS = ("clip_id", "candidate_id")
MIN_CHARS = 1  # T2: a manual title only needs to be non-empty (no CP6 min_chars)


class ReviewError(Exception):
    """Invalid manual title, unknown clip/alternative, missing inputs or invalid ``review.json``."""


def empty_review(episode_id: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "titles": []}


def check_review(doc: object, episode_id: str) -> dict:
    """T1 schema check of a parsed ``review.json``; returns it unchanged or raises ReviewError."""
    def bad(msg: str) -> ReviewError:
        return ReviewError(f"{REVIEW_NAME}: {msg}")

    if not isinstance(doc, dict) or list(doc) not in (list(DOC_KEYS), list(DOC_KEYS) + [REJECTED_KEY]):
        raise bad(f"must be an object with keys {list(DOC_KEYS)} (+ optional {REJECTED_KEY!r})")
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
    return doc


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
        out.append(ResolvedTitle(t["clip_id"], t["candidate_id"], ai, AI if ai is not None else None, rejected))
    for o in by_clip.values():
        warnings.append(f"title override for clip {o['clip_id']} ignored: no such clip in clips.json")
    for r in rej.values():
        warnings.append(f"deleted Short {r['clip_id']} ignored: no such clip in clips.json")
    return out, warnings


def _order(review: dict, clip_order: list[str]) -> dict:
    """Canonical document: entries sorted by clips.json order (unknown ids last, by id); ``rejected`` only when
    non-empty, so a file without deleted Shorts keeps the CP8.2 shape."""
    pos = {cid: n for n, cid in enumerate(clip_order)}

    def key(e: dict) -> tuple:
        return pos.get(e["clip_id"], len(pos)), e["clip_id"]

    doc = {"schema_version": SCHEMA_VERSION, "episode_id": review["episode_id"],
           "titles": sorted(review["titles"], key=key)}
    rejected = sorted(review.get(REJECTED_KEY, []), key=key)
    if rejected:
        doc[REJECTED_KEY] = rejected
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
