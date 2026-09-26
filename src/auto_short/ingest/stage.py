"""Ingest stage: register a source in ``work/<episode_id>/`` and write ``metadata.json``."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import hashing
from ..config import Config
from ..workspace import (
    StageError,
    Workspace,
    WorkspaceError,
    atomic_write_json,
    iter_manifests,
    record_failure,
    run_stage,
    validate_episode_id,
)
from . import probe as probe_mod
from .source import LOCAL, YOUTUBE, SourceError, SourceSpec, classify, local_episode_id, youtube_video_id
from .youtube import Downloader, youtube_info, ytdlp_download

log = logging.getLogger("auto_short")

STAGE = "ingest"
METADATA_NAME = "metadata.json"
METADATA_SCHEMA_VERSION = 1
_TMP_DIR = ".ingest-tmp"


class IngestError(Exception):
    """Ingest could not run; message is user-facing."""


@dataclass(frozen=True)
class IngestResult:
    episode_id: str
    workspace: Path
    ran: bool  # False when skipped as up to date


def _used_config(spec: SourceSpec, config: Config) -> dict:
    """Config keys the ingest stage uses for this source kind (D7)."""
    if spec.kind == YOUTUBE:
        return {"ingest.youtube_format": config.ingest.youtube_format}
    return {}


def _source_entry(ws: Workspace, spec: SourceSpec, fp: hashing.FileFingerprint | None) -> dict:
    return {
        "kind": spec.kind,
        "uri": spec.uri,
        "path": ws.relpath(fp.path) if fp else None,
        "sha256": fp.sha256 if fp else None,
        "size": fp.size if fp else None,
        "mtime_ns": fp.mtime_ns if fp else None,
    }


def _metadata(ws: Workspace, source: dict, media: dict, yt: dict | None) -> dict:
    meta = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "episode_id": ws.episode_id,
        "source": {k: source[k] for k in ("kind", "uri", "path", "sha256", "size")},
        **media,
    }
    if yt is not None:
        meta["title"] = yt.get("title")
        meta["channel"] = yt.get("channel")
        meta["youtube"] = yt
    return meta


def _cached_fingerprints(root: Path) -> list[hashing.FileFingerprint]:
    """Hash cache from every local-source manifest in the workspace root."""
    out = []
    for ws, manifest in iter_manifests(root):
        if (manifest.get("source") or {}).get("kind") == LOCAL:
            out.extend(ws.source_fingerprint(manifest))
    return out


def _check_same_source(ws: Workspace, manifest: dict, spec: SourceSpec) -> None:
    """Refuse to reuse a workspace for a different kind of source or another video.

    A local source may change path/content: that is an input change and reruns ingest.
    """
    stored = manifest.get("source") or {}
    same = stored.get("kind") == spec.kind
    if same and spec.kind == YOUTUBE:
        same = youtube_video_id(stored.get("uri") or "") == spec.youtube_id
    if not same:
        raise IngestError(
            f"workspace {ws.dir} already belongs to source {stored.get('uri')}; "
            "use another --episode-id"
        )


def _fingerprint_local(spec: SourceSpec, cache: list[hashing.FileFingerprint]) -> hashing.FileFingerprint:
    path = spec.path
    if not path.exists():
        raise IngestError(f"source file not found: {path}")
    if not path.is_file():
        raise IngestError(f"source is not a regular file: {path}")
    try:
        return hashing.fingerprint(path, cache)
    except OSError as exc:
        raise IngestError(f"cannot read source file {path}: {exc}") from exc


def run_ingest(
    target: str,
    config: Config,
    *,
    episode_id: str | None = None,
    force: bool = False,
    downloader: Downloader = ytdlp_download,
) -> IngestResult:
    try:
        spec = classify(target)
    except SourceError as exc:
        raise IngestError(str(exc)) from exc
    root = config.workspace.dir

    fp = None
    if spec.kind == LOCAL and episode_id is None:
        # The id depends on the content hash; look up the cache across workspaces first.
        fp = _fingerprint_local(spec, _cached_fingerprints(root))
        episode_id = local_episode_id(spec.path, fp.sha256)
    elif spec.kind == YOUTUBE and episode_id is None:
        episode_id = spec.youtube_id
    try:
        ws = Workspace(root, validate_episode_id(episode_id))
    except WorkspaceError as exc:
        raise IngestError(str(exc)) from exc

    try:
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise IngestError(str(exc)) from exc
    if manifest is not None:
        _check_same_source(ws, manifest, spec)
    else:
        manifest = ws.new_manifest(_source_entry(ws, spec, None))

    if spec.kind == LOCAL:
        if fp is None:
            try:
                fp = _fingerprint_local(spec, ws.source_fingerprint(manifest))
            except IngestError as exc:
                record_failure(ws, manifest, STAGE, str(exc))
                raise
        inputs = [{"path": str(fp.path), "sha256": fp.sha256}]
    else:
        inputs = []  # the URL is bound by episode id + source.uri; the download is an artifact

    cfg_hash = hashing.config_hash(_used_config(spec, config))

    def action() -> list[str]:
        if spec.kind == LOCAL:
            return _ingest_local(ws, manifest, spec, fp)
        return _ingest_youtube(ws, manifest, spec, config, downloader)

    try:
        ran = run_stage(ws, manifest, STAGE, inputs=inputs, cfg_hash=cfg_hash, force=force, action=action)
    except StageError as exc:
        raise IngestError(str(exc)) from exc
    if not ran and spec.kind == LOCAL and manifest["source"] != _source_entry(ws, spec, fp):
        # Same content but new mtime/path: refresh the hash cache so the next run skips hashing.
        manifest["source"] = _source_entry(ws, spec, fp)
        ws.save_manifest(manifest)
    return IngestResult(ws.episode_id, ws.dir, ran)


def _ingest_local(ws: Workspace, manifest: dict, spec: SourceSpec, fp: hashing.FileFingerprint) -> list[str]:
    media = probe_mod.probe(fp.path)
    source = _source_entry(ws, spec, fp)
    atomic_write_json(ws.dir / METADATA_NAME, _metadata(ws, source, media, None))
    manifest["source"] = source
    return [METADATA_NAME]


def _ingest_youtube(ws: Workspace, manifest: dict, spec: SourceSpec, config: Config,
                    downloader: Downloader) -> list[str]:
    tmp = ws.dir / _TMP_DIR
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        log.info("ingest: downloading %s", spec.uri)
        result = downloader(spec.uri, tmp, config.ingest)
        media = probe_mod.probe(result.path)
        # Replace any previous source.* only after the new download probed fine.
        for old in ws.dir.glob("source.*"):
            old.unlink()
        final = ws.dir / f"source{result.path.suffix}"
        result.path.replace(final)
        fp = hashing.fingerprint(final)
        source = _source_entry(ws, spec, fp)
        yt = youtube_info(result.info)
        atomic_write_json(ws.dir / METADATA_NAME, _metadata(ws, source, media, yt))
        manifest["source"] = source
        return [final.name, METADATA_NAME]
    except BaseException:
        for f in ws.dir.glob("source.*"):
            f.unlink()
        (ws.dir / METADATA_NAME).unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
