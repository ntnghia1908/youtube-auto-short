"""PKG2: deterministic episode thumbnails, offline and independent of web adapters."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from ..enhance import state as enhance_state
from ..hashing import config_hash, sha256_file
from ..render import full
from ..render.stage import RenderError
from ..render.text import TextError, nfc
from ..titling.logic import TitlingError, resolve_header
from ..titling.playlist import playlist_header
from ..workspace import atomic_write_json, is_episode_id, read_json_dict, utc_now
from . import PackageError, assets, thumbnail

FILE_NAME = re.compile(r"(landscape|vertical)-([a-f0-9]{64})\.jpg")


def _no_symlinks(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise PackageError("đường dẫn thumbnail không được là symlink")
    return path


def directory(config, video_id):
    if not isinstance(video_id, str) or not is_episode_id(video_id):
        raise PackageError("video id không hợp lệ")
    return _no_symlinks(Path(config.render.output_dir) / video_id / "thumbs")


def playlist(config, pid):
    if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,64}", pid):
        raise PackageError("playlist id không hợp lệ")
    path = _no_symlinks(Path(config.workspace.dir) / "_playlists" / f"{pid}.json")
    doc = read_json_dict(path)
    if doc is None or doc.get("playlist_id") != pid or not isinstance(doc.get("entries"), list):
        raise PackageError("không có danh sách tập hợp lệ")
    return doc


def read(config, video_id):
    path = _no_symlinks(directory(config, video_id) / "thumbs.json")
    if not path.exists():
        return None
    doc = read_json_dict(path)
    try:
        if doc is None or doc.get("schema_version") != 1 or doc["video_id"] != video_id \
                or not isinstance(doc["header"], dict) or not isinstance(doc["files"], dict) \
                or doc["override"] is not None and not assets.SHA.fullmatch(doc["override"]) \
                or doc["asset_id"] is not None and not assets.SHA.fullmatch(doc["asset_id"]) \
                or doc["skipped_reason"] is not None and not isinstance(doc["skipped_reason"], str):
            raise PackageError("hồ sơ thumbnail không hợp lệ")
        for shape, entry in doc["files"].items():
            match = FILE_NAME.fullmatch(entry["file"])
            if not match or shape != match[1] or entry["key"] != match[2] \
                    or not assets.SHA.fullmatch(entry["sha256"]):
                raise PackageError("file thumbnail không hợp lệ")
    except (KeyError, TypeError, AttributeError) as exc:
        raise PackageError("hồ sơ thumbnail không hợp lệ") from exc
    return doc


def _new(video_id):
    return dict(schema_version=1, video_id=video_id, header={}, asset_id=None, override=None,
                files={}, skipped_reason=None, updated_at=utc_now())


def header(config, video_id):
    directory(config, video_id)  # validate identity before reading workspace paths
    root = Path(config.workspace.dir)
    fields = None
    for ident in (video_id, video_id + ".kt"):
        path = _no_symlinks(root / ident / "titles.json")
        doc = read_json_dict(path)
        if doc and isinstance(doc.get("header"), dict) and isinstance(doc["header"].get("fields"), dict):
            fields = doc["header"]["fields"]
            break
    if fields is None:
        meta = read_json_dict(_no_symlinks(root / video_id / "metadata.json")) or {}
        fields = resolve_header(config.titling.header, meta.get("title"),
                                playlist=lambda: playlist_header(root, video_id))["fields"]
    result = {k: " ".join(nfc(str(fields.get(k) or "")).split()) for k in ("series", "episode", "speaker")}
    number = result["episode"]
    if not result["series"] or not re.fullmatch(r"[0-9]{1,9}", number) or int(number) < 1:
        raise PackageError("thiếu tên bộ kinh hoặc số tập hợp lệ")
    result["episode"] = str(int(number))
    return result


def shapes(config, video_id):
    # Same owner + effective source decision as web.episodes.hd_file; archived originals have no path.
    _no_symlinks(Path(config.workspace.dir) / enhance_state.owner_id(video_id))
    src = enhance_state.effective_source(config, enhance_state.owner_id(video_id))
    _no_symlinks(Path(config.render.output_dir) / full.owner_of(video_id) / full.FULL_DIR)
    vertical = full.ready_file(config, video_id)
    # G7: a vertical episode also gets the shared landscape thumbnail.
    return (["landscape"] if (src is not None and src.path is not None) or vertical is not None else []) \
        + (["vertical"] if vertical is not None else [])


def images(config):
    usable = []
    for entry in sorted(assets.list_assets(config.packaging.asset_dir), key=lambda a: a["id"]):
        if entry["kind"] == "image":
            try:
                asset, _ = assets.usable(config.packaging.asset_dir, entry["id"], kind="image")
                usable.append(asset)
            except PackageError:
                continue
    return usable


def context(config, video_id, doc):
    fields = header(config, video_id)
    formats = shapes(config, video_id)
    if not formats:
        raise PackageError("chưa có bản ngang HD hoặc bản dọc hoàn chỉnh")
    ident = doc.get("override")
    if ident is None:
        pool = images(config)
        ident = pool[int(fields["episode"]) % len(pool)]["id"] if pool else None
    image = assets.usable(config.packaging.asset_dir, ident, kind="image")[1] if ident else None
    return fields, formats, ident, image


def cache_key(fields, asset_id, shape):
    return config_hash(dict(header=fields, asset_sha256=asset_id, layout_version=thumbnail.EPISODE_LAYOUT_VERSION,
                            font_sha256=sha256_file(thumbnail.FONT), shape=shape))


def valid_files(config, video_id, doc=None):
    """Only current, complete, hash-verified artifacts may be previewed or downloaded."""
    try:
        folder = directory(config, video_id)
        doc = read(config, video_id) if doc is None else doc
        if doc is None or doc.get("skipped_reason"):
            return {}
        fields, formats, ident, _ = context(config, video_id, doc)
        if doc["header"] != fields or doc["asset_id"] != ident:
            return {}
        return {shape: entry for shape, entry in doc["files"].items() if shape in formats
                and thumbnail.reusable(folder, entry, cache_key(fields, ident, shape), file_pattern=FILE_NAME)}
    except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
        return {}


def set_override(config, video_id, asset_id):
    if asset_id is not None:
        assets.usable(config.packaging.asset_dir, asset_id, kind="image")
    folder = directory(config, video_id)
    doc = read(config, video_id) or _new(video_id)
    doc.update(override=asset_id, updated_at=utc_now())
    atomic_write_json(folder / "thumbs.json", doc)


def build_episode(config, video_id, *, run=None):
    """Stage every format before publishing any of them; count episodes, not individual JPEGs."""
    folder = directory(config, video_id)
    previous = read(config, video_id) or _new(video_id)
    fields, formats, ident, image = context(config, video_id, previous)
    doc = dict(previous, header=fields, asset_id=ident, files={}, skipped_reason=None, updated_at=utc_now())
    folder.mkdir(parents=True, exist_ok=True)
    staged = []
    with tempfile.TemporaryDirectory(prefix=".episode-thumbs-", dir=folder) as tmpname:
        for shape in formats:
            expected = cache_key(fields, ident, shape)
            old = previous["files"].get(shape)
            if thumbnail.reusable(folder, old, expected, file_pattern=FILE_NAME):
                doc["files"][shape] = old
                continue
            work = Path(tmpname) / shape
            work.mkdir()
            name = f"{shape}-{expected}.jpg"
            output = thumbnail.build_episode(work, fields, shape, image, name, run=run)
            doc["files"][shape] = dict(file=name, key=expected, sha256=sha256_file(output))
            staged.append((output, folder / name))
        for source, dest in staged:
            os.replace(source, dest)
        atomic_write_json(folder / "thumbs.json", doc)
    keep = {entry["file"] for entry in doc["files"].values()}
    for path in folder.iterdir():
        if FILE_NAME.fullmatch(path.name) and path.name not in keep:
            path.unlink()
    return "built" if staged else "reused"


def build_playlist(config, pid, *, run=None, progress=None, video_id=None):
    """Isolate episode failures. ``video_id`` restricts the same job to a single override edit."""
    entries = playlist(config, pid)["entries"]
    if video_id is not None:
        entries = [e for e in entries if isinstance(e, dict) and e.get("video_id") == video_id]
        if not entries:
            raise PackageError("tập không thuộc bộ kinh")
    summary = dict(built=0, reused=0, skipped=[])
    seen = set()
    for entry in entries:
        ident = entry.get("video_id") if isinstance(entry, dict) else None
        if isinstance(ident, str) and ident in seen:
            continue
        if isinstance(ident, str):
            seen.add(ident)
        try:
            summary[build_episode(config, ident, run=run)] += 1
        except (PackageError, TitlingError, TextError, RenderError, OSError, ValueError, KeyError, TypeError) as exc:
            reason = str(exc)
            summary["skipped"].append(dict(episode=ident, reason=reason))
            try:
                folder = directory(config, ident)
                doc = read(config, ident) or _new(ident)
                doc.update(skipped_reason=reason, updated_at=utc_now())
                atomic_write_json(folder / "thumbs.json", doc)
            except (PackageError, OSError):
                pass  # invalid paths / records must never be overwritten
        if progress is not None:
            progress(summary)
    return summary
