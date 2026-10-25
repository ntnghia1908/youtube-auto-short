"""Plan and apply file-name matches without changing local packaging artifacts."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..hashing import sha256_file
from ..packaging import PackageError, episode
from ..render.text import nfc
from ..titling.logic import TitlingError
from ..titling.playlist import stored_series
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import PublishError

FILE_NAME = re.compile(r"^\[(HD|HD Dọc)\] (.+) - Tập ([0-9]+)\.(?i:mp4)$")
MAX_BYTES = 2 * 1024 * 1024


def _series(value):
    return " ".join(nfc(value).casefold().split()) if isinstance(value, str) else ""


def _thumbnail(config, video_id, pid, shape):
    entry = episode.valid_files(config, video_id, pid=pid).get(shape)
    if entry is None:
        doc = episode.read(config, video_id) or {}
        recorded = doc.get("files", {}).get(shape)
        if recorded:
            path = episode.directory(config, video_id) / recorded["file"]
            if path.is_file() and path.stat().st_size > MAX_BYTES:
                raise PublishError("ảnh lớn hơn 2 MB")
        raise PublishError("chưa có ảnh thumbnail hợp lệ hoặc ảnh đã cũ")
    path = episode.directory(config, video_id) / entry["file"]
    if path.stat().st_size > MAX_BYTES:
        raise PublishError("ảnh lớn hơn 2 MB")
    if sha256_file(path) != entry["sha256"]:
        raise PublishError("sha256 thumbnail không khớp")
    return entry, path


def plan(config, videos, *, pid, series=None, output=None):
    """Return one reviewable row per YouTube video; no HTTP or writes."""
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
    rows, groups = [], {}
    for video in videos:
        details = video.get("fileDetails") if isinstance(video, dict) else None
        name = details.get("fileName") if isinstance(details, dict) else None
        ident = video.get("id") if isinstance(video, dict) else None
        row = dict(youtube_id=ident if isinstance(ident, str) else "", file_name=name if isinstance(name, str) else "",
                   playlist_id=pid, status="bỏ qua", reason="", warning="")
        rows.append(row)
        match = FILE_NAME.fullmatch(nfc(name)) if isinstance(name, str) else None
        if not row["youtube_id"]:
            row["reason"] = "thiếu id video YouTube"
        elif match is None:
            row["reason"] = "tên file gốc không theo mẫu [HD] / [HD Dọc]"
        elif _series(match[2]) != expected:
            row["reason"] = "tên bộ kinh khác"
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
                   ("youtube_id", "video_id", "playlist_id", "shape", "sha256", "set_at")) for r in doc["records"]):
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
            entry, image = _thumbnail(config, row["video_id"], row["playlist_id"], row["shape"])
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
        record["set_at"] = utc_now()
        journal["records"] = [r for r in journal["records"] if r["youtube_id"] != row["youtube_id"]] + [record]
        atomic_write_json(path, journal)
        previous[row["youtube_id"]] = row["sha256"]
        row["status"] = "đã gắn"
    return result
