"""Manual title overrides of one episode (CP8.2): list, preview, set, choose an AI alternative, reset.

Functions shared by the CLI (``auto-short title``) and the web UI. Each call reads the episode from the workspace
(no state kept between calls), validates, and writes ``work/<id>/review.json`` atomically only when the new title
is valid. They never call the AI and never render; run :func:`auto_short.render.run_render` afterwards.

Canonical contract: docs/decisions/CP8.2-title-override-contract.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..titling.logic import TITLED, normalize_title
from ..workspace import DONE, Workspace, WorkspaceError, atomic_write_json, validate_episode_id
from .logic import (AI, ALTERNATIVE, MANUAL, REVIEW_NAME, ReviewError, manual_title_error, read_review,
                    resolve_titles, with_override, without_override)


@dataclass(frozen=True)
class TitlePreview:
    """How a title will be displayed in the Short's title panel (CP7 R5)."""

    clip_id: str
    title: str  # normalized text (NFC, single spaces) as stored and rendered
    origin: str  # ai | manual | alternative
    display_lines: list[str]
    font_size: int  # px
    panel_height: int  # px


@dataclass
class _Episode:
    ws: Workspace
    clips: list[dict]  # clips.json clips
    titles: list[dict]  # titles.json entries (same order)
    review: dict

    @property
    def order(self) -> list[str]:
        return [c["id"] for c in self.clips]

    def entry(self, clip_id: str) -> dict:
        for t in self.titles:
            if t["clip_id"] == clip_id:
                return t
        raise ReviewError(f"no clip {clip_id!r} in episode {self.ws.episode_id!r} "
                          f"(clips: {', '.join(self.order) or 'none'})")


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError(f"cannot read {path}: {exc}") from exc


def _load(episode_id: str, config: Config) -> _Episode:
    try:
        ws = Workspace(config.workspace.dir, validate_episode_id(episode_id))
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise ReviewError(str(exc)) from exc
    if manifest is None:
        raise ReviewError(f"no manifest for episode {episode_id!r} in {ws.dir}; run 'auto-short ingest' first")
    status = (manifest["stages"].get("titling") or {}).get("status", "pending")
    if status != DONE:
        raise ReviewError(f"titling is not done for {episode_id!r} (status: {status}); run 'auto-short titling' first")
    clips = _read(ws.dir / "clips.json").get("clips", [])
    titles = _read(ws.dir / "titles.json").get("titles", [])
    if [(c["id"], c["candidate_id"]) for c in clips] != [(t["clip_id"], t["candidate_id"]) for t in titles]:
        raise ReviewError("titles.json entries do not match clips.json (ids/order); re-run 'auto-short titling'")
    return _Episode(ws, clips, titles, read_review(ws.dir / REVIEW_NAME, ws.episode_id))


def _fit(config: Config, clip_id: str, text: str, origin: str) -> TitlePreview:
    """Glyph coverage + R5 fit with the render font/geometry (the same code the render uses)."""
    from ..render import plan
    from ..render import stage as render_stage
    from ..render.text import Font, TextError

    cfg = config.render
    try:
        font = Font(render_stage.font_path(cfg))
        missing = font.missing(text)
        if missing:
            raise ReviewError("character(s) not in the font: " + ", ".join(f"{c!r} (U+{ord(c):04X})"
                                                                            for c in missing))
        fit = render_stage.fit_clip_title(font, text, cfg, plan.geometry(cfg))
    except TextError as exc:
        raise ReviewError(f"title does not fit: {exc}") from exc
    except plan.PlanError as exc:
        raise ReviewError(str(exc)) from exc
    return TitlePreview(clip_id, text, origin, list(fit.lines), fit.font_size, fit.panel_height)


def _validate(config: Config, clip_id: str, text: str, origin: str) -> TitlePreview:
    """T2: form rules (CP6 G5 without evidence, 1..max_chars), then glyphs and fit."""
    if not isinstance(text, str):
        raise ReviewError("title must be a string")
    reason = manual_title_error(text, max_chars=config.titling.max_chars)
    if reason:
        raise ReviewError(f"invalid title: {reason}")
    return _fit(config, clip_id, normalize_title(text), origin)


def _write(ep: _Episode, review: dict) -> None:
    atomic_write_json(ep.ws.dir / REVIEW_NAME, review)
    ep.review = review


