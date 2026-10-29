"""Silent thumbnail inputs shared by VERT2 and KTI1; clip content keeps its encoded packets."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from .. import hashing
from ..workspace import read_json_dict
from . import plan

INTRO_SECONDS = 3


def inputs(image: Path, fps: Fraction, seconds=INTRO_SECONDS) -> list[str]:
    return ["-loop", "1", "-framerate", plan.fps_text(fps), "-t", str(seconds), "-i", str(image),
            "-f", "lavfi", "-t", str(seconds), "-i", f"anullsrc=r={plan.SAMPLE_RATE}:cl=stereo"]


def filters(fps: Fraction, *, color_correct=False) -> list[str]:
    color = "scale=out_color_matrix=bt709:out_range=tv," if color_correct else ""
    return [
        f"[1:v]fps={plan.fps_text(fps)},scale={plan.WIDTH}:{plan.HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={plan.WIDTH}:{plan.HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,{color}format={plan.PIX_FMT},"
        "setpts=PTS-STARTPTS[introv]",
        "[2:a]aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB[introa]",
        "[introv][introa][contentv][contenta]concat=n=2:v=1:a=1[vout][aout]",
    ]


def offset(record: dict) -> float:
    """Actual frame boundary, also for NTSC (90 / 29.97 rather than an off-grid 3 s)."""
    if not record.get("intro"):
        return 0.0
    try:
        value = float(record["content_offset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("độ lệch intro khai thị không hợp lệ") from exc
    if not 0 < value < INTRO_SECONDS + .1:
        raise ValueError("độ lệch intro khai thị không hợp lệ")
    return value


def content_record(record: dict) -> dict:
    """The pre-intro manifest entry, with the SHA of the original encoded content file."""
    result = deepcopy(record)
    if result.get("intro"):
        result["sha256"] = result.pop("content_sha256")
        result["render_key"] = result.pop("content_render_key")
        result.pop("intro")
        result.pop("content_offset")
    return result


def content_manifest(doc: dict) -> dict:
    result = deepcopy(doc)
    result.pop("content_workspace_manifest_sha256", None)
    result["shorts"] = [content_record(s) for s in result.get("shorts", [])]
    return result


def clip_record(path: Path) -> dict:
    """Local output, a kept favourite, or a private verified copy borrowed from the store."""
    sidecar = path.with_suffix(".intro.json")
    doc = read_json_dict(sidecar)
    if doc is not None:
        record = doc
    elif sidecar.exists():
        raise ValueError("sidecar intro khai thị không đọc được")
    else:
        doc = read_json_dict(path.parent.parent / "render_manifest.json") or {}
        record = next((s for s in doc.get("shorts", []) if s.get("file") == f"shorts/{path.name}"), {})
    if record.get("intro") and hashing.sha256_file(path) != record.get("sha256"):
        raise ValueError("clip có intro không khớp sha256 sidecar")
    return record


def prepend(content: Path, output: Path, image: Path, fps: Fraction, cfg, work: Path, run) -> float:
    """Encode only the picture, then mux it before the untouched content (whose first frame is an IDR).

    Using a second full encode would change content bytes, invalidate approved TC3 plans and cost CPU on
    every minute of every clip. The prefix uses VERT2's concat filter, bounded to its first three seconds.
    """
    from .stage import RenderError, _last_line
    from ..compilation.assemble import concat_command, list_line

    frames = round(INTRO_SECONDS * fps)
    seconds = frames / float(fps)
    graph, prefix, listing = work / "intro.filter", work / "intro.mp4", work / "intro.txt"
    graph.write_text(";".join(["[0:v]null[contentv]", "[0:a]anull[contenta]", *filters(fps, color_correct=True)]), encoding="utf-8")
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(content),
           *inputs(image, fps, seconds), "-filter_complex_script", str(graph),
           "-map", "[vout]", "-map", "[aout]", "-t", str(seconds),
           "-c:v", plan.VCODEC, "-preset", cfg.preset, "-crf", str(cfg.crf), "-pix_fmt", plan.PIX_FMT,
           "-r", plan.fps_text(fps), "-force_key_frames", str(INTRO_SECONDS),
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
           "-threads", str(cfg.threads), "-c:a", plan.ACODEC, "-b:a", cfg.audio_bitrate,
           "-ar", str(plan.SAMPLE_RATE), "-ac", str(plan.CHANNELS), "-f", "mp4", str(prefix)]
    proc = run(cmd)
    if proc.returncode:
        raise RenderError(f"ffmpeg intro: {_last_line(proc.stderr)}")
    # Duration overrides AAC packet rounding (e.g. 3.008 s); the content IDR starts exactly on the video grid.
    listing.write_text(list_line(prefix) + f"duration {seconds:.12f}\n" + list_line(content), encoding="utf-8")
    cmd = concat_command(listing, output)
    cmd.insert(1, "-copyts")
    cmd[-1:-1] = ["-avoid_negative_ts", "disabled"]
    proc = run(cmd)
    if proc.returncode or not output.is_file():
        raise RenderError(f"ffmpeg intro concat: {_last_line(proc.stderr)}")
    return seconds
