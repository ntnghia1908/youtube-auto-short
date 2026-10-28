"""Per-clip khai thị thumbnails using approved covers and the video's resolved titles."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .. import khaithi
from ..hashing import config_hash, sha256_file
from ..render.text import Font, TextError, check_glyphs, nfc, wrap_balanced
from ..review.logic import ReviewError, added_entries, read_review, resolve_titles
from ..titling.logic import TitlingError
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import PackageError, cover, episode, thumbnail

LAYOUT_VERSION = 1
CLIP_ID = re.compile(r"[km][0-9]{2,}")
FILE_NAME = re.compile(r"([km][0-9]{2,}-(?:vertical|landscape))-([a-f0-9]{64})\.jpg")


def directory(config, ident):
    if not isinstance(ident, str) or not ident.endswith(".kt"):
        raise PackageError("cần id tập khai thị")
    return episode.directory(config, ident)


def titles(config, ident, *, include_hidden=False):
    directory(config, ident)
    folder = episode._no_symlinks(Path(config.workspace.dir) / ident)
    episode._no_symlinks(folder / "khaithi.json")
    try:
        kind = khaithi.read(folder, config.khaithi.max_minutes_limit)
    except khaithi.KhaithiError as exc:
        raise PackageError(exc.vi) from exc
    if kind is None:
        return []
    if kind.base_episode_id != ident[:-3]:
        raise PackageError("tập gốc khai thị không khớp id")
    doc = read_json_dict(episode._no_symlinks(folder / "titles.json"))
    if doc is None:
        return []
    try:
        review = read_review(episode._no_symlinks(folder / "review.json"), ident)
    except ReviewError as exc:
        raise PackageError(str(exc)) from exc
    resolved, _ = resolve_titles(doc.get("titles", []) + added_entries(review), review)
    return [t for t in resolved if CLIP_ID.fullmatch(t.clip_id) and (include_hidden or t.title and not t.rejected)]


def title_lines(title, number, box):
    """Word-wrap into at most three lines; fit all ink plus the smaller number inside the box."""
    title = " ".join(nfc(title).split())
    font = Font(thumbnail.EPISODE_FONTS[cover.FONT_NAME])
    check_glyphs(font, [title, f"TẬP {number}"])
    if not title:
        raise PackageError("tiêu đề khai thị rỗng")
    x, y, w, h = box
    width, height = int(w * cover.FIT_WIDTH), int(h * cover.FIT_HEIGHT)
    for size in range(min(180, height // 2), 12, -1):
        wrapped = wrap_balanced(font, title, size, width, max_lines=3)
        if not wrapped:
            continue
        number_size = max(12, round(size * .65))
        texts = [(t, size) for t in wrapped] + [(f"TẬP {number}", number_size)]
        bounds = [font.ink_bounds(t, s) for t, s in texts]
        gap = max(6, round(size * .22))
        total = sum(bottom - top + 6 for top, bottom in bounds) + gap * (len(texts) - 1)
        if total > height:
            continue
        top = round(y + (h - total) / 2)
        result = []
        try:
            for (text, nominal), (ink_top, ink_bottom) in zip(texts, bounds):
                bottom = top + ink_bottom - ink_top + 6
                fitted, baseline = thumbnail._fit_line(text, cover.FONT_NAME, nominal, width,
                    reference=text, nominal_top=top + 2, top=top, bottom=bottom, shadow=2)
                result.append(thumbnail.EpisodeLine(text, cover.FONT_NAME, fitted, x, baseline, w, centered=True))
                top = bottom + gap
            return result
        except TextError:
            continue
    raise TextError("tiêu đề khai thị không vừa tối đa 3 dòng trong khung")


def cache_key(title, number, entry, shape):
    return config_hash(dict(title=nfc(title), episode=number, cover_sha256=entry["sha256"], box=entry["box"],
                            layout_version=LAYOUT_VERSION, font_sha256=sha256_file(thumbnail.EPISODE_FONTS[cover.FONT_NAME]),
                            shape=shape))


def read(config, ident):
    path = episode._no_symlinks(directory(config, ident) / "thumbs.json")
    doc = read_json_dict(path)
    if doc is None:
        return None
    if doc.get("schema_version") != 1 or doc.get("video_id") != ident or not isinstance(doc.get("clips"), dict):
        raise PackageError("hồ sơ thumbnail khai thị không hợp lệ")
    numbers = doc.get("clip_numbers")
    if not isinstance(numbers, dict) or len(set(numbers.values())) != len(numbers) \
            or any(not CLIP_ID.fullmatch(cid) or type(n) is not int or n < 1 for cid, n in numbers.items()):
        raise PackageError("số thứ tự clip khai thị không hợp lệ")
    for cid, files in doc["clips"].items():
        if not CLIP_ID.fullmatch(cid) or cid not in numbers or not isinstance(files, dict):
            raise PackageError("clip thumbnail khai thị không hợp lệ")
        for shape, entry in files.items():
            if shape not in thumbnail.EPISODE_SIZES or not isinstance(entry, dict) \
                    or entry.get("file") != f"{cid}-{shape}-{entry.get('key')}.jpg" \
                    or not FILE_NAME.fullmatch(entry["file"]):
                raise PackageError("file thumbnail khai thị không hợp lệ")
    return doc


def valid_files(config, ident, *, pid=None):
    try:
        doc = read(config, ident)
        if not doc or doc.get("skipped_reason"):
            return {}
        pid = pid or doc["playlist_id"]
        covers = cover.current(config, pid)
        number = episode.header(config, ident[:-3])["episode"]
        result = {}
        current_titles = titles(config, ident, include_hidden=True)
        if doc["clip_numbers"] != {t.clip_id: n for n, t in enumerate(current_titles, 1)}:
            return {}
        for title in current_titles:
            if not title.title or title.rejected:
                continue
            files = {}
            for shape, entry in doc["clips"].get(title.clip_id, {}).items():
                c = covers.get("kt_" + shape)
                if c and thumbnail.reusable(directory(config, ident), entry,
                        cache_key(title.title, number, c, shape), file_pattern=FILE_NAME):
                    files[shape] = entry
            if files:
                result[title.clip_id] = files
        return result
    except (PackageError, TitlingError, OSError, ValueError, KeyError, TypeError):
        return {}


def build_episode(config, ident, *, pid, run=None):
    folder = directory(config, ident)
    covers = cover.current(config, pid)
    covers = {s: covers["kt_" + s] for s in thumbnail.EPISODE_SIZES if "kt_" + s in covers}
    if not covers:
        return dict(built=0, reused=0, skipped_reason="bộ kinh chưa có ảnh bìa khai thị")
    all_titles = titles(config, ident, include_hidden=True)
    selected = [t for t in all_titles if t.title and not t.rejected]
    if not selected:
        return dict(built=0, reused=0, skipped_reason="chưa có tiêu đề clip khai thị")
    fields = episode.header(config, ident[:-3])
    old = read(config, ident) or {}
    doc = dict(schema_version=1, video_id=ident, playlist_id=pid, header=fields, clips={},
               clip_numbers={t.clip_id: n for n, t in enumerate(all_titles, 1)}, updated_at=utc_now())
    folder.mkdir(parents=True, exist_ok=True)
    counts = dict(built=0, reused=0, skipped_reason=None)
    staged = []
    with tempfile.TemporaryDirectory(prefix=".kt-thumbs-", dir=folder) as tmp:
        for title in selected:
            files = doc["clips"][title.clip_id] = {}
            for shape, entry in covers.items():
                key = cache_key(title.title, fields["episode"], entry, shape)
                previous = old.get("clips", {}).get(title.clip_id, {}).get(shape)
                if thumbnail.reusable(folder, previous, key, file_pattern=FILE_NAME):
                    files[shape] = previous
                    counts["reused"] += 1
                    continue
                work = Path(tmp) / f"{title.clip_id}-{shape}"
                work.mkdir()
                name = f"{title.clip_id}-{shape}-{key}.jpg"
                image = cover.draw_lines(work, title_lines(title.title, fields["episode"], entry["box"]),
                                         cover.directory(config, pid) / entry["file"], name, run=run)
                files[shape] = dict(file=name, key=key, sha256=sha256_file(image))
                staged.append((image, episode._no_symlinks(folder / name)))
                counts["built"] += 1
        for source, destination in staged:
            os.replace(source, destination)
        if staged or doc["clips"] != old.get("clips") or fields != old.get("header") \
                or doc["clip_numbers"] != old.get("clip_numbers"):
            atomic_write_json(folder / "thumbs.json", doc)
    keep = {f["file"] for files in doc["clips"].values() for f in files.values()}
    for path in folder.iterdir():
        if FILE_NAME.fullmatch(path.name) and path.name not in keep:
            episode._no_symlinks(path).unlink()
    return counts
