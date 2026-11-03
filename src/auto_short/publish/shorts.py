"""Match coded YouTube Shorts to KTI2 images or cached images of their uploaded titles."""
import re

from ..hashing import sha256_file
from ..packaging import PackageError, cover, episode, khaithi_thumbs, thumbnail
from ..render.stage import RenderError
from ..render.text import TextError, nfc
from ..titling.logic import TitlingError
from . import PublishError, kt, thumbs

CODE = re.compile(r"^T([0-9]+)[ _]S([0-9]{1,3})(?!\d)", re.I)


def _title(value, match):
    title = nfc(value.strip())[match.end():].lstrip("_ ")
    title = re.sub(r"#\S+", "", title).strip()
    return " ".join(re.sub(r"\.mp4$", "", title, flags=re.I).split())


def _web_thumbnail(config, ident, pid, clip_id):
    """Validate KTI2's title/number mapping and the same vertical cache inputs, without rendering."""
    doc = khaithi_thumbs.read(config, ident, short=True) or {}
    titles = khaithi_thumbs.titles(config, ident, include_hidden=True, short=True)
    if doc.get("playlist_id") != pid or doc.get("clip_numbers") != {t.clip_id: n for n, t in enumerate(titles, 1)}:
        raise PublishError("số clip Short web đã thay đổi")
    title = next((t for t in titles if t.clip_id == clip_id and t.title and not t.rejected), None)
    entry = cover.current(config, pid).get("kt_vertical")
    if title is None or entry is None:
        raise PublishError("chưa có tiêu đề hoặc bìa Short web hợp lệ")
    fields = khaithi_thumbs.display_fields(config, pid, episode.header(config, ident))
    items = khaithi_thumbs.portraits(config)
    _, portrait_sha, _ = khaithi_thumbs.choose_portrait(items, fields["episode"])
    key = khaithi_thumbs.cache_key(title.title, fields["episode"], entry, "vertical",
        portrait_sha256=portrait_sha, speaker=fields["speaker"], series=fields["series"],
        portrait_library=[sha for _, sha, _ in items], label=khaithi_thumbs.SHORT_LABEL)
    image = doc.get("clips", {}).get(clip_id, {}).get("vertical")
    folder = khaithi_thumbs._clip_directory(config, ident, short=True)
    if not thumbnail.reusable(folder, image, key, file_pattern=khaithi_thumbs.FILE_NAME):
        raise PublishError("chưa có ảnh dọc Short web hợp lệ hoặc ảnh đã cũ")
    return image, folder / image["file"]


def _thumbnail(config, row):
    """Recheck the planned source before apply; never generate a replacement during apply."""
    try:
        if row["source"] == "web":
            return _web_thumbnail(config, row["video_id"], row["playlist_id"], row["clip_id"])
        fields = khaithi_thumbs.display_fields(config, row["playlist_id"], episode.header(config, row["video_id"]))
        path = khaithi_thumbs.short_title(config, row["video_id"], row["clip_id"], row["title"],
                                         pid=row["playlist_id"], fields=fields, reuse_only=True)
        return dict(sha256=sha256_file(path)), path
    except (PackageError, PublishError):
        raise
    except (TitlingError, ValueError, KeyError, TypeError) as exc:
        raise PublishError("không đọc được hồ sơ thumbnail Short") from exc


def plan(config, videos, *, pid, episodes=None):
    """Plan locally, generating only missing YouTube-title images; episodes is an inclusive pair."""
    numbers = kt._episodes(config, pid)
    rows = []
    for video in videos:
        row, name, title = kt._video_row(video, pid, "vertical")
        row["source"] = ""
        file_code, title_code = kt._code(name, CODE), kt._code(title, CODE)
        match = file_code if file_code is not None else title_code
        if match:
            number, clip_number = map(int, match.groups())
            row.update(code=f"T{number}_S{clip_number:02d}", episode=number, clip_number=clip_number)
        if episodes is not None and (match is None or not episodes[0] <= row["episode"] <= episodes[1]):
            continue
        rows.append(row)
        if not row["youtube_id"]:
            row["reason"] = "thiếu id video YouTube"
            continue
        if match is None:
            row["reason"] = "không có mã Short"
            continue
        if file_code and title_code and tuple(map(int, file_code.groups())) != tuple(map(int, title_code.groups())):
            row["reason"] = "tên file và tiêu đề lệch mã"
            continue
        candidates = numbers.get(number, set())
        if len(candidates) != 1:
            row["reason"] = ("không có tập trong playlist nguồn" if not candidates else
                             "nhiều tập cùng số trong playlist nguồn")
            continue
        ident = next(iter(candidates))
        row["video_id"] = ident
        try:
            # A stale/missing KTI2 image falls back to the YouTube title, leaving KTI2 untouched.
            try:
                doc = khaithi_thumbs.read(config, ident, short=True) or {}
                cid = next((cid for cid, n in doc.get("clip_numbers", {}).items() if n == clip_number), None)
                if cid is None:
                    raise PublishError("không có clip Short web")
                image, path = _web_thumbnail(config, ident, pid, cid)
                row.update(source="web", clip_id=cid)
            except (PublishError, PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
                clean = _title(name if file_code is not None else title, match)
                row.update(source="youtube-title", clip_id=f"s{clip_number:02d}", title=clean)
                fields = khaithi_thumbs.display_fields(config, pid, episode.header(config, ident))
                path = khaithi_thumbs.short_title(config, ident, row["clip_id"], clean, pid=pid, fields=fields)
                image = dict(sha256=sha256_file(path))
            if path.stat().st_size > thumbs.MAX_BYTES:
                raise PublishError("ảnh lớn hơn 2 MB")
            row.update(file=str(path), sha256=image["sha256"], status="sẵn sàng")
        except (PublishError, PackageError, TitlingError, RenderError, TextError, OSError) as exc:
            row["reason"] = str(exc) if not isinstance(exc, OSError) else "không đọc / vẽ được thumbnail Short"
    return rows
