"""AUD1: preserve video packets and voice gain while adding approved, looped music."""
from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
import time
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path

from ..hashing import sha256_file
from ..render.stage import RenderError, _run, probe_media
from ..theme_render import audio
from ..workspace import utc_now
from . import PackageError, assets, variant
from .visual import _call

MUSIC_VERSION = 1
AAC_FRAME = 1024 / 48000


def encoding(audio_bitrate="192k"):
    if not isinstance(audio_bitrate, str) or not re.fullmatch(r"[1-9][0-9]*k", audio_bitrate):
        raise PackageError("audio_bitrate không hợp lệ")
    return dict(music_version=MUSIC_VERSION, audio_bitrate=audio_bitrate)


def measure(path, run):
    """Read only the final ebur128 summary, not the per-frame diagnostics."""
    proc = _call(run, ["-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=true",
                       "-vn", "-f", "null", "-"], level="info")
    summary = proc.stderr.rsplit("Summary:", 1)[-1]
    loudness = re.findall(r"\bI:\s*([-+\w.]+)\s*LUFS", summary)
    peak = re.findall(r"\bPeak:\s*([-+\w.]+)\s*dBFS", summary)
    try:
        values = float(loudness[-1]), float(peak[-1])
        if not all(math.isfinite(x) for x in values):
            raise ValueError
        return values
    except (ValueError, IndexError):
        raise PackageError("không đo được loudness / true peak audio") from None


def video_hash(path, run):
    proc = _call(run, ["-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "streamhash",
                       "-hash", "sha256", "-"])
    match = re.search(r"^0,v,SHA256=([a-f0-9]{64})$", proc.stdout, re.M)
    if not match:
        raise RenderError("không xác minh được streamhash hình")
    return match[1]


def video_source(folder, tc3, meta, spec):
    if spec["visual"] is None:
        return tc3, dict(key="tc3", sha256=meta["sha256"])
    ident = variant.key({"visual": spec["visual"]}, meta["sha256"])
    try:
        doc = variant.read(folder, ident[:12])
        if doc is None or doc["tc3"] != variant.reference(tc3, meta) or not variant.reusable(folder, doc):
            raise PackageError("missing source")
    except PackageError:
        raise PackageError("hãy dựng hình ambient trước (bản không nhạc, cùng TC3)") from None
    return folder / f"variant-{ident[:12]}.mp4", dict(key=ident, sha256=doc["sha256"])


def loop_unit(path, output, crossfade, run):
    """Rotate to C, crossfade tail into [0,C]; the resulting L-C unit ends at C."""
    # Compressed music can report duration including encoder padding. Decode to obtain the exact
    # sample duration before choosing the tail; WAV also makes mono / resampling deterministic.
    with tempfile.TemporaryDirectory(prefix=".loop-", dir=output.parent) as work:
        normalized = Path(work) / "source.wav"
        _call(run, ["-y", "-i", str(path), "-map", "0:a:0", "-vn", "-ar", "48000", "-ac", "2",
                    "-c:a", "pcm_f32le", str(normalized)])
        duration = probe_media(normalized, run)["duration"]
        if not math.isfinite(duration) or duration < 2 * crossfade + 1:
            raise PackageError(f"Nhạc cần dài ít nhất {2 * crossfade + 1:g} giây")
        graph = ("[0:a]asplit=3[b][t][h];"
                 f"[b]atrim=start={crossfade}:end={duration - crossfade},asetpts=PTS-STARTPTS[body];"
                 f"[t]atrim=start={duration - crossfade}:end={duration},asetpts=PTS-STARTPTS,"
                 f"afade=t=out:st=0:d={crossfade}:curve=qsin[tail];"
                 f"[h]atrim=end={crossfade},asetpts=PTS-STARTPTS,afade=t=in:st=0:d={crossfade}:curve=qsin[head];"
                 "[tail][head]amix=inputs=2:normalize=0:duration=longest[seam];"
                 "[body][seam]concat=n=2:v=0:a=1[out]")
        _call(run, ["-y", "-i", str(normalized), "-filter_complex_threads", "1", "-filter_complex", graph,
                    "-map", "[out]", "-c:a", "pcm_f32le", str(output)])
        actual = probe_media(output, run)["duration"]
        if abs(actual - (duration - crossfade)) > 1 / 48000 + 1e-9:
            raise RenderError("thời lượng đơn vị lặp nhạc không hợp lệ")


