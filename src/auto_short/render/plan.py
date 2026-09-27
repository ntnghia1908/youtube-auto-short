"""Pure render planning: kept segments (R3), pixel layout (R4) and the ffmpeg command (R6).

Canonical contract: docs/decisions/CP7-render-contract.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

WIDTH, HEIGHT = 1080, 1920  # CP1 §2
BACKGROUND = "#000000"  # CP1 §4
PANEL_COLOR = "#FEDB00"  # CP1 §4
MAX_FPS = Fraction(30)  # CP1 §2: keep the source rate when <= 30, else 30
VCODEC, PIX_FMT, ACODEC = "libx264", "yuv420p", "aac"
SAMPLE_RATE, CHANNELS = 48000, 2
SCALE_FLAGS = "lanczos"


class PlanError(Exception):
    """Inconsistent input data (segments) or impossible layout."""


# --- R3: kept segments -------------------------------------------------------------------------------------------

def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def kept_segments(source_start: float, source_end: float, trims: list[list[float]]) -> list[tuple[int, int]]:
    """``[source_start, source_end]`` minus the trims that intersect it, in integer milliseconds (CP4 A8,
    CP5 B11 "Cho CP7": a trim cut by ``source_start`` only counts its part inside the clip)."""
    start, end = _ms(source_start), _ms(source_end)
    if end <= start:
        raise PlanError(f"empty clip range [{source_start}, {source_end}]")
    cuts = sorted((max(_ms(a), start), min(_ms(b), end)) for a, b in trims)
    cuts = [(a, b) for a, b in cuts if a < b]
    out, pos = [], start
    for a, b in cuts:
        if a < pos:
            raise PlanError(f"overlapping trims around {a / 1000:.3f} s")
        if a > pos:
            out.append((pos, a))
        pos = b
    if pos < end:
        out.append((pos, end))
    return out


def segments_seconds(segments: list[tuple[int, int]]) -> list[list[float]]:
    return [[a / 1000, b / 1000] for a, b in segments]


def total_ms(segments: list[tuple[int, int]]) -> int:
    return sum(b - a for a, b in segments)


def check_duration(clip_id: str, segments: list[tuple[int, int]], duration: float) -> None:
    got = total_ms(segments)
    if abs(got - _ms(duration)) > 1:
        raise PlanError(f"clip {clip_id}: kept segments total {got / 1000:.3f} s but clips.json duration is "
                        f"{duration:.3f} s; data inconsistent, re-run 'auto-short analysis' and 'selection'")


def frame_plan(segments: list[tuple[int, int]], fps: Fraction) -> list[tuple[int, int]]:
    """For each segment: (first source frame index on the output frame grid, frame count).

    Frame counts come from the rounded cumulative output time, so the video length stays within half a
    frame of the audio length (sample exact) however many segments there are."""
    out, cum = [], 0
    for a, b in segments:
        first = round(Fraction(a, 1000) * fps)
        n = round(Fraction(cum + b - a, 1000) * fps) - round(Fraction(cum, 1000) * fps)
        out.append((first, n))
        cum += b - a
    return out


# --- Video dissolve at junctions (CP8.1 V2) -------------------------------------------------------------------

@dataclass(frozen=True)
class DissolvePlan:
    """Per junction j (between segments j and j+1): ``frames[j]`` = D_j blended frames (0 = hard cut).
    Per segment i: ``extend[i]`` = (e_in, e_out) frames borrowed from the trimmed gap before / after it."""

    frames: list[int]
    extend: list[tuple[int, int]]

    @property
    def active(self) -> bool:
        return any(self.frames)


def dissolve_half(seconds: float, fps: Fraction) -> int:
    """Target frames on each side of a junction: ``e = round(seconds x fps / 2)`` (0.15 s @ 29.97 -> 2)."""
    return round(Fraction(seconds) * fps / 2)


def dissolve_plan(frames: list[tuple[int, int]], fps: Fraction, seconds: float) -> DissolvePlan:
    """Dissolve length per junction from the frame plan (V2): ``e_j = min(e, gap // 2)`` where ``gap`` is the
    number of grid frames trimmed between the segments, so the extension never leaves the trimmed silence (and
    never the clip: the first/last segment are not extended outwards). Guard beyond V2: a segment gives at
    most half its own frames to each side (``n // 2``), so consecutive dissolve windows never overlap and every
    ``xfade`` input is long enough; it only bites for segments shorter than 2e frames."""
    e = dissolve_half(seconds, fps)
    d = []
    for (f0, n0), (f1, n1) in zip(frames, frames[1:]):
        gap = f1 - (f0 + n0)
        d.append(2 * max(0, min(e, gap // 2, n0 // 2, n1 // 2)))
    k = len(frames)
    extend = [(d[i - 1] // 2 if i > 0 else 0, d[i] // 2 if i < k - 1 else 0) for i in range(k)]
    return DissolvePlan(d, extend)


def junction_frames(frames: list[tuple[int, int]]) -> list[int]:
    """Output frame index of each junction (first frame of segment j+1 on the Short's timeline)."""
    out, cum = [], 0
    for _, n in frames[:-1]:
        cum += n
        out.append(cum)
    return out


def dissolves(segments: list[tuple[int, int]], fps: Fraction, seconds: float) -> list[dict]:
    """``render_manifest.json`` ``shorts[].dissolves`` (V4): one entry per junction, ``at`` = junction time on
    the Short's video timeline (s, 3 decimals; centre of the blend), ``frames`` = D_j."""
    frames = frame_plan(segments, fps)
    dp = dissolve_plan(frames, fps, seconds)
    return [{"at": float(round(Fraction(c) / fps, 3)), "frames": dj}
            for c, dj in zip(junction_frames(frames), dp.frames)]


def output_fps(source_fps: Fraction) -> Fraction:
    return source_fps if source_fps <= MAX_FPS else MAX_FPS


def fps_text(fps: Fraction) -> str:
    return str(fps.numerator) if fps.denominator == 1 else f"{fps.numerator}/{fps.denominator}"


# --- R4: layout --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int
    radius: int = 0

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h, "radius": self.radius}


@dataclass(frozen=True)
class Crop:
    w: int
    h: int
    x: int
    y: int


@dataclass(frozen=True)
class Layout:
    header: Box
    video: Box
    crop: Crop
    title: Box

    def as_dict(self) -> dict:
        v = self.video
        return {"header_panel": self.header.as_dict(),
                "video": {"x": v.x, "y": v.y, "w": v.w, "h": v.h,
                          "crop": {"w": self.crop.w, "h": self.crop.h, "x": self.crop.x, "y": self.crop.y}},
                "title_panel": self.title.as_dict()}


def px(ratio: float) -> int:
    return round(ratio * WIDTH)


def even(n: int) -> int:
    return n + (n % 2)


def center_crop(src_w: int, src_h: int, out_w: int, out_h: int) -> Crop:
    """Largest centred crop of the source with the output aspect (scale-to-fill), even sizes."""
    if src_w * out_h > out_w * src_h:  # source wider -> crop width
        w = min(src_w, even(round(src_h * out_w / out_h)))
        return Crop(w, src_h, (src_w - w) // 2, 0)
    h = min(src_h, even(round(src_w * out_h / out_w)))
    return Crop(src_w, h, 0, (src_h - h) // 2)


@dataclass(frozen=True)
class Geometry:
    """Pixel sizes derived from the [render] ratios (R4)."""

    header_w: int
    header_h: int
    video_h: int
    title_w: int
    title_h: int
    gap_header_video: int
    gap_video_title: int
    radius: int
    min_frame_margin: int

    @property
    def fixed_height(self) -> int:
        """Content block height without the title panel."""
        return self.header_h + self.gap_header_video + self.video_h + self.gap_video_title

    @property
    def title_max_h(self) -> int:
        """Tallest title panel that keeps the content block inside the frame with ``min_frame_margin``."""
        return HEIGHT - 2 * self.min_frame_margin - self.fixed_height


def geometry(cfg) -> Geometry:
    g = Geometry(header_w=px(cfg.header_panel_width), header_h=px(cfg.header_panel_height),
                 video_h=even(px(cfg.video_height)), title_w=px(cfg.title_panel_width),
                 title_h=px(cfg.title_panel_height), gap_header_video=px(cfg.gap_header_video),
                 gap_video_title=px(cfg.gap_video_title), radius=px(cfg.panel_radius),
                 min_frame_margin=px(cfg.min_frame_margin))
    if g.title_max_h < g.title_h:
        raise PlanError(f"layout does not fit {WIDTH}x{HEIGHT}: content block {g.fixed_height + g.title_h} px "
                        f"with min_frame_margin {g.min_frame_margin} px")
    for name, w in (("header_panel_width", g.header_w), ("title_panel_width", g.title_w)):
        if w > WIDTH:
            raise PlanError(f"render.{name} gives {w} px > frame width {WIDTH}")
    return g


def layout(g: Geometry, title_h: int, src_w: int, src_h: int) -> Layout:
    """Content block (header, video, title) centred vertically; panels centred horizontally."""
    top = (HEIGHT - (g.fixed_height + title_h)) // 2
    header = Box((WIDTH - g.header_w) // 2, top, g.header_w, g.header_h, g.radius)
    vy = top + g.header_h + g.gap_header_video
    video = Box(0, vy, WIDTH, g.video_h)
    title = Box((WIDTH - g.title_w) // 2, vy + g.video_h + g.gap_video_title, g.title_w, title_h, g.radius)
    return Layout(header, video, center_crop(src_w, src_h, WIDTH, g.video_h), title)


# --- R6: ffmpeg command ------------------------------------------------------------------------------------------

def escape_option(value: str) -> str:
    """Escape a filter option value for the filtergraph parser (two levels, see ffmpeg-filters "Notes on
    filtergraph escaping")."""
    level1 = "".join("\\" + c if c in "\\':" else c for c in value)
    return "".join("\\" + c if c in "\\'[],;" else c for c in level1)


def _num(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".")


def _hex(color: str) -> str:
    return "0x" + color.lstrip("#")


def panel_alpha(w: int, h: int, r: int) -> str:
    """geq alpha of a rounded rectangle with 1 px anti-aliased edges."""
    dx = f"max(max({r}-X-0.5,X+0.5-{w - r}),0)"
    dy = f"max(max({r}-Y-0.5,Y+0.5-{h - r}),0)"
    return f"255*clip({r}-hypot({dx},{dy})+0.5,0,1)"


@dataclass(frozen=True)
class TextLine:
    textfile: Path  # UTF-8 file holding exactly the line (no newline)
    baseline: int  # px from the panel top


def _panel_chain(box: Box, lines: list[TextLine], font_file: Path, size: int, label: str) -> str:
    r, g, b = (int(PANEL_COLOR[i:i + 2], 16) for i in (1, 3, 5))
    parts = [f"color=c={_hex(PANEL_COLOR)}:s={box.w}x{box.h}:r=1:d=1", "format=rgba",
             f"geq=r={r}:g={g}:b={b}:a='{panel_alpha(box.w, box.h, box.radius)}'"]
    for line in lines:
        parts.append(f"drawtext=fontfile={escape_option(str(font_file))}:textfile={escape_option(str(line.textfile))}"
                     f":expansion=none:text_shaping=1:fontsize={size}:fontcolor=black"
                     f":x=(w-text_w)/2:y_align=baseline:y={line.baseline}")
    parts += ["scale=out_color_matrix=bt709:out_range=tv", "format=yuva444p"]
    return ",".join(parts) + f"[{label}]"


def _video_cut(frames: list[tuple[int, int]], f: str, per_frame: str, pad: str) -> str:
    """CP7 video chain: one ``select`` of all kept frames on the absolute grid (hard cuts)."""
    sel = "+".join(f"between(n_grid,{first},{first + n - 1})" for first, n in frames if n > 0)
    # n_grid = index of the frame on the absolute output grid (t * fps); fps= puts frames on that grid.
    sel = sel.replace("n_grid", f"round(t*{f})")
    return f"[0:v]fps={f},select='{sel}',setpts=N/({f})/TB,{per_frame},{pad}"


def _video_dissolve(frames: list[tuple[int, int]], fps: Fraction, dp: DissolvePlan, per_frame: str,
                    pad: str) -> list[str]:
    """V3: one branch per segment (``split`` + ``trim`` of the extended range + per-frame conversions), joined
    left to right with ``xfade=transition=fade`` over D_j frames (``concat`` when D_j = 0); ``pad`` after."""
    f = fps_text(fps)
    idx = [i for i, (_, n) in enumerate(frames) if n > 0]  # segments shorter than half a frame have no video
    m = len(idx)
    chain = [f"[0:v]fps={f},split={m}" + "".join(f"[s{i}]" for i in idx)]
    for i in idx:
        (first, n), (e_in, e_out) = frames[i], dp.extend[i]
        # after fps= the pts are the grid indices (time base 1/fps), so this trim keeps exactly the frames of
        # select='between(round(t*fps),lo,hi)' but ends the branch after its last frame: concat/xfade move on
        # without buffering the later segments until the end of the input (select only ends at input EOF).
        chain.append(f"[s{i}]trim=start_pts={first - e_in}:end_pts={first + n + e_out},"
                     f"setpts=PTS-STARTPTS,{per_frame}[v{i}]")
    cur, length = f"v{idx[0]}", sum(dp.extend[idx[0]]) + frames[idx[0]][1]
    for prev, i in zip(idx, idx[1:]):
        d = dp.frames[i - 1] if i == prev + 1 else 0  # a skipped empty segment in between: its junctions are 0
        out = f"x{i}"
        if d == 0:
            chain.append(f"[{cur}][v{i}]concat=n=2:v=1:a=0,settb=1/({f}),setpts=N[{out}]")
        else:
            chain.append(f"[{cur}][v{i}]xfade=transition=fade:duration={_num(float(Fraction(d) / fps))}"
                         f":offset={_num(float(Fraction(length - d) / fps))}[{out}]")
        length += frames[i][1] + sum(dp.extend[i]) - d
        cur = out
    chain.append(f"[{cur}]setpts=N/({f})/TB,{pad}")
    return chain


def filter_graph(*, segments: list[tuple[int, int]], fps: Fraction, lay: Layout, font_file: Path,
                 header_lines: list[TextLine], header_size: int, title_lines: list[TextLine],
                 title_size: int, dissolve: float = 0.0) -> str:
    """R6 filter graph. ``dissolve`` (s, CP8.1): video dissolve at junctions; when no junction gets a dissolve
    (``dissolve = 0``, one segment, or every gap too short) the graph is exactly the CP7 one."""
    frames = frame_plan(segments, fps)
    f = fps_text(fps)
    c, v = lay.crop, lay.video
    per_frame = (f"crop={c.w}:{c.h}:{c.x}:{c.y},scale={v.w}:{v.h}:flags={SCALE_FLAGS},setsar=1,"
                 f"scale=out_color_matrix=bt709:out_range=tv,format=yuv444p")
    pad = f"pad={WIDTH}:{HEIGHT}:{v.x}:{v.y}:color={_hex(BACKGROUND)}[vid]"
    dp = dissolve_plan(frames, fps, dissolve)
    video = _video_dissolve(frames, fps, dp, per_frame, pad) if dp.active else [_video_cut(frames, f, per_frame, pad)]
    k = len(segments)
    audio = [f"[0:a]asplit={k}" + "".join(f"[as{i}]" for i in range(k)) if k > 1 else "[0:a]anull[as0]"]
    for i, (a, b) in enumerate(segments):
        audio.append(f"[as{i}]atrim=start={_num(a / 1000)}:end={_num(b / 1000)},asetpts=PTS-STARTPTS[a{i}]")
    audio.append("".join(f"[a{i}]" for i in range(k)) + f"concat=n={k}:v=0:a=1,"
                 f"aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB[aout]")
    return ";".join([
        *video,
        _panel_chain(lay.header, header_lines, font_file, header_size, "hp"),
        _panel_chain(lay.title, title_lines, font_file, title_size, "tp"),
        f"[vid][hp]overlay={lay.header.x}:{lay.header.y}:format=yuv444[v1]",
        f"[v1][tp]overlay={lay.title.x}:{lay.title.y}:format=yuv444,format={PIX_FMT}[vout]",
        *audio,
    ])


def input_window(segments: list[tuple[int, int]], fps: Fraction) -> tuple[float, float]:
    """(seek, read duration) in seconds: from one second before the first kept frame to one frame after the
    last, so the input-seeked decode covers every selected frame and sample."""
    start = max(0.0, segments[0][0] / 1000 - 1.0)
    end = segments[-1][1] / 1000 + 2 / float(fps)
    return start, end - start


def ffmpeg_command(*, ffmpeg: str, source: Path, output: Path, graph_script: Path, segments: list[tuple[int, int]],
                   fps: Fraction, crf: int, preset: str, audio_bitrate: str, threads: int) -> list[str]:
    seek, length = input_window(segments, fps)
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-y",
        "-ss", _num(seek), "-t", _num(length), "-copyts", "-i", str(source),
        "-filter_complex_script", str(graph_script),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", VCODEC, "-preset", preset, "-crf", str(crf), "-pix_fmt", PIX_FMT, "-r", fps_text(fps),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-threads", str(threads),
        "-c:a", ACODEC, "-b:a", audio_bitrate, "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-movflags", "+faststart", "-f", "mp4", str(output),
    ]


def planned_frames(segments: list[tuple[int, int]], fps: Fraction) -> int:
    return sum(n for _, n in frame_plan(segments, fps))


def planned_video_seconds(segments: list[tuple[int, int]], fps: Fraction) -> float:
    return planned_frames(segments, fps) / float(fps)
