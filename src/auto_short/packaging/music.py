"""AUD2: a separate, verified music rendition; original speech and video stay untouched."""
from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
from contextlib import nullcontext
from pathlib import Path

from ..config import MusicConfig
from ..hashing import config_hash, sha256_file
from ..render.stage import RenderError, _run, probe_media
from ..theme_render import audio
from ..workspace import atomic_write_json, read_json_dict, utc_now
from . import PackageError, assets
from .episode import _no_symlinks

MUSIC_VERSION = 2
AAC_FRAME = 1024 / 48000
MIX_PAD = 1.  # amix loses the last frames when its inputs end together: pad both, then cut to the exact length


def _call(run, args, *, level="error"):
    proc = run(["ffmpeg", "-nostdin", "-hide_banner", "-v", level, *args])
    if proc.returncode:
        raise RenderError(f"ffmpeg music: {proc.stderr[-2000:]}")
    return proc


def normalize(spec, intro_offset=0, defaults=None):
    if spec is None or isinstance(spec, dict) and spec.get("asset_id") in (None, ""):
        return None
    if not isinstance(spec, dict) or set(spec) - {"asset_id", "level_lu", "fade_in", "fade_out", "loop_crossfade", "intro_mode"}:
        raise PackageError("spec nhạc không hợp lệ")
    if not isinstance(spec["asset_id"], str) or not assets.SHA.fullmatch(spec["asset_id"]):
        raise PackageError("asset_id nhạc không hợp lệ")
    defaults = defaults or MusicConfig()
    values = dict(asset_id=spec["asset_id"], intro_mode=spec.get("intro_mode", "from_zero"))
    if values["intro_mode"] != "from_zero":
        raise PackageError("nhạc phải fade vào từ 0 s")
    for field, default, lo, hi in (("level_lu", defaults.default_level_lu, -30, -12),
                                  ("fade_in", intro_offset or defaults.fade_in, 0, 10),
                                  ("fade_out", defaults.fade_out, 0, 15),
                                  ("loop_crossfade", defaults.loop_crossfade, .5, 8)):
        value = spec.get(field, default)
        if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
            raise PackageError(f"{field} phải trong {lo}…{hi}")
        if field == "level_lu" and value * 2 != round(value * 2):
            raise PackageError("level_lu phải theo bước 0,5")
        values[field] = round(float(value), 1)
    return values


def key(spec, source_sha, asset_sha, audio_bitrate="192k", *, loop_end=None):
    return config_hash(dict(spec=spec, source_sha256=source_sha, asset_sha256=asset_sha,
                            music_version=MUSIC_VERSION, audio_bitrate=audio_bitrate, loop_end=loop_end))


def trim_silence(path, output, run, *, loop_end=None):
    """Decode once at 48 kHz, detect only boundary silence, then retain the approved loop range."""
    raw = output.with_name("untrimmed.wav")
    _call(run, ["-y", "-i", str(path), "-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le", str(raw)])
    duration = probe_media(raw, run)["duration"]
    proc = _call(run, ["-i", str(raw), "-af", "silencedetect=noise=-50dB:d=0.05", "-f", "null", "-"], level="info")
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", proc.stderr)]
    start = ends[0] if starts and starts[0] <= 1 / 48000 and ends else 0.
    end = starts[-1] if starts and (len(starts) > len(ends) or ends and ends[-1] >= duration - .05) else duration
    if loop_end is not None:
        if not math.isfinite(loop_end) or not 0 < loop_end <= duration + .05:
            raise PackageError("loop_end nằm ngoài bài nhạc")
        end = min(loop_end, duration)
    if end <= start:
        raise PackageError("nhạc gần im lặng (dưới −60 LUFS)")
    _call(run, ["-y", "-i", str(raw), "-af", f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS",
                "-c:a", "pcm_f32le", str(output)])
    return dict(start=start, end=end, duration=end - start)


