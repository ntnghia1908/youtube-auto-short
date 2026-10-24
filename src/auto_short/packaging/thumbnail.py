"""Three versioned, single-frame ffmpeg compositions; no image dependencies."""
from __future__ import annotations

import os
import math
import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from ..hashing import sha256_file
from ..render.plan import escape_option
from ..render.stage import RenderError, _last_line, _run
from ..render.text import Font, TextError, check_glyphs, fit_title, nfc, wrap_greedy
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
def _draw_text(work, index, text, size, color, x, y, previous, *, font_file=None, options=""):
    path = work / f"line{index}.txt"
    path.write_text(text, encoding="utf-8")
    return (f"[{previous}]drawtext=fontfile={escape_option(str(font_file or work / 'font.ttf'))}:"
            f"textfile={escape_option(str(path))}:expansion=none:fontsize={size}:"
            f"fontcolor={color}:x={x}:y={y}{options}[text{index}]")


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


EPISODE_LAYOUT_VERSION = 4  # baseline/ink-height fitting and preservation of portrait alpha
EPISODE_SIZES = {"landscape": (1280, 720), "vertical": (1080, 1920)}
EPISODE_FONTS = {
    "serif": FONT.parent / "PlayfairDisplaySC-Bold.ttf",
    "old": FONT.parent / "OldStandard-Bold.ttf",
    "anton": FONT.parent / "Anton-Regular.ttf",
    "sans": FONT,
}
STYLE_FONTS = {"A": ("serif", "old", "sans"), "B": ("anton", "old"), "C": ("old",)}


def font_hashes(style):
    return {name: sha256_file(EPISODE_FONTS[name]) for name in STYLE_FONTS[style]}


