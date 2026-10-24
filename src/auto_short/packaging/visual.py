"""Loop once, stream-copy TC3 audio, and verify before publishing ambient media."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path

from ..hashing import sha256_file
from ..render.stage import RenderError, _last_line, _run, probe_media
from ..workspace import utc_now
from . import PackageError, variant
from .variant import VISUAL_CRF, VISUAL_FPS, VISUAL_GOP


def _call(run, args, *, level="error"):
    proc = run(["ffmpeg", "-hide_banner", "-v", level, "-nostdin", *args])
    if proc.returncode:
        raise RenderError("ambient ffmpeg failed: " + (_last_line(proc.stderr) or str(proc.returncode)))
    return proc


def _encode(preset):
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(VISUAL_CRF), "-threads", "2",
            "-pix_fmt", "yuv420p", "-g", str(VISUAL_GOP), "-keyint_min", str(VISUAL_GOP),
            "-sc_threshold", "0", "-flags", "+cgop"]


def _graph(spec, kind):
    v = spec["visual"]
    length, fade = v["loop_seconds"], min(v["crossfade"], v["loop_seconds"])
    frames = length * VISUAL_FPS
    graph = []
    if kind == "generated":
        a, b = variant.PRESETS[v["asset_id"].split(":")[1]]
        graph.append(f"gradients=s=1920x1080:r={VISUAL_FPS}:c0={a}:c1={b}:"
                     f"x0=0:y0=0:x1=1920:y1=1080:speed=0.0001:seed=0:d={length + fade}[base]")
    else:
        graph.append(f"[0:v]fps={VISUAL_FPS},setpts=PTS-STARTPTS,"
                     "scale=w='trunc(ih*dar/2)*2':h=ih,setsar=1[asset]")
        if v["fit"] == "blur":
            width, height = (1808, 1016) if v["motion"] == "kenburns" else (1920, 1080)
            graph.extend(["[asset]split=2[bg][fg]",
                          "[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
                          "boxblur=40:2,eq=brightness=-0.08[back]",
                          f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[front]",
                          "[back][front]overlay=(W-w)/2:(H-h)/2[base]"])
        else:
            graph.append("[asset]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080[base]")
    if kind == "image":
        if v["motion"] == "kenburns":
            graph.append(f"[base]scale=3840:2160,zoompan=z='1+0.06*(1-cos(2*PI*on/{frames}))/2':"
                         f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps={VISUAL_FPS}[loop]")
        else:
            graph.append("[base]null[loop]")
    else:
        # Rotate the source by C seconds: the tail fades into [0,C], then meets frame C at the seam.
        graph.extend(["[base]split=2[body][head]",
                      f"[body]trim=start={fade}:end={length + fade},setpts=PTS-STARTPTS[main]",
                      f"[head]trim=end={fade},setpts=PTS-STARTPTS[start]",
                      f"[main][start]xfade=transition=fade:duration={fade}:offset={length - fade}[loop]"])
    graph.append(f"[loop]trim=end_frame={frames},setsar=1,format=yuv420p[out]")
    return ";".join(graph)


def _geometry(info):
    v = info["video"] or {}
    if (v.get("width"), v.get("height"), v.get("sample_aspect_ratio"), v.get("codec_name"),
        v.get("pix_fmt")) != (1920, 1080, "1:1", "h264", "yuv420p") \
            or v.get("avg_frame_rate") not in ("30/1", "60/2"):
        raise RenderError("ambient video must be 1920×1080 SAR 1:1 H.264 yuv420p 30 fps")


def _decode(path, run):
    proc = _call(run, ["-xerror", "-err_detect", "explode", "-i", str(path), "-map", "0:v:0",
                       "-vf", "blackdetect=d=0.1", "-an", "-f", "null", "-"], level="info")
    if "black_start:" in proc.stderr:
        raise RenderError("ambient video contains black frames")


def check_loop(path, spec, run):
    info = probe_media(path, run)
    _geometry(info)
    frames = spec["visual"]["loop_seconds"] * VISUAL_FPS
    if int(info["video"].get("nb_frames", 0)) != frames or info["audio"] is not None:
        raise RenderError("ambient loop frame count/audio mismatch")
    _decode(path, run)
    graph = (f"[0:v]split=2[a][b];[a]select=eq(n\\,0),setpts=PTS-STARTPTS[first];"
             f"[b]select=eq(n\\,{frames - 1}),setpts=PTS-STARTPTS[last];[first][last]ssim[out]")
    proc = _call(run, ["-i", str(path), "-filter_complex_threads", "1", "-filter_complex", graph,
                       "-map", "[out]", "-an", "-f", "null", "-"], level="info")
    scores = re.findall(r"All:([0-9.]+)", proc.stderr)
    if not scores or not .97 <= float(scores[-1]) <= 1:
        raise RenderError("ambient loop seam SSIM below 0.97")
    return float(scores[-1])


def audio_hash(path, run):
    proc = _call(run, ["-i", str(path), "-map", "0:a:0", "-c", "copy", "-f", "streamhash",
                       "-hash", "sha256", "-"])
    match = re.search(r"^0,a,SHA256=([a-f0-9]{64})$", proc.stdout, re.M)
    if not match:
        raise RenderError("cannot verify ambient audio streamhash")
    return match[1]


def _check_full(path, duration, expected_audio, run, *, preview=False):
    info = probe_media(path, run)
    _geometry(info)
    v, a = info["video"], info["audio"] or {}
    vd, ad = float(v.get("duration", 0)), float(a.get("duration", 0))
    if a.get("codec_name") != "aac" or abs(vd - ad) > 2 + 1 / VISUAL_FPS \
            or abs(ad - duration) > .1:
        raise RenderError("ambient audio/video duration or codec mismatch")
    digest = audio_hash(path, run)
    if not preview and digest != expected_audio:
        raise RenderError("ambient audio differs from TC3")
    _decode(path, run)
    return digest, info["duration"]


def build(folder, tc3, meta, spec, asset_dir, *, run=None, preview=False, before_publish=None, publish_lock=None):
    """Only open TC3 as an input. TemporaryDirectory also unwinds on KeyboardInterrupt."""
    run = run or _run
    spec = variant.normalize(spec)
    kind, asset = variant.source(spec, asset_dir)  # approval precedes every possible ffmpeg call
    ident, loopkey = variant.key(spec, meta["sha256"]), variant.key(spec)
    folder.mkdir(parents=True, exist_ok=True)
    if not preview:
        try:
            cached = variant.read(folder, ident[:12])
        except PackageError:
            cached = None
        if cached and cached["tc3"] == variant.reference(tc3, meta) and variant.reusable(folder, cached):
            return cached
    if shutil.disk_usage(folder).free < 3 * 1024 ** 3:
        raise PackageError("ổ đĩa cần còn ít nhất 3 GB để dựng hình ambient")
    if tc3.is_symlink() or sha256_file(tc3) != meta["sha256"]:
        raise PackageError("TC3 đã đổi; hãy xuất lại")
    start = time.monotonic()
    published, complete = [], False
    work = tempfile.TemporaryDirectory(prefix=".tmp-", dir=folder)
    tmp = Path(work.name)

    def publish(source, dest):
        backup = None
        if dest.is_file() and not dest.is_symlink():
            backup = tmp / ("previous-" + dest.name)
            os.link(dest, backup)
        published.append((dest, backup))
        os.replace(source, dest)

    try:
        loop = folder / f"loop-{loopkey[:12]}.mp4"
        seam = None
        if loop.is_file() and not loop.is_symlink():
            try:
                seam = check_loop(loop, spec, run)
            except (RenderError, ValueError):
                pass
        if seam is None:
            loop = tmp / loop.name
            inputs = []
            if kind == "image":
                inputs = ["-loop", "1", "-framerate", str(VISUAL_FPS), "-i", str(asset)]
            elif kind == "loop":
                inputs = ["-i", str(asset)]
            _call(run, ["-y", "-filter_complex_threads", "1", *inputs, "-filter_complex", _graph(spec, kind),
                        "-map", "[out]", "-frames:v", str(spec["visual"]["loop_seconds"] * VISUAL_FPS),
                        "-an", *_encode("slow"), "-movflags", "+faststart", str(loop)])
            seam = check_loop(loop, spec, run)
        info = probe_media(tc3, run)
        audio = info["audio"] or {}
        duration = float(audio.get("duration") or info["duration"])
        if audio.get("codec_name") != "aac" or duration <= 0:
            raise PackageError("TC3 phải có audio AAC hợp lệ")
        if preview:
            duration = min(20, duration)
        expected_audio = audio_hash(tc3, run)
        name = f"{'preview' if preview else 'variant'}-{ident[:12]}.mp4"
        output = tmp / name
        for method in ("copy", "reencode"):
            try:
                _call(run, ["-y", "-stream_loop", "-1", "-i", str(loop), "-i", str(tc3),
                            "-map", "0:v:0", "-map", "1:a:0",
                            *(["-c:v", "copy"] if method == "copy" else _encode("veryfast")),
                            "-c:a", "copy", "-t", str(duration), "-movflags", "+faststart", str(output)])
                digest, actual_duration = _check_full(output, duration, expected_audio, run, preview=preview)
                break
            except (RenderError, ValueError):
                if method == "reencode":
                    raise
        result = dict(schema_version=1, key=ident, loop_key=loopkey, spec=spec, encoding=variant.encoding(),
                      tc3=variant.reference(tc3, meta), chapters=deepcopy(meta["chapters"]),
                      description=meta["description"], sha256=sha256_file(output), size=output.stat().st_size,
                      duration=actual_duration, checks=dict(width=1920, height=1080, sar="1:1",
                      audio_streamhash=digest, seam_ssim=seam, black=False, method=method),
                      build_seconds=round(time.monotonic() - start, 3), built_at=utc_now(), approved_at=None)
        if not preview:
            variant.write(tmp, result)
        if sha256_file(tc3) != meta["sha256"]:
            raise PackageError("TC3 đã đổi trong khi dựng")
        with publish_lock or nullcontext():
            try:
                if before_publish:
                    before_publish()
                if loop.parent == tmp:
                    dest = folder / loop.name
                    publish(loop, dest)
                publish(output, folder / name)
                if not preview:
                    sidecar = f"variant-{ident[:12]}.json"
                    publish(tmp / sidecar, folder / sidecar)
                else:
                    for old in folder.glob("preview-*.mp4"):
                        if old.name != name and variant.MEDIA_NAME.fullmatch(old.name):
                            backup = tmp / ("previous-" + old.name)
                            published.append((old, backup))
                            os.replace(old, backup)
                complete = True
            finally:
                if not complete:
                    for path, backup in reversed(published):
                        if backup is not None and backup.exists():
                            os.replace(backup, path)
                        elif backup is None:
                            path.unlink(missing_ok=True)
        return result
    finally:
        work.cleanup()
