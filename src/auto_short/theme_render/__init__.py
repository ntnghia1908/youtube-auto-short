"""TC3: reconstruct an approved thematic plan from full-frame sources.

No workspace writes, AI, queue management or changes to CP8.33 artifacts. All
intermediate media lives in private directories beneath the theme output folder.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .. import hashing, theme_index, theme_plan
from ..compilation import meta, store
from ..compilation.assemble import Encode, assemble
from ..compilation.spec import item_from_json
from ..config import Config
from ..ingest.youtube import DownloadError, YoutubeBlocked, ytdlp_download
from ..render import plan
from ..render.full import SourceBlocked
from ..render.stage import RenderError, _last_line, _run, episode_render_config, probe_media
from ..review.names import clean_part, truncate_utf8
from ..selection.client import ChatError
from ..workspace import atomic_write_json, utc_now
from . import audio

WIDTH, HEIGHT = 1920, 1080
SCHEMA_VERSION = 1
RENDER_VERSION = 1


@dataclass(frozen=True)
class LandscapeResult:
    path: Path
    metadata: dict
    ran: bool


class _RefusingClient:
    def chat(self, **kwargs):
        raise ChatError("TC3 chỉ đọc index; không được gọi AI")


def _read(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("expected object")
        return doc
    except (OSError, ValueError) as exc:
        raise RenderError(f"không đọc được {path.name}: {exc}") from exc


def _reference(config: Config, pid: str, record: dict) -> tuple[Path, str]:
    ident = record["identity"]
    folder = Path(config.render.output_dir) / ident["episode_id"]
    doc = _read(folder / "render_manifest.json")
    shorts = doc.get("shorts", [])
    short = next((s for s in shorts if s.get("clip_id") == ident["clip"]), None)
    if short is None:
        raise RenderError("không có Short tham chiếu trong render manifest")
    path = (folder / short["file"]).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise RenderError("đường dẫn Short nằm ngoài output của tập")
    if not path.is_file():
        item = item_from_json(record["inputs"]["favorite"])
        path = store.kept_path(store.directory(config.render.output_dir, pid), item)
    if path is None or not path.is_file() or hashing.sha256_file(path) != record["inputs"]["render_sha256"]:
        raise RenderError("Short tham chiếu bị thiếu hoặc sha256 không khớp (kể cả bản kept)")
    number = next(i for i, s in enumerate(shorts, 1) if s is short)
    titles = _read(Path(config.workspace.dir) / ident["episode_id"] / "titles.json")
    episode = ((titles.get("header") or {}).get("fields") or {}).get("episode") or ident["episode_id"]
    title = short.get("title")
    return path, title.strip() if isinstance(title, str) and title.strip() else f"T{episode} KT{number}"


def filter_graph(segments: list[tuple[int, int]], fps: Fraction, dissolve: float) -> str:
    frames = plan.frame_plan(segments, fps)
    dp = plan.dissolve_plan(frames, fps, dissolve)
    # Preserve display aspect, including anamorphic input, then make square pixels.
    per_frame = (f"scale=w='trunc(ih*dar/2)*2':h=ih,setsar=1,"
                 f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2:"
                 f"flags={plan.SCALE_FLAGS},scale=out_color_matrix=bt709:out_range=tv,setsar=1,format=yuv444p")
    pad = f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,format={plan.PIX_FMT}[vout]"
    video = (plan._video_dissolve(frames, fps, dp, per_frame, pad) if dp.active else
             [plan._video_cut(frames, plan.fps_text(fps), per_frame, pad)])
    k = len(segments)
    sound = [f"[0:a]asplit={k}" + "".join(f"[as{i}]" for i in range(k)) if k > 1 else "[0:a]anull[as0]"]
    for i, (a, b) in enumerate(segments):
        sound.append(f"[as{i}]atrim=start={plan._num(a / 1000)}:end={plan._num(b / 1000)},"
                     f"asetpts=PTS-STARTPTS[a{i}]")
    sound.append("".join(f"[a{i}]" for i in range(k)) + f"concat=n={k}:v=0:a=1,aresample={plan.SAMPLE_RATE},"
                 "aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB[aout]")
    return ";".join([*video, *sound])


def _verify(path: Path, expected: float, tolerance: float, runner, *, fps: Fraction | None = None,
            frames: int | None = None, audio_tolerance: float = audio.MAX_DURATION_DIFF) -> dict:
    info = probe_media(path, runner)
    v, a = info["video"], info["audio"]
    problems = []
    if v is None or a is None:
        raise RenderError(f"{path.name}: thiếu luồng video / audio")
    if (v.get("codec_name"), v.get("width"), v.get("height"), v.get("pix_fmt"), v.get("sample_aspect_ratio")) \
            != ("h264", WIDTH, HEIGHT, plan.PIX_FMT, "1:1"):
        problems.append("video cần là H.264 1920×1080, yuv420p, SAR 1")
    if (a.get("codec_name"), a.get("sample_rate"), a.get("channels")) != ("aac", str(plan.SAMPLE_RATE), plan.CHANNELS):
        problems.append("audio cần là AAC 48 kHz stereo")
    if fps is not None and Fraction(v.get("r_frame_rate") or "0/1") != fps:
        problems.append("fps không khớp nguồn")
    if frames is not None and str(v.get("nb_frames")) != str(frames):
        problems.append(f"số frame {v.get('nb_frames')} != {frames}")
    for stream, limit in ((v, tolerance), (a, audio_tolerance)):
        if abs(float(stream.get("duration") or 0) - expected) > limit + 1e-3:
            problems.append(f"thời lượng {stream.get('codec_type')} không khớp {expected:.3f} s")
    if problems:
        raise RenderError(f"{path.name}: " + "; ".join(problems))
    return info


def _source(config: Config, record: dict, fetched: dict, downloader):
    from . import sources

    ref = record["source_reference"]
    src = Path(ref["path"])
    if record["source_status"] == "present":
        if not src.is_file() or hashing.sha256_file(src) != ref["sha256"]:
            raise RenderError("video nguồn đã thay đổi hoặc bị xóa sau khi audit")
        return src, "present", None
    video_id = sources._owner(record["identity"]["episode_id"])
    if video_id not in fetched:
        try:
            src = sources.cached_source(config, video_id)
            if src is None:
                src = sources.fetch_to_cache(config, video_id, downloader)
        except YoutubeBlocked as exc:
            raise SourceBlocked(str(exc)) from exc
        fetched[video_id] = (src, hashing.sha256_file(src))
    src, sha = fetched[video_id]
    warning = "video tải lại khác sha256 nguồn đã render; đã kiểm lại audio từng clip" if sha != ref["sha256"] else None
    return src, "refetched", warning


def _encode_key(config: Config, records: list[dict]) -> str:
    cfg = config.render
    return hashing.config_hash({"version": RENDER_VERSION, "short_plan_version": plan.RENDER_PLAN_VERSION,
        "size": [WIDTH, HEIGHT], "crf": cfg.crf, "preset": cfg.preset, "audio_bitrate": cfg.audio_bitrate,
        "threads": cfg.threads, "codecs": [plan.VCODEC, plan.PIX_FMT, plan.ACODEC, plan.SAMPLE_RATE, plan.CHANNELS],
        "max_fps": str(plan.MAX_FPS), "scale_flags": plan.SCALE_FLAGS,
        "dissolve": [episode_render_config(config, Path(config.workspace.dir) / r["identity"]["episode_id"])[0].dissolve
                     for r in records],
        "audio_match": [audio.SAMPLE_RATE, audio.WINDOW_SECONDS, audio.SEARCH_SECONDS, audio.MAX_LAG,
                        audio.MIN_CORRELATION, audio.MAX_DURATION_DIFF]})


def _description(config: Config, approved: dict, chapters: list[dict], hashtags: list[str]) -> str:
    clips = approved.get("clips") or []
    fields = theme_plan.title_fields(config, clips[0]["episode_id"]) if clips else {}
    byline = " · ".join(x for x in (theme_plan.speaker_for_clips(config, clips), fields.get("series")) if x)
    heading = "\n".join(x for x in (approved["title"], byline) if x)
    return "\n\n".join(x for x in (heading, meta.description("concat", chapters, None, []),
                                    " ".join(hashtags)) if x)


def render_landscape(config: Config, playlist_id: str, plan_id: str, *, hashtags: list[str] = (), runner=_run,
                     downloader=ytdlp_download) -> LandscapeResult:
    """Make/reuse ``theme/<plan_id>-r<revision>.mp4``; reject unapproved or stale input before any writes."""
    approved = theme_plan.approved_plan(config, playlist_id, plan_id)
    index = theme_index.build_index(config, playlist_id, client=_RefusingClient(), write=False)
    known = {f"{r['identity']['episode_id']}/{r['identity']['clip']}": r
             for r in index["records"] if r.get("status") == "indexed"}
    records = []
    for snap in approved["clips"]:
        rec = known.get(snap["id"])
        if rec is None or rec["input_fingerprint"] != snap["input_fingerprint"] \
                or rec["inputs"]["render_sha256"] != snap["render_sha256"]:
            raise RenderError(f"{snap['id']}: fingerprint clip đã thay đổi; cần duyệt lại plan")
        records.append(rec)
    fingerprint, key = theme_plan.plan_fingerprint(approved), _encode_key(config, records)
    folder = store.directory(config.render.output_dir, playlist_id) / "theme"
    out = folder / f"{plan_id}-r{approved['revision']}.mp4"
    metadata_path = out.with_suffix(".json")
    if out.is_file() and metadata_path.is_file():
        try:
            cached = _read(metadata_path)
        except RenderError:
            cached = {}
        if cached.get("schema_version") == SCHEMA_VERSION and cached.get("plan_fingerprint") == fingerprint \
                and cached.get("encode_key") == key and cached.get("sha256") == hashing.sha256_file(out):
            description = _description(config, approved, cached.get("chapters") or [], hashtags)
            if cached.get("description") != description:
                cached["description"] = description
                atomic_write_json(metadata_path, cached)
            return LandscapeResult(out, cached, False)
    # Validate every reference before downloading/encoding any source.
    references = [_reference(config, playlist_id, r) for r in records]
    folder.mkdir(parents=True, exist_ok=True)
    fetch_root = folder / ".fetch"
    cfg = config.render
    try:
        with ExitStack() as stack:
            tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=folder, prefix=".render-")))
            fetched, paths, clips, tolerances = {}, [], [], []
            for n, (snap, record, (reference, title)) in enumerate(zip(approved["clips"], records, references)):
                try:
                    source, status, warning = _source(config, record, fetched, downloader)
                    info = probe_media(source, runner)
                    if info["video"] is None or info["audio"] is None:
                        raise RenderError("video nguồn thiếu video / audio")
                    fps = plan.output_fps(plan.source_fps(info["video"]))
                    segments = [(round(a * 1000), round(b * 1000)) for a, b in record["final_segments"]]
                    if not segments or any(b <= a for a, b in segments):
                        raise RenderError("final_segments rỗng hoặc không hợp lệ")
                    seconds = plan.total_ms(segments) / 1000
                    if abs(seconds - snap["duration"]) > 0.001:
                        raise RenderError("thời lượng final_segments không khớp plan")
                    dissolve = episode_render_config(config, Path(config.workspace.dir) / record["identity"]["episode_id"])[0].dissolve
                    graph, clip = tmp / f"{n}.filter", tmp / f"{n}.mp4"
                    graph.write_text(filter_graph(segments, fps, dissolve), encoding="utf-8")
                    proc = runner(plan.ffmpeg_command(ffmpeg="ffmpeg", source=source, output=clip, graph_script=graph,
                        segments=segments, fps=fps, crf=cfg.crf, preset=cfg.preset,
                        audio_bitrate=cfg.audio_bitrate, threads=cfg.threads))
                    if proc.returncode != 0 or not clip.is_file():
                        raise RenderError(f"ffmpeg lỗi: {_last_line(proc.stderr)}")
                    _verify(clip, seconds, 1 / float(fps), runner, fps=fps, frames=plan.planned_frames(segments, fps))
                    match = audio.compare(clip, reference, tmp, runner)
                except SourceBlocked:
                    raise
                except (RenderError, ValueError) as exc:
                    raise RenderError(f"{snap['id']}: {exc}") from exc
                paths.append(clip)
                tolerances.append(1 / float(fps))
                clips.append({"id": snap["id"], "source": status, "warning": warning, "audio_match": match})
            joined = tmp / "compilation.mp4"
            result = assemble(paths, joined, Encode(cfg.crf, cfg.preset, cfg.audio_bitrate, cfg.threads), runner=runner)
            _verify(joined, sum(s["duration"] for s in approved["clips"]), sum(tolerances), runner,
                    audio_tolerance=sum(tolerances))
            chapters = meta.chapters([title for _, title in references], result.parts)
            doc = {"schema_version": SCHEMA_VERSION, "plan_id": plan_id, "revision": approved["revision"],
                   "plan_fingerprint": fingerprint, "encode_key": key, "clips": clips, "duration": result.duration,
                   "chapters": chapters, "description": _description(config, approved, chapters, hashtags),
                   "download_name": (truncate_utf8(clean_part(approved["title"])) or plan_id) + ".mp4",
                   "created_at": utc_now(), "sha256": hashing.sha256_file(joined)}
            atomic_write_json(tmp / "metadata.json", doc)
            os.replace(joined, out)
            os.replace(tmp / "metadata.json", metadata_path)
            return LandscapeResult(out, doc, True)
    finally:
        try:
            fetch_root.rmdir()  # private job directories have already been cleaned, including on cancellation
        except OSError:
            pass
