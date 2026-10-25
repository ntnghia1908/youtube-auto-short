"""Clean up the source video of an episode, keeping its Shorts (CP8.6 S3): the episode becomes *archived*.

``archive_source`` deletes ``work/<id>/source.*`` (only a YouTube download inside the workspace; a local source
is never touched) and writes the flag ``work/<id>/archive.json``. An archived episode can still be listed,
played, downloaded, ticked "Đã đăng" and have Shorts deleted (:func:`reject_archived_clip`, no render), but
nothing that needs the source runs again: title edit, restoring a deleted Short, resubmitting the URL, ingest,
render (they raise :class:`ArchivedError` / refuse). CP8.37 permits restoring only the exact ingest bytes,
without rerunning any pipeline stage.
Canonical contract: docs/decisions/CP8.3-web-contract.md W9.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..hashing import sha256_file
from ..khaithi import SUFFIX
from ..workspace import DONE, Workspace, WorkspaceError, atomic_write_json, utc_now, validate_episode_id
from .logic import ReviewError

log = logging.getLogger("auto_short")

ARCHIVE_NAME = "archive.json"
SCHEMA_VERSION = 1
RENDER_MANIFEST = "render_manifest.json"
ARCHIVED_MESSAGE = "đã dọn video nguồn; bấm Khôi phục nguồn để sửa"
RESTORED_NAME = "restored.json"
MISMATCH_MESSAGE = "video tải lại khác bản gốc; không khôi phục được (xóa tập rồi chạy lại)"


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
    doc = {"schema_version": SCHEMA_VERSION, "episode_id": ws.episode_id, "archived_at": now or utc_now(),
           "removed": [{"path": p.name, "size": size} for p, size in sizes]}
    if config.store.backup_source:
        from ..store.backup import backup_state
        from ..store.client import StoreError

        try:
            if not files:
                raise ReviewError("không còn file nguồn để đối chiếu")
            for path, size in sizes:
                state = backup_state(config, episode_id, path=path)
                if not state["backed_up"] or state["size"] != size:
                    raise ReviewError(f"{path.name}: sha256 / kích thước không khớp")
            doc["backup"] = {"store": "source", "sha256": state["sha256"]}
        except (StoreError, OSError, ReviewError) as exc:
            raise ReviewError(f"chưa sao lưu lên 3090: {exc}") from exc
    if auto:
        doc["auto"] = True
    atomic_write_json(archive_path(ws.dir), doc)
    for p, _ in sizes:
        p.unlink()
    freed = sum(size for _, size in sizes)
    log.info("review: archived %s: removed %s (%d bytes)", ws.episode_id, ", ".join(p.name for p in files) or "-",
             freed)
    return ArchiveResult(ws.episode_id, True, freed, [p.name for p in files])


@dataclass(frozen=True)
class RestoreResult:
    episodes: list[str]
    downloaded: bool


def restore_parts(episode_id: str, config: Config) -> list[tuple[Workspace, dict]]:
    """Validate every archived part before fetching anything. No writes; also used by the HTTP route."""
    try:
        eid = validate_episode_id(episode_id)
        root = Path(config.workspace.dir)
        if not is_archived(root / eid):
            raise ReviewError(f"tập {eid} chưa dọn video nguồn")
        owner = eid[:-len(SUFFIX)] if eid.endswith(SUFFIX) else eid
        parts = []
        for part in (owner, owner + SUFFIX):
            ws = Workspace(root, part)
            if not is_archived(ws.dir):
                continue
            manifest = ws.load_manifest()
            source = (manifest or {}).get("source") or {}
            if not isinstance(source, dict):
                raise ReviewError("manifest không có thông tin nguồn hợp lệ")
            name, sha, size, uri = (source.get(k) for k in ("path", "sha256", "size", "uri"))
            if source.get("kind") != "youtube":
                raise ReviewError("nguồn là file local: không khôi phục video nguồn")
            if not isinstance(name, str) or not re.fullmatch(r"source\.[A-Za-z0-9]+", name) \
                    or ws.dir.is_symlink() or (ws.dir / name).is_symlink() \
                    or not ws.dir.resolve().is_relative_to(root.resolve()):
                raise ReviewError("manifest không có đường dẫn video nguồn an toàn trong workspace")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) \
                    or not isinstance(size, int) or isinstance(size, bool) or size <= 0 \
                    or not isinstance(uri, str) or not uri:
                raise ReviewError("manifest thiếu URL / sha256 / kích thước nguồn để khôi phục")
            parts.append((ws, source))
        return parts
    except WorkspaceError as exc:
        raise ReviewError(str(exc)) from exc


def restore_source(episode_id: str, config: Config, *, downloader=None,
                   lock=None, now: str | None = None, clock=None) -> RestoreResult:
    """CP8.37: verify all parts against ingest, then install sources and clear archive flags under ``lock``.

    A cache hit uses hard links; downloads live only in a private temporary workspace directory until verified.
    A mismatch changes no persistent file. ``YoutubeBlocked`` propagates for the prepare lane to wait/retry.
    The caller reserves the video in the runner while fetching; ``lock`` is the app's submit/sweep lock.
    """
    # Lazy imports: ingest / render also import archive guards during package initialization.
    from ..ingest.youtube import DownloadError, YoutubeBlocked, ytdlp_download
    from ..theme_render.sources import cached_source

    downloader = downloader or ytdlp_download
    parts = restore_parts(episode_id, config)
    cached = cached_source(config, episode_id)
    with tempfile.TemporaryDirectory(prefix=".restore-source-", dir=parts[0][0].dir) as tmpname:
        tmp = Path(tmpname)
        verified = {}
        downloaded = False
        for ws, source in parts:
            key = (source["sha256"], source["size"])
            if key in verified:
                continue
            path = cached
            if config.store.enabled:
                from ..store.client import StoreClient, StoreError
                from ..theme_render.sources import workspace_source

                path = workspace_source(config, episode_id) or cached
                if path is not None and (path.stat().st_size != source["size"]
                                         or sha256_file(path) != source["sha256"]):
                    path = None
                if path is None:
                    remote = tmp / f"store-{len(verified)}.mp4"
                    try:
                        StoreClient.from_config(config.store).fetch(
                            ws.episode_id.removesuffix(SUFFIX), "source", remote, source["sha256"])
                        if remote.stat().st_size == source["size"] and sha256_file(remote) == source["sha256"]:
                            path = remote
                            downloaded = True
                    except (StoreError, OSError):
                        pass  # 3090 unavailable / wrong bytes: retain the existing YouTube fallback.
            if path is None:
                dest = tmp / str(len(verified))
                dest.mkdir()
                try:
                    path = Path(downloader(source["uri"], dest, config.ingest).path)
                except YoutubeBlocked:
                    raise
                except DownloadError as exc:
                    raise ReviewError(f"tải lại video nguồn lỗi: {exc}") from exc
                if not path.resolve().is_relative_to(dest.resolve()) or not path.is_file():
                    raise ReviewError("downloader không trả file trong thư mục tải tạm")
                downloaded = True
            if path.stat().st_size != source["size"] or sha256_file(path) != source["sha256"]:
                raise ReviewError(MISMATCH_MESSAGE)
            verified[key] = path

        with lock if lock is not None else nullcontext():
            if restore_parts(episode_id, config) != parts:
                raise ReviewError("trạng thái tập đã đổi trong lúc khôi phục; thử lại")
            # Prepare every link first. If installation fails, keep the archive guards and roll back files.
            originals = {}
            installed = []
            try:
                staged = []
                for i, (ws, source) in enumerate(parts):
                    final = ws.dir / source["path"]
                    link = tmp / f"install-{i}"
                    os.link(verified[(source["sha256"], source["size"])], link)
                    staged.append((link, final))
                    for path in (final, ws.dir / RESTORED_NAME, archive_path(ws.dir)):
                        backup = tmp / f"backup-{len(originals)}"
                        if path.exists():
                            os.link(path, backup)
                            originals[path] = backup
                        else:
                            originals[path] = None
                stamp = now or (datetime.fromtimestamp(clock(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                                if clock is not None else utc_now())
                for link, final in staged:
                    link.replace(final)
                    installed.append(final)
                for ws, _ in parts:
                    marker = ws.dir / RESTORED_NAME
                    installed.append(marker)
                    atomic_write_json(marker, {"restored_at": stamp})
                for ws, _ in parts:
                    flag = archive_path(ws.dir)
                    installed.append(flag)
                    flag.unlink()
            except BaseException:
                for path in reversed(installed):
                    backup = originals[path]
                    if backup is None:
                        path.unlink(missing_ok=True)
                    else:
                        backup.replace(path)
                raise
    episodes = [ws.episode_id for ws, _ in parts]
    log.info("review: restored source %s (%s)", ", ".join(episodes), "download" if downloaded else "cache")
    return RestoreResult(episodes, downloaded)


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
