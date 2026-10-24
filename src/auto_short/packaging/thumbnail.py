"""Three versioned, single-frame ffmpeg compositions; no image dependencies."""
from __future__ import annotations

import os
import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from ..hashing import sha256_file
from ..render.plan import escape_option
from ..render.stage import RenderError, _last_line, _run
from ..render.text import Font, TextError, check_glyphs, fit_title, nfc, wrap_balanced, wrap_greedy
from . import PackageError, assets, record

FONT = Path(__file__).resolve().parents[1] / "render" / "fonts" / "BeVietnamPro-ExtraBold.ttf"
MAX_BYTES = 2 * 1024 * 1024
WIDTH, HEIGHT = 1280, 720


@dataclass(frozen=True)
class Template:
    name: str
    version: int
    colors: tuple[str, str]
    text_color: str
    x: int
    width: int
    centered: bool = False


TEMPLATES = {
    "classic": Template("classic", 1, ("0xffdd88", "0xa56a21"), "0x29190e", 64, 710),
    "minimal": Template("minimal", 1, ("0x152b33", "0x486976"), "white", 80, 1120),
    "scenic": Template("scenic", 1, ("0x183c35", "0x69a78d"), "white", 110, 1060, True),
}


def fit(headline, template, *, font=None):
    headline = nfc(headline).strip()
    font = font or Font(FONT)
    # Bound the combinatorial balanced wrapper for hostile / accidental huge input.
    if not headline or len(headline) > 300:
        raise TextError("headline không vừa tối đa 3 dòng ở cỡ chữ tối thiểu 48 px")
    headline = " ".join(headline.split())
    check_glyphs(font, [headline])
    minimum = wrap_greedy(font, headline, 48, template.width)
    if minimum is None or len(minimum) > 3:
        raise TextError("headline không vừa tối đa 3 dòng ở cỡ chữ tối thiểu 48 px; hãy rút ngắn")
    try:
        return fit_title(font, headline, size0=88, line_spacing=1.35, inner_width=template.width,
                         panel_height=400, max_panel_height=400, padding_y=35, min_font_scale=48 / 88)
    except TextError as exc:
        raise TextError("headline không vừa tối đa 3 dòng ở cỡ chữ tối thiểu 48 px; hãy rút ngắn") from exc


def key(doc, entry):
    template = TEMPLATES[entry["template"]]
    return record.cache_key(doc, template.name, template.version, entry["asset_ids"], sha256_file(FONT))


def reusable(folder, entry, expected, *, file_pattern=record.FILE_NAME):
    if not isinstance(entry, dict):
        return False
    match = file_pattern.fullmatch(entry.get("file") or "")
    if match is None or match[2] != expected or entry.get("key") != expected:
        return False
    path = folder / entry["file"]
    return path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_BYTES \
        and sha256_file(path) == entry.get("sha256")


def _graph(tmp, template, layout, image):
    # User text only enters textfiles (expansion=none), never the filtergraph.
    if image is None:
        graph = [f"gradients=s=1280x720:c0={template.colors[0]}:c1={template.colors[1]}:"
                 "x0=0:y0=0:x1=1280:y1=720:speed=0.00001:seed=0[base]"]
    elif template.name == "classic":
        graph = [f"color=c={template.colors[0]}:s=1280x720[bg]",
                 "[0:v]scale=440:720:force_original_aspect_ratio=increase,crop=440:720[portrait]",
                 "[bg][portrait]overlay=840:0[base]"]
    else:
        blur = ",boxblur=18:2" if template.name == "scenic" else ""
        graph = ["[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720" + blur + "[base]"]
    panel = "drawbox=x=0:y=125:w=1280:h=470:color=black@0.62:t=fill" \
        if template.name == "minimal" else "drawbox=x=0:y=0:w=1280:h=720:color=black@0.28:t=fill" \
        if template.name == "scenic" else "null"
    graph.append(f"[base]{panel}[panel]")
    pitch = layout.line_pitch
    top = (620 - (len(layout.lines) * pitch)) / 2
    for i, line in enumerate(layout.lines):
        x = "(w-text_w)/2" if template.centered else str(template.x)
        graph.append(_draw_text(tmp, i, line, layout.font_size, template.text_color, x,
                                round(top + i * pitch), "panel" if i == 0 else f"text{i - 1}"))
    graph.append(f"[text{len(layout.lines) - 1}]format=yuvj420p[out]")
    return ";\n".join(graph)


def build(folder: Path, doc: dict, asset_dir: Path, *, run=None) -> dict:
    """Stage all three before publication. A failed encode leaves the previous record/files intact."""
    record.validate(doc)
    runner = run or _run
    result = deepcopy(doc)
    folder.mkdir(parents=True, exist_ok=True)
    staged = []
    with tempfile.TemporaryDirectory(prefix=".thumbnail-", dir=folder) as tmpname:
        tmp = Path(tmpname)
        for entry in result["thumbnails"]:
            template = TEMPLATES[entry["template"]]
            layout = fit(result["headline"], template)
            image = None
            for ident in entry["asset_ids"]:
                _, image = assets.usable(asset_dir, ident, kind="image")
            expected = key(result, entry)
            if reusable(folder, entry, expected):
                continue
            work = tmp / template.name
            work.mkdir()
            filename = f"{template.name}-{expected}.jpg"
            output = _encode(work, _graph(work, template, layout, image), image, filename, runner)
            entry.update(template_version=template.version, file=filename, key=expected, sha256=sha256_file(output))
            staged.append((output, folder / filename))
        for source, dest in staged:
            os.replace(source, dest)
    return result