def music_filter(m, gain_db, duration, *, start=0, seconds=None):
    filters = [f"volume={gain_db:.9f}dB"]
    if m["fade_in"]:
        filters.append(f"afade=t=in:st=0:d={m['fade_in']}")
    if m["fade_out"]:
        # Clamp only the fade duration for short TC3 fixtures; the fade always ends at TC3's end.
        fade = min(m["fade_out"], duration)
        filters.append(f"afade=t=out:st={duration - fade:.9f}:d={fade}")
    filters += [f"atrim=start={start:.9f}:end={start + (seconds if seconds is not None else duration):.9f}",
                "asetpts=PTS-STARTPTS"]
    return ",".join(filters)


def check_audio(path, duration, peak_limit, run):
    info = probe_media(path, run)
    a = info["audio"] or {}
    actual = float(a.get("duration", 0))
    diff = abs(actual - duration)
    if (a.get("codec_name"), a.get("channels"), str(a.get("sample_rate"))) != ("aac", 2, "48000") \
            or diff > AAC_FRAME + 1e-9:
        raise RenderError("audio phải là AAC stereo 48 kHz, thời lượng bằng TC3 ± một khung AAC")
    _, peak = measure(path, run)
    if peak > peak_limit:
        raise PackageError(f"true peak {peak:g} dBTP vượt {peak_limit:g}; hãy giảm level_lu của nhạc")
    return peak, dict(codec="aac", channels=2, sample_rate=48000, duration_diff=diff, method="copy")