def white_background(image, work, *, run=None):
    """Read RGB pixels at the four original corners, without resizing or a binary runner API."""
    output = work / "corners.rgb"
    graph = ("[0:v]format=rgb24,split=4[a][b][c][d];[a]crop=1:1:0:0[tl];"
             "[b]crop=1:1:iw-1:0[tr];[c]crop=1:1:0:ih-1[bl];[d]crop=1:1:iw-1:ih-1[br];"
             "[tl][tr][bl][br]hstack=inputs=4[out]")
    proc = (run or _run)(["ffmpeg", "-v", "error", "-y", "-filter_complex_threads", "1", "-i", str(image),
                          "-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-threads", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", str(output)])
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size != 12:
        raise RenderError("không lấy được mẫu bốn góc ảnh: " + (_last_line(proc.stderr) or "invalid RGB samples"))
    return all(channel >= 240 for channel in output.read_bytes())


@dataclass(frozen=True)
class EpisodeLine:
    text: str
    font: str
    size: int
    x: int
    y: int
    width: int
    gold: bool = False
    color: str = "white"
    centered: bool = False


def _fit_line(text, font_name, size, width, *, reference, nominal_top, top, bottom, gold=False, shadow=0):
    font = Font(EPISODE_FONTS[font_name])
    check_glyphs(font, [text])
    above, below = (5, 9) if gold else (2, 2 + shadow)  # stroke/shadow + 2px hinting allowance
    # Fit the constant reference first: the slot baseline is independent of user text,
    # including short titles which would otherwise choose a larger width-only font size.
    for reference_size in range(size, 11, -1):
        ink_top, ink_bottom = font.ink_bounds(reference, reference_size)
        baseline = math.ceil(nominal_top - ink_top)
        if font.width(reference, reference_size) <= width * 0.98 \
                and baseline + ink_top - above >= top and baseline + ink_bottom + below <= bottom:
            break
    else:
        raise TextError(f"font không vừa khung {width}px × {bottom - top}px")
    for fitted in range(size, 11, -1):
        ink_top, ink_bottom = font.ink_bounds(text, fitted)
        if font.width(text, fitted) <= width * 0.98 \
                and baseline + ink_top - above >= top and baseline + ink_bottom + below <= bottom:
            return fitted, baseline
    raise TextError(f"dòng chữ không vừa khung {width}px × {bottom - top}px: {text!r}")


def episode_text(header, shape, settings):
    """Measured single lines within each style's text region; portraits never share that region."""
    style = settings["style"]
    vertical = shape == "vertical"
    x, width = ((70, 940) if vertical else ((540, 660) if style == "C" else (64, 560)))
    font = {"A": "serif", "B": "anton", "C": "old"}[style]
    sizes = (90, 180, 78) if vertical else {"A": (64, 150, 62), "B": (64, 118, 84), "C": (56, 92, 50)}[style]
    tops = (130, 270, 494) if vertical else {"A": (70, 150, 305), "B": (100, 180, 318), "C": (70, 150, 280)}[style]
    colors = {"A": "0xffefb0", "B": "white", "C": "0x5a3412"}
    lines = []
    shadow = 4 if style == "B" else 0
    title_padding = 5 if style == "A" else 2
    credit_top = 720 if vertical else (425 if style == "B" else 400 if style == "A" else 530)
    bx, by, bw, bh = episode_badge(style, shape)
    references = ("KINH", "ĐỊA TẠNG", "BỒ TÁT BỔN NGUYỆN") if style != "C" else ("Kinh", "Địa Tạng", "Bồ Tát Bổn Nguyện")
    slots = (0, 1, 2) if len(settings["title_lines"]) == 3 else ((1, 2) if len(settings["title_lines"]) == 2 else (1,))
    for i, text in zip(slots, settings["title_lines"]):
        text = nfc(text).upper() if style in ("A", "B") else nfc(text)
        color = "0xf3dfa6" if style == "C" and i == 2 else colors[style]
        inset = 24 if style == "C" and i == 2 else 0
        line_width = width - 2 * inset
        top = tops[i] - title_padding
        bottom = (tops[i + 1] - title_padding if i < 2 else min(credit_top, by)) - 4
        if inset:
            ribbon_top, ribbon_height = (480, 110) if vertical else (268, 78)
            top = max(top, ribbon_top + 6)
            bottom = min(bottom, ribbon_top + ribbon_height - 6)
        fitted, baseline = _fit_line(text, font, sizes[i], line_width, reference=references[i],
                                     nominal_top=tops[i], top=top, bottom=bottom, gold=style == "A", shadow=shadow)
        lines.append(EpisodeLine(text, font, fitted, x + inset, baseline, line_width,
                                 gold=style == "A", color=color, centered=bool(inset)))
    credit = settings["credit"]
    if credit:
        font = "sans" if style == "A" else "old"
        fitted, baseline = _fit_line(credit, font, 42 if vertical else 26, width,
            reference="CHỦ GIẢNG: PHÁP SƯ TỊNH KHÔNG", nominal_top=credit_top,
            top=credit_top - 2, bottom=by - 4 if credit_top < by else EPISODE_SIZES[shape][1] - 24,
            shadow=shadow)
        lines.append(EpisodeLine(credit, font, fitted, x, baseline, width,
                                 color={"A": "0xe8d6b0", "B": "0xd9c08a", "C": "0x4a3a2a"}[style]))
    number = ("Tập " if style == "C" else "TẬP ") + header["episode"]
    fitted, baseline = _fit_line(number, "old", 90 if vertical else 88 if style == "C" else 64, bw - 24,
        reference="Tập 102" if style == "C" else "TẬP 102",
        nominal_top=by + (10 if vertical or style == "C" else 8), top=by + 3, bottom=by + bh - 3,
        gold=style != "C", shadow=shadow)
    lines.append(EpisodeLine(number, "old", fitted, bx + 12, baseline, bw - 24,
                             gold=style != "C", color="0x8a1c14", centered=True))
    return lines


def episode_badge(style, shape):
    if shape == "vertical":
        return 280, 850, 520, 126
    return (700, 390, 480, 110) if style == "C" else (64, 480, 320, 92)


class _EpisodeGraph:
    """Small graph composer for the approved prototypes; all labels/options are internal constants."""
    def __init__(self, work, width, height):
        self.work, self.width, self.height = work, width, height
        self.parts, self.index = [], 0

    def add(self, filters, *sources):
        self.index += 1
        label = f"s{self.index}"
        self.parts.append("".join(f"[{s}]" for s in sources) + filters + f"[{label}]")
        return label

    def text(self, base, line, *, color=None, dx=0, dy=0, options=""):
        self.index += 1
        x = f"{line.x}+({line.width}-text_w)/2" if line.centered else str(line.x)
        self.parts.append(_draw_text(self.work, self.index, line.text, line.size, color or line.color,
                                     f"({x})+{dx}", line.y + dy, base,
                                     font_file=self.work / (line.font + ".ttf"), options=":y_align=baseline" + options))
        return f"text{self.index}"

    def gold_text(self, base, line):
        shadow = self.text(base, line, color="0x2a1606", dx=3, dy=4,
                           options=":borderw=3:bordercolor=0x2a1606")
        mask = self.add(f"color=c=black:s={self.width}x{self.height}")
        mask = self.text(mask, line, color="white")
        mask = self.add("format=gray", mask)
        ink_top, ink_bottom = Font(EPISODE_FONTS[line.font]).ink_bounds(line.text, line.size)
        gradient = self.add(f"gradients=s={self.width}x{self.height}:c0=0xfff3b0:c1=0xb8862b:"
                            f"x0=0:y0={round(line.y + ink_top)}:x1=0:y1={round(line.y + ink_bottom)}:nb_colors=2:speed=0.00001:seed=0,format=rgba")
        fill = self.add("alphamerge", gradient, mask)
        return self.add("overlay=0:0", shadow, fill)


def _portrait(graph, shape, style, focus, white):
    vertical = shape == "vertical"
    if vertical:
        w, h, x, y = 1080, 860 if style == "B" else 940, 0, 980
    elif style == "C":
        w, h, x, y = 500, 720, 0, 0
    else:
        w, h, x, y = 640, 560 if style == "B" else 720, 640, 80 if style == "B" else 0
    crop = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:'min(iw-{w},max(0,iw*{focus}-{w}/2))':0,format=rgba")
    mask = ",colorkey=0xffffff:0.12:0.08" if white else (
        ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        "a='alpha(X,Y)*clip(2.2*(1-hypot((X-W*0.56)/(W*0.52),(Y-H*0.58)/(H*0.62))),0,1)*clip(X/180,0,1)'")
    return graph.add(crop + mask, "0:v"), x, y


def build_episode(work, header, shape, image, filename, *, settings, run=None):
    """Encode one staged A/B/C JPEG; the caller owns publication and preview cleanup."""
    width, height = EPISODE_SIZES[shape]
    style = settings["style"]
    lines = episode_text(header, shape, settings)  # validate glyphs / fit before ffmpeg
    for name in STYLE_FONTS[style]:
        shutil.copyfile(EPISODE_FONTS[name], work / (name + ".ttf"))
    g = _EpisodeGraph(work, width, height)
    if style == "A":
        base = g.add(f"color=c=0x16100b:s={width}x{height},format=rgb24,"
                     f"geq=r='22+70*exp(-((X-{width * .28})^2+(Y-{height * .46})^2)/90000)':"
                     f"g='16+45*exp(-((X-{width * .28})^2+(Y-{height * .46})^2)/90000)':"
                     f"b='11+18*exp(-((X-{width * .28})^2+(Y-{height * .46})^2)/90000)'")
    elif style == "B":
        base = g.add(f"color=c=0x0c0a08:s={width}x{height}")
        for y in (0, height - 80):
            bar = g.add(f"gradients=s={width}x80:c0=0xf7d774:c1=0xa8761c:c2=0xf3d27a:c3=0x9a6a18:"
                        f"x0=0:y0=0:x1={width}:y1=80:nb_colors=4:speed=0.00001:seed=0")
            base = g.add(f"overlay=0:{y}", base, bar)
    else:
        # Paper with a restrained, deterministic ink wash; no additional external art asset.
        base = g.add(f"color=c=0xf1e6cf:s={width}x{height},format=rgb24,"
                     f"geq=r='241-25*(X/{width})^2-12*exp(-((X-{width*.18})^2+(Y-{height*.7})^2)/60000)':"
                     f"g='230-28*(X/{width})^2-12*exp(-((X-{width*.18})^2+(Y-{height*.7})^2)/60000)':"
                     f"b='207-30*(X/{width})^2-12*exp(-((X-{width*.18})^2+(Y-{height*.7})^2)/60000)'")
    if image is not None:
        portrait, x, y = _portrait(g, shape, style, settings["focus_x"], white_background(image, work, run=run))
        base = g.add(f"overlay={x}:{y}", base, portrait)
    if style == "A":
        base = g.add("vignette=PI/5", base)
    if style == "C":
        x, y, w, h = (70, 480, 940, 110) if shape == "vertical" else (540, 268, 660, 78)
        base = g.add(f"drawbox=x={x}:y={y}:w={w}:h={h}:color=0x2f4a34:t=fill,"
                     f"drawbox=x={x+8}:y={y+8}:w={w-16}:h={h-16}:color=0xd8b56a:t=2", base)
    bx, by, bw, bh = episode_badge(style, shape)
    if style != "C" or shape == "vertical":
        color = "0xf1e6cf" if style == "C" else "0xb3261e"
        base = g.add(f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color={color}:t=fill,"
                     f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=0xf2c46a:t=3", base)
    for line in lines:
        base = g.gold_text(base, line) if line.gold else g.text(base, line,
                options=":shadowx=4:shadowy=4:shadowcolor=black@0.7" if style == "B" else "")
    g.parts.append(f"[{base}]format=yuvj420p[out]")
    return _encode(work, ";\n".join(g.parts), image, filename, run or _run)