def measure(path, run, *, start=0):
    """Read only the final ebur128 summary, not the per-frame diagnostics."""
    proc = _call(run, ["-ss", str(start), "-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=true",
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
    fade_in, fade_out = m["fade_in"], m["fade_out"]
    if fade_in + fade_out > duration:
        scale = duration / (fade_in + fade_out)
        fade_in, fade_out = fade_in * scale, fade_out * scale
    filters = [f"volume={gain_db:.9f}dB"]
    if fade_in:
        filters.append(f"afade=t=in:st=0:d={fade_in:.9f}")
    if fade_out:
        filters.append(f"afade=t=out:st={duration - fade_out:.9f}:d={fade_out:.9f}")
    filters += [f"atrim=start={start:.9f}:end={start + (seconds if seconds is not None else duration):.9f}",
                "asetpts=PTS-STARTPTS"]
    return ",".join(filters)


def true_peak_limit(source_peak):
    """ebur128 reports one decimal; rounding keeps a peak exactly at the limit from failing on float noise."""
    return round(max(-1., source_peak + .5), 1)


def check_audio(path, duration, peak_limit, run):
    info = probe_media(path, run)
    a = info["audio"] or {}
    actual = float(a.get("duration", 0))
    diff = abs(actual - duration)
    if (a.get("codec_name"), a.get("channels"), str(a.get("sample_rate"))) != ("aac", 2, "48000") \
            or not math.isfinite(actual) or actual <= 0 or diff > AAC_FRAME + 1e-9:
        raise RenderError("audio phải là AAC stereo 48 kHz, thời lượng bằng nguồn ± một khung AAC")
    _, peak = measure(path, run)
    if peak > peak_limit:
        raise PackageError(f"true peak {peak:g} dBTP vượt {peak_limit:g}; hãy giảm level_lu của nhạc")
    return peak, dict(codec="aac", channels=2, sample_rate=48000, duration_diff=diff, method="copy")


def artifact_files(folder, stem, *, preview=False, family_stem=None):
    """Canonical filenames only; a theme family spans revisions of the same plan."""
    _no_symlinks(folder)
    prefix = re.escape(family_stem) + r"-r[1-9][0-9]*" if family_stem else re.escape(stem)
    extension = r"(?:-preview\.json|-preview-[12]\.m4a)" if preview else r"(?:\.json|\.mp4)"
    pattern = re.compile(prefix + r"-[a-f0-9]{12}" + extension)
    return [p for p in folder.iterdir() if pattern.fullmatch(p.name)] if folder.is_dir() else []


def records(folder, stem, *, preview=False, family_stem=None):
    docs = []
    for path in artifact_files(folder, stem, preview=preview, family_stem=family_stem):
        if path.suffix == ".json":
            doc = read_json_dict(_no_symlinks(path))
            if doc:
                docs.append(doc)
    return sorted(docs, key=lambda d: str(d.get("built_at", "")), reverse=True)



def current(folder, doc, source_sha, asset_dir, *, audio_bitrate="192k"):
    """Used for both cache hits and download gates; never trusts recorded filenames."""
    try:
        _no_symlinks(asset_dir)
        asset, _ = assets.usable(asset_dir, doc["spec"]["asset_id"], kind="music")
        ident = key(doc["spec"], source_sha, asset["id"], audio_bitrate, loop_end=asset.get("loop_end"))
        if ident != doc["key"] or doc.get("source_sha256") != source_sha or doc.get("attribution", "") != asset.get("attribution", ""):
            return False
        names = doc.get("previews") or [dict(file=doc["file"], sha256=doc["sha256"])]
        for item in names:
            name = item["file"]
            if not isinstance(name, str) or Path(name).name != name or "\\" in name:
                return False
            path = _no_symlinks(folder / name)
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                return False
        return True
    except (PackageError, OSError, ValueError, KeyError, TypeError):
        return False


def _publish(folder, tmp, files, old_files, *, before_publish=None, publish_lock=None):
    """Replace a set with rollback, retaining the prior rendition until every new file is published."""
    published, complete = [], False
    with publish_lock or nullcontext():
        try:
            if before_publish:
                before_publish()
            for src in files:
                dest = _no_symlinks(folder / src.name)
                backup = None
                if dest.exists():
                    backup = tmp / ("previous-" + dest.name)
                    os.link(dest, backup)
                published.append((dest, backup))
                os.replace(src, dest)
            for dest in old_files:
                if dest.name not in {p.name for p in files} and dest.exists():
                    _no_symlinks(dest)
                    backup = tmp / ("previous-" + dest.name)
                    published.append((dest, backup))
                    os.replace(dest, backup)
            complete = True
        finally:
            if not complete:
                for dest, backup in reversed(published):
                    if backup is not None and backup.exists():
                        os.replace(backup, dest)
                    elif backup is None:
                        dest.unlink(missing_ok=True)


def preview_positions(duration, track_duration, period, crossfade):
    seconds = min(30., duration)
    center = period - crossfade / 2 if duration >= track_duration else duration / 2
    return [0., min(max(0., center - seconds / 2), duration - seconds)]


def mix(source, intro_offset, spec, asset_dir, *, folder=None, stem=None, defaults=None,
        audio_bitrate="192k", run=None, before_publish=None, publish_lock=None,
        description="", preview_only=False, family_stem=None):
    spec = normalize(spec, intro_offset, defaults)
    if spec is None:
        return None
    run = run or _run
    source = _no_symlinks(Path(source))
    folder = _no_symlinks(Path(folder) if folder is not None else source.parent / "music")
    stem = stem or source.stem
    if not re.fullmatch(r"[A-Za-z0-9_-]+", stem) or not re.fullmatch(r"[1-9][0-9]*k", audio_bitrate):
        raise PackageError("tên nguồn / audio_bitrate không hợp lệ")
    _no_symlinks(asset_dir)
    asset, asset_path = assets.usable(asset_dir, spec["asset_id"], kind="music")
    source_sha = sha256_file(source)
    ident = key(spec, source_sha, asset["id"], audio_bitrate, loop_end=asset.get("loop_end"))
    for doc in records(folder, stem, preview=preview_only):
        if doc.get("key") == ident and current(folder, doc, source_sha, asset_dir, audio_bitrate=audio_bitrate):
            return doc
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < 3 * 1024 ** 3:
        raise PackageError("ổ đĩa cần còn ít nhất 3 GB để dựng nhạc")
    with tempfile.TemporaryDirectory(prefix=".music-", dir=folder) as work:
        tmp = Path(work)
        info = probe_media(source, run)
        duration = float((info["audio"] or {}).get("duration") or 0)
        if not math.isfinite(duration) or duration <= intro_offset or intro_offset < 0:
            raise PackageError("nguồn phải có thời lượng audio hợp lệ")
        voice_lufs, _ = measure(source, run, start=intro_offset)
        _, source_peak = measure(source, run)
        trimmed, unit = tmp / "trimmed.wav", tmp / "unit.wav"
        cut = trim_silence(asset_path, trimmed, run, loop_end=asset.get("loop_end"))
        music_lufs, _ = measure(trimmed, run)
        if music_lufs < -60:
            raise PackageError("nhạc gần im lặng (dưới −60 LUFS)")
        loop_unit(trimmed, unit, spec["loop_crossfade"], run)
        period = probe_media(unit, run)["duration"]
        gain_db = voice_lufs + spec["level_lu"] - music_lufs
        peak_limit = true_peak_limit(source_peak)
        length = min(30., duration) if preview_only else duration
        seam = period - spec["loop_crossfade"] / 2
        positions = preview_positions(duration, cut["duration"], period, spec["loop_crossfade"]) if preview_only else [0.]
        name = f"{stem}-{ident[:12]}"
        result = dict(schema_version=1, key=ident, spec=spec, source_sha256=source_sha,
                      music_version=MUSIC_VERSION, audio_bitrate=audio_bitrate, built_at=utc_now(),
                      attribution=asset.get("attribution", ""), description=description,
                      music=dict(voice_lufs=voice_lufs, music_lufs=music_lufs, gain_db=gain_db,
                                 trim=cut, loop_period=period, first_seam=seam))
        outputs, previews = [], []
        expected_video = video_hash(source, run) if not preview_only else None
        for i, start in enumerate(positions, 1):
            out = tmp / (f"{name}-preview-{i}.m4a" if preview_only else name + ".mp4")
            # Music starts at time zero in both paths. Trim AFTER fades so phase and gain match full output.
            graph = (f"[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,apad=pad_dur={MIX_PAD}[voice];"
                     f"[1:a]{music_filter(spec, gain_db, duration, start=start, seconds=length + MIX_PAD)}[music];"
                     f"[voice][music]amix=inputs=2:weights='1 1':normalize=0:duration=shortest,atrim=end={length:.9f}[out]")
            inputs = ["-ss", str(start), "-i", str(source)] if preview_only else ["-i", str(source)]
            mapping = ["-vn"] if preview_only else ["-map", "0:v:0", "-c:v", "copy", "-map_metadata", "0", "-map_chapters", "0"]
            _call(run, ["-y", *inputs, "-stream_loop", "-1", "-t", str(start + length + MIX_PAD), "-i", str(unit),
                        "-filter_complex_threads", "1", "-filter_complex", graph, *mapping,
                        "-map", "[out]", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", audio_bitrate,
                        *(["-t", str(length)] if preview_only else []), "-movflags", "+faststart", str(out)])
            peak, checks = check_audio(out, length, peak_limit, run)
            outputs.append(out)
            if preview_only:
                previews.append(dict(file=out.name, start=start, duration=length, sha256=sha256_file(out)))
            else:
                facts = audio.compare(out, source, tmp, run)
                checks["video_streamhash"] = video_hash(out, run)
                if checks["video_streamhash"] != expected_video:
                    raise RenderError("hình bản nhạc khác nguồn (streamhash)")
                result.update(file=out.name, sha256=sha256_file(out), duration=duration, checks=checks,
                              speech=facts, true_peak=peak, true_peak_limit=peak_limit)
        if preview_only:
            result["previews"] = previews
        record = tmp / (name + ("-preview" if preview_only else "") + ".json")
        atomic_write_json(record, result)
        outputs.append(record)
        old_files = artifact_files(folder, stem, preview=preview_only, family_stem=family_stem)

        def recheck():
            _no_symlinks(asset_dir)
            if sha256_file(source) != source_sha or assets.usable(asset_dir, spec["asset_id"], kind="music")[0] != asset:
                raise PackageError("nguồn / nhạc đã đổi trong khi dựng")
            if before_publish:
                before_publish()

        _publish(folder, tmp, outputs, old_files, before_publish=recheck, publish_lock=publish_lock)
        return result


def preview(source, intro_offset, spec, asset_dir, **kwargs):
    return mix(source, intro_offset, spec, asset_dir, preview_only=True, **kwargs)


def attributed_description(description, attribution):
    if not attribution:
        return description
    return description.rstrip() + ("\n\n" if description.strip() else "") + f"Nhạc: {attribution}"
