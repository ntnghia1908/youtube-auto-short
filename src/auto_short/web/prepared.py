"""CP13.2 H1: marker of an episode that went through the "Chuẩn bị + HD" job (``prepare`` lane only) and waits for
"Chạy tiếp" (AI → render). Light state file ``prepared.json`` in ``work/<id>/``; the playlist page shows the state
"Đã chuẩn bị — chờ cắt" while the file exists and the ``selection`` stage has not run (so it never reads as an error).
Removed when the ``ai`` lane of a normal job starts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..workspace import atomic_write_json

PREPARED_NAME = "prepared.json"


def path_of(config: Config, episode_id: str) -> Path:
    return Path(config.workspace.dir) / episode_id / PREPARED_NAME


def is_prepared(ws_dir: Path) -> bool:
    return (Path(ws_dir) / PREPARED_NAME).is_file()


def mark(config: Config, episode_id: str) -> None:
    atomic_write_json(path_of(config, episode_id), {
        "schema_version": 1, "episode_id": episode_id,
        "prepared_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})


def clear(config: Config, episode_id: str) -> None:
    path_of(config, episode_id).unlink(missing_ok=True)
