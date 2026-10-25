"""SRC1: sequential source backups, verified against the bytes available on the VM.

No YouTube downloads here. Missing originals remain pending for SRC2.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..enhance.state import owner_for
from ..hashing import sha256_file
from ..review.names import clean_part, truncate_utf8
from ..theme_render.sources import _owner, cached_source, favorite_videos, workspace_source
from ..titling.logic import match_title
from ..titling.playlist import stored_series
from ..workspace import iter_manifests, read_json_dict
from .client import StoreClient, StoreMismatch, StoreUnavailable


@dataclass
class _SourceMemo:
    signature: tuple
    local: dict
    confirmed: tuple[str, int] | None = None


_MEMO: dict[tuple[str, str, str], _SourceMemo] = {}
_MEMO_LOCK = threading.Lock()


def source_inventory(config: Config) -> list[str]:
    """Distinct YouTube owners, including archived videos and khai thị-only workspaces."""
    return sorted({_owner(ws.episode_id) for ws, manifest in iter_manifests(Path(config.workspace.dir))
                   if (manifest.get("source") or {}).get("kind") == "youtube"})


def _source(config: Config, video_id: str) -> dict:
    folder = Path(config.workspace.dir) / owner_for(config, video_id)
    return (read_json_dict(folder / "manifest.json") or {}).get("source") or {}


def _local_source(config: Config, video_id: str) -> tuple[Path, str, int] | None:
    """Reuse the digest already verified by the source validators; do not hash the selected file twice."""
    path = workspace_source(config, video_id)
    if path is not None:
        return path, _source(config, video_id)["sha256"], path.stat().st_size
    # workspace_source uses the Short workspace; a video may have only its khai thị left.
    folder = Path(config.workspace.dir) / owner_for(config, video_id)
    source = _source(config, video_id)
    name = source.get("path")
    if folder.name != video_id and isinstance(name, str) and re.fullmatch(r"source\.[A-Za-z0-9]+", name):
        path = folder / name
        if not folder.is_symlink() and not path.is_symlink() and path.is_file() \
                and sha256_file(path) == source.get("sha256"):
            return path, source["sha256"], path.stat().st_size
    path = cached_source(config, video_id)
    if path is not None:
        meta = read_json_dict(Path(config.workspace.dir) / "_theme_sources" / video_id / "meta.json") or {}
        return path, meta["sha256"], path.stat().st_size
    return None


def _signature(config: Config, video_id: str) -> tuple:
    """Stat every validation dependency, including missing candidates and cache provenance/duration."""
    root = Path(config.workspace.dir)
    folders = {root / video_id, root / owner_for(config, video_id)}
    paths = {folder / name for folder in folders for name in ("manifest.json", "metadata.json")}
    cache = root / "_theme_sources" / video_id
    paths.update((cache / "meta.json", cache / "source.mp4"))
    for folder in (*folders, cache):
        paths.update(folder.glob("source.*"))
    signature = []
    for path in sorted(paths):
        try:
            stat = path.stat()
            signature.append((str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size,
                              stat.st_mtime_ns, stat.st_ctime_ns))
        except FileNotFoundError:
            signature.append((str(path.absolute()), None))
    return tuple(signature)


def _memo(config: Config, video_id: str, source: dict) -> _SourceMemo:
    key = (str(Path(config.workspace.dir).resolve()), config.store.url, video_id)
    with _MEMO_LOCK:
        signature = _signature(config, video_id)
        previous = _MEMO.get(key)
        if previous is not None and previous.signature == signature:
            return previous
        local = _local_source(config, video_id)
        path, sha, size = local if local is not None else (None, source.get("sha256"), source.get("size"))
        entry = _SourceMemo(signature, {"path": path, "sha256": sha, "size": size},
                            previous.confirmed if previous is not None else None)
        # If a source/provenance file changed while hashing, the next call must validate it again.
        if _signature(config, video_id) == signature:
            _MEMO[key] = entry
        else:
            _MEMO.pop(key, None)
        return entry


def _matches(remote: dict, sha, size) -> bool:
    return bool(sha and isinstance(size, int) and not isinstance(size, bool) and size > 0
                and remote.get("sha256") == sha and remote.get("size") == size)


def backup_state(config: Config, video_id: str, *, client=None, path: Path | None = None) -> dict:
    """A scheduling snapshot accepts ingest or the current local copy; memoize unchanged validation/confirmation.

    ``path`` pins an archive deletion: always HEAD then hash that exact file afresh, without any memo.
    """
    if not config.store.enabled:
        raise StoreUnavailable("kho 3090 đang tắt")
    video_id = _owner(video_id)
    source = _source(config, video_id)
    if source.get("kind") != "youtube":
        raise StoreMismatch("nguồn không phải YouTube")
    client = client or StoreClient.from_config(config.store)
    if path is None:
        entry = _memo(config, video_id, source)
        state = {**entry.local, "backed_up": False}
        if entry.confirmed is not None:
            remote = dict(zip(("sha256", "size"), entry.confirmed))
            if _matches(remote, source.get("sha256"), source.get("size")):
                return {**state, "backed_up": True, "sha256": remote["sha256"], "size": remote["size"]}
            if _matches(remote, state["sha256"], state["size"]):
                return {**state, "backed_up": True}
    else:
        entry = None
    try:
        remote = client.head(video_id, "source")
    except StoreMismatch:
        remote = {}
    # Hash after the network wait so a source changed during HEAD cannot authorize deletion.
    if path is not None:
        local = Path(path)
        if local.is_symlink() or not local.is_file():
            raise StoreMismatch("không có file nguồn cục bộ hợp lệ")
        sha, size = sha256_file(local), local.stat().st_size
        return {"backed_up": _matches(remote, sha, size), "sha256": sha, "size": size, "path": local}
    if _matches(remote, source.get("sha256"), source.get("size")):
        state.update(backed_up=True, sha256=remote["sha256"], size=remote["size"])
    else:
        state["backed_up"] = _matches(remote, state["sha256"], state["size"])
    with _MEMO_LOCK:
        entry.confirmed = (remote["sha256"], remote["size"]) if state["backed_up"] else None
    return state


def _destination(config: Config, video_id: str) -> tuple[str, str]:
    # No backup.ps1 generator exists in web at this revision; reuse CP6 parsing and filename sanitizing.
    root = Path(config.workspace.dir)
    owner = root / owner_for(config, video_id)
    title = (read_json_dict(owner / "metadata.json") or {}).get("title")
    header = (read_json_dict(owner / "titles.json") or {}).get("header") or {}
    fields = (header.get("fields") or {}) if isinstance(header, dict) else {}
    fields = fields if isinstance(fields, dict) else {}
    match = match_title(config.titling.header.title_patterns, title)
    parsed = match.groupdict() if match is not None else {}
    number = fields.get("episode") or parsed.get("episode")
    label = fields.get("series") or parsed.get("series")
    series = "_khac"
    for path in sorted((root / "_playlists").glob("*.json")):
        doc = read_json_dict(path) or {}
        entries = doc.get("entries") or []
        if not isinstance(entries, list):
            continue
        entry = next((e for e in entries if isinstance(e, dict) and e.get("video_id") == video_id), None)
        if entry is not None and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", path.stem):
            series = path.stem
            label = stored_series(doc) or label or doc.get("title")
            match = match_title(config.titling.header.title_patterns, entry.get("title"))
            parsed = match.groupdict() if match is not None else {}
            number = number or entry.get("episode") or parsed.get("episode")
            break
    label = truncate_utf8(clean_part(label if isinstance(label, str) else None).replace("..", ""))
    number = clean_part(str(number or "")).replace("..", "")
    name = f"[Goc] {label} - Tập {number}.mp4" if label and number else f"[Goc] {video_id}.mp4"
    return series, name


def push_source(config: Config, video_id: str, *, client=None) -> dict:
    """Upload the intact ingest source, else the verified TC3 cache (which may have different bytes)."""
    if not config.store.enabled:
        raise StoreUnavailable("kho 3090 đang tắt")
    video_id = _owner(video_id)
    if _source(config, video_id).get("kind") != "youtube":
        raise StoreMismatch("nguồn không phải YouTube")
    client = client or StoreClient.from_config(config.store)
    state = backup_state(config, video_id, client=client)
    if state["path"] is None:
        raise StoreMismatch("không còn bản gốc / cache hợp lệ để sao lưu")
    if not state["backed_up"]:
        series, name = _destination(config, video_id)
        client.put(video_id, "source", series, name, state["path"], state["sha256"])
        remote = client.head(video_id, "source")
        if not _matches(remote, state["sha256"], state["size"]):
            raise StoreMismatch("kho chưa xác nhận đúng sha256 / kích thước sau khi gửi")
        state["backed_up"] = True
        key = (str(Path(config.workspace.dir).resolve()), config.store.url, video_id)
        with _MEMO_LOCK:
            entry = _MEMO.get(key)
            if entry is not None and _matches(entry.local, state["sha256"], state["size"]):
                entry.confirmed = (state["sha256"], state["size"])
    return state


def backup_order(config: Config, *, client=None, states: dict | None = None, now: float | None = None) -> list[str]:
    """Due/approaching auto archive, then favorites, then others. ``states`` receives the pass's HEAD results."""
    from ..web.storage import auto_archive_plan, episode_sizes

    if not config.store.enabled:
        raise StoreUnavailable("kho 3090 đang tắt")
    client = client or StoreClient.from_config(config.store)
    states = states if states is not None else {}
    rows = episode_sizes(config)
    # A zero grace selects eligible videos whose countdown has started, retaining all existing exclusions.
    due = auto_archive_plan(rows, time.time() if now is None else now, 0) if config.storage.auto_archive else []
    deadlines = {item["video_id"]: item["since"] for item in due}
    favorites = set(favorite_videos(config))
    pending = []
    for video_id in source_inventory(config):
        state = backup_state(config, video_id, client=client)
        states[video_id] = state
        if not state["backed_up"] and state["path"] is not None:
            pending.append(video_id)
    return sorted(pending, key=lambda vid: (0, deadlines[vid], vid) if vid in deadlines
                  else (1 if vid in favorites else 2, 0, vid))
