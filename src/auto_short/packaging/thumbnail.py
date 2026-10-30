"""PKG2 single-frame ffmpeg episode thumbnails in styles A/B/C. No image dependencies."""
from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..hashing import sha256_file
from ..render.plan import escape_option
from ..render.stage import RenderError, _last_line, _run
from ..render.text import Font, TextError, check_glyphs, nfc

FONT = Path(__file__).resolve().parents[1] / "render" / "fonts" / "BeVietnamPro-ExtraBold.ttf"
MAX_BYTES = 2 * 1024 * 1024


def reusable(folder, entry, expected, *, file_pattern):
    if not isinstance(entry, dict):
        return False
    match = file_pattern.fullmatch(entry.get("file") or "")
    if match is None or match[2] != expected or entry.get("key") != expected:
        return False
    path = folder / entry["file"]
    return path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_BYTES \
        and sha256_file(path) == entry.get("sha256")


# Text never becomes filter syntax: it only enters textfiles (expansion=none).
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

# The fixed PKG2 style A palette. Theme presets were retired by THUMB2.
EPISODE_PALETTE = dict(base=(22, 16, 11), glow=(70, 45, 18), gold=("0xfff3b0", "0xb8862b"), badge="0xb3261e")


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


def _fit_line(text, font_name, size, width, *, reference, nominal_top, top, bottom, gold=False, shadow=0, floor=12):
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
    for fitted in range(size, floor - 1, -1):
        ink_top, ink_bottom = font.ink_bounds(text, fitted)
        if font.width(text, fitted) <= width * 0.98 \
                and baseline + ink_top - above >= top and baseline + ink_bottom + below <= bottom:
            return fitted, baseline
    raise TextError(f"dòng chữ không vừa khung {width}px × {bottom - top}px: {text!r}")


def _text(style, shape, title_lines, credits, badge_text, badge, floors=(12, 12, 12)):
    """Measured single lines within each style's text region; portraits never share that region.

    ``credits`` holds 0-2 texts (already cased); one credit reproduces the episode layout exactly.
    ``floors`` = smallest accepted font size of (title, credit, badge): a line that needs less does not fit."""
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
    bx, by, bw, bh = badge
    references = ("KINH", "ĐỊA TẠNG", "BỒ TÁT BỔN NGUYỆN") if style != "C" else ("Kinh", "Địa Tạng", "Bồ Tát Bổn Nguyện")
    slots = (0, 1, 2) if len(title_lines) == 3 else ((1, 2) if len(title_lines) == 2 else (1,))
    for i, text in zip(slots, title_lines):
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
                                     nominal_top=tops[i], top=top, bottom=bottom, gold=style == "A", shadow=shadow,
                                     floor=floors[0])
        lines.append(EpisodeLine(text, font, fitted, x + inset, baseline, line_width,
                                 gold=style == "A", color=color, centered=bool(inset)))
    if credits:
        font = "sans" if style == "A" else "old"
        color = {"A": "0xe8d6b0", "B": "0xd9c08a", "C": "0x4a3a2a"}[style]
        size = 42 if vertical else 26
        bottom = by - 4 if credit_top < by else EPISODE_SIZES[shape][1] - 24
        reference = "CHỦ GIẢNG: PHÁP SƯ TỊNH KHÔNG"
        if len(credits) == 1:
            fitted, baseline = _fit_line(credits[0], font, size, width, reference=reference, nominal_top=credit_top,
                                         top=credit_top - 2, bottom=bottom, shadow=shadow, floor=floors[1])
            lines.append(EpisodeLine(credits[0], font, fitted, x, baseline, width, color=color))
        else:
            # Both lines share one size. The second baseline is measured from the real ink of the two texts
            # (accents above, dots below, shadow) so they never touch; shrink until it also ends above the badge.
            face = Font(EPISODE_FONTS[font])
            check_glyphs(face, credits)
            for fitted in range(size, floors[1] - 1, -1):
                first, baseline = _fit_line(credits[0], font, fitted, width, reference=reference,
                                            nominal_top=credit_top, top=credit_top - 2, bottom=bottom,
                                            shadow=shadow, floor=floors[1])
                top_1, bottom_1 = face.ink_bounds(credits[0], fitted)
                top_2, bottom_2 = face.ink_bounds(credits[1], fitted)
                second = baseline + math.ceil(bottom_1 - top_2) + shadow + 4
                if first == fitted and face.width(credits[1], fitted) <= width * 0.98 \
                        and second + bottom_2 + 2 + shadow <= bottom:
                    break
            else:
                raise TextError(f"dòng ghi công không vừa khung {width}px: {credits!r}")
            lines.extend(EpisodeLine(text, font, fitted, x, base, width, color=color)
                         for text, base in zip(credits, (baseline, second)))
    fitted, baseline = _fit_line(badge_text, "old", 90 if vertical else 88 if style == "C" else 64, bw - 24,
        reference="Tập 102" if style == "C" else "TẬP 102",
        nominal_top=by + (10 if vertical or style == "C" else 8), top=by + 3, bottom=by + bh - 3,
        gold=style != "C", shadow=shadow, floor=floors[2])
    lines.append(EpisodeLine(badge_text, "old", fitted, bx + 12, baseline, bw - 24,
                             gold=style != "C", color="0x8a1c14", centered=True))
    return lines


