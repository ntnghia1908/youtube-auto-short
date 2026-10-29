"""COV1: one approved series cover per shape, with a deterministic episode number."""
from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from ..hashing import sha256_file
from ..render.stage import RenderError, _last_line, _run, probe_media
from ..render.text import Font, check_glyphs
from ..workspace import atomic_write_json, read_json_dict
from . import PackageError, assets, thumbnail

COVER_LAYOUT_VERSION = 4
FIT_WIDTH, FIT_HEIGHT = 0.8, 0.85  # share of the box the number ink (with diacritics) may fill
SIZES = dict(thumbnail.EPISODE_SIZES, kt_vertical=thumbnail.EPISODE_SIZES["vertical"],
             kt_landscape=thumbnail.EPISODE_SIZES["landscape"])
FONT_NAME = "old"  # Old Standard: lining figures; Playfair SC old-style digits read poorly (HUMAN LEAD 2026-10-28)


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
        if doc is None or doc.get("schema_version") not in (1, 2) or not isinstance(doc["shapes"], dict):
            raise PackageError("hồ sơ cover không hợp lệ")
        for shape, entry in doc["shapes"].items():
            if shape not in SIZES or not re.fullmatch(rf"{shape}(?:-[a-f0-9]{{64}})?\.png", entry["file"]) \
                    or not assets.SHA.fullmatch(entry["sha256"]) \
                    or "prompt" in entry and not isinstance(entry["prompt"], str):
                raise PackageError("hồ sơ cover không hợp lệ")
            _box(entry["box"], *SIZES[shape])
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
    if shape not in SIZES:
        raise PackageError("khổ cover không hợp lệ")
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
        width, height = SIZES[shape]
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
        if shape.startswith("kt_"):
            doc["schema_version"] = 2
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
    if shape not in SIZES:
        raise PackageError("khổ cover không hợp lệ")
    folder = directory(config, pid)
    doc = read(config, pid)
    entry = doc["shapes"].pop(shape, None)
    path = episode._no_symlinks(folder / (entry["file"] if entry else f"{shape}.png"))
    if entry is not None:
        atomic_write_json(folder / "cover.json", doc)
        path.unlink(missing_ok=True)
    return doc


def number_line(number, box, shape="vertical"):
    """Fit the full Vietnamese ink and its shadow, then centre its baseline in the box."""
    text = f"TẬP {number}"
    font = Font(thumbnail.EPISODE_FONTS[FONT_NAME])
    check_glyphs(font, [text])
    x, y, w, h = box
    width = int(w * FIT_WIDTH)
    height = min(int(h * FIT_HEIGHT), int(SIZES[shape][1] * (.08 if shape == "vertical" else .12)))
    # _fit_line keeps a fixed reference baseline; using the same text centres this single label.
    size, _ = thumbnail._fit_line(text, FONT_NAME, max(12, height * 2), width,
                                reference=text, nominal_top=y + (h - height) / 2 + 2,
                                top=y + (h - height) / 2, bottom=y + (h + height) / 2,
                                shadow=2)
    ink_top, ink_bottom = font.ink_bounds(text, size)
    baseline = round(y + (h - (ink_bottom - ink_top + 2)) / 2 - ink_top)
    return thumbnail.EpisodeLine(text, FONT_NAME, size, x, baseline, w, centered=True)


def build_episode(work, fields, shape, image, filename, *, entry, portrait=None, run=None):
    _box(entry["box"], *SIZES[shape])
    line = number_line(fields["episode"], entry["box"], shape)
    return draw_lines(work, [line], image, filename, portrait=portrait, shape=shape,
                      portrait_layout="episode", run=run)


def episode_portrait_box(shape, source_size):
    """Preserve aspect ratio; place episode cutouts above the vertical title or at the right."""
    width, height = SIZES[shape]
    sw, sh = source_size
    landscape = shape == "landscape"
    scale = min(height * (.92 if landscape else .46) / sh,
                width * (.50 if landscape else .84) / sw)
    pw, ph = max(1, round(sw * scale)), max(1, round(sh * scale))
    if landscape:
        return pw, ph, width - round(width * .015) - pw, height - ph
    return pw, ph, round((width - pw) / 2), round(height * .525) - ph


