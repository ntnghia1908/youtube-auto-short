"""Match an explicitly selected YouTube KT playlist by episode and web clip number."""
from pathlib import Path
import re

from ..packaging import PackageError, episode, khaithi_thumbs
from ..render.text import nfc
from ..titling.logic import TitlingError
from . import PublishError, thumbs, youtube

CODE = re.compile(r"^T([0-9]+)[ _]KT([0-9]{1,3})(?!\d)", re.I)


def _code(value, pattern=CODE):
    return pattern.match(nfc(value.strip())) if isinstance(value, str) else None


def _title_key(value):
    """Keep Vietnamese letters and digits; ignore punctuation, case and whitespace."""
    return " ".join(re.sub(r"[\W_]+", " ", thumbs._series(value)).split())


def _episodes(config, pid, *, khai_thi=False):
    """Index source episodes by the header authority; KT additionally requires its marker."""
    numbers = {}
    for entry in episode.playlist(config, pid)["entries"]:
        try:
            base = entry["video_id"]
            episode.directory(config, base)
            if base.endswith(".kt"):
                continue
            ident = base + ".kt" if khai_thi else base
            if khai_thi:
                marker = episode._no_symlinks(Path(config.workspace.dir) / ident / "khaithi.json")
                if not marker.is_file():
                    continue
            number = int(episode.header(config, base)["episode"])
            numbers.setdefault(number, set()).add(ident)
        except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
            continue
    return numbers


def _video_row(video, pid, shape):
    details = video.get("fileDetails") if isinstance(video, dict) else None
    snippet = video.get("snippet") if isinstance(video, dict) else None
    name = details.get("fileName") if isinstance(details, dict) else None
    title = snippet.get("title") if isinstance(snippet, dict) else None
    ident = video.get("id") if isinstance(video, dict) else None
    row = dict(youtube_id=ident if isinstance(ident, str) else "",
               file_name=name if isinstance(name, str) else "", playlist_id=pid,
               code="", shape=shape, status="bỏ qua", reason="", warning="")
    return row, name, title


def plan(config, videos, *, pid, shape="vertical", since=None):
    """Plan without HTTP or writes; only source-playlist episodes with khaithi.json qualify."""
    numbers = _episodes(config, pid, khai_thi=True)
    rows = []
    for video in videos:
        row, name, title = _video_row(video, pid, shape)
        rows.append(row)
        file_code, title_code = _code(name), _code(title)
        if not row["youtube_id"]:
            row["reason"] = "thiếu id video YouTube"
            continue
        if file_code is None and title_code is None:
            row["reason"] = "không có mã KT"
            continue
        match = file_code if file_code is not None else title_code
        number, clip_number = map(int, match.groups())
        row.update(code=f"T{number}_KT{clip_number:02d}", episode=number, clip_number=clip_number)
        reason = youtube.since_reason(video, since)
        if reason:
            row["reason"] = reason
            continue
        if file_code and title_code and tuple(map(int, file_code.groups())) != tuple(map(int, title_code.groups())):
            row["reason"] = "tên file và tiêu đề lệch mã"
            continue
        candidates = numbers.get(number, set())
        if not candidates:
            row["reason"] = "không có tập khai thị trong playlist nguồn"
            continue
        if len(candidates) > 1:
            row["reason"] = "nhiều tập khai thị cùng số trong playlist nguồn"
            continue
        ident = next(iter(candidates))
        row.update(video_id=ident)
        try:
            doc = khaithi_thumbs.read(config, ident) or {}
            clip_id = next((cid for cid, n in doc.get("clip_numbers", {}).items() if n == clip_number), None)
            if clip_id is None:
                row["reason"] = "không có clip số KT trong hồ sơ thumbnail khai thị"
                continue
            row["clip_id"] = clip_id
            image, path = thumbs._thumbnail(config, ident, pid, shape, clip_id=clip_id)
            web_title = next((t.title for t in khaithi_thumbs.titles(config, ident) if t.clip_id == clip_id), "")
            clean_title = nfc(title.strip()) if isinstance(title, str) else ""
            if title_code:
                clean_title = clean_title[title_code.end():].lstrip("_ ")
            clean_title = re.sub(r"#\S+", "", clean_title)
            if _title_key(clean_title) != _title_key(web_title):
                row["warning"] = "tiêu đề YouTube khác tiêu đề web"
            row.update(file=str(path), sha256=image["sha256"], status="sẵn sàng")
        except (PublishError, PackageError, OSError) as exc:
            row["reason"] = str(exc) if isinstance(exc, (PublishError, PackageError)) else "không đọc được thumbnail"
    return rows
