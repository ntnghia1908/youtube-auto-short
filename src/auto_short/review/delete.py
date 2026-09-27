"""Delete a whole episode (CP8.5 X3, cannot be undone): ``<workspace.dir>/<id>/`` and ``<render.output_dir>/<id>/``.

Paths come from the config + a validated episode id only, and each must resolve to a direct child of its root
before ``rmtree``. A local source outside the workspace (CP2 D4) is never deleted: only these two directories are
removed, and ``rmtree`` does not follow symlinks. The caller makes sure no job of the episode is queued/running.
Canonical contract: docs/decisions/CP8.3-web-contract.md § Xóa tập.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Config
from ..workspace import WorkspaceError, validate_episode_id
from .logic import ReviewError

log = logging.getLogger("auto_short")


class EpisodeNotFound(ReviewError):
    """Neither the workspace nor the output directory of the episode exists."""


def episode_dirs(episode_id: str, config: Config) -> list[Path]:
    """Existing directories of the episode (workspace, output), each checked to be exactly ``<root>/<id>`` (no
    symlink, no traversal). Raises EpisodeNotFound / ReviewError."""
    try:
        validate_episode_id(episode_id)
    except WorkspaceError as exc:
        raise EpisodeNotFound(str(exc)) from exc
    found = []
    for root in (Path(config.workspace.dir), Path(config.render.output_dir)):
        path = root / episode_id
        if not path.exists() and not path.is_symlink():
            continue
        real_root = root.resolve()
        if path.is_symlink() or not path.is_dir() or path.resolve().parent != real_root \
                or path.resolve().name != episode_id:
            raise ReviewError(f"refusing to delete {path}: not a directory directly inside {real_root}")
        if all(path.resolve() != p.resolve() for p in found):  # workspace.dir == output_dir
            found.append(path)
    if not found:
        raise EpisodeNotFound(f"no episode {episode_id!r}")
    return found


def delete_episode(episode_id: str, config: Config) -> list[Path]:
    """Remove the episode's output then workspace directory (the episode leaves the list only once its manifest
    is gone); returns the removed paths."""
    dirs = episode_dirs(episode_id, config)
    for path in sorted(dirs, key=lambda p: p.parent.resolve() == Path(config.workspace.dir).resolve()):
        shutil.rmtree(path)
        log.info("review: deleted %s", path)
    return dirs
