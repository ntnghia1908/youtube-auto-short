"""Episode workspace, manifest (schema v1) and stage skip/stale framework.

Canonical convention: docs/decisions/CP2-workspace-contract.md.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .hashing import FileFingerprint

log = logging.getLogger("auto_short")

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"

# Pipeline order from docs/decisions/CP1-product-contract.md §8.
STAGES = ("ingest", "transcript", "analysis", "selection", "titling", "review", "render")

PENDING, RUNNING, DONE, FAILED, STALE = "pending", "running", "done", "failed", "stale"

_EPISODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class WorkspaceError(Exception):
    """Invalid workspace, episode id or manifest."""


class StageError(Exception):
    """A stage failed; the manifest already records status ``failed``."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_episode_id(episode_id: str) -> str:
    if not _EPISODE_ID_RE.match(episode_id):
        raise WorkspaceError(
            f"invalid episode id {episode_id!r}: use letters, digits, '.', '_' or '-' "
            "(must start with a letter or digit, max 128 chars)"
        )
    return episode_id


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory, then ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        # mkstemp creates 0600; use normal umask-based permissions like open() would.
        umask = os.umask(0)
        os.umask(umask)
        os.fchmod(fd, 0o666 & ~umask)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, obj: object) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    atomic_write_bytes(path, text.encode("utf-8"))


@dataclass(frozen=True)
class Workspace:
    root: Path  # workspace root, e.g. ./work
    episode_id: str

    @property
    def dir(self) -> Path:
        return self.root / self.episode_id

    @property
    def manifest_path(self) -> Path:
        return self.dir / MANIFEST_NAME

    def resolve(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        return p if p.is_absolute() else self.dir / p

    def relpath(self, path: Path) -> str:
        """Paths inside the episode dir are stored relative; others absolute."""
        path = path.resolve()
        try:
            return path.relative_to(self.dir.resolve()).as_posix()
        except ValueError:
            return str(path)

    def load_manifest(self) -> dict | None:
        if not self.manifest_path.is_file():
            return None
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError(f"cannot read {self.manifest_path}: {exc}") from exc
        if data.get("schema_version") != SCHEMA_VERSION:
            raise WorkspaceError(
                f"{self.manifest_path}: unsupported schema_version {data.get('schema_version')!r}"
            )
        return data

    def save_manifest(self, manifest: dict) -> None:
        atomic_write_json(self.manifest_path, manifest)

    def new_manifest(self, source: dict) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "episode_id": self.episode_id,
            "source": source,
            "stages": {},
        }

    def source_fingerprint(self, manifest: dict | None) -> list[FileFingerprint]:
        """The manifest's source entry as a hash-cache candidate (empty if incomplete)."""
        src = (manifest or {}).get("source") or {}
        if not all(src.get(k) is not None for k in ("path", "size", "mtime_ns", "sha256")):
            return []
        return [FileFingerprint(self.resolve(src["path"]).resolve(), src["size"], src["mtime_ns"], src["sha256"])]


def iter_manifests(root: Path):
    """Yield (Workspace, manifest) for every readable manifest under ``root``."""
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if not (child / MANIFEST_NAME).is_file() or not _EPISODE_ID_RE.match(child.name):
            continue
        ws = Workspace(root, child.name)
        try:
            manifest = ws.load_manifest()
        except WorkspaceError:
            continue
        if manifest is not None:
            yield ws, manifest


def mark_downstream_stale(manifest: dict, stage: str) -> list[str]:
    """Mark every recorded stage after ``stage`` (CP1 §8 order) as stale."""
    marked = []
    for name in STAGES[STAGES.index(stage) + 1:]:
        entry = manifest["stages"].get(name)
        if entry and entry.get("status") != PENDING and entry.get("status") != STALE:
            entry["status"] = STALE
            marked.append(name)
    return marked


def check_up_to_date(ws: Workspace, manifest: dict, stage: str, inputs: list[dict], cfg_hash: str) -> str | None:
    """Return None when ``stage`` can be skipped, otherwise the reason it must run."""
    entry = manifest["stages"].get(stage)
    if not entry:
        return "not run yet"
    if entry.get("status") != DONE:
        return f"previous status is {entry.get('status')}"
    if entry.get("config_hash") != cfg_hash:
        return "config changed"
    if entry.get("inputs") != inputs:
        return "input changed"
    missing = [a for a in entry.get("artifacts", []) if not ws.resolve(a).exists()]
    if missing:
        return f"artifact missing: {', '.join(missing)}"
    return None


def _remove_artifacts(ws: Workspace, artifacts: list[str]) -> None:
    for rel in artifacts:
        p = ws.resolve(rel)
        # Only ever delete files inside the episode workspace (never a referenced source).
        if p.is_file() and ws.relpath(p) == rel and not Path(rel).is_absolute():
            p.unlink()


def record_failure(ws: Workspace, manifest: dict, stage: str, error: str, *, started_at: str | None = None) -> None:
    entry = manifest["stages"].get(stage) or {}
    _remove_artifacts(ws, entry.get("artifacts", []))
    manifest["stages"][stage] = {
        "status": FAILED,
        "artifacts": [],
        "inputs": entry.get("inputs", []),
        "config_hash": entry.get("config_hash"),
        "started_at": started_at or utc_now(),
        "finished_at": utc_now(),
        "error": error,
    }
    ws.save_manifest(manifest)


def run_stage(
    ws: Workspace,
    manifest: dict,
    stage: str,
    *,
    inputs: list[dict],
    cfg_hash: str,
    force: bool,
    action: Callable[[], list[str]],
) -> bool:
    """Run ``action`` unless the stage is up to date. Returns True if it ran.

    ``action`` returns the artifact paths (relative to the episode dir) it produced.
    On failure the stage is recorded as ``failed`` with ``error``, its artifacts are
    removed and :class:`StageError` is raised.
    """
    reason = "--force" if force else check_up_to_date(ws, manifest, stage, inputs, cfg_hash)
    if reason is None:
        log.info("%s: skip (up to date) [%s]", stage, ws.episode_id)
        return False

    log.info("%s: run (%s) [%s]", stage, reason, ws.episode_id)
    previous = manifest["stages"].get(stage) or {}
    started = utc_now()
    manifest["stages"][stage] = {
        "status": RUNNING,
        "artifacts": previous.get("artifacts", []),
        "inputs": inputs,
        "config_hash": cfg_hash,
        "started_at": started,
        "finished_at": None,
        "error": None,
    }
    stale = mark_downstream_stale(manifest, stage)
    if stale:
        log.info("%s: marked downstream stale: %s", stage, ", ".join(stale))
    ws.save_manifest(manifest)

    try:
        artifacts = action()
    except Exception as exc:
        record_failure(ws, manifest, stage, str(exc), started_at=started)
        raise StageError(f"{stage} failed: {exc}") from exc
    except KeyboardInterrupt:
        record_failure(ws, manifest, stage, "interrupted", started_at=started)
        raise

    entry = manifest["stages"][stage]
    entry.update(status=DONE, artifacts=artifacts, finished_at=utc_now(), error=None)
    ws.save_manifest(manifest)
    log.info("%s: done [%s]", stage, ws.episode_id)
    return True
