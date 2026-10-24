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


def reusable(folder, entry, expected):
    path = folder / (entry.get("file") or "")
    return entry.get("key") == expected and record.FILE_NAME.fullmatch(entry.get("file") or "") \
        and path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_BYTES \
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
        (tmp / f"line{i}.txt").write_text(line, encoding="utf-8")
        x = "(w-text_w)/2" if template.centered else str(template.x)
        graph.append(f"[{'panel' if i == 0 else 'text' + str(i - 1)}]"
                     f"drawtext=fontfile=font.ttf:textfile=line{i}.txt:expansion=none:"
                     f"fontsize={layout.font_size}:fontcolor={template.text_color}:"
                     f"x={x}:y={round(top + i * pitch)}[text{i}]")
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
            shutil.copyfile(FONT, work / "font.ttf")
            inputs = []
            if image is not None:
                local = work / ("asset" + image.suffix)
                shutil.copyfile(image, local)
                inputs = ["-i", str(local)]
            graph = _graph(work, template, layout, image)
            graph = graph.replace("fontfile=font.ttf", "fontfile=" + escape_option(str(work / "font.ttf")))
            for i in range(len(layout.lines)):
                graph = graph.replace(f"textfile=line{i}.txt",
                                      "textfile=" + escape_option(str(work / f"line{i}.txt")))
            script = work / "graph.txt"
            script.write_text(graph, encoding="utf-8")
            filename = f"{template.name}-{expected}.jpg"
            output = work / filename
            # JPEG qscale: larger values mean lower quality / fewer bytes.
            for quality in (2, 5, 9, 15, 23, 31):
                proc = runner(["ffmpeg", "-v", "error", "-y", "-filter_complex_threads", "1", *inputs,
                               "-filter_complex_script", str(script), "-map", "[out]", "-frames:v", "1",
                               "-c:v", "mjpeg", "-threads", "1", "-q:v", str(quality), str(output)])
                if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
                    raise RenderError("thumbnail ffmpeg failed: " + (_last_line(proc.stderr) or "no output"))
                if output.stat().st_size <= MAX_BYTES:
                    break
            else:
                raise RenderError("thumbnail vượt quá 2 MB ở chất lượng JPEG tối thiểu")
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
