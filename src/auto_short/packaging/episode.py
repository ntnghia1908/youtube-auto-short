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
from ..titling.playlist import playlist_header, stored_series
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
                or doc["asset_id"] is not None and not assets.SHA.fullmatch(doc["asset_id"]) \
                or doc["skipped_reason"] is not None and not isinstance(doc["skipped_reason"], str):
            raise PackageError("hồ sơ thumbnail không hợp lệ")
        owners = doc.get("asset_ids", {})  # PKG2.1: per-shape assets; older records only have asset_id
        if not isinstance(owners, dict) or any(k not in ("landscape", "vertical") or v is not None
                                               and not assets.SHA.fullmatch(v) for k, v in owners.items()):
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
    return dict(schema_version=1, video_id=video_id, header={}, asset_id=None,
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


def effective(settings, shape):
    """Settings one shape is rendered with: the shared fields, plus the vertical override for 9:16.

    Without an override both shapes get exactly the five shared fields, so cache keys equal the pre-PKG2.1 ones."""
    result = {k: settings[k] for k in SETTING_FIELDS}
    if shape == "vertical" and settings.get("vertical"):
        result.update(settings["vertical"])
    return result


def context(config, video_id, settings):
    """fields, formats, {shape: asset id}, {shape: image path}; assets are checked for both shapes."""
    fields = header(config, video_id)
    formats = shapes(config, video_id)
    if not formats:
        raise PackageError("chưa có bản ngang HD hoặc bản dọc hoàn chỉnh")
    idents, images = {}, {}
    for shape in thumbnail.EPISODE_SIZES:
        ident = idents[shape] = effective(settings, shape)["asset_id"]
        images[shape] = assets.usable(config.packaging.asset_dir, ident, kind="image")[1] if ident else None
    return fields, formats, idents, images


def cache_key(fields, settings, shape):
    look = effective(settings, shape)
    return config_hash(dict(header=fields, settings=look, layout_version=thumbnail.EPISODE_LAYOUT_VERSION,
                            font_sha256=thumbnail.font_hashes(look["style"]), shape=shape))


def recorded_asset(doc, shape):
    return doc.get("asset_ids", {}).get(shape, doc["asset_id"])


def valid_files(config, video_id, doc=None, *, pid=None, settings=None):
    """Only current, complete, hash-verified artifacts may be previewed or downloaded."""
    try:
        folder = directory(config, video_id)
        doc = read(config, video_id) if doc is None else doc
        if doc is None or doc.get("skipped_reason"):
            return {}
        pid = pid or doc.get("playlist_id")
        if not pid:
            return {}
        settings = read_settings(config, pid) if settings is None else settings
        fields, formats, idents, _ = context(config, video_id, settings)
        if doc["header"] != fields:
            return {}
        return {shape: entry for shape, entry in doc["files"].items() if shape in formats
                and recorded_asset(doc, shape) == idents[shape]
                and thumbnail.reusable(folder, entry, cache_key(fields, settings, shape), file_pattern=FILE_NAME)}
    except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
        return {}


SETTING_FIELDS = ("style", "asset_id", "focus_x", "title_lines", "credit")


def settings_path(config, pid):
    playlist(config, pid)
    return _no_symlinks(Path(config.render.output_dir) / "_compilations" / pid / "thumbs.json")


VERTICAL_FIELDS = ("style", "asset_id", "focus_x")


def _check_look(config, look, check_asset):
    if not isinstance(look["style"], str) or look["style"] not in thumbnail.STYLE_FONTS:
        raise PackageError("kiểu thumbnail phải là A, B hoặc C")
    if type(look["focus_x"]) not in (int, float) or not 0 <= look["focus_x"] <= 1:
        raise PackageError("focus_x phải từ 0 đến 1")
    if look["asset_id"] is not None:
        if not isinstance(look["asset_id"], str) or not assets.SHA.fullmatch(look["asset_id"]):
            raise PackageError("asset id không hợp lệ")
        if check_asset:
            assets.usable(config.packaging.asset_dir, look["asset_id"], kind="image")


def validate_settings(config, settings, *, check_asset=True):
    if not isinstance(settings, dict) or any(k not in settings for k in SETTING_FIELDS):
        raise PackageError("cấu hình thumbnail thiếu trường")
    result = {k: settings[k] for k in SETTING_FIELDS}
    _check_look(config, result, check_asset)
    vertical = settings.get("vertical")  # None = share the landscape look
    if vertical is not None:
        if not isinstance(vertical, dict) or set(vertical) != set(VERTICAL_FIELDS):
            raise PackageError("kiểu riêng cho bản dọc cần đủ style, asset_id, focus_x")
        vertical = {k: vertical[k] for k in VERTICAL_FIELDS}
        _check_look(config, vertical, check_asset)
    result["vertical"] = vertical
    lines = result["title_lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 3 \
            or any(not isinstance(v, str) or not v.strip() or len(nfc(v)) > 40 or len(v.splitlines()) != 1 for v in lines):
        raise PackageError("tiêu đề cần 1–3 dòng không rỗng, tối đa 40 ký tự mỗi dòng")
    if not isinstance(result["credit"], str) or len(nfc(result["credit"])) > 60 \
            or len(result["credit"].splitlines()) > 1:
        raise PackageError("credit tối đa 60 ký tự trên một dòng")
    result["title_lines"] = [" ".join(nfc(v).split()) for v in lines]
    result["credit"] = " ".join(nfc(result["credit"]).split())
    return result


def default_settings(config, pid):
    doc = playlist(config, pid)
    fields = {}
    for entry in doc["entries"]:
        try:
            fields = header(config, entry["video_id"])
            break
        except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
            continue
    series = stored_series(doc) or fields.get("series") or doc.get("title")
    words = nfc(series if isinstance(series, str) and series.strip() else "Bộ kinh").split()
    lines = []
    if words[0].casefold() == "kinh":
        lines.append(words.pop(0))
    for group in (words[:2], words[2:]):
        line = ""
        for word in group:
            if len(word) > 40:
                continue  # omit an indivisible oversized word rather than create invalid defaults
            candidate = (line + " " + word).strip()
            if len(candidate) > 40:
                lines.append(line)
                line = ""
                if len(lines) == 3:
                    break
            line = (line + " " + word).strip()
        if line and len(lines) < 3:
            lines.append(line)
        if len(lines) == 3:
            break
    lines = lines or ["Bộ kinh"]
    speaker = fields.get("speaker") or config.titling.header.speaker
    if "tịnh không" in speaker.casefold():
        speaker = "PHÁP SƯ TỊNH KHÔNG"
    credit = ("CHỦ GIẢNG: " + speaker.upper())[:60].rstrip() if speaker else ""
    return validate_settings(config, dict(style="A", asset_id=None, focus_x=0.5, title_lines=lines, credit=credit))


def read_settings(config, pid):
    path = settings_path(config, pid)
    if not path.exists():
        return default_settings(config, pid)
    doc = read_json_dict(path)
    if doc is None or doc.get("schema_version") != 1 or doc.get("playlist_id") != pid:
        raise PackageError("cấu hình thumbnail bộ kinh không hợp lệ")
    return validate_settings(config, doc, check_asset=False)


def write_settings(config, pid, settings):
    settings = validate_settings(config, settings)
    atomic_write_json(settings_path(config, pid), dict(schema_version=1, playlist_id=pid, **settings, updated_at=utc_now()))
    return settings


def build_episode(config, video_id, *, pid, settings=None, run=None):
    """Stage every format before publishing any of them; count episodes, not individual JPEGs."""
    folder = directory(config, video_id)
    previous = read(config, video_id) or _new(video_id)
    settings = read_settings(config, pid) if settings is None else settings
    fields, formats, idents, images = context(config, video_id, settings)
    doc = dict(_new(video_id), playlist_id=pid, header=fields, asset_id=idents["landscape"],
               asset_ids={shape: idents[shape] for shape in formats})
    folder.mkdir(parents=True, exist_ok=True)
    staged = []
    with tempfile.TemporaryDirectory(prefix=".episode-thumbs-", dir=folder) as tmpname:
        for shape in formats:
            expected = cache_key(fields, settings, shape)
            old = previous["files"].get(shape)
            if thumbnail.reusable(folder, old, expected, file_pattern=FILE_NAME):
                doc["files"][shape] = old
                continue
            work = Path(tmpname) / shape
            work.mkdir()
            name = f"{shape}-{expected}.jpg"
            output = thumbnail.build_episode(work, fields, shape, images[shape], name,
                                             settings=effective(settings, shape), run=run)
            doc["files"][shape] = dict(file=name, key=expected, sha256=sha256_file(output))
            staged.append((output, folder / name))
        if not staged:
            doc["updated_at"] = previous.get("updated_at") or doc["updated_at"]
            if doc == previous:
                return "reused"  # a cache hit does not rewrite another episode's record
        for source, dest in staged:
            os.replace(source, dest)
        atomic_write_json(folder / "thumbs.json", doc)
    keep = {entry["file"] for entry in doc["files"].values()}
    for path in folder.iterdir():
        if FILE_NAME.fullmatch(path.name) and path.name not in keep:
            path.unlink()
    return "built" if staged else "reused"


def build_playlist(config, pid, *, run=None, progress=None):
    """Isolate episode failures; every episode uses the same settings snapshot."""
    entries = playlist(config, pid)["entries"]
    settings = read_settings(config, pid)
    summary = dict(built=0, reused=0, skipped=[])
    seen = set()
    for entry in entries:
        ident = entry.get("video_id") if isinstance(entry, dict) else None
        if isinstance(ident, str) and ident in seen:
            continue
        if isinstance(ident, str):
            seen.add(ident)
        try:
            summary[build_episode(config, ident, pid=pid, settings=settings, run=run)] += 1
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


def preview(config, pid, *, settings=None, run=None):
    """Both shapes of the first eligible episode, returned as bytes; never publish into episode output."""
    settings = read_settings(config, pid) if settings is None else validate_settings(config, settings)
    for entry in playlist(config, pid)["entries"]:
        try:
            fields, _, _, images = context(config, entry["video_id"], settings)
            break
        except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
            continue
    else:
        raise PackageError("không có tập đủ điều kiện để xem trước")
    with tempfile.TemporaryDirectory(prefix="episode-thumbs-preview-") as tmp:
        result = {}
        for shape in thumbnail.EPISODE_SIZES:
            work = Path(tmp) / shape
            work.mkdir()
            path = thumbnail.build_episode(work, fields, shape, images[shape], "preview.jpg",
                                             settings=effective(settings, shape), run=run)
            result[shape] = path.read_bytes()
        return result
