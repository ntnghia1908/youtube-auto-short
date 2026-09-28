""""Tên bộ kinh" of a stored bộ kinh as the fallback header source (CP8.11 D5, D6).

Read-only, lock-free reader of ``<workspace.dir>/_playlists/*.json`` (written by ``auto_short.web.playlists``,
CP8.3 W10 L1) so the CLI sees the same source as the web. Core module: never imports ``auto_short.web``.

Canonical contract: docs/decisions/CP6-titling-contract.md G2.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

PLAYLISTS_DIR = "_playlists"
MAX_SERIES_CHARS = 100


def normalize_series(value: object) -> str:
    """User-set series name: NFC + collapsed whitespace, 1-100 characters; anything else -> ValueError."""
    if not isinstance(value, str):
        raise ValueError("tên bộ kinh phải là chuỗi")
    text = " ".join(unicodedata.normalize("NFC", value).split())
    if not text:
        raise ValueError("tên bộ kinh rỗng")
    if len(text) > MAX_SERIES_CHARS:
        raise ValueError(f"tên bộ kinh tối đa {MAX_SERIES_CHARS} ký tự ({len(text)})")
    return text


def stored_series(doc: dict) -> str | None:
    """The playlist's "Tên bộ kinh", or None (not set) when absent, not a string, empty or invalid."""
    try:
        return normalize_series(doc.get("series"))
    except ValueError:
        return None


def playlist_header(workspace_dir: str | Path, video_id: str | None) -> tuple[str, str] | None:
    """``(series, episode)`` from the first stored playlist (by playlist id = file name) that has a series name and
    an entry for ``video_id``: episode = the entry's ``episode``, else its ``index``. None when there is none."""
    if not video_id:
        return None
    root = Path(workspace_dir) / PLAYLISTS_DIR
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or doc.get("playlist_id") != path.stem or not isinstance(doc.get("entries"), list):
            continue
        series = stored_series(doc)
        if series is None:
            continue
        for entry in doc["entries"]:
            if not isinstance(entry, dict) or entry.get("video_id") != video_id:
                continue
            episode = entry.get("episode")
            if not (isinstance(episode, str) and episode.strip()):
                index = entry.get("index")
                episode = str(index) if isinstance(index, int) and not isinstance(index, bool) else None
            if episode is not None:
                return series, episode
    return None
