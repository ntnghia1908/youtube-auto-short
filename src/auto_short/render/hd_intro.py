"""HDI1: stream-copy a landscape thumbnail intro, verify, then conditionally replace the released HD."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from fractions import Fraction
from pathlib import Path

from .. import hashing
from ..config import Config
from ..enhance import state as enh
from ..workspace import atomic_write_json, read_json_dict, validate_episode_id
from . import plan
from .stage import RenderError, Runner, _last_line, _run, probe_media

NAME = "hd_intro.json"
VERSION = 1


def read(folder: Path) -> dict | None:
    doc = read_json_dict(folder / NAME)
    return doc if doc and doc.get("version") == VERSION else None


def write(folder: Path, doc: dict) -> None:
    atomic_write_json(folder / NAME, doc)
    kid = folder.parent / (enh.owner_id(folder.name) + ".kt")
    if kid != folder and (kid / "manifest.json").is_file():
        atomic_write_json(kid / NAME, doc)


def complete(folder: Path, doc: dict) -> dict:
    from ..review import backup
    from ..store import index_cache

    doc.update(status="done", replaced_at=doc.get("replaced_at") or enh.now_iso())
    doc.pop("previous_intro", None)
    write(folder, doc)
    with backup._LOCK:
        record = backup.read_backup(folder)
        if (record.get("released") or {}).get("hd"):
            atomic_write_json(backup.backup_path(folder), record)
    index_cache.invalidate()
    return doc


def playlist(config: Config, episode_id: str) -> str | None:
    video_id = enh.owner_id(episode_id)
    for pid in config.hd_intro.playlists:
        doc = read_json_dict(Path(config.workspace.dir) / "_playlists" / f"{pid}.json") or {}
        if doc.get("playlist_id") == pid and any(isinstance(e, dict) and e.get("video_id") == video_id
                                                 for e in doc.get("entries", [])):
            return pid
    return None


def thumbnail(config: Config, episode_id: str, pid: str, *, build: bool = True) -> Path | None:
    from ..packaging import episode

    video_id = enh.owner_id(episode_id)
    files = episode.valid_files(config, video_id, pid=pid)
    if "landscape" not in files and build:
        episode.build_episode(config, video_id, pid=pid)
        files = episode.valid_files(config, video_id, pid=pid)
    return episode.directory(config, video_id) / files["landscape"]["file"] if "landscape" in files else None


def view(config: Config, episode_id: str) -> dict | None:
    pid = playlist(config, episode_id)
    if pid is None:
        return None
    d = Path(config.workspace.dir) / enh.owner_for(config, episode_id)
    doc = read(d)
    image = thumbnail(config, episode_id, pid, build=False)
    current = bool(doc and doc.get("status") == "done" and image is not None
                   and doc.get("thumb_sha256") == hashing.sha256_file(image))
    return {"ready": current, "stale": bool(doc and doc.get("status") == "done" and not current),
            "status": (doc or {}).get("status"), "can_make": config.store.enabled and enh.is_released(d)}


def intro_spec(info: dict) -> dict:
    v, a = info.get("video"), info.get("audio")
    if not v or not a or v.get("codec_name") != "h264" or a.get("codec_name") not in ("aac", "opus"):
        raise RenderError("HD intro cần h264 + aac/opus")
    profiles = {"High": "high", "Main": "main", "Constrained Baseline": "baseline", "Baseline": "baseline"}
    try:
        fps = plan.source_fps(v)
        frames = round(3 * fps)
        timebase = Fraction(v["time_base"])
        profile = profiles[v["profile"]]
        if timebase.numerator != 1 or frames < 1:
            raise ValueError("invalid timescale / fps")
        return {"fps": fps, "frames": frames, "offset": float(frames / fps), "timescale": timebase.denominator,
                "width": int(v["width"]), "height": int(v["height"]), "pix_fmt": v["pix_fmt"], "profile": profile,
                "audio_codec": a["codec_name"], "sample_rate": int(a["sample_rate"]), "channels": int(a["channels"]),
                "layout": a.get("channel_layout") or {1: "mono", 2: "stereo"}[int(a["channels"])]}
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise RenderError(f"HD có thông số chưa hỗ trợ: {exc}") from exc


def intro_command(spec: dict, image: Path, output: Path) -> list[str]:
    fps, w, h = plan.fps_text(spec["fps"]), spec["width"], spec["height"]
    return ["ffmpeg", "-nostdin", "-v", "error", "-y", "-loop", "1", "-framerate", fps, "-t", "4", "-i", str(image),
            "-f", "lavfi", "-t", "4", "-i", f"anullsrc=r={spec['sample_rate']}:cl={spec['layout']}",
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format={spec['pix_fmt']}",
            "-frames:v", str(spec["frames"]), "-af", f"atrim=0:{spec['offset']}",
            "-c:v", "libx264", "-profile:v", spec["profile"], "-preset", "medium", "-crf", "16", "-r", fps,
            "-c:a", "libopus" if spec["audio_codec"] == "opus" else "aac", "-b:a", "160k",
            "-ar", str(spec["sample_rate"]), "-ac", str(spec["channels"]), "-threads", "2",
            "-video_track_timescale", str(spec["timescale"]), "-movflags", "+faststart", str(output)]


def concat_command(list_file: Path, output: Path, spec: dict | None = None) -> list[str]:
    # MP4's movie edit list uses millisecond ticks for the encoder priming (AAC 1024, Opus 312 samples).
    priming = (1024 if spec["audio_codec"] == "aac" else 312) if spec else 0
    shift = int(1000 * priming / spec["sample_rate"]) / 1000 if spec else 0
    return ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart",
            *(["-output_ts_offset", str(-shift)] if shift else []), str(output)]


def checked(command: list[str], run: Runner):
    proc = run(command)
    if proc.returncode:
        raise RenderError(f"HD intro: {_last_line(proc.stderr) or f'exit {proc.returncode}'}")
    return proc


def check_timing(original: dict, stored: dict, spec: dict, pts: dict[str, float]) -> None:
    if abs(stored["duration"] - original["duration"] - spec["offset"]) > 1 / float(spec["fps"]) + 0.001:
        raise RenderError("HD intro: thời lượng ghép sai quá 1 khung")
    if set(pts) != {"video", "audio"} or any(abs(t - spec["offset"]) > 0.020 for t in pts.values()):
        raise RenderError(f"HD intro: pts mốc ghép lệch quá 20 ms: {pts}")


def packets(path: Path, selector: str, interval: str, run: Runner) -> list[dict]:
    proc = checked(["ffprobe", "-v", "error", "-select_streams", selector, "-read_intervals", interval,
                    "-show_packets", "-show_data_hash", "sha256", "-show_entries", "packet=pts_time,data_hash",
                    "-of", "json", str(path)], run)
    return json.loads(proc.stdout)["packets"]


def frame_hash(path: Path, seconds: float, run: Runner) -> str:
    proc = checked(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(seconds), "-i", str(path),
                    "-map", "0:v:0", "-frames:v", "1", "-f", "framemd5", "-"], run)
    lines = [line for line in proc.stdout.splitlines() if line and not line.startswith("#")]
    if len(lines) != 1:
        raise RenderError("HD intro: không giải mã được khung kiểm tra")
    return lines[0].split(",")[-1].strip()


def boundary_pts(source: Path, output: Path, selector: str, kind: str,
                 original: dict, spec: dict, run: Runner) -> float:
    first = packets(source, selector, "%+#4", run)
    joined = packets(output, selector, "%+6", run)
    window = 0.0
    limit = float(original["duration"]) + 1
    while True:
        if not first:
            raise RenderError(f"HD intro: thiếu gói {kind}")
        # Concat may attach H.264 SPS/PPS to the first key packet; skip only that payload.
        sequence = first[1:] if kind == "video" else first
        hashes = [p["data_hash"] for p in sequence]
        joined_hashes = [p["data_hash"] for p in joined]
        matches = [i for i in range(len(joined) - len(hashes) + 1)
                   if hashes and joined_hashes[i:i + len(hashes)] == hashes]
        if not matches:
            raise RenderError(f"HD intro: gói {kind} đã đổi")
        if len(matches) == 1:
            return (float(joined[matches[0]]["pts_time"]) - float(sequence[0]["pts_time"])
                    + float(first[0]["pts_time"]))
        if kind == "video" or window >= limit:
            raise RenderError(f"HD intro: không xác định được mốc gói {kind} duy nhất")
        # Digital silence can repeat for minutes. Extend the consecutive prefix until
        # it identifies one position; never choose a candidate just because its PTS fits.
        window = min(6 if not window else window * 10, limit)
        first = packets(source, selector, f"%+{window}", run)
        joined = packets(output, selector, f"%+{window + spec['offset'] + 1}", run)


def verify(source: Path, output: Path, original: dict, spec: dict, run: Runner) -> None:
    stored = probe_media(output, run)
    pts = {}
    for kind, selector in (("video", "v:0"), ("audio", "a:0")):
        pts[kind] = boundary_pts(source, output, selector, kind, original, spec, run)
    check_timing(original, stored, spec, pts)
    duration = float(original["video"].get("duration") or original["duration"])
    count = max(1, round(duration * spec["fps"]))
    for n in sorted({0, count // 2, max(0, count - 2)}):
        seconds = float(n / spec["fps"])
        if frame_hash(source, seconds, run) != frame_hash(output, seconds + spec["offset"], run):
            raise RenderError(f"HD intro: khung hình sau offset khác bản gốc tại {seconds:.3f} s")


def render(source: Path, image: Path, output: Path, *, run: Runner = _run) -> dict:
    if not source.is_file() or not image.is_file():
        raise RenderError("HD intro: thiếu HD hoặc thumbnail ngang")
    if source.resolve() == output.resolve():
        raise RenderError("HD intro: cần file đầu ra riêng")
    info = probe_media(source, run)
    spec = intro_spec(info)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".hd-intro-", dir=output.parent) as name:
            tmp = Path(name)
            intro = tmp / "intro.mp4"
            checked(intro_command(spec, image, intro), run)
            listing = tmp / "concat.txt"
            def quoted(path):
                return str(path.resolve()).replace("'", "'\\''")
            listing.write_text(f"file '{quoted(intro)}'\nfile '{quoted(source)}'\n", encoding="utf-8")
            checked(concat_command(listing, output, spec), run)
            verify(source, output, info, spec, run)
        return spec
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def run_intro(episode_id: str, config: Config, *, keep_original: bool = False, client=None,
              run: Runner = _run) -> dict:
    from ..store.borrow import borrow_hd, released_hd_sha
    from ..store.client import StoreClient, StoreMismatch

    validate_episode_id(episode_id)
    owner = enh.owner_for(config, episode_id)
    d = Path(config.workspace.dir) / owner
    pid = playlist(config, owner)
    if pid is None or not (d / "manifest.json").is_file():
        raise RenderError("không có tập / bộ kinh chưa bật HD intro")
    if not config.store.enabled or not enh.is_released(d):
        raise RenderError("HD intro chỉ áp dụng HD đã giải phóng lên kho")
    client = client or StoreClient.from_config(config.store)
    video_id = enh.owner_id(owner)
    head = client.head(video_id, "hd")
    previous = read(d)
    if previous and previous.get("status") == "pending":
        if head == previous["stored"]:
            complete(d, previous)
        elif head == previous.get("previous", previous["original"]):
            if previous.get("previous_intro"):
                write(d, previous["previous_intro"])
            else:
                (d / NAME).unlink()
                kid = d.parent / (enh.owner_id(owner) + ".kt")
                if kid != d:
                    (kid / NAME).unlink(missing_ok=True)
        else:
            raise StoreMismatch("HD intro pending: kho khác cả bản cũ và bản mới; không thay")
    image = thumbnail(config, owner, pid)
    if image is None:
        raise RenderError("thiếu thumbnail ngang hiện hành")
    thumb_sha = hashing.sha256_file(image)
    completed = enh.hd_intro_record(d)
    if completed and completed["stored"] == head and completed["thumb_sha256"] == thumb_sha:
        return complete(d, completed)
    expected = released_hd_sha(config, owner, d)
    if head["sha256"] != expected:
        raise StoreMismatch("HD trên kho khác sha đã giải phóng; không thay")
    with tempfile.TemporaryDirectory(prefix="auto-short-hd-intro-") as name:
        tmp = Path(name)
        with borrow_hd(config, owner, tmp, client=client) as stored_source:
            source = stored_source
            if completed:
                source = tmp / "original.mp4"
                spec = intro_spec(probe_media(stored_source, run))
                # Copy only the lecture packets; input seeking alone keeps earlier packets hidden by MP4 edits.
                checked(["ffmpeg", "-nostdin", "-v", "error", "-y",
                         *enh.hd_input_args(enh.hd_source(d, completed["original"]["sha256"]), stored_source),
                         "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                         "-bsf:v", "noise=drop='lt(pts*tb,0)'", "-bsf:a", "noise=drop='lt(pts*tb,0)'",
                         "-video_track_timescale",
                         str(spec["timescale"]), str(source)], run)
                duration = probe_media(source, run)["duration"]
                count = max(1, round(duration * spec["fps"]))
                for n in sorted({0, count // 2, max(0, count - 2)}):
                    seconds = float(n / spec["fps"])
                    if frame_hash(stored_source, seconds + completed["offset_seconds"], run) != frame_hash(source, seconds, run):
                        raise RenderError("HD intro: không tách được bài giảng từ bản có intro")
            if keep_original and completed is None:
                sample = Path(config.render.output_dir) / "_samples" / "hdi1-original" / f"{video_id}.mp4"
                sample.parent.mkdir(parents=True, exist_ok=True)
                if not sample.exists():
                    part = sample.with_suffix(".mp4.part")
                    try:
                        shutil.copyfile(source, part)
                        os.replace(part, sample)
                    finally:
                        part.unlink(missing_ok=True)
                if hashing.sha256_file(sample) != head["sha256"]:
                    raise RenderError("bản gốc giữ lại khác sha HD; không thay kho")
            output = tmp / "hd.mp4"
            spec = render(source, image, output, run=run)
            doc = {"version": VERSION, "status": "pending", "original": completed["original"] if completed else head,
                   "stored": {"sha256": hashing.sha256_file(output), "size": output.stat().st_size},
                   "frames": spec["frames"], "fps": plan.fps_text(spec["fps"]), "offset_seconds": spec["offset"],
                   "thumb_sha256": thumb_sha, "replaced_at": None}
            if completed:
                doc.update(previous=head, previous_intro=completed)
            write(d, doc)
            rows = [r for r in client.index() if r.get("video_id") == video_id and r.get("kind") == "hd"]
            if len(rows) != 1:
                raise StoreMismatch("không xác định được file HD trên kho")
            row = rows[0]
            client.replace(video_id, "hd", row["series"], row["file"], output, doc["stored"]["sha256"],
                           current_sha256=head["sha256"])
            if client.head(video_id, "hd") != doc["stored"]:
                raise StoreMismatch("kho chưa xác nhận sha / size HD mới")
            complete(d, doc)
    return doc
