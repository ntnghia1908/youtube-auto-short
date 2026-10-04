"""Vertical full-episode version (CP8.27 H4, Amendment 2): ``work/<id>/source_hd.mp4`` -> ``<output_dir>/<id>/full/vertical.mp4``.

1080x1920 like a Short, in the yellow rounded panel style: top panel = bộ kinh + "(tập N)", bottom panel = the speaker
("HT. Tịnh Không", larger font), and the video between them, centre-cropped and scaled up so only even margins of
``[render] min_frame_margin`` stay black; no dissolve, no silence trim (every frame and every audio sample of the HD
source). Reused (no encode) while ``vertical.json`` holds the same key (HD sha256, layout, header, render config).
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .. import hashing, khaithi
from ..config import Config
from ..enhance import state as enhance_state
from ..workspace import Workspace, WorkspaceError, atomic_write_json, validate_episode_id
from . import plan
from .stage import (RenderError, _last_line, _read_json, _run, _sha, _write_lines, font_path, probe_media, used_config,
                    _rate)
from .text import Font, TextError, baselines, fit_header, nfc

log = logging.getLogger("auto_short")

FULL_DIR = "full"
VIDEO_NAME = "vertical.mp4"
META_NAME = "vertical.json"
TOP_SCALE = 1.6  # top panel font size / [render] header font size (Amendment 2: "phóng chữ để lấp đen")
SPEAKER_SCALE = 2.4  # speaker font size / [render] header font size (even larger than the top panel)
TOP_SHARE = 0.43  # share of the panel height (video box excluded) taken by the top panel
_SPEAKER_DOT_RE = re.compile(r"\.(?=[^\W\d_])")  # CP8.16 R5: "HT.Tịnh Không" -> "HT. Tịnh Không"
FULL_PLAN_VERSION = 3  # bump when the filter graph / ffmpeg command below changes
DURATION_TOLERANCE = 0.1  # s, audio length vs the source


@dataclass
class FullResult:
    episode_id: str
    path: Path
    ran: bool  # False = reused
    seconds: float
    size: int


def owner_of(episode_id: str) -> str:
    """The video a khai thị episode (``<id>.kt``) belongs to; the HD source and the vertical file are the video's."""
    sfx = khaithi.SUFFIX
    return episode_id[:-len(sfx)] if episode_id.endswith(sfx) and len(episode_id) > len(sfx) else episode_id


def vertical_dir(config: Config, episode_id: str) -> Path:
    return (Path(config.render.output_dir) / owner_of(episode_id) / FULL_DIR).resolve()


def vertical_path(config: Config, episode_id: str) -> Path:
    return vertical_dir(config, episode_id) / VIDEO_NAME