def build(folder, tc3, meta, spec, asset_dir, *, audio_bitrate="192k", run=None, preview=False,
          before_publish=None, publish_lock=None):
    run = run or _run
    spec = variant.normalize(spec)
    if "music" not in spec:
        raise PackageError("hãy chọn nhạc để trộn")
    variant.source(spec, asset_dir)  # Approval and integrity gate before any subprocess.
    _, asset = assets.usable(asset_dir, spec["music"]["asset_id"], kind="music")
    settings = encoding(audio_bitrate)
    ident = variant.key(spec, meta["sha256"], settings=settings)
    folder.mkdir(parents=True, exist_ok=True)
    source, source_ref = video_source(folder, tc3, meta, spec) if not preview else (None, None)
    if tc3.is_symlink() or sha256_file(tc3) != meta["sha256"]:
        raise PackageError("TC3 đã đổi; hãy xuất lại")
    if not preview:
        try:
            cached = variant.read(folder, ident[:12])
        except PackageError:
            cached = None
        if cached and cached["tc3"] == variant.reference(tc3, meta) \
                and cached["video_source"] == source_ref and variant.reusable(folder, cached):
            return cached
    if shutil.disk_usage(folder).free < 3 * 1024 ** 3:
        raise PackageError("ổ đĩa cần còn ít nhất 3 GB để dựng nhạc")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".tmp-", dir=folder) as work:
        tmp = Path(work)
        info = probe_media(tc3, run)
        a = info["audio"] or {}
        duration = float(a.get("duration") or 0)
        if a.get("codec_name") != "aac" or not math.isfinite(duration) or duration <= 0:
            raise PackageError("TC3 phải có audio AAC hợp lệ")
        voice_lufs, peak_tc3 = measure(tc3, run)
        music_lufs, _ = measure(asset, run)
        if music_lufs < -60:
            raise PackageError("nhạc gần im lặng (dưới −60 LUFS)")
        m = spec["music"]
        gain_db, peak_limit = voice_lufs + m["level_lu"] - music_lufs, max(-1., peak_tc3 + .5)
        unit = tmp / "unit.wav"
        loop_unit(asset, unit, m["loop_crossfade"], run)
        expected_video = video_hash(source, run) if not preview else None
        seconds = min(30., duration)
        positions = [0., max(0., (duration - seconds) / 2), max(0., duration - seconds)] if preview else [0.]
        outputs, previews = [], []
        for index, start in enumerate(positions, 1):
            length = seconds if preview else duration
            name = f"preview-{ident[:12]}-{index}.m4a" if preview else f"variant-{ident[:12]}.mp4"
            output = tmp / name
            graph = ("[0:a]aformat=sample_fmts=flt:sample_rates=48000:channel_layouts=stereo[voice];"
                     f"[1:a]{music_filter(m, gain_db, duration, start=start, seconds=length)}[music];"
                     "[voice][music]amix=inputs=2:normalize=0:duration=first[out]")
            inputs = ["-ss", str(start), "-i", str(tc3)] if preview else ["-i", str(tc3)]
            inputs += ["-stream_loop", "-1", "-t", str(start + length), "-i", str(unit)]
            mapping = ["-vn"] if preview else ["-i", str(source), "-map", "2:v:0", "-c:v", "copy"]
            _call(run, ["-y", *inputs, *mapping, "-filter_complex_threads", "1", "-filter_complex", graph,
                        "-map", "[out]", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", audio_bitrate,
                        *(["-t", str(length)] if preview else []), "-movflags", "+faststart", str(output)])
            peak, checks = check_audio(output, length, peak_limit, run)
            outputs.append(output)
            if preview:
                previews.append(dict(file=name, start=start, duration=length, sha256=sha256_file(output)))
            else:
                facts = audio.compare(output, tc3, tmp, run)
                checks["video_streamhash"] = video_hash(output, run)
                if checks["video_streamhash"] != expected_video:
                    raise RenderError("hình variant khác nguồn hình (streamhash)")
        result = dict(key=ident, spec=spec, tc3=variant.reference(tc3, meta))
        if preview:
            result["previews"] = previews
        else:
            result.update(schema_version=1, encoding=settings, video_source=source_ref,
                          chapters=deepcopy(meta["chapters"]), description=meta["description"],
                          sha256=sha256_file(output), size=output.stat().st_size, duration=duration,
                          build_seconds=round(time.monotonic() - started, 3), built_at=utc_now(), approved_at=None,
                          checks=checks, music=dict(asset_id=m["asset_id"], voice_lufs=voice_lufs,
                          music_lufs=music_lufs, gain_db=gain_db, true_peak=peak, true_peak_tc3=peak_tc3,
                          true_peak_limit=peak_limit, corr=facts["corr"], lag=facts["lag"]))
            variant.write(tmp, result)
            outputs.append(tmp / f"variant-{ident[:12]}.json")

        def check_inputs():
            variant.source(spec, asset_dir)
            if sha256_file(tc3) != meta["sha256"]:
                raise PackageError("TC3 đã đổi trong khi dựng")
            if not preview and video_source(folder, tc3, meta, spec)[1] != source_ref:
                raise PackageError("nguồn hình đã đổi trong khi dựng")

        # visual.build's transaction is a local closure; keep the same backup/rollback protocol here.
        published, complete = [], False
        with publish_lock or nullcontext():
            try:
                check_inputs()
                if before_publish:
                    before_publish()
                for output in outputs:
                    dest = folder / output.name
                    backup = None
                    if dest.is_file() and not dest.is_symlink():
                        backup = tmp / ("previous-" + dest.name)
                        os.link(dest, backup)
                    published.append((dest, backup))
                    os.replace(output, dest)
                if preview:
                    for old in folder.glob("preview-*.m4a"):
                        if variant.MUSIC_PREVIEW.fullmatch(old.name) and old.name not in {p.name for p in outputs}:
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