def ready(folder, doc, asset_dir):
    selected = next(t for t in doc["thumbnails"] if t["template"] == doc["selected"])
    for ident in selected["asset_ids"]:
        assets.usable(asset_dir, ident, kind="image")
    if not reusable(folder, selected, key(doc, selected)):
        raise PackageError("thumbnail chưa dựng hoặc đã đổi; hãy dựng lại")
    return selected


# Shared by PKG1 and PKG2; text never becomes filter syntax.
def _draw_text(work, index, text, size, color, x, y, previous):
    path = work / f"line{index}.txt"
    path.write_text(text, encoding="utf-8")
    return (f"[{previous}]drawtext=fontfile={escape_option(str(work / 'font.ttf'))}:"
            f"textfile={escape_option(str(path))}:expansion=none:fontsize={size}:"
            f"fontcolor={color}:x={x}:y={y}[text{index}]")


def _encode(work, graph, image, filename, runner):
    shutil.copyfile(FONT, work / "font.ttf")
    inputs = []
    if image is not None:
        local = work / ("asset" + image.suffix)
        shutil.copyfile(image, local)
        inputs = ["-i", str(local)]
    script = work / "graph.txt"
    script.write_text(graph, encoding="utf-8")
    output = work / filename
    for quality in (2, 5, 9, 15, 23, 31):
        proc = runner(["ffmpeg", "-v", "error", "-y", "-filter_complex_threads", "1", *inputs,
                       "-filter_complex_script", str(script), "-map", "[out]", "-frames:v", "1",
                       "-c:v", "mjpeg", "-threads", "1", "-q:v", str(quality), str(output)])
        if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            raise RenderError("thumbnail ffmpeg failed: " + (_last_line(proc.stderr) or "no output"))
        if output.stat().st_size <= MAX_BYTES:
            return output
    raise RenderError("thumbnail vượt quá 2 MB ở chất lượng JPEG tối thiểu")


EPISODE_LAYOUT_VERSION = 1
EPISODE_SIZES = {"landscape": (1280, 720), "vertical": (1080, 1920)}


def episode_text(header, shape):
    """Fit the series in <= 2 balanced lines; number and speaker each stay on one line."""
    font = Font(FONT)
    width = 760 if shape == "landscape" else 940
    texts = [nfc(str(header.get(k) or "")) for k in ("series", "episode", "speaker")]
    series, number, speaker = [" ".join(t.split()) for t in texts]
    if not series or len(series) > 300 or len(speaker) > 160 or len(number) > 9:
        raise TextError("header tập quá dài hoặc thiếu tên bộ kinh")
    number = "TẬP " + number
    check_glyphs(font, [series, number, speaker])
    for size in range(70 if shape == "landscape" else 90, 31, -1):
        lines = wrap_balanced(font, series, size, width, max_lines=2)
        if lines:
            break
    else:
        raise TextError("tên bộ kinh không vừa 2 dòng")
    result = [(ln, size, (120 if shape == "landscape" else 130) + i * size * 1.4)
              for i, ln in enumerate(lines)]
    for text, initial, top in ((number, 172 if shape == "landscape" else 240, 340 if shape == "landscape" else 440),
                                (speaker, 38 if shape == "landscape" else 52, 580 if shape == "landscape" else 810)):
        if not text:
            continue
        for size in range(initial, 23, -1):
            if wrap_balanced(font, text, size, width, max_lines=1):
                break
        else:
            raise TextError("dòng số tập / người giảng không vừa")
        result.append((text, size, top))
    return result


def build_episode(work, header, shape, image, filename, *, run=None):
    """Encode one staged episode JPEG. Publication belongs to packaging.episode."""
    width, height = EPISODE_SIZES[shape]
    colors = TEMPLATES["classic"].colors
    graph = [f"gradients=s={width}x{height}:c0={colors[0]}:c1={colors[1]}:"
             f"x0=0:y0=0:x1={width}:y1={height}:speed=0.00001:seed=0[bg]"]
    if image is not None:
        pw, ph, x, y = (440, 720, 840, 0) if shape == "landscape" else (1080, 960, 0, 960)
        graph += [f"[0:v]scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph}[portrait]",
                  f"[bg][portrait]overlay={x}:{y}[base]"]
    else:
        graph.append("[bg]null[base]")
    lines = episode_text(header, shape)
    for i, (text, size, y) in enumerate(lines):
        graph.append(_draw_text(work, i, text, size, "0x29190e", "64" if shape == "landscape" else "70",
                                round(y), "base" if i == 0 else f"text{i - 1}"))
    graph.append(f"[text{len(lines) - 1}]format=yuvj420p[out]")
    return _encode(work, ";\n".join(graph), image, filename, run or _run)
