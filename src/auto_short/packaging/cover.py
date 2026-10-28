"""COV1: one approved series cover per shape, with a deterministic episode number."""
from __future__ import annotations

import math
import os
import shutil
import tempfile
from pathlib import Path

from ..hashing import sha256_file
from ..render.stage import RenderError, _last_line, _run, probe_media
from ..render.text import Font, check_glyphs
from ..workspace import atomic_write_json, read_json_dict
from . import PackageError, assets, thumbnail

COVER_LAYOUT_VERSION = 1
FONT_NAME = thumbnail.STYLE_FONTS["A"][0]


def directory(config, pid):
    from . import episode
    return episode._no_symlinks(episode.settings_path(config, pid).parent / "cover")


def _box(box, width, height):
    if not isinstance(box, (list, tuple)) or len(box) != 4 or any(type(v) is not int for v in box):
        raise PackageError("box cần bốn số nguyên x,y,w,h")
    x, y, w, h = box
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise PackageError("box phải nằm trong ảnh và có chiều rộng / cao dương")
    return list(box)


def read(config, pid):
    """Read metadata; malformed records fail closed rather than silently reverting to PKG2."""
    from . import episode
    path = episode._no_symlinks(directory(config, pid) / "cover.json")
    if not path.exists():
        return dict(schema_version=1, shapes={})
    doc = read_json_dict(path)
    try:
        if doc is None or doc.get("schema_version") != 1 or not isinstance(doc["shapes"], dict):
            raise PackageError("hồ sơ cover không hợp lệ")
        for shape, entry in doc["shapes"].items():
            if shape not in thumbnail.EPISODE_SIZES or entry["file"] != f"{shape}.png" \
                    or not assets.SHA.fullmatch(entry["sha256"]) \
                    or "prompt" in entry and not isinstance(entry["prompt"], str):
                raise PackageError("hồ sơ cover không hợp lệ")
            _box(entry["box"], *thumbnail.EPISODE_SIZES[shape])
    except (KeyError, TypeError, AttributeError) as exc:
        raise PackageError("hồ sơ cover không hợp lệ") from exc
    return doc


def current(config, pid):
    """Only hash-verified, local cover files can influence a thumbnail."""
    from . import episode
    folder = directory(config, pid)
    entries = read(config, pid)["shapes"]
    for entry in entries.values():
        path = episode._no_symlinks(folder / entry["file"])
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise PackageError("ảnh cover thiếu hoặc SHA không khớp; hãy cài lại ảnh mẫu")
    return entries


