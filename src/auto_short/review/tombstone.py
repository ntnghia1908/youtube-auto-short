"""Tombstones of deleted episodes (CP8.7, bổ sung HUMAN LEAD 2026-09-27).

``delete_episode`` first writes ``<workspace.dir>/_deleted/<episode_id>.json`` (the leading ``_`` can never be an
episode id, CP2 D3) so a bộ kinh keeps its statistics after finished episodes are deleted to save disk: title,
source URL, Short counts, whether it was "Xong" (L4) and the header fields. Tiny, never deleted automatically;
ignored while a workspace of the same id exists (the episode was processed again).
Canonical contract: docs/decisions/CP8.3-web-contract.md W8 / W10.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..workspace import Workspace, WorkspaceError, atomic_write_json, validate_episode_id
from .logic import ReviewError
from .publish import PUBLISH_NAME, episode_complete, publish_status, read_publish

DELETED_DIR = "_deleted"
SCHEMA_VERSION = 1
KEYS = ("schema_version", "episode_id", "title", "source_url", "deleted_at", "shorts", "published", "complete",
        "header")


def _read_json(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def tombstone_dir(config: Config) -> Path:
    return Path(config.workspace.dir) / DELETED_DIR


def tombstone_path(config: Config, episode_id: str) -> Path:
    return tombstone_dir(config) / f"{validate_episode_id(episode_id)}.json"


def build_tombstone(episode_id: str, config: Config, *, now: str | None = None) -> dict | None:
    """Tombstone of an existing workspace (None without a manifest)."""
    ws = Workspace(Path(config.workspace.dir), validate_episode_id(episode_id))
    try:
        manifest = ws.load_manifest()
    except WorkspaceError:
        manifest = None
    if manifest is None:
        return None
    meta = _read_json(ws.dir / "metadata.json") or {}
    titles = _read_json(ws.dir / "titles.json") or {}
    fields = (titles.get("header") or {}).get("fields") or {}
    rm = _read_json(Path(config.render.output_dir) / ws.episode_id / "render_manifest.json")
    shorts = rm.get("shorts", []) if rm and rm.get("episode_id") == ws.episode_id else []
    shorts = [s for s in shorts if isinstance(s, dict)]
    rendered = [s for s in shorts if s.get("status") == "rendered"]
    try:
        pub = read_publish(ws.dir / PUBLISH_NAME, ws.episode_id)
    except ReviewError:
        pub = {"published": []}
    status = publish_status(pub, rendered)
    render_status = ((manifest.get("stages") or {}).get("render") or {}).get("status")
    src = manifest.get("source") or {}
    source_url = src.get("uri") if isinstance(src.get("uri"), str) else None
    if src.get("kind") == "youtube":
        source_url = f"https://youtu.be/{ws.episode_id}"
    return {
        "schema_version": SCHEMA_VERSION, "episode_id": ws.episode_id,
        "title": meta.get("title") if isinstance(meta.get("title"), str) else None,
        "source_url": source_url,
        "deleted_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "shorts": len(rendered),
        # ticked for the current file (same rule as "Xong", L4)
        "published": sum(1 for s in rendered if status.get(s.get("clip_id"), {}).get("published")
                         and not status.get(s.get("clip_id"), {}).get("stale")),
        "complete": rm is not None and episode_complete(render_status, shorts, pub),
        "header": {"series": fields.get("series"), "episode": fields.get("episode")},
    }


def write_tombstone(episode_id: str, config: Config, *, now: str | None = None) -> dict | None:
    doc = build_tombstone(episode_id, config, now=now)
    if doc is not None:
        atomic_write_json(tombstone_path(config, episode_id), doc)
    return doc


def read_tombstone(config: Config, episode_id: str) -> dict | None:
    try:
        path = tombstone_path(config, episode_id)
    except WorkspaceError:
        return None
    doc = _read_json(path)
    return doc if doc is not None and doc.get("episode_id") == episode_id else None


def list_tombstones(config: Config) -> list[dict]:
    """Every tombstone whose episode has no workspace now (newest deletion first)."""
    root = tombstone_dir(config)
    out = []
    if root.is_dir():
        for p in root.glob("*.json"):
            doc = read_tombstone(config, p.stem)
            if doc is not None and not (Path(config.workspace.dir) / p.stem / "manifest.json").is_file():
                out.append(doc)
    out.sort(key=lambda d: (d.get("deleted_at") or "", d["episode_id"]), reverse=True)
    return out


def remove_tombstone(config: Config, episode_id: str) -> bool:
    """"Xóa khỏi lịch sử": the tombstone only."""
    try:
        path = tombstone_path(config, episode_id)
    except WorkspaceError:
        return False
    if not path.is_file():
        return False
    path.unlink()
    return True
