"""Plan and apply thumbnail matches without changing local packaging artifacts."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..hashing import sha256_file
from ..packaging import PackageError, episode, khaithi_thumbs
from ..render.text import nfc
from ..titling.logic import TitlingError
from ..titling.playlist import stored_series
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import PublishError

# HD1 G6: the store names a vertical "[HD Mobile] …"; "[HD Dọc] …" stays for videos uploaded before the rename.
FILE_NAME = re.compile(r"^\[(HD|HD Dọc|HD Mobile)\] (.+) - Tập ([0-9]+)\.(?i:mp4)$")
WEB_FILE_NAME = re.compile(r"^(?:\[HD\] )?(.+)_Tập([0-9]+)_Doc\.mp4$", re.I)
TITLE = re.compile(r"^\[(HD|HD Dọc|HD Mobile)\] (.+?) - (?:.+ - )?Tập ([0-9]+)$", re.I)
MAX_BYTES = 2 * 1024 * 1024


def _series(value):
    return " ".join(nfc(value).casefold().split()) if isinstance(value, str) else ""


def _thumbnail(config, video_id, pid, shape, *, clip_id=None):
    provider = episode if clip_id is None else khaithi_thumbs
    files = provider.valid_files(config, video_id, pid=pid)
    entry = (files if clip_id is None else files.get(clip_id, {})).get(shape)
    if entry is None:
        doc = provider.read(config, video_id) or {}
        files = doc.get("files", {}) if clip_id is None else doc.get("clips", {}).get(clip_id, {})
        recorded = files.get(shape)
        if recorded:
            path = provider.directory(config, video_id) / recorded["file"]
            if path.is_file() and path.stat().st_size > MAX_BYTES:
                raise PublishError("ảnh lớn hơn 2 MB")
        if clip_id is not None:
            label = "ngang" if shape == "landscape" else "dọc"
            raise PublishError(f"chưa có ảnh {label} khai thị hợp lệ hoặc ảnh đã cũ")
        raise PublishError("chưa có ảnh thumbnail hợp lệ hoặc ảnh đã cũ")
    path = provider.directory(config, video_id) / entry["file"]
    if path.stat().st_size > MAX_BYTES:
        raise PublishError("ảnh lớn hơn 2 MB")
    if sha256_file(path) != entry["sha256"]:
        raise PublishError("sha256 thumbnail không khớp")
    return entry, path


def _playlist_match(row, video, expected, numbers, records):
    """Reconcile recognized sources before choosing journal, filename, then title."""
    matches = []
    record = records.get(row["youtube_id"])
    if record is not None:
        number = next((n for n, ids in numbers.items() if record["video_id"] in ids), None)
        if number is None or record["shape"] not in ("landscape", "vertical"):
            row["reason"] = "nhật ký không trỏ tới tập / khuôn hợp lệ trong playlist nguồn"
            return None
        matches.append((record["video_id"], number, record["shape"], "nhật ký"))

    name = row["file_name"]
    file_match = FILE_NAME.fullmatch(nfc(name))
    old_match = WEB_FILE_NAME.fullmatch(nfc(name)) if file_match is None else None
    snippet = video.get("snippet")
    title = snippet.get("title") if isinstance(snippet, dict) else None
    title_match = TITLE.fullmatch(nfc(title)) if isinstance(title, str) else None
    sources = []
    if file_match:
        sources.append((file_match[2], int(file_match[3]),
                        "landscape" if file_match[1] == "HD" else "vertical", "tên file"))
    elif old_match:
        sources.append((old_match[1], int(old_match[2]), "vertical", "tên file"))
    if title_match:
        sources.append((title_match[2], int(title_match[3]),
                        "landscape" if title_match[1].casefold() == "hd" else "vertical", "tiêu đề"))
    for series, number, shape, source in sources:
        if _series(series) != expected:
            row["reason"] = "tên bộ kinh khác"
            return None
        matches.append((None, number, shape, source))
    if len({(m[1], m[2]) for m in matches}) > 1:
        row["reason"] = "nhật ký và tên / tiêu đề lệch nhau"
        return None
    if not matches:
        row["reason"] = "nhật ký, tên file gốc và tiêu đề không ghép được tập / khuôn"
        return None
    video_id, number, shape, source = matches[0]
    if video_id is None:
        candidates = numbers.get(number, set())
        if len(candidates) != 1:
            row["reason"] = "không tìm thấy tập duy nhất trong playlist"
            return None
        video_id = next(iter(candidates))
    row["matched_by"] = source
    return video_id, number, shape


def plan(config, videos, *, pid, series=None, output=None, journal=None):
    """Return reviewable rows; journal enables matching for a selected YouTube playlist.

    With journal=None, retain the uploads-only filename rules. No HTTP or writes.
    """
    playlist = episode.playlist(config, pid)
    selected = stored_series(playlist) if series is None else series
    numbers = {}
    for entry in playlist["entries"]:
        try:
            ident = entry["video_id"]
            fields = episode.header(config, ident)
            number = int(fields["episode"])
        except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
            continue
        numbers.setdefault(number, set()).add(ident)
        if selected is None:
            selected = fields["series"]
    expected = _series(selected)
    if not expected:
        raise PublishError("thiếu tên bộ kinh; đặt series của playlist hoặc dùng --series")
    if output is not None:
        output(f"Bộ kinh: {' '.join(nfc(selected).split())}")
    records = {r["youtube_id"]: r for r in journal["records"] if r["playlist_id"] == pid and "clip_id" not in r} \
        if journal is not None else {}
    rows, groups = [], {}
    for video in videos:
        details = video.get("fileDetails") if isinstance(video, dict) else None
        name = details.get("fileName") if isinstance(details, dict) else None
        ident = video.get("id") if isinstance(video, dict) else None
        row = dict(youtube_id=ident if isinstance(ident, str) else "", file_name=name if isinstance(name, str) else "",
                   playlist_id=pid, status="bỏ qua", reason="", warning="")
        rows.append(row)
        if journal is not None:
            row["matched_by"] = ""
        match = FILE_NAME.fullmatch(nfc(name)) if isinstance(name, str) else None
        if not row["youtube_id"]:
            row["reason"] = "thiếu id video YouTube"
            continue
        if journal is not None:
            resolved = _playlist_match(row, video, expected, numbers, records)
            if resolved is None:
                continue
            video_id, number, shape = resolved
        elif match is None:
            row["reason"] = "tên file gốc không theo mẫu [HD] / [HD Mobile] / [HD Dọc]"
            continue
        elif _series(match[2]) != expected:
            row["reason"] = "tên bộ kinh khác"
            continue
        else:
            number = int(match[3])
            candidates = numbers.get(number, set())
            if len(candidates) != 1:
                row["reason"] = "không tìm thấy tập duy nhất trong playlist"
                continue
            video_id = next(iter(candidates))
            shape = "landscape" if match[1] == "HD" else "vertical"
        row.update(video_id=video_id, episode=number, shape=shape)
        groups.setdefault((number, shape), []).append(row)
        try:
            entry, path = _thumbnail(config, video_id, pid, shape)
            row.update(file=str(path), sha256=entry["sha256"], status="sẵn sàng")
        except (PublishError, PackageError, OSError) as exc:
            row["reason"] = str(exc) if isinstance(exc, (PublishError, PackageError)) else "không đọc được thumbnail"
    for group in groups.values():
        if len(group) > 1:
            for row in group:
                row["warning"] = "nhiều video YouTube cùng tập / khuôn; sẽ gắn cho tất cả"
    return rows


def _journal(config):
    path = Path(config.workspace.dir) / "_publish" / "thumbs.json"
    if not path.exists():
        return path, dict(schema_version=1, records=[])
    doc = read_json_dict(path)
    if doc is None or doc.get("schema_version") != 1 or not isinstance(doc.get("records"), list) \
            or any(not isinstance(r, dict) or any(not isinstance(r.get(k), str) for k in
                   ("youtube_id", "video_id", "playlist_id", "shape", "sha256", "set_at"))
                   or "clip_id" in r and not isinstance(r["clip_id"], str) for r in doc["records"]):
        raise PublishError("nhật ký thumbnail không hợp lệ; không ghi đè")
    return path, doc


def apply(config, rows, youtube, *, force=False):
    """Persist each success before proceeding; API errors stop the batch."""
    path, journal = _journal(config)
    previous = {r["youtube_id"]: r["sha256"] for r in journal["records"]}
    result = []
    for original in rows:
        row = dict(original)
        result.append(row)
        if row["status"] != "sẵn sàng":
            continue
        if not force and previous.get(row["youtube_id"]) == row["sha256"]:
            row.update(status="bỏ qua", reason="đã gắn cùng sha256")
            continue
        try:
            entry, image = _thumbnail(config, row["video_id"], row["playlist_id"], row["shape"],
                                      clip_id=row.get("clip_id"))
            if entry["sha256"] != row["sha256"] or str(image) != row["file"]:
                raise PublishError("thumbnail đã thay đổi; chạy lại lệnh để lập bảng mới")
            body = image.read_bytes()
            if len(body) > MAX_BYTES:
                raise PublishError("ảnh lớn hơn 2 MB")
            if hashlib.sha256(body).hexdigest() != row["sha256"]:
                raise PublishError("sha256 thumbnail không khớp; ảnh đã thay đổi")
        except (PublishError, PackageError, OSError) as exc:
            row.update(status="bỏ qua", reason=str(exc) if isinstance(exc, (PublishError, PackageError))
                       else "không đọc được thumbnail")
            continue
        youtube.set_thumbnail(row["youtube_id"], body)
        record = {k: row[k] for k in ("youtube_id", "video_id", "playlist_id", "shape", "sha256")}
        if "clip_id" in row:
            record["clip_id"] = row["clip_id"]
        record["set_at"] = utc_now()
        journal["records"] = [r for r in journal["records"] if r["youtube_id"] != row["youtube_id"]] + [record]
        atomic_write_json(path, journal)
        previous[row["youtube_id"]] = row["sha256"]
        row["status"] = "đã gắn"
    return result
