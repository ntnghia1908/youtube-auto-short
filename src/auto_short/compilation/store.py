"""CP8.33 G4, G9: files under ``<output_dir>/_compilations/<playlist_id>/``: ``<cid>.mp4`` + ``<cid>.json`` (one per
compilation) and ``favorites.json`` (the khai thị hearted in that bộ kinh). All writes are atomic. The namespace
belongs to no episode workspace (a leading ``_`` can never be an episode id, CP2 D3), so deleting an episode or
cleaning a source never touches it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..workspace import atomic_write_json
from .spec import CID_RE, CompilationError, Item, item_from_json

SCHEMA_VERSION = 1
NAMESPACE = "_compilations"
FAVORITES_NAME = "favorites.json"
KEPT_DIR = "kept"  # G11: <folder>/kept/<episode_id>/<clip>.mp4
QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def directory(output_dir: Path | str, playlist_id: str) -> Path:
    return Path(output_dir) / NAMESPACE / playlist_id


def video_path(folder: Path, cid: str) -> Path:
    return folder / f"{cid}.mp4"


def doc_path(folder: Path, cid: str) -> Path:
    return folder / f"{cid}.json"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_doc(folder: Path, cid: str) -> dict | None:
    if not CID_RE.match(cid):
        return None
    doc = _read(doc_path(folder, cid))
    return doc if doc is not None and doc.get("cid") == cid else None


def write_doc(folder: Path, doc: dict) -> None:
    atomic_write_json(doc_path(folder, doc["cid"]), doc)


def new_doc(playlist_id: str, cid: str, mode: str, items: tuple[Item, ...], repeat: int, *, download_name: str,
            title: str | None, duration_estimate: float | None) -> dict:
    return {"schema_version": SCHEMA_VERSION, "playlist_id": playlist_id, "cid": cid, "mode": mode,
            "items": [i.to_json() for i in items], "repeat": repeat, "duration": None,
            "duration_estimate": duration_estimate, "chapters": [], "title": title, "download_name": download_name,
            "size": None, "reencoded": None, "created_at": now(), "finished_at": None, "status": QUEUED,
            "error": None}


def list_docs(folder: Path) -> list[dict]:
    """Stored compilations, newest first."""
    out = []
    if folder.is_dir():
        for p in folder.glob("*.json"):
            if CID_RE.match(p.stem) and (doc := read_doc(folder, p.stem)) is not None:
                out.append(doc)
    out.sort(key=lambda d: (d.get("created_at") or "", d["cid"]), reverse=True)
    return out


def delete(folder: Path, cid: str) -> bool:
    """G6 DELETE: remove ``<cid>.mp4`` and ``<cid>.json``; False when neither exists."""
    if not CID_RE.match(cid):
        return False
    found = False
    for path in (video_path(folder, cid), doc_path(folder, cid)):
        if path.exists():
            path.unlink()
            found = True
    return found


def read_favorites(folder: Path) -> list[Item]:
    path = folder / FAVORITES_NAME
    if not path.is_file():
        return []
    data = _read(path)
    if data is None or not isinstance(data.get("items"), list):
        raise CompilationError(f"{FAVORITES_NAME} không đọc được")
    out: list[Item] = []
    for raw in data["items"]:
        item = item_from_json(raw)
        if item not in out:
            out.append(item)
    return out


def write_favorites(folder: Path, items: list[Item]) -> None:
    atomic_write_json(folder / FAVORITES_NAME, {"schema_version": SCHEMA_VERSION, "items": [i.favorite_json() for i in items]})


def kept_path(folder: Path, item: Item) -> Path | None:
    """Absolute path of the kept file of a favourite (G11), only when it lies inside ``<folder>/kept/``."""
    if item.kept is None:
        return None
    base = (folder / KEPT_DIR).resolve()
    path = (folder / item.kept["path"]).resolve()
    return path if path.parent.parent == base else None


def remove_kept(folder: Path, item: Item) -> None:
    """Delete the kept file of ``item`` (un-hearting it) and the then-empty folders."""
    path = kept_path(folder, item)
    if path is None:
        return
    path.unlink(missing_ok=True)
    for d in (path.parent, folder / KEPT_DIR):
        try:
            d.rmdir()
        except OSError:
            break