def read_meta(config: Config, episode_id: str) -> dict | None:
    try:
        doc = json.loads((vertical_dir(config, episode_id) / META_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def ready_file(config: Config, episode_id: str) -> Path | None:
    """The finished vertical file (meta present, size matches), else None."""
    meta, path = read_meta(config, episode_id), vertical_path(config, episode_id)
    try:
        if meta is None or not path.is_file() or path.stat().st_size != meta.get("size"):
            return None
    except OSError:
        return None
    return path


def current(config: Config, episode_id: str) -> bool:
    """True when the stored vertical file matches the HD source now there (nothing to re-encode)."""
    path = ready_file(config, episode_id)
    meta = read_meta(config, episode_id)
    if path is None or meta is None:
        return False
    hd = enhance_state.hd_fingerprint(Path(config.workspace.dir) / owner_of(episode_id))
    return hd is not None and meta.get("hd_sha256") == hd.sha256


@dataclass(frozen=True)
class FullLayout:
    top: plan.Box
    video: plan.Box
    bottom: plan.Box
    crop: plan.Crop

    def as_dict(self) -> dict:
        return {"top_panel": self.top.as_dict(), "video": self.video.as_dict(), "bottom_panel": self.bottom.as_dict(),
                "crop": [self.crop.w, self.crop.h, self.crop.x, self.crop.y]}


def full_layout(geo: plan.Geometry, src_w: int, src_h: int) -> FullLayout:
    """The video box and crop of the first CP8.27 version (Short V16 video box, ``[render] video_height``); the rest of
    the height is shared by the two panels (``TOP_SHARE`` / the remainder) with the same spacing ``s`` (= top margin =
    gaps = bottom margin), so only the margins stay black."""
    s = geo.min_frame_margin
    video_h = geo.video_h
    panels = plan.HEIGHT - 4 * s - video_h
    top_h = round(panels * TOP_SHARE)
    bottom_h = panels - top_h
    x = (plan.WIDTH - geo.header_w) // 2
    top = plan.Box(x, s, geo.header_w, top_h, geo.radius)
    video = plan.Box(0, s + top_h + s, plan.WIDTH, video_h)
    bottom = plan.Box(x, video.y + video_h + s, geo.header_w, bottom_h, geo.radius)
    return FullLayout(top, video, bottom, plan.center_crop(src_w, src_h, plan.WIDTH, video_h))


def _one_line(font: Font, text: str, size0: int, panel_height: int, min_scale: float, fit_kw: dict):
    """The speaker line on ONE line: the largest font size <= ``size0`` where it fits the panel width (a wrapped
    "HT. Tịnh / Không" is worse than a smaller font); several lines only below ``min_scale`` x ``size0``."""
    fit_kw = {**fit_kw, "min_font_scale": 1.0}
    for size in range(size0, round(size0 * min_scale) - 1, -1):
        try:
            fit = fit_header(font, [text], size0=size, panel_height=panel_height, **fit_kw)
        except TextError:
            continue
        if len(fit.lines) == 1:
            return fit
    return fit_header(font, [text], size0=size0, panel_height=panel_height, **{**fit_kw, "min_font_scale": min_scale})


def split_header(lines: list[str], speaker: str | None) -> tuple[list[str], str]:
    """(top panel lines, speaker line): the speaker line (titles.json ``fields.speaker``, else the first header line)
    leaves the header lines; the rest (bộ kinh + "(tập N)") is the top panel. Dot-space after an abbreviation dot."""
    spk = nfc(speaker) if isinstance(speaker, str) and speaker.strip() else lines[0]
    rest = [ln for ln in lines if ln != spk] or list(lines)
    return rest, _SPEAKER_DOT_RE.sub(". ", spk)


def filter_graph(*, fps: Fraction, lay: FullLayout, font_file: Path, top_lines: list[plan.TextLine], top_size: int,
                 bottom_lines: list[plan.TextLine], bottom_size: int) -> str:
    """The Short chain without cuts / title panel: every frame (``fps=`` only normalises the rate), all audio."""
    c, v = lay.crop, lay.video
    per_frame = (f"crop={c.w}:{c.h}:{c.x}:{c.y},scale={v.w}:{v.h}:flags={plan.SCALE_FLAGS},setsar=1,"
                 f"scale=out_color_matrix=bt709:out_range=tv,format=yuv444p")
    pad = f"pad={plan.WIDTH}:{plan.HEIGHT}:{v.x}:{v.y}:color={plan._hex(plan.BACKGROUND)}[vid]"
    return ";".join([
        f"[0:v]fps={plan.fps_text(fps)},{per_frame},{pad}",
        plan._panel_chain(lay.top, top_lines, font_file, top_size, "hp"),
        plan._panel_chain(lay.bottom, bottom_lines, font_file, bottom_size, "bp"),
        f"[vid][hp]overlay={lay.top.x}:{lay.top.y}:format=yuv444[v1]",
        f"[v1][bp]overlay={lay.bottom.x}:{lay.bottom.y}:format=yuv444,format={plan.PIX_FMT}[vout]",
        f"[0:a]aresample={plan.SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo[aout]",
    ])


def ffmpeg_command(*, ffmpeg: str, source: Path, output: Path, graph_script: Path, fps: Fraction, crf: int,
                   preset: str, audio_bitrate: str, threads: int) -> list[str]:
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(source),
        "-filter_complex_script", str(graph_script), "-map", "[vout]", "-map", "[aout]",
        "-c:v", plan.VCODEC, "-preset", preset, "-crf", str(crf), "-pix_fmt", plan.PIX_FMT, "-r", plan.fps_text(fps),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-threads", str(threads),
        "-c:a", plan.ACODEC, "-b:a", audio_bitrate, "-ar", str(plan.SAMPLE_RATE), "-ac", str(plan.CHANNELS),
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-movflags", "+faststart", "-f", "mp4", str(output),
    ]


def verify(path: Path, fps: Fraction, src: dict, run) -> dict:
    """1080x1920 h264 yuv420p aac 48 kHz stereo; video length within one frame of the source, audio within 0.1 s."""
    info = probe_media(path, run)
    v, a = info["video"], info["audio"]
    problems = []
    src_v = float((src["video"] or {}).get("duration") or src["duration"] or 0)
    if v is None:
        problems.append("no video stream")
    else:
        got, want = (v.get("codec_name"), v.get("width"), v.get("height"), v.get("pix_fmt")), \
            ("h264", plan.WIDTH, plan.HEIGHT, plan.PIX_FMT)
        if got != want:
            problems.append(f"video {got} != {want}")
        vd = float(v.get("duration") or 0)
        if abs(vd - src_v) > 1 / float(fps) + 1e-3:
            problems.append(f"video duration {vd:.3f} s != source {src_v:.3f} s")
    if a is None:
        problems.append("no audio stream")
    else:
        got, want = (a.get("codec_name"), int(a.get("sample_rate") or 0), a.get("channels")), \
            ("aac", plan.SAMPLE_RATE, plan.CHANNELS)
        if got != want:
            problems.append(f"audio {got} != {want}")
        ad = float(a.get("duration") or 0)
        src_a = float((src["audio"] or {}).get("duration") or src["duration"] or 0)
        if abs(ad - src_a) > DURATION_TOLERANCE:
            problems.append(f"audio duration {ad:.3f} s != source {src_a:.3f} s")
    if problems:
        raise RenderError(f"{path.name}: output check failed: {'; '.join(problems)}")
    return {"duration": float((v or {}).get("duration") or 0), "frames": (v or {}).get("nb_frames")}


def run_vertical(episode_id: str, config: Config, *, run=None, force: bool = False) -> FullResult:
    """Make (or reuse) the vertical full-episode file of the video ``episode_id`` (a ``.kt`` id means its video)."""
    runner = run or _run
    owner = owner_of(episode_id)
    try:
        ws = Workspace(config.workspace.dir, validate_episode_id(owner))
    except WorkspaceError as exc:
        raise RenderError(str(exc)) from exc
    hd = enhance_state.hd_fingerprint(ws.dir)
    if hd is None:
        raise RenderError(f"chưa có bản HD của {owner!r} (cần enhance xong trước)")
    cfg = config.render
    titles_path = ws.dir / "titles.json"
    if not titles_path.is_file():
        raise RenderError(f"chưa có tiêu đề (titles.json) của {owner!r}; chạy xử lý tập trước")
    titles = _read_json(titles_path, "titling")
    lines = [nfc(x) for x in ((titles.get("header") or {}).get("lines") or []) if isinstance(x, str)]
    if not lines:
        raise RenderError(f"titles.json của {owner!r} không có header")
    top_text, speaker = split_header(lines, ((titles.get("header") or {}).get("fields") or {}).get("speaker"))
    fpath = font_path(cfg)
    if not fpath.is_file():
        raise RenderError(f"font file not found: {fpath} (config render.font_file)")
    font_sha = hashing.sha256_file(fpath)
    font = Font(fpath)
    src = probe_media(hd.path, runner)
    if src["video"] is None or src["audio"] is None:
        raise RenderError(f"bản HD cần có cả video và audio: {hd.path}")
    fps = plan.output_fps(_rate(src["video"]))
    try:
        geo = plan.geometry(cfg)
        lay = full_layout(geo, int(src["video"]["width"]), int(src["video"]["height"]))
        fit_kw = dict(line_spacing=cfg.line_spacing, inner_width=geo.header_w - 2 * cfg.panel_padding_x * plan.WIDTH,
                      padding_y=cfg.panel_padding_y * plan.WIDTH, min_font_scale=cfg.min_font_scale)
        header = fit_header(font, top_text, size0=round(plan.px(cfg.header_font_size) * TOP_SCALE),
                            panel_height=lay.top.h, **fit_kw)
        spk_fit = _one_line(font, speaker, round(plan.px(cfg.header_font_size) * SPEAKER_SCALE), lay.bottom.h,
                            cfg.min_font_scale, fit_kw)
    except (plan.PlanError, TextError) as exc:
        raise RenderError(str(exc)) from exc
    key = _sha({"full_plan_version": FULL_PLAN_VERSION, "plan_version": plan.RENDER_PLAN_VERSION,
                "render_config_hash": hashing.config_hash(used_config(cfg, font_sha)), "font_sha256": font_sha,
                "hd_sha256": hd.sha256, "fps": plan.fps_text(fps),
                "layout": lay.as_dict(),
                "header": {"display_lines": header.lines, "font_size": header.font_size},
                "speaker": {"display_lines": spk_fit.lines, "font_size": spk_fit.font_size}})
    out_dir = vertical_dir(config, owner)
    out = out_dir / VIDEO_NAME
    meta = read_meta(config, owner)
    ready = ready_file(config, owner)
    if not force and ready is not None and meta is not None and meta.get("key") == key:
        log.info("full: %s: reuse (key unchanged)", owner)
        return FullResult(owner, ready, False, 0.0, ready.stat().st_size)
    out_dir.mkdir(parents=True, exist_ok=True)
    part = out_dir / f".{VIDEO_NAME}.part"
    t0 = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="auto-short-full-") as tmpname:
            tmp = Path(tmpname)
            h_lines = _write_lines(tmp, "h", header.lines, baselines(len(header.lines), font=font, size=header.font_size,
                                                                     pitch=header.line_pitch, panel_height=lay.top.h))
            b_lines = _write_lines(tmp, "b", spk_fit.lines, baselines(len(spk_fit.lines), font=font, size=spk_fit.font_size,
                                                                      pitch=spk_fit.line_pitch, panel_height=lay.bottom.h))
            script = tmp / "full.filter"
            script.write_text(filter_graph(fps=fps, lay=lay, font_file=fpath, top_lines=h_lines,
                                           top_size=header.font_size, bottom_lines=b_lines,
                                           bottom_size=spk_fit.font_size), encoding="utf-8")
            log.info("full: %s: encode %s (%.0f s, fps %s, threads %s)", owner, hd.path.name, src["duration"],
                     plan.fps_text(fps), cfg.threads or "auto")
            proc = runner(ffmpeg_command(ffmpeg="ffmpeg", source=hd.path, output=part, graph_script=script, fps=fps,
                                         crf=cfg.crf, preset=cfg.preset, audio_bitrate=cfg.audio_bitrate,
                                         threads=cfg.threads))
        if proc.returncode != 0 or not part.is_file():
            raise RenderError(f"ffmpeg failed: {_last_line(proc.stderr) or f'exit {proc.returncode}'}")
        facts = verify(part, fps, src, runner)
        for stale in (out_dir / META_NAME,):
            stale.unlink(missing_ok=True)
        os.replace(part, out)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    size = out.stat().st_size
    atomic_write_json(out_dir / META_NAME, {"schema_version": 1, "key": key, "hd_sha256": hd.sha256, "size": size,
                                            "fps": plan.fps_text(fps), "header": header.lines, "speaker": spk_fit.lines, "layout": lay.as_dict(),
                                            "duration": facts["duration"], "frames": facts["frames"],
                                            "seconds": round(time.monotonic() - t0, 1)})
    secs = time.monotonic() - t0
    log.info("full: %s: vertical %.1f MB in %.1f s", owner, size / 1e6, secs)
    return FullResult(owner, out, True, secs, size)
