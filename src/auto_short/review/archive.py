"""Clean up the source video of an episode, keeping its Shorts (CP8.6 S3): the episode becomes *archived*.

``archive_source`` deletes ``work/<id>/source.*`` (only a YouTube download inside the workspace; a local source
is never touched) and writes the flag ``work/<id>/archive.json``. An archived episode can still be listed,
played, downloaded, ticked "Đã đăng" and have Shorts deleted (:func:`reject_archived_clip`, no render), but
nothing that needs the source runs again: title edit, restoring a deleted Short, resubmitting the URL, ingest,
render (they raise :class:`ArchivedError` / refuse) — re-downloading may give other bytes, so the whole pipeline
would re-run and the AI could choose other clips / titles (CP5/CP6 are not deterministic).
Canonical contract: docs/decisions/CP8.3-web-contract.md W9.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..workspace import DONE, Workspace, WorkspaceError, atomic_write_json, validate_episode_id
from .logic import ReviewError

log = logging.getLogger("auto_short")

ARCHIVE_NAME = "archive.json"
SCHEMA_VERSION = 1
RENDER_MANIFEST = "render_manifest.json"
ARCHIVED_MESSAGE = "đã dọn video nguồn; muốn sửa thì xóa tập rồi chạy lại"


class ArchivedError(ReviewError):
    """The episode's source video was cleaned up: the action needs it (web: 409)."""

    def __init__(self, episode_id: str):
        super().__init__(f"tập {episode_id}: {ARCHIVED_MESSAGE}")


@dataclass(frozen=True)
class ArchiveResult:
    episode_id: str
    changed: bool  # False: already archived
    freed: int  # bytes of the removed source files
    removed: list[str]  # file names (relative to work/<id>/)


def archive_path(ws_dir: Path) -> Path:
    return ws_dir / ARCHIVE_NAME


def read_archive(ws_dir: Path) -> dict | None:
    """The archive flag of a workspace dir, or None (not archived). An unreadable file still counts as archived
    (fail closed: never re-run the pipeline on a half-cleaned episode)."""
    path = archive_path(ws_dir)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema_version": SCHEMA_VERSION, "episode_id": ws_dir.name, "archived_at": None, "removed": []}
    return doc if isinstance(doc, dict) else {"schema_version": SCHEMA_VERSION, "episode_id": ws_dir.name,
                                              "archived_at": None, "removed": []}


def is_archived(ws_dir: Path) -> bool:
    return archive_path(ws_dir).exists()


def check_not_archived(ws_dir: Path, episode_id: str) -> None:
    if is_archived(ws_dir):
        raise ArchivedError(episode_id)


def source_files(ws_dir: Path) -> list[Path]:
    """``source.*`` directly inside the workspace dir (regular files or symlinks; never followed)."""
    if not ws_dir.is_dir():
        return []
    return sorted(p for p in ws_dir.iterdir() if p.name.startswith("source.") and (p.is_symlink() or p.is_file()))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def archive_source(episode_id: str, config: Config, *, now: str | None = None, auto: bool = False) -> ArchiveResult:
    """S3: delete the downloaded source video of a YouTube episode whose render is ``done`` and mark the episode
    archived. Local sources, unfinished renders -> ReviewError (nothing deleted). Already archived -> no-op.
    ``auto=True`` (server auto clean-up, W9 S5) adds ``"auto": true`` to ``archive.json``."""
    try:
        ws = Workspace(Path(config.workspace.dir), validate_episode_id(episode_id))
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise ReviewError(str(exc)) from exc
    if manifest is None:
        raise ReviewError(f"không có tập {episode_id!r}")
    if is_archived(ws.dir):
        return ArchiveResult(ws.episode_id, False, 0, [])
    if (manifest.get("source") or {}).get("kind") != "youtube":
        raise ReviewError("nguồn là file local (ngoài workspace): không dọn video nguồn")
    render = (manifest.get("stages") or {}).get("render") or {}
    if render.get("status") != DONE:
        raise ReviewError(f"tập chưa dựng Short xong (render: {render.get('status', 'pending')}); "
                          "không dọn video nguồn")
    files = source_files(ws.dir)
    sizes = [(p, p.lstat().st_size) for p in files]
    doc = {"schema_version": SCHEMA_VERSION, "episode_id": ws.episode_id, "archived_at": now or _now(),
           "removed": [{"path": p.name, "size": size} for p, size in sizes]}
    if auto:
        doc["auto"] = True
    atomic_write_json(archive_path(ws.dir), doc)
    for p, _ in sizes:
        p.unlink()
    freed = sum(size for _, size in sizes)
    log.info("review: archived %s: removed %s (%d bytes)", ws.episode_id, ", ".join(p.name for p in files) or "-",
             freed)
    return ArchiveResult(ws.episode_id, True, freed, [p.name for p in files])


def reject_archived_clip(episode_id: str, config: Config, clip_id: str) -> bool:
    """CP8.5 X2 on an archived episode (no render possible): record the deletion in ``review.json``, then apply it
    to the last render directly — the Short's entry becomes ``skipped`` / ``rejected`` (CP7 R2, R11), stats are
    updated, its mp4 is removed. Returns False when it was already deleted."""
    from .titles import reject_clip

    ws = Workspace(Path(config.workspace.dir), validate_episode_id(episode_id))
    if not is_archived(ws.dir):
        raise ReviewError(f"tập {episode_id} chưa dọn video nguồn")
    changed = reject_clip(episode_id, config, clip_id)
    out_dir = Path(config.render.output_dir) / ws.episode_id
    rm_path = out_dir / RENDER_MANIFEST
    try:
        doc = json.loads(rm_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError(f"cannot read {rm_path}: {exc}") from exc
    entry = next((s for s in doc.get("shorts", []) if s.get("clip_id") == clip_id), None)
    if entry is None or entry.get("status") != "rendered":
        return changed
    rel = entry.get("file")
    entry.update(status="skipped", skip_reason="rejected", file=None, sha256=None, title_display_lines=None,
                 title_font_size=None, layout=None, dissolves=None, render_key=None)
    rendered = [s for s in doc["shorts"] if s.get("status") == "rendered"]
    doc["stats"] = {**doc.get("stats", {}), "rendered": len(rendered),
                    "skipped": len(doc["shorts"]) - len(rendered),
                    "seconds": round(sum(s["duration"] for s in rendered), 3)}
    atomic_write_json(rm_path, doc)
    if isinstance(rel, str):
        path = (out_dir / rel)
        shorts_dir = (out_dir / "shorts").resolve()
        if path.resolve().parent == shorts_dir and (path.is_file() or path.is_symlink()):
            path.unlink()
        manifest = ws.load_manifest() or {}
        artifacts = ((manifest.get("stages") or {}).get("render") or {}).get("artifacts")
        if isinstance(artifacts, list) and str(out_dir.resolve() / rel) in artifacts:
            artifacts.remove(str(out_dir.resolve() / rel))
            ws.save_manifest(manifest)
    log.info("review: archived %s: Short %s deleted without render", ws.episode_id, clip_id)
    return True