def episode_text(header, shape, settings):
    style = settings["style"]
    number = ("Tập " if style == "C" else "TẬP ") + header["episode"]
    credit = settings["credit"]
    return _text(style, shape, settings["title_lines"], [credit] if credit else [], number,
                 episode_badge(style, shape))


def episode_badge(style, shape):
    if shape == "vertical":
        return 280, 850, 520, 126
    return (700, 390, 480, 110) if style == "C" else (64, 480, 320, 92)


class _EpisodeGraph:
    """Small graph composer for the approved prototypes; all labels/options are internal constants."""
    def __init__(self, work, width, height, gold=("0xfff3b0", "0xb8862b")):
        self.work, self.width, self.height, self.gold = work, width, height, gold
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
        gradient = self.add(f"gradients=s={self.width}x{self.height}:c0={self.gold[0]}:c1={self.gold[1]}:"
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


def _render(work, shape, image, filename, *, style, lines, focus_x, badge, run=None):
    """Compose and encode one episode JPEG."""
    width, height = EPISODE_SIZES[shape]
    palette = EPISODE_PALETTE
    for name in STYLE_FONTS[style]:
        shutil.copyfile(EPISODE_FONTS[name], work / (name + ".ttf"))
    g = _EpisodeGraph(work, width, height, palette["gold"])
    if style == "A":
        (r0, g0, b0), (r1, g1, b1) = palette["base"], palette["glow"]
        glow = f"exp(-((X-{width * .28})^2+(Y-{height * .46})^2)/90000)"
        base = g.add(f"color=c=0x{r0:02x}{g0:02x}{b0:02x}:s={width}x{height},format=rgb24,"
                     f"geq=r='{r0}+{r1}*{glow}':g='{g0}+{g1}*{glow}':b='{b0}+{b1}*{glow}'")
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
        portrait, x, y = _portrait(g, shape, style, focus_x, white_background(image, work, run=run))
        base = g.add(f"overlay={x}:{y}", base, portrait)
    if style == "A":
        base = g.add("vignette=PI/5", base)
    if style == "C":
        x, y, w, h = (70, 480, 940, 110) if shape == "vertical" else (540, 268, 660, 78)
        base = g.add(f"drawbox=x={x}:y={y}:w={w}:h={h}:color=0x2f4a34:t=fill,"
                     f"drawbox=x={x+8}:y={y+8}:w={w-16}:h={h-16}:color=0xd8b56a:t=2", base)
    bx, by, bw, bh = badge
    if style != "C" or shape == "vertical":
        color = "0xf1e6cf" if style == "C" else palette["badge"] if style == "A" else "0xb3261e"
        base = g.add(f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color={color}:t=fill,"
                     f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=0xf2c46a:t=3", base)
    for line in lines:
        base = g.gold_text(base, line) if line.gold else g.text(base, line,
                options=":shadowx=4:shadowy=4:shadowcolor=black@0.7" if style == "B" else "")
    g.parts.append(f"[{base}]format=yuvj420p[out]")
    return _encode(work, ";\n".join(g.parts), image, filename, run or _run)


def build_episode(work, header, shape, image, filename, *, settings, run=None):
    """Encode one staged A/B/C JPEG; the caller owns publication and preview cleanup."""
    style = settings["style"]
    lines = episode_text(header, shape, settings)  # validate glyphs / fit before ffmpeg
    return _render(work, shape, image, filename, style=style, lines=lines, focus_x=settings["focus_x"],
                   badge=episode_badge(style, shape), run=run)
