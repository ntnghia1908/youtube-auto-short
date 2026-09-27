"""Read-only views of episodes for the web API: manifest stages, metadata and rendered Shorts (stdlib only).

The web never writes stage artifacts; the only files it serves are the Shorts listed in
``<output_dir>/<episode_id>/render_manifest.json`` (W2), offered under the CP8.5 download names.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import Config
from ..pipeline import PIPELINE_STAGES
from ..review import (ReviewError, download_name, episode_complete, episode_label, list_titles, publish_status,
                      read_archive, zip_name)
from ..review.publish import PUBLISH_NAME, read_publish
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


def _render_manifest(config: Config, episode_id: str) -> dict | None:
    """The episode's last committed render manifest, whatever the render stage status is now: a render run stages
    new Shorts as ``.part`` files and only replaces files + manifest at its commit, and a failed / interrupted run
    leaves the previous render intact (CP8.2 T5), so the listed files always exist and match."""
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


def _label(config: Config, episode_id: str) -> str:
    """``<episode>`` of the download names: titles.json ``header.fields.episode``, else the episode id (X1)."""
    doc = _read_json(Path(config.workspace.dir) / episode_id / "titles.json") or {}
    fields = (doc.get("header") or {}).get("fields") or {}
    value = fields.get("episode") if isinstance(fields, dict) else None
    return episode_label(value if isinstance(value, str) else None, episode_id)


def _names(config: Config, episode_id: str, doc: dict) -> dict[str, str]:
    """Download name of every Short of the render manifest: number = position in the manifest (= clips.json
    order, CP7 R9, deleted Shorts included so the numbers never shift), title = the title in the file."""
    label, shorts = _label(config, episode_id), doc.get("shorts") or []
    return {s["clip_id"]: download_name(label, n, len(shorts), s.get("title"))
            for n, s in enumerate(shorts, 1) if isinstance(s, dict) and isinstance(s.get("clip_id"), str)}


def _publish(config: Config, episode_id: str, doc: dict) -> tuple[dict[str, dict], str | None]:
    """X4 status per clip (``publish.json``) + an error message when the file is broken."""
    try:
        pub = read_publish(Path(config.workspace.dir) / episode_id / PUBLISH_NAME, episode_id)
    except ReviewError as exc:
        return {}, str(exc)
    return publish_status(pub, [s for s in doc.get("shorts") or [] if isinstance(s, dict)]), None


def is_complete(config: Config, episode_id: str, manifest: dict, doc: dict | None) -> bool:
    """CP8.7 L4 "Xong" of an episode (derived): render done + every rendered Short ticked for its current file."""
    render_status = ((manifest.get("stages") or {}).get("render") or {}).get("status")
    if doc is None:
        return False
    try:
        pub = read_publish(Path(config.workspace.dir) / episode_id / PUBLISH_NAME, episode_id)
    except ReviewError:
        return False
    return episode_complete(render_status, doc.get("shorts") or [], pub)


def _short_view(episode_id: str, short: dict, titles: dict | None, *, name: str | None = None,
                published: dict | None = None) -> dict | None:
    clip_id = short.get("clip_id")
    if not isinstance(clip_id, str) or not valid_clip_id(clip_id):
        return None
    rendered = short.get("status") == "rendered"
    sha = short.get("sha256") or ""
    base = f"/files/{episode_id}/{clip_id}.mp4"
    view = {
        "clip_id": clip_id,
        "status": short.get("status"),
        "skip_reason": short.get("skip_reason"),
        "duration": short.get("duration"),
        "source_start": short.get("source_start"),
        "source_end": short.get("source_end"),
        # The title burnt into the file (render_manifest.json, CP8.2 T4).
        "title": {"text": short.get("title"), "origin": short.get("title_origin") or ("ai" if rendered else None),
                  "display_lines": short.get("title_display_lines") or []},
        "sha256": sha or None,
        "video_url": f"{base}?v={sha[:12]}" if rendered else None,
        "download_url": f"{base}?download=1" if rendered else None,
        "download_name": name if rendered else None,
        # CP8.5 X2: ``deleted`` = the last render skipped it as rejected; ``rejected`` = review.json says deleted
        # (differs from ``deleted`` while the render job runs).
        "deleted": short.get("status") == "skipped" and short.get("skip_reason") == "rejected",
        "rejected": short.get("status") == "skipped" and short.get("skip_reason") == "rejected",
        "published": bool((published or {}).get("published")),
        "published_stale": bool((published or {}).get("stale")),
        "published_at": (published or {}).get("at"),
        "editable": titles is not None,
        "ai_title": None, "alternatives": [], "override": None,
        "pending_title": None,  # title the next render will use, when it differs from the file's
        "rendering": False,
    }
    if titles is not None:
        view.update(ai_title=titles["ai_title"], alternatives=titles["alternatives"], override=titles["override"],
                    rejected=bool(titles.get("rejected")))
        if titles["title"] != short.get("title") or (titles["title"] is not None
                                                     and titles["origin"] != view["title"]["origin"]):
            view["pending_title"] = {"text": titles["title"], "origin": titles["origin"]}
    return view


def _titles(config: Config, episode_id: str) -> tuple[dict[str, dict], list[str], str | None]:
    """CP8.2 ``list_titles`` by clip id, T3 warnings and an error message (titling not done, review.json broken)."""
    try:
        doc = list_titles(episode_id, config)
    except ReviewError as exc:
        return {}, [], str(exc)
    return {c["clip_id"]: c for c in doc["clips"]}, list(doc["ignored"]), None


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
    doc = _render_manifest(config, episode_id)
    titles, ignored, titles_error = _titles(config, episode_id) if doc else ({}, [], None)
    names = _names(config, episode_id, doc) if doc else {}
    published, publish_error = _publish(config, episode_id, doc) if doc else ({}, None)
    shorts = [v for v in (_short_view(episode_id, s, titles.get(s.get("clip_id")) if not titles_error else None,
                                      name=names.get(s.get("clip_id")), published=published.get(s.get("clip_id")))
                          for s in (doc or {}).get("shorts", []) if isinstance(s, dict)) if v]
    rendered = sum(1 for s in shorts if s["status"] == "rendered")
    return {
        "id": episode_id,
        "title": meta.get("title"),
        "channel": meta.get("channel"),
        "duration": meta.get("duration"),
        "source_url": _source_url(manifest),
        "stages": stages,
        "render_status": stages[-1]["status"],
        "header": (doc or {}).get("header", {}).get("lines"),
        "shorts": shorts,
        "rendered": rendered,
        "deleted": sum(1 for s in shorts if s["deleted"]),
        "published": sum(1 for s in shorts if s["status"] == "rendered" and s["published"]),
        "publish_error": publish_error,
        "zip_url": f"/files/{episode_id}/shorts.zip" if rendered else None,
        "zip_name": zip_name(_label(config, episode_id)) if rendered else None,
        "max_title_chars": config.titling.max_chars,
        "titles_error": titles_error,
        "titles_ignored": ignored,
        # CP8.6 S3: source video cleaned up -> view / download / tick / delete Short only
        "archived": _archived_view(ws.dir),
        "complete": is_complete(config, episode_id, manifest, doc),  # CP8.7 L4 "Xong"
    }


def _archived_view(ws_dir: Path) -> dict | None:
    doc = read_archive(ws_dir)
    if doc is None:
        return None
    removed = doc.get("removed") if isinstance(doc.get("removed"), list) else []
    return {"at": doc.get("archived_at"),
            "freed": sum(r.get("size", 0) for r in removed if isinstance(r, dict) and isinstance(r.get("size"), int))}


def list_episodes(config: Config) -> list[dict]:
    """Summary per episode workspace, newest manifest first."""
    items = []
    for ws, manifest in iter_manifests(Path(config.workspace.dir)):
        meta = _read_json(ws.dir / "metadata.json") or {}
        stages = _stages(manifest)
        doc = _render_manifest(config, ws.episode_id)
        pub = _publish(config, ws.episode_id, doc)[0] if doc else {}
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
            # "đã đăng x/y" (X4): x = rendered Shorts ticked (an old version counts), y = "shorts"
            "published": sum(1 for s in doc["shorts"] if s.get("status") == "rendered"
                             and pub.get(s.get("clip_id"), {}).get("published")) if doc else 0,
            "archived": read_archive(ws.dir) is not None,  # CP8.6
            "complete": is_complete(config, ws.episode_id, manifest, doc),  # CP8.7 L4 "Xong"
            "_mtime": mtime,
        })
    items.sort(key=lambda x: x.pop("_mtime"), reverse=True)
    return items


def short_files(config: Config, episode_id: str) -> list[tuple[str, Path, str]] | None:
    """``(clip_id, path, download name)`` of every rendered Short that exists, in manifest order; None when the
    episode has no finished render. Paths are taken from the render manifest and must stay inside
    ``<output>/<id>/shorts/``."""
    ws = Workspace(Path(config.workspace.dir), episode_id)
    try:
        manifest = ws.load_manifest()
    except WorkspaceError:
        return None
    if manifest is None:
        return None
    doc = _render_manifest(config, episode_id)
    if doc is None:
        return None
    out_dir = _output_dir(config, episode_id)
    shorts_dir = (out_dir / "shorts").resolve()
    names = _names(config, episode_id, doc)
    files = []
    for short in doc["shorts"]:
        clip_id, rel = short.get("clip_id"), short.get("file")
        if short.get("status") != "rendered" or not isinstance(clip_id, str) or not valid_clip_id(clip_id) \
                or not isinstance(rel, str):
            continue
        path = (out_dir / rel).resolve()
        if path.parent != shorts_dir or path.suffix != ".mp4" or not path.is_file():
            continue
        files.append((clip_id, path, names[clip_id]))
    return files


def short_file(config: Config, episode_id: str, clip_id: str) -> tuple[Path, str] | None:
    """Path + download name of one rendered Short."""
    for cid, path, name in short_files(config, episode_id) or []:
        if cid == clip_id:
            return path, name
    return None


def zip_download_name(config: Config, episode_id: str) -> str:
    return zip_name(_label(config, episode_id))



TODO, ALL_PUBLISHED = "todo", "done"  # list filter groups (CP8.5 X4, bổ sung HUMAN LEAD 2026-09-27)


def publish_group(item: dict) -> str | None:
    """Episode list filter "Còn Short chưa đăng" (``todo``) / "Đã đăng hết" (``done``) from a list item with its
    ``job``. CP8.7: ``done`` = the derived "Xong" (L4, ``complete``: render done and every rendered Short ticked
    for its current file — "đã đăng bản cũ" does not count; no Short left counts). Otherwise ``todo`` when the
    episode has rendered Shorts or work is pending (a job queued/running or the pipeline not finished: some
    stage not ``done``, incl. failed / interrupted), else None (only under "Tất cả")."""
    job = item.get("job") or {}
    active = job.get("status") in ("queued", "running")
    if item.get("complete") and not active:
        return ALL_PUBLISHED
    if item.get("shorts"):
        return TODO
    finished = item.get("stages_done") == item.get("stages_total") and not item.get("failed") \
        and not item.get("running")
    return TODO if active or not finished else None