def load_overrides(episode_id: str, config: Config) -> list[dict]:
    """Overrides stored in ``review.json`` (T1 entries ``{"clip_id", "candidate_id", "title", "origin"}``, clips.json
    order); ``[]`` when there is no file. Includes overrides the render would ignore (see :func:`list_titles`)."""
    return list(_load(episode_id, config).review["titles"])


def list_titles(episode_id: str, config: Config) -> dict:
    """Every clip's titles::

        {"episode_id": str,
         "clips": [{"clip_id", "candidate_id", "status": "titled" | "untitled",
                    "ai_title": str | None,
                    "alternatives": [{"n": 1, "title": str}, ...],      # n = number for set_alternative
                    "override": {"title": str, "origin": "manual" | "alternative"} | None,
                    "title": str | None,                               # title the render uses (T4)
                    "origin": "ai" | "manual" | "alternative" | None}],
         "ignored": [str, ...]}                                         # T3 warnings (override not applied)
    """
    ep = _load(episode_id, config)
    resolved, warnings = resolve_titles(ep.titles, ep.review)
    overrides = {e["clip_id"]: e for e in ep.review["titles"]}
    clips = []
    for t, r in zip(ep.titles, resolved):
        o = overrides.get(t["clip_id"])
        applied = o is not None and o["candidate_id"] == t["candidate_id"]
        clips.append({"clip_id": t["clip_id"], "candidate_id": t["candidate_id"], "status": t["status"],
                      "ai_title": t["title"] if t["status"] == TITLED else None,
                      "alternatives": [{"n": n, "title": a["title"]}
                                       for n, a in enumerate(t.get("alternatives") or [], 1)],
                      "override": {"title": o["title"], "origin": o["origin"]} if applied else None,
                      "title": r.title, "origin": r.origin})
    return {"episode_id": ep.ws.episode_id, "clips": clips, "ignored": warnings}


def preview_title(episode_id: str, config: Config, clip_id: str, text: str) -> TitlePreview:
    """Validate ``text`` as a manual title for ``clip_id`` (T2) and return its display (lines, font size, panel
    height) without writing anything; raises ReviewError with the reason when it is invalid."""
    _load(episode_id, config).entry(clip_id)
    return _validate(config, clip_id, text, MANUAL)


def set_title(episode_id: str, config: Config, clip_id: str, text: str) -> TitlePreview:
    """Store ``text`` as the manual title of ``clip_id`` (origin ``manual``). Invalid -> ReviewError, review.json
    unchanged."""
    ep = _load(episode_id, config)
    entry = ep.entry(clip_id)
    preview = _validate(config, clip_id, text, MANUAL)
    _write(ep, with_override(ep.review, ep.order, clip_id=clip_id, candidate_id=entry["candidate_id"],
                             title=preview.title, origin=MANUAL))
    return preview


def set_alternative(episode_id: str, config: Config, clip_id: str, n: int) -> TitlePreview:
    """Use AI alternative number ``n`` (1-based, titles.json ``alternatives`` order) of ``clip_id`` verbatim as its
    title (origin ``alternative``). Unknown number or invalid title -> ReviewError, review.json unchanged."""
    ep = _load(episode_id, config)
    entry = ep.entry(clip_id)
    alts = entry.get("alternatives") or []
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= len(alts):
        raise ReviewError(f"clip {clip_id} has no alternative {n!r} "
                          f"({'choose 1-' + str(len(alts)) if alts else 'it has no alternatives'})")
    preview = _validate(config, clip_id, alts[n - 1]["title"], ALTERNATIVE)
    _write(ep, with_override(ep.review, ep.order, clip_id=clip_id, candidate_id=entry["candidate_id"],
                             title=preview.title, origin=ALTERNATIVE))
    return preview


def reset_title(episode_id: str, config: Config, clip_id: str) -> TitlePreview | None:
    """Remove the override of ``clip_id`` (back to the AI title; review.json rewritten only if one existed).
    Returns the AI title's display, or None when the clip is untitled (it will not be rendered)."""
    ep = _load(episode_id, config)
    entry = ep.entry(clip_id)
    review, removed = without_override(ep.review, ep.order, clip_id)
    if removed:
        _write(ep, review)
    if entry["status"] != TITLED:
        return None
    return _fit(config, clip_id, entry["title"], AI)