def portrait_box(shape, box, source_size):
    """Bottom-anchor an RGBA cutout without covering the writing surface."""
    width, height = SIZES[shape]
    sw, sh = source_size
    if shape == "landscape":
        ph = round(height * .92)
        pw = round(ph * sw / sh)
        # Keep the right edge flush; shrink wide portraits to at most 4% overlap.
        pw = min(pw, max(1, round(width - box[0] - box[2] + width * .04)))
        ph = min(ph, round(pw * sh / sw))
        pw = max(1, round(ph * sw / sh))
        return pw, ph, width - pw, height - ph
    ph = min(round(height * .48), height - box[1] - box[3])
    ph = max(1, min(ph, round(width * .84 * sh / sw)))
    pw = max(1, round(ph * sw / sh))
    return pw, ph, round(width * .42 - pw / 2), height - ph


def draw_lines(work, lines, image, filename, *, run=None, styles=None, portrait=None, shape=None, box=None,
               portrait_layout="kt"):
    """Shared COV1 encoder, with optional fonts, colors and portrait before text."""
    font = work / "cover.ttf"
    shutil.copyfile(thumbnail.EPISODE_FONTS[FONT_NAME], font)
    graph = "[0:v]setsar=1[base]"
    runner = run or _run
    if portrait is not None:
        stream = probe_media(portrait, runner)["video"]
        source_size = int(stream["width"]), int(stream["height"])
        pw, ph, px, py = (episode_portrait_box(shape, source_size) if portrait_layout == "episode"
                          else portrait_box(shape, box, source_size))
        fade = (",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                "a='alpha(X,Y)*min(1,(H-1-Y)/(H*0.18))'"
                if portrait_layout == "episode" and shape == "vertical" else "")
        local = work / "portrait.png"
        shutil.copyfile(portrait, local)
        graph = (f"[0:v]setsar=1[background];[1:v]scale={pw}:{ph},setsar=1,format=rgba{fade}[portrait];"
                 f"[background][portrait]overlay={px}:{py}:format=auto[base]")
        def encode_runner(cmd):
            index = cmd.index("-filter_complex_script")
            return runner(cmd[:index] + ["-i", str(local)] + cmd[index:])
    else:
        encode_runner = runner
    for index, line in enumerate(lines):
        color, shadow = "0xe8bf62", True
        line_font = font
        if styles is not None:
            style = styles[index]
            line_font = work / f"cover-{line.font}.ttf"
            shutil.copyfile(thumbnail.EPISODE_FONTS[line.font], line_font)
            color, shadow = style["color"], style["shadow"]
        graph += ";" + thumbnail._draw_text(
            work, index, line.text, line.size, color, f"{line.x}+({line.width}-text_w)/2", line.y,
            "base" if index == 0 else f"text{index - 1}", font_file=line_font,
            options=":y_align=baseline" + (":shadowcolor=0x241507@0.65:shadowx=2:shadowy=2" if shadow else ""))
    return thumbnail._encode(work, graph + f";[text{len(lines) - 1}]format=yuvj420p[out]",
                             image, filename, encode_runner)


def install_set(config, pid, images, *, prompt=None, run=None):
    """Prepare through the CLI validator, publish immutable images, swap one manifest.

    A crash before the manifest swap leaves only unreferenced images; readers keep the old set.
    """
    if set(images) != set(SIZES):
        raise PackageError("cần đủ bốn khổ ảnh bìa")
    return _install_shapes(config, pid, images, {}, prompt=prompt, run=run)


def install_kt(config, pid, images, *, prompt=None, run=None):
    """Publish just the KT pair; preserve existing episode entries byte for byte."""
    if set(images) != {"kt_vertical", "kt_landscape"}:
        raise PackageError("cần đủ hai khổ ảnh khai thị")
    entries = current(config, pid)
    if "vertical" not in entries:
        raise PackageError("bộ kinh chưa có bìa dọc")
    return _install_shapes(config, pid, images, dict(entries), prompt=prompt, run=run)


def _install_shapes(config, pid, images, entries, *, prompt=None, run=None):
    from . import episode
    folder = directory(config, pid)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cover-set-", dir=folder) as tmp:
        staging = replace(config, render=replace(config.render, output_dir=Path(tmp)))
        for shape, (image, box) in images.items():
            entry = install(staging, pid, shape, image, box, prompt=prompt, run=run)
            source = directory(staging, pid) / entry["file"]
            name = f"{shape}-{entry['sha256']}.png"
            dest = episode._no_symlinks(folder / name)
            os.replace(source, dest)
            entries[shape] = dict(entry, file=name)
        atomic_write_json(folder / "cover.json", dict(schema_version=2, shapes=entries))
    return entries