def install(config, pid, shape, image, box, *, prompt=None, run=None):
    """Normalize to PKG2 dimensions, transform the box, then publish complete files atomically."""
    from . import episode
    if shape not in thumbnail.EPISODE_SIZES:
        raise PackageError("khổ cover phải là vertical hoặc landscape")
    if prompt is not None and not isinstance(prompt, str):
        raise PackageError("prompt phải là văn bản")
    folder = directory(config, pid)
    doc = read(config, pid)
    destination = episode._no_symlinks(folder / f"{shape}.png")
    runner = run or _run
    with tempfile.TemporaryDirectory(prefix="cover-install-") as tmp:
        work = Path(tmp)
        source = work / ("source" + Path(image).suffix)
        shutil.copyfile(image, source)
        try:
            stream = probe_media(source, runner)["video"]
            if stream is None:
                raise PackageError("ảnh cover không có luồng ảnh đọc được")
            sw, sh = int(stream["width"]), int(stream["height"])
            if sw <= 0 or sh <= 0:
                raise ValueError("invalid dimensions")
        except (RenderError, KeyError, TypeError, ValueError) as exc:
            raise PackageError("không đọc được ảnh cover: " + str(exc)) from exc
        x, y, bw, bh = _box(box, sw, sh)
        width, height = thumbnail.EPISODE_SIZES[shape]
        scale = max(width / sw, height / sh)
        scaled_w, scaled_h = math.ceil(sw * scale), math.ceil(sh * scale)
        crop_x, crop_y = (scaled_w - width) // 2, (scaled_h - height) // 2
        left, top = round(x * scaled_w / sw) - crop_x, round(y * scaled_h / sh) - crop_y
        right = round((x + bw) * scaled_w / sw) - crop_x
        bottom = round((y + bh) * scaled_h / sh) - crop_y
        normalized = _box([left, top, right - left, bottom - top], width, height)
        staged = work / "normalized.png"
        proc = runner(["ffmpeg", "-v", "error", "-y", "-noautorotate", "-i", str(source),
                       "-vf", f"scale={scaled_w}:{scaled_h},crop={width}:{height}:{crop_x}:{crop_y}:exact=1,setsar=1",
                       "-frames:v", "1", "-threads", "1", str(staged)])
        if proc.returncode != 0 or not staged.is_file() or not staged.stat().st_size:
            raise PackageError("không giải mã được ảnh cover: " + (_last_line(proc.stderr) or "no output"))
        entry = dict(file=f"{shape}.png", sha256=sha256_file(staged), box=normalized)
        if prompt is not None:
            entry["prompt"] = prompt
        doc["shapes"][shape] = entry
        folder.mkdir(parents=True, exist_ok=True)
        # Stage on the destination filesystem; keep the previous image for metadata-write rollback.
        with tempfile.TemporaryDirectory(prefix=".install-", dir=folder) as local:
            local = Path(local)
            new = local / "new.png"
            shutil.copyfile(staged, new)
            backup = local / "old.png"
            if destination.exists():
                shutil.copyfile(destination, backup)
            os.replace(new, destination)
            try:
                atomic_write_json(folder / "cover.json", doc)
            except BaseException:
                if backup.exists():
                    os.replace(backup, destination)
                else:
                    destination.unlink(missing_ok=True)
                raise
    return entry


def remove(config, pid, shape):
    from . import episode
    if shape not in thumbnail.EPISODE_SIZES:
        raise PackageError("khổ cover phải là vertical hoặc landscape")
    folder = directory(config, pid)
    path = episode._no_symlinks(folder / f"{shape}.png")
    doc = read(config, pid)
    if doc["shapes"].pop(shape, None) is not None:
        atomic_write_json(folder / "cover.json", doc)
        path.unlink(missing_ok=True)
    return doc


def number_line(number, box):
    """Fit the full Vietnamese ink and its shadow, then centre its baseline in the box."""
    text = f"TẬP {number}"
    font = Font(thumbnail.EPISODE_FONTS[FONT_NAME])
    check_glyphs(font, [text])
    x, y, w, h = box
    width, height = int(w * 0.8), int(h * 0.6)
    # _fit_line keeps a fixed reference baseline; using the same text centres this single label.
    size, _ = thumbnail._fit_line(text, FONT_NAME, max(12, height * 2), width,
                                reference=text, nominal_top=y + (h - height) / 2 + 2,
                                top=y + (h - height) / 2, bottom=y + (h + height) / 2,
                                shadow=2)
    ink_top, ink_bottom = font.ink_bounds(text, size)
    baseline = round(y + (h - (ink_bottom - ink_top + 2)) / 2 - ink_top)
    return thumbnail.EpisodeLine(text, FONT_NAME, size, x, baseline, w, centered=True)


def build_episode(work, fields, shape, image, filename, *, entry, run=None):
    _box(entry["box"], *thumbnail.EPISODE_SIZES[shape])
    line = number_line(fields["episode"], entry["box"])
    font = work / "cover.ttf"
    shutil.copyfile(thumbnail.EPISODE_FONTS[FONT_NAME], font)
    graph = "[0:v]setsar=1[base];" + thumbnail._draw_text(
        work, 0, line.text, line.size, "0xe8bf62", f"{line.x}+({line.width}-text_w)/2", line.y, "base",
        font_file=font, options=":y_align=baseline:shadowcolor=0x241507@0.65:shadowx=2:shadowy=2")
    return thumbnail._encode(work, graph + ";[text0]format=yuvj420p[out]", image, filename, run or _run)
