"""Read-only views of episodes for the web API: manifest stages, metadata and rendered Shorts (stdlib only).

The web never writes stage artifacts; the only files it serves are the Shorts listed in
``<output_dir>/<episode_id>/render_manifest.json`` (W2).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import Config
from ..pipeline import PIPELINE_STAGES
from ..workspace import DONE, PENDING, Workspace, WorkspaceError, iter_manifests, validate_episode_id
from .urls import UrlError, parse_youtube_url

RENDER_MANIFEST = "render_manifest.json"
_CLIP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def valid_episode_id(episode_id: str) -> bool:
    try:
        validate_episode_id(episode_id)
    except WorkspaceError:
        return False
    return True


def valid_clip_id(clip_id: str) -> bool:
    return bool(_CLIP_ID_RE.match(clip_id))


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _output_dir(config: Config, episode_id: str) -> Path:
    return Path(config.render.output_dir) / episode_id


def _stages(manifest: dict) -> list[dict]:
    out = []
    for name in PIPELINE_STAGES:
        entry = (manifest.get("stages") or {}).get(name) or {}
        out.append({"stage": name, "status": entry.get("status", PENDING), "started_at": entry.get("started_at"),
                    "finished_at": entry.get("finished_at"), "error": entry.get("error")})
    return out


def _render_manifest(config: Config, episode_id: str, stages: list[dict]) -> dict | None:
    """The episode's render manifest, only while the render stage is ``done`` (a running render rewrites it)."""
    if next(s for s in stages if s["stage"] == "render")["status"] != DONE:
        return None
    doc = _read_json(_output_dir(config, episode_id) / RENDER_MANIFEST)
    if doc is None or doc.get("episode_id") != episode_id or not isinstance(doc.get("shorts"), list):
        return None
    return doc


def _source_url(manifest: dict) -> str | None:
    """Canonical URL to resubmit a YouTube episode (None for a local source: the web does not take paths)."""
    src = manifest.get("source") or {}
    if src.get("kind") != "youtube":
        return None
    try:
        return parse_youtube_url(src.get("uri") or "")[1]
    except UrlError:
        return None


def _short_view(episode_id: str, short: dict) -> dict | None:
    clip_id = short.get("clip_id")
    if not isinstance(clip_id, str) or not valid_clip_id(clip_id):
        return None
    rendered = short.get("status") == "rendered"
    sha = short.get("sha256") or ""
    base = f"/files/{episode_id}/{clip_id}.mp4"
    return {
        "clip_id": clip_id,
        "status": short.get("status"),
        "skip_reason": short.get("skip_reason"),
        "duration": short.get("duration"),
        "source_start": short.get("source_start"),
        "source_end": short.get("source_end"),
        # ``source``: "ai" while titles come from titles.json (CP7 R2); CP8.2 adds "manual" / "alternative".
        "title": {"text": short.get("title"), "source": "ai",
                  "display_lines": short.get("title_display_lines") or []},
        "sha256": sha or None,
        "video_url": f"{base}?v={sha[:12]}" if rendered else None,
        "download_url": f"{base}?download=1" if rendered else None,
    }


def episode_view(config: Config, episode_id: str) -> dict | None:
    """Full episode detail, or None when there is no manifest."""
    ws = Workspace(Path(config.workspace.dir), episode_id)
    try:
        manifest = ws.load_manifest()
    except WorkspaceError:
        return None
    if manifest is None:
        return None
    meta = _read_json(ws.dir / "metadata.json") or {}
    stages = _stages(manifest)
    doc = _render_manifest(config, episode_id, stages)
    shorts = [v for v in (_short_view(episode_id, s) for s in (doc or {}).get("shorts", [])) if v]
    rendered = sum(1 for s in shorts if s["status"] == "rendered")
    return {
        "id": episode_id,
        "title": meta.get("title"),
        "channel": meta.get("channel"),
        "duration": meta.get("duration"),
        "source_url": _source_url(manifest),
        "stages": stages,
        "header": (doc or {}).get("header", {}).get("lines"),
        "shorts": shorts,
        "rendered": rendered,
        "zip_url": f"/files/{episode_id}/shorts.zip" if rendered else None,
    }


def list_episodes(config: Config) -> list[dict]:
    """Summary per episode workspace, newest manifest first."""
    items = []
    for ws, manifest in iter_manifests(Path(config.workspace.dir)):
        meta = _read_json(ws.dir / "metadata.json") or {}
        stages = _stages(manifest)
        doc = _render_manifest(config, ws.episode_id, stages)
        try:
            mtime = ws.manifest_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        items.append({
            "id": ws.episode_id,
            "title": meta.get("title"),
            "stages_done": sum(1 for s in stages if s["status"] == DONE),
            "stages_total": len(stages),
            "running": next((s["stage"] for s in stages if s["status"] == "running"), None),
            "failed": next((s["stage"] for s in stages if s["status"] == "failed"), None),
            "shorts": sum(1 for s in doc["shorts"] if s.get("status") == "rendered") if doc else 0,
            "_mtime": mtime,
        })
    items.sort(key=lambda x: x.pop("_mtime"), reverse=True)
    return items


def short_files(config: Config, episode_id: str) -> list[tuple[str, Path]] | None:
    """``(clip_id, path)`` of every rendered Short that exists, in manifest order; None when the episode has no
    finished render. Paths are taken from the render manifest and must stay inside ``<output>/<id>/shorts/``."""
    ws = Workspace(Path(config.workspace.dir), episode_id)
    try:
        manifest = ws.load_manifest()
    except WorkspaceError:
        return None
    if manifest is None:
        return None
    doc = _render_manifest(config, episode_id, _stages(manifest))
    if doc is None:
        return None
    out_dir = _output_dir(config, episode_id)
    shorts_dir = (out_dir / "shorts").resolve()
    files = []
    for short in doc["shorts"]:
        clip_id, rel = short.get("clip_id"), short.get("file")
        if short.get("status") != "rendered" or not isinstance(clip_id, str) or not valid_clip_id(clip_id) \
                or not isinstance(rel, str):
            continue
        path = (out_dir / rel).resolve()
        if path.parent != shorts_dir or path.suffix != ".mp4" or not path.is_file():
            continue
        files.append((clip_id, path))
    return files


def short_file(config: Config, episode_id: str, clip_id: str) -> Path | None:
    for cid, path in short_files(config, episode_id) or []:
        if cid == clip_id:
            return path
    return None

