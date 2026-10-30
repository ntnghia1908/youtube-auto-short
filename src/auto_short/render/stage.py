"""Render stage (CP7): titling done -> ``<output_dir>/<episode_id>/shorts/<clip_id>.mp4`` + ``render_manifest.json``.

Canonical contract: docs/decisions/CP7-render-contract.md; title overrides and deleted Shorts (``review.json``) and
per-Short reuse (``render_key``): docs/decisions/CP8.2-title-override-contract.md; manual cut points and Shorts
added by hand (``review.json`` ``cuts`` / ``added``, CP9): same contract T1, T8.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .. import hashing, khaithi
from ..config import Config, RenderConfig
from ..workspace import (
    DONE,
    StageError,
    Workspace,
    WorkspaceError,
    atomic_write_json,
    read_json_dict,
    read_stage_json,
    record_failure,
    run_stage,
    validate_episode_id,
)
from ..enhance import state as enhance_state
from ..review import archive as review_archive
from ..review import cuts as review_cuts
from ..review import logic as review_logic
from . import plan
from . import intro as clip_intro
from .text import MAX_LINES, Font, TextError, TextFit, baselines, fit_header, fit_title, nfc

log = logging.getLogger("auto_short")

STAGE = "render"
SCHEMA_VERSION = 1
METADATA_NAME = "metadata.json"
CANDIDATES_NAME = "candidates.json"
CLIPS_NAME = "clips.json"
TITLES_NAME = "titles.json"
SILENCES_NAME = "silences.json"
REVIEW_NAME = review_logic.REVIEW_NAME
RENDER_MANIFEST_NAME = "render_manifest.json"
SHORTS_DIR = "shorts"
TITLE_ORIGINS = (review_logic.AI, review_logic.MANUAL, review_logic.ALTERNATIVE)
RENDERED, SKIPPED = "rendered", "skipped"
UNTITLED, REJECTED = "untitled", "rejected"  # skip_reason (R2; CP8.5 X2)
PACKAGE_DIR = Path(__file__).resolve().parent

# [render] keys outside the config hash (R10): execution-only.
EXEC_KEYS = ("output_dir", "threads", "jobs")
HASH_KEYS = tuple(k for k in RenderConfig.__dataclass_fields__ if k not in EXEC_KEYS)
DURATION_TOLERANCE = 0.1  # s, R9


class RenderError(Exception):
    """Render failed; the manifest records status ``failed`` (except for invalid arguments)."""


class StoreWait(RenderError):
    """HD2a: the HD source of a released video is on the 3090 store and the store cannot lend it now (off the air, file
    missing, sha256 differs, no token). Not a render failure: the job waits ("đợi 3090") and is tried again."""


@dataclass(frozen=True)
class RenderResult:
    episode_id: str
    path: Path  # render_manifest.json
    ran: bool  # False when skipped as up to date
    rendered: int | None = None
    clips: int | None = None
    encoded: int | None = None  # Shorts encoded by this run (CP8.2 T5)
    reused: int | None = None  # Shorts reused unchanged from the previous render (CP8.2 T5)


Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)
    except FileNotFoundError as exc:
        raise RenderError(f"'{cmd[0]}' not found on PATH; install ffmpeg") from exc


def font_path(cfg: RenderConfig) -> Path:
    return PACKAGE_DIR / cfg.font_file


def fit_clip_title(font: Font, title: str, cfg: RenderConfig, geo: plan.Geometry) -> TextFit:
    """R5 title fit of one clip (display lines, font size, panel height); raises TextError. Shared by the
    render and the manual-title preview (CP8.2 T2)."""
    return fit_title(font, nfc(title), size0=plan.px(cfg.title_font_size), line_spacing=cfg.line_spacing,
                     inner_width=geo.title_w - 2 * cfg.panel_padding_x * plan.WIDTH, panel_height=geo.title_h,
                     max_panel_height=geo.title_max_h, padding_y=cfg.panel_padding_y * plan.WIDTH,
                     min_font_scale=cfg.min_font_scale)


def is_khaithi(ws_dir: Path) -> bool:
    """CP8.21 D1: a khai thị episode (CP8.9: decided only by the presence of ``khaithi.json``)."""
    return khaithi.path_of(ws_dir).exists()


def episode_render_config(config: Config, ws_dir: Path) -> tuple[RenderConfig, bool]:
    """([render] values the episode is rendered with, is khai thị): Short -> ``config.render`` untouched."""
    kt = is_khaithi(ws_dir)
    return plan.render_config_for(config.render, kt), kt


def used_config(cfg: RenderConfig, font_sha256: str, khaithi: bool = False) -> dict:
    used = {f"render.{k}": getattr(cfg, k) for k in HASH_KEYS}
    used["render.font_sha256"] = font_sha256
    if khaithi:  # CP8.21 D1; a Short keeps its hash byte for byte
        used["render.layout"] = plan.KHAITHI_LAYOUT_NAME
    return used


def _sha(doc: dict) -> str:
    return hashlib.sha256(hashing.canonical_json(doc).encode("utf-8")).hexdigest()


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


# --- media probing -----------------------------------------------------------------------------------------------

def probe_media(path: Path, run: Runner) -> dict:
    """Streams of ``path`` via ffprobe: {"video": {...}, "audio": {...} | None, "duration": float}."""
    proc = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if proc.returncode != 0:
        raise RenderError(f"ffprobe cannot read {path}: {_last_line(proc.stderr) or f'exit {proc.returncode}'}")
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        raise RenderError(f"ffprobe returned invalid JSON for {path}") from exc
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return {"video": video, "audio": audio, "duration": float(data.get("format", {}).get("duration") or 0)}


def _rate(stream: dict) -> Fraction:
    try:
        return plan.source_fps(stream)
    except ValueError:
        raise RenderError("cannot determine the source frame rate") from None


def video_end_seconds(video: dict, fps: Fraction) -> float | None:
    """End of the video stream (``start_time + duration``, s); falls back to ``nb_frames / fps`` when the stream
    has no duration; None when neither is known (FIX-render-video-tail)."""
    try:
        start = float(video.get("start_time") or 0)
        if video.get("duration") not in (None, "N/A", ""):
            return start + float(video["duration"])
        if video.get("nb_frames") not in (None, "N/A", ""):
            return start + int(video["nb_frames"]) / float(fps)
    except (TypeError, ValueError):
        pass
    return None


def verify_output(path: Path, fps: Fraction, planned_frames: int, run: Runner) -> None:
    """R9: 1080x1920 h264 yuv420p at ``fps``, aac 48 kHz stereo, video and audio within 0.1 s of the planned
    length; CP8.1 V5: exactly ``planned_frames`` video frames."""
    planned = planned_frames / float(fps)
    info = probe_media(path, run)
    v, a = info["video"], info["audio"]
    problems = []
    if v is None:
        problems.append("no video stream")
    else:
        got = (v.get("codec_name"), v.get("width"), v.get("height"), v.get("pix_fmt"))
        want = ("h264", plan.WIDTH, plan.HEIGHT, plan.PIX_FMT)
        if got != want:
            problems.append(f"video {got} != {want}")
        if Fraction(v.get("r_frame_rate") or "0/1") != fps:
            problems.append(f"frame rate {v.get('r_frame_rate')} != {plan.fps_text(fps)}")
        vd = float(v.get("duration") or 0)
        if abs(vd - planned) > DURATION_TOLERANCE:
            problems.append(f"video duration {vd:.3f} s != {planned:.3f} s")
        if str(v.get("nb_frames")) != str(planned_frames):
            problems.append(f"video frames {v.get('nb_frames')} != {planned_frames}")
    if a is None:
        problems.append("no audio stream")
    else:
        got = (a.get("codec_name"), int(a.get("sample_rate") or 0), a.get("channels"))
        want = ("aac", plan.SAMPLE_RATE, plan.CHANNELS)
        if got != want:
            problems.append(f"audio {got} != {want}")
        ad = float(a.get("duration") or 0)
        if abs(ad - planned) > DURATION_TOLERANCE:
            problems.append(f"audio duration {ad:.3f} s != {planned:.3f} s")
    if problems:
        raise RenderError(f"{path.name}: output check failed: {'; '.join(problems)}")


# --- planning ----------------------------------------------------------------------------------------------------

@dataclass
class ClipPlan:
    clip: dict  # render target (see render_targets)
    text: str | None  # title rendered (T4: override > AI title); None = untitled without override
    origin: str | None  # ai | manual | alternative
    segments: list[tuple[int, int]]
    title: TextFit | None
    layout: plan.Layout | None
    rejected: bool = False  # deleted in review.json (CP8.5 X2): skipped, no fit


def check_inputs(clips_doc: dict, titles_doc: dict, cand_doc: dict) -> None:
    """R3/R9: the three documents belong together (sha256 of the canonical JSON read)."""
    cands_sha, clips_sha = _sha(cand_doc), _sha(clips_doc)
    if clips_doc.get("candidates_sha256") != cands_sha:
        raise RenderError("clips.json does not match candidates.json (candidates_sha256); "
                          "re-run 'auto-short selection'")
    if titles_doc.get("clips_sha256") != clips_sha or titles_doc.get("candidates_sha256") != cands_sha:
        raise RenderError("titles.json does not match clips.json/candidates.json; re-run 'auto-short titling'")
    clips, titles = clips_doc.get("clips", []), titles_doc.get("titles", [])
    if [(c["id"], c["candidate_id"]) for c in clips] != [(t["clip_id"], t["candidate_id"]) for t in titles]:
        raise RenderError("titles.json entries do not match clips.json (ids/order); re-run 'auto-short titling'")
    lines = (titles_doc.get("header") or {}).get("lines") or []
    if not 1 <= len(lines) <= MAX_LINES or not all(isinstance(x, str) and x.strip() for x in lines):
        raise RenderError("titles.json header must have 1-3 non-empty lines; re-run 'auto-short titling'")


def load_silences(ws: Workspace, cand_doc: dict) -> list[tuple[float, float]]:
    """CP9 C5: ``silences.json`` for the trims of manual ranges; it must be the one candidates.json was built
    from (``silences_sha256``, like CP5 B8)."""
    doc = read_stage_json(ws.dir / SILENCES_NAME, "analysis", RenderError)
    if cand_doc.get("silences_sha256") != _sha(doc):
        raise RenderError("silences.json does not match candidates.json (silences_sha256); "
                          "re-run 'auto-short analysis'")
    return [(x["start"], x["end"]) for x in doc.get("silences", [])]


def render_targets(clips_doc: dict, review: dict, cand_doc: dict,
                   silences: Callable[[], list[tuple[float, float]]]) -> tuple[list[dict], list[str]]:
    """Every Short of the episode in render order (CP9 C2: clips.json clips, then the Shorts added by hand in
    creation order) with its range and kept segments (ms): a clip without manual cut keeps R3 (candidate trims);
    a manual range (cut or added Short) gets its trims from ``silences.json`` by CP4 A8 (C5). ``silences`` is
    called only when a manual range exists. Returns (targets, warnings of ignored cuts)."""
    trims = {c["id"]: c.get("trims", []) for c in cand_doc.get("candidates", [])}
    added = review.get(review_logic.ADDED_KEY, [])
    keys = [(c["id"], c["candidate_id"]) for c in clips_doc["clips"]] + [(a["clip_id"], a["candidate_id"])
                                                                        for a in added]
    cuts, warnings = review_logic.resolve_cuts(keys, review)
    sils: list | None = None

    def manual(clip_id: str, start: float, end: float) -> list[tuple[int, int]]:
        nonlocal sils
        if sils is None:
            sils = silences()
        try:
            max_pause = cand_doc["params"]["max_pause"]
        except (KeyError, TypeError) as exc:
            raise RenderError("candidates.json has no params.max_pause; re-run 'auto-short analysis'") from exc
        try:
            return review_cuts.kept_segments_ms(start, end, sils, max_pause)
        except plan.PlanError as exc:
            raise RenderError(f"clip {clip_id}: {exc}") from exc

    out = []
    for clip in clips_doc["clips"]:
        cid = clip["id"]
        if clip["candidate_id"] not in trims:
            raise RenderError(f"clip {cid}: candidate {clip['candidate_id']} not in candidates.json")
        if cid in cuts:
            start, end = cuts[cid]
            segs = manual(cid, start, end)
        else:
            start, end = clip["source_start"], clip["source_end"]
            try:
                segs = plan.kept_segments(start, end, trims[clip["candidate_id"]])
                plan.check_duration(cid, segs, clip["duration"])
            except plan.PlanError as exc:
                raise RenderError(str(exc)) from exc
        out.append({"id": cid, "candidate_id": clip["candidate_id"], "source_start": start, "source_end": end,
                    "duration": plan.total_ms(segs) / 1000 if cid in cuts else clip["duration"], "segments": segs,
                    "origin": review_logic.ORIGIN_AI,
                    "cut": {"start": start, "end": end} if cid in cuts else None})
    for a in added:
        cid = a["clip_id"]
        start, end = cuts.get(cid) or (a["start"], a["end"])
        segs = manual(cid, start, end)
        out.append({"id": cid, "candidate_id": a["candidate_id"], "source_start": start, "source_end": end,
                    "duration": plan.total_ms(segs) / 1000, "segments": segs, "origin": review_logic.ORIGIN_ADDED,
                    "cut": {"start": start, "end": end} if cid in cuts else None})
    return out, warnings


def plan_clips(targets: list[dict], titles: list[review_logic.ResolvedTitle], *, font: Font, cfg: RenderConfig,
               geo: plan.Geometry, src_w: int, src_h: int) -> list[ClipPlan]:
    """``titles``: the title of each target after overrides (T4), in the same order."""
    out = []
    for clip, rt in zip(targets, titles):
        fit = lay = None
        if rt.title is not None and not rt.rejected:
            try:
                fit = fit_clip_title(font, rt.title, cfg, geo)
            except TextError as exc:
                raise RenderError(f"clip {clip['id']}: {exc}") from exc
            lay = plan.layout(geo, fit.panel_height, src_w, src_h)
        out.append(ClipPlan(clip, rt.title, rt.origin, clip["segments"], fit, lay, rt.rejected))
    return out


def render_key(*, cfg_hash: str, font_sha: str, source_sha: str, fps: Fraction, segments: list[list[float]],
               dissolves: list[dict], layout: dict, header: TextFit, title: TextFit) -> str:
    """T5: sha256 (canonical JSON) of everything that decides a Short's bytes: plan version, render config
    hash, font and source sha256, fps, segments, dissolve plan, layout and the displayed header/title text
    (lines + font size; content, never temp file paths)."""
    return _sha({"plan_version": plan.RENDER_PLAN_VERSION, "render_config_hash": cfg_hash, "font_sha256": font_sha,
                 "source_sha256": source_sha, "fps": plan.fps_text(fps), "segments": segments,
                 "dissolves": dissolves, "layout": layout,
                 "header": {"display_lines": header.lines, "font_size": header.font_size},
                 "title": {"display_lines": title.lines, "font_size": title.font_size}})


def _write_lines(tmp: Path, tag: str, lines: list[str], bases: list[int]) -> list[plan.TextLine]:
    out = []
    for i, (line, base) in enumerate(zip(lines, bases)):
        f = tmp / f"{tag}{i}.txt"
        f.write_bytes(line.encode("utf-8"))
        out.append(plan.TextLine(f, base))
    return out


# --- validation (R9) ---------------------------------------------------------------------------------------------

def validate_render(doc: dict, targets: list[dict], out_dir: Path, *,
                    staged: dict[str, Path] | None = None, removing: frozenset[Path] = frozenset()) -> None:
    """R9 on the state after commit: ``targets`` = :func:`render_targets` (clips.json clips then added Shorts,
    CP9); ``staged`` maps the ``file`` of a Short encoded by this run to the .part holding it; ``removing`` =
    previous output files the commit deletes (T5)."""
    staged = staged or {}

    def exists_after(rel: str) -> bool:
        p = out_dir / rel
        return rel in staged or (p.exists() and p.resolve() not in removing)

    fps = Fraction(doc["encode"]["fps"])
    shorts = doc["shorts"]
    if [(s["clip_id"], s["candidate_id"]) for s in shorts] != [(c["id"], c["candidate_id"]) for c in targets]:
        raise RenderError("render_manifest shorts do not match clips.json + added Shorts (ids/order)")
    if len(doc["header"]["display_lines"]) > MAX_LINES:
        raise RenderError("header has more than 3 display lines")
    for s, c in zip(shorts, targets):
        if s["segments"] != plan.segments_seconds(c["segments"]) or s["duration"] != c["duration"] \
                or (s["source_start"], s["source_end"]) != (c["source_start"], c["source_end"]):
            raise RenderError(f"clip {s['clip_id']}: segments do not match R3")
        if (s["origin"], s["cut"]) != (c["origin"], c["cut"]):
            raise RenderError(f"clip {s['clip_id']}: origin / cut do not match review.json")
        if s["status"] == RENDERED:
            planned = plan.dissolves(c["segments"], fps, doc["encode"]["dissolve"])
            if s["dissolves"] != planned:
                raise RenderError(f"clip {s['clip_id']}: dissolves do not match the plan")
            path = staged.get(s["file"], out_dir / s["file"])
            if not path.is_file() or hashing.sha256_file(path) != s["sha256"]:
                raise RenderError(f"clip {s['clip_id']}: {s['file']} missing or sha256 mismatch")
            if not 1 <= len(s["title_display_lines"]) <= MAX_LINES:
                raise RenderError(f"clip {s['clip_id']}: title has {len(s['title_display_lines'])} display lines")
            if s["title_origin"] not in TITLE_ORIGINS or not isinstance(s["render_key"], str) \
                    or len(s["render_key"]) != 64:
                raise RenderError(f"clip {s['clip_id']}: invalid title_origin/render_key")
        elif s["status"] == SKIPPED:
            if s["skip_reason"] not in (UNTITLED, REJECTED):
                raise RenderError(f"clip {s['clip_id']}: invalid skip_reason {s['skip_reason']!r}")
            if s["file"] is not None or s["dissolves"] is not None or s["render_key"] is not None \
                    or exists_after(f"{SHORTS_DIR}/{s['clip_id']}.mp4"):
                raise RenderError(f"clip {s['clip_id']}: skipped clip has a file")
        else:
            raise RenderError(f"clip {s['clip_id']}: invalid status {s['status']!r}")
    st = doc["stats"]
    rendered = [s for s in shorts if s["status"] == RENDERED]
    if (st["clips"], st["rendered"], st["skipped"]) != (len(shorts), len(rendered), len(shorts) - len(rendered)) \
            or st["seconds"] != round(sum(s["duration"] for s in rendered), 3):
        raise RenderError("render_manifest stats are inconsistent")


# --- output cleanup (R8, CP8.2 T5) -------------------------------------------------------------------------------

def previous_outputs(out_dir: Path, artifacts: list[str]) -> list[Path]:
    """Files written by an earlier render of this episode: the stage's recorded artifacts and the files named
    in an existing render_manifest.json; only files inside ``out_dir`` are ever returned."""
    found: list[Path] = []
    rm = out_dir / RENDER_MANIFEST_NAME
    candidates = [Path(a) for a in artifacts] + [rm]
    if rm.is_file():
        try:
            old = json.loads(rm.read_text(encoding="utf-8"))
            candidates += [out_dir / s["file"] for s in old.get("shorts", []) if s.get("file")]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
    root = out_dir.resolve()
    for p in candidates:
        p = p if p.is_absolute() else out_dir / p
        try:
            p.resolve().relative_to(root)
        except ValueError:
            continue
        if p.resolve() != root and p not in found:
            found.append(p)
    return found


def previous_shorts(out_dir: Path, episode_id: str) -> dict[str, dict]:
    """``rendered`` entries of the existing render_manifest.json by clip id (T5 reuse candidates); an unreadable
    or foreign manifest gives none."""
    try:
        old = json.loads((out_dir / RENDER_MANIFEST_NAME).read_text(encoding="utf-8"))
        if old.get("episode_id") != episode_id:
            return {}
        return {s["clip_id"]: s for s in old.get("shorts", [])
                if isinstance(s, dict) and s.get("status") == RENDERED and isinstance(s.get("clip_id"), str)}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def reusable(prev: dict | None, key: str, rel: str, out_dir: Path) -> bool:
    """T5: the previous Short has the same render_key and its file is present with the recorded sha256."""
    if not prev or prev.get("render_key") != key or prev.get("file") != rel:
        return False
    path = out_dir / rel
    return path.is_file() and hashing.sha256_file(path) == prev.get("sha256")


def _remove(paths: list[Path]) -> None:
    for p in paths:
        if p.is_file() or p.is_symlink():
            p.unlink()


@dataclass
class _RunFiles:
    """Files touched by one render run, so a failure deletes only what this run wrote (T5)."""

    staged: dict[str, Path]  # file (relative to out_dir) -> .part encoded by this run, not yet committed
    committed: list[Path]  # finals moved into place by the commit
    committing: bool = False


@dataclass
class _Encode:
    """One Short to encode (planned sequentially, J3); ``record`` receives the sha256."""

    clip: dict
    cp: ClipPlan
    record: dict
    fit: TextFit
    dissolves: list[dict]
    part: Path
    cmd: list[str]
    intro_image: Path | None
    cfg: RenderConfig


def _encode_one(task: _Encode, run: Runner, fps: Fraction) -> None:
    clip, cp, fit, part = task.clip, task.cp, task.fit, task.part
    t0 = time.monotonic()
    proc = run(task.cmd)
    if proc.returncode != 0 or not part.is_file():
        raise RenderError(f"clip {clip['id']}: ffmpeg failed: "
                          f"{_last_line(proc.stderr) or f'exit {proc.returncode}'}")
    verify_output(part, fps, plan.planned_frames(cp.segments, fps), run)
    if task.intro_image is not None:
        task.record["content_sha256"] = hashing.sha256_file(part)
        with tempfile.TemporaryDirectory(prefix=".clip-intro-", dir=part.parent) as name:
            work = Path(name)
            content = work / "content.mp4"
            os.replace(part, content)
            task.record["content_offset"] = clip_intro.prepend(content, part, task.intro_image, fps, task.cfg, work, run)
        verify_output(part, fps, plan.planned_frames(cp.segments, fps) + round(clip_intro.INTRO_SECONDS * fps), run)
    task.record["sha256"] = hashing.sha256_file(part)
    log.info("%s: clip %s: %s (%d px, panel %d px, %s), %d segment(s), %d dissolve(s), %.3f s, "
             "rendered in %.1f s", STAGE, clip["id"], " / ".join(fit.lines), fit.font_size,
             fit.panel_height, cp.origin, len(cp.segments), sum(1 for d in task.dissolves if d["frames"]),
             clip["duration"], time.monotonic() - t0)


def _encode_all(tasks: list[_Encode], run: Runner, fps: Fraction, jobs: int) -> None:
    """J3/J4: encode up to ``jobs`` Shorts at once. After the first failure no new encode starts; running ones
    finish (never killed); the error of the earliest failing clip in clip order is raised."""
    if jobs <= 1 or len(tasks) <= 1:
        for task in tasks:
            _encode_one(task, run, fps)
        return
    stop = threading.Event()
    errors: dict[int, RenderError] = {}

    def work(i: int) -> None:
        if stop.is_set():
            return
        try:
            _encode_one(tasks[i], run, fps)
        except RenderError as exc:
            errors[i] = exc
            stop.set()

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        try:
            for f in [pool.submit(work, i) for i in range(len(tasks))]:
                f.result()
        except BaseException:
            stop.set()
            raise
    if errors:
        raise errors[min(errors)]


# --- stage -------------------------------------------------------------------------------------------------------

def _intro_from_existing(ws: Workspace, manifest: dict, config: Config, cfg: RenderConfig,
                         images: dict[str, Path], run: Runner) -> RenderResult | None:
    """Add/replace the intro of unchanged clips, including archived sources and SHO1 releases.

    Verify the complete old stage input chain and config before trusting its encoded content. A title / cut /
    config change takes the normal render path instead.
    """
    out_dir = (cfg.output_dir / ws.episode_id).resolve()
    path = out_dir / RENDER_MANIFEST_NAME
    old = read_json_dict(path)
    entry = manifest["stages"].get(STAGE) or {}
    if not old or old.get("episode_id") != ws.episode_id or entry.get("status") not in (DONE, "failed"):
        return None
    if not font_path(cfg).is_file():
        return None
    cfg_hash = hashing.config_hash(used_config(cfg, hashing.sha256_file(font_path(cfg)), True))
    if old.get("render_config_hash") != cfg_hash or entry.get("config_hash") != cfg_hash:
        return None
    docs = {n: read_json_dict(ws.dir / n) for n in (CLIPS_NAME, TITLES_NAME, CANDIDATES_NAME)}
    if any(not d or _sha(d) != old.get(key) for key, d in (
            ("clips_sha256", docs[CLIPS_NAME]), ("titles_sha256", docs[TITLES_NAME]),
            ("candidates_sha256", docs[CANDIDATES_NAME]))):
        return None
    try:
        review = review_logic.read_review(ws.dir / REVIEW_NAME, ws.episode_id)
        resolved, _ = review_logic.resolve_titles(docs[TITLES_NAME]["titles"] + review_logic.added_entries(review), review)
        targets, _ = render_targets(docs[CLIPS_NAME], review, docs[CANDIDATES_NAME],
                                    lambda: load_silences(ws, docs[CANDIDATES_NAME]))
    except (review_logic.ReviewError, RenderError):
        return None
    if len(targets) != len(old["shorts"]) or len(resolved) != len(targets):
        return None
    for s, target, title in zip(old["shorts"], targets, resolved):
        fields = ("candidate_id", "source_start", "source_end", "duration", "origin", "cut")
        if s["clip_id"] != target["id"] or any(s.get(k) != target[k] for k in fields) \
                or s["segments"] != plan.segments_seconds(target["segments"]) \
                or s.get("title") != title.title or s.get("title_origin") != title.origin \
                or (s.get("status") == RENDERED) != bool(title.title and not title.rejected):
            return None
    inputs = [i for i in entry.get("inputs", []) if "clip_intro" not in i]
    expected = {ws.relpath(ws.dir / n) for n in (CLIPS_NAME, TITLES_NAME, CANDIDATES_NAME, METADATA_NAME)}
    if (ws.dir / REVIEW_NAME).is_file():
        expected.add(ws.relpath(ws.dir / REVIEW_NAME))
    source_paths = {ws.resolve(manifest["source"]["path"]).resolve(), enhance_state.hd_path(ws.dir).resolve()}
    cached = ws.source_fingerprint(manifest)
    hd_fp = enhance_state.hd_fingerprint(ws.dir)
    if hd_fp is not None:
        cached.append(hd_fp)
    actual = set()
    for inp in inputs:
        p = ws.resolve(inp["path"])
        if p.resolve() not in source_paths:
            actual.add(inp["path"])
        if p.is_file():
            sha = hashing.fingerprint(p, cached).sha256 if p.resolve() in source_paths else hashing.sha256_file(p)
            if sha != inp["sha256"]:
                return None
        elif p.resolve() not in source_paths or inp["sha256"] != old.get("source_sha256"):
            return None
    if actual != expected:
        return None
    hd = enhance_state.read(ws.dir) or {}
    source_sha = hd.get("source_hd_sha256") if enhance_state._hd_usable(hd) else manifest["source"]["sha256"]
    if source_sha != old.get("source_sha256"):
        return None
    records = [s for s in old["shorts"] if s.get("status") == RENDERED]
    if {s["clip_id"] for s in records} != set(images):
        return None
    pending = []
    for s in records:
        if s.get("intro") != clip_intro.metadata(images[s["clip_id"]]):
            pending.append(s["clip_id"])
        if s.get("file") != f"{SHORTS_DIR}/{s['clip_id']}.mp4":
            return None
    released = (read_json_dict(out_dir / "store.json") or {}).get("released", {})
    for s in records:
        p = out_dir / s["file"]
        if p.is_file():
            if hashing.sha256_file(p) != s["sha256"]:
                return None
        elif released.get(s["clip_id"], {}).get("sha256") != s["sha256"]:
            return None
    if not pending and entry.get("status") == DONE:
        return RenderResult(ws.episode_id, path, False)
    from ..store.shorts import restore_released
    if pending:
        restore_released(config, ws.episode_id)
    workspace_sha = hashing.sha256_file(ws.manifest_path)
    for cid, image in sorted(images.items()):
        inputs.append({"clip_intro": cid, **clip_intro.metadata(image)})
    fps = Fraction(old["encode"]["fps"])

    def action():
        doc = read_json_dict(path)
        staged, committed = {}, []
        try:
            for s in doc["shorts"]:
                if s["clip_id"] not in pending:
                    continue
                source = out_dir / s["file"]
                part = source.with_name(f".{source.name}.part")
                staged[part] = source
                base = clip_intro.content_record(s)
                with tempfile.TemporaryDirectory(prefix=".clip-intro-", dir=source.parent) as tmp:
                    work = Path(tmp)
                    content = clip_intro.extract_content(source, work / "content.mp4", s, run) if s.get("intro") else source
                    s["content_offset"] = clip_intro.prepend(content, part, images[s["clip_id"]], fps, cfg, work, run)
                s.update(content_sha256=base["sha256"], content_render_key=base["render_key"],
                         intro=clip_intro.metadata(images[s["clip_id"]]))
                s["render_key"] = _sha({"content_render_key": s["content_render_key"], "intro": s["intro"]})
                s["sha256"] = hashing.sha256_file(part)
                frames = plan.planned_frames([(round(a * 1000), round(b * 1000)) for a, b in s["segments"]], fps)
                verify_output(part, fps, frames + round(clip_intro.INTRO_SECONDS * fps), run)
            doc["content_workspace_manifest_sha256"] = old.get("content_workspace_manifest_sha256") or workspace_sha
            for part, destination in staged.items():
                os.replace(part, destination)
                committed.append(destination)
            atomic_write_json(path, doc)
        except BaseException:
            if committed:
                _remove(committed + [path])
            raise
        finally:
            _remove(list(staged))
        return [str(path)] + [str(out_dir / s["file"]) for s in records]

    try:
        ran = run_stage(ws, manifest, STAGE, inputs=inputs, cfg_hash=cfg_hash, force=False, action=action)
    except StageError as exc:
        raise RenderError(str(exc)) from exc
    return RenderResult(ws.episode_id, path, ran, old["stats"]["rendered"], old["stats"]["clips"],
                        len(pending), len(records) - len(pending))


def run_render(episode_id: str, config: Config, *, force: bool = False, run: Runner | None = None,
               _hd_borrowed: bool = False) -> RenderResult:
    """Render the episode's Shorts (CP7), applying ``review.json`` title overrides and reusing every Short whose
    render_key is unchanged (CP8.2 T4/T5); ``force`` re-runs the stage and encodes every Short."""
    runner = run or _run
    try:
        ws = Workspace(config.workspace.dir, validate_episode_id(episode_id))
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise RenderError(str(exc)) from exc
    cfg, kt = episode_render_config(config, ws.dir)
    if manifest is None:
        raise RenderError(f"no manifest for episode {episode_id!r} in {ws.dir}; run 'auto-short ingest' first")
    images = {}
    if kt:
        from ..packaging import PackageError, khaithi_thumbs
        try:
            context = khaithi_thumbs.intro_context(config, ws.episode_id)
            if context is not None:
                pid, fields = context
                if "kt_vertical" not in khaithi_thumbs.cover.current(config, pid):
                    raise PackageError(f"Bộ kinh chưa có ảnh bìa khai thị — /playlists/{pid}/thumbs")
                for title in khaithi_thumbs.titles(config, ws.episode_id):
                    images[title.clip_id] = khaithi_thumbs.vertical_clip(
                        config, ws.episode_id, title.clip_id, pid=pid, fields=fields, run=runner)
        except (PackageError, TextError, OSError, ValueError) as exc:
            record_failure(ws, manifest, STAGE, str(exc))
            raise RenderError(str(exc)) from exc
    if images and not force:
        existing = _intro_from_existing(ws, manifest, config, cfg, images, runner)
        if existing is not None:
            return existing
    if review_archive.is_archived(ws.dir):
        # CP8.6 S3: the source video was cleaned up; the last render stays as it is (manifest untouched).
        raise RenderError(f"episode {ws.episode_id!r} is archived (source video cleaned up); its Shorts are kept "
                          "as they are — delete the episode and run it again to change them")
    from ..store.shorts import restore_released  # lazy: shorts uses render/web metadata helpers
    restore_released(config, ws.episode_id)
    if not _hd_borrowed and (enhance_state.is_released(ws.dir)
                             or enhance_state.is_released(Path(ws.root) / enhance_state.owner_id(ws.episode_id))):
        # HD1 G3: the HD source was moved to an external machine; never fall back to the original silently, and the
        # manifest stays untouched (the Shorts rendered from the HD source stay current).
        if config.store.enabled:  # HD2a G4: lend the HD from the 3090 store for this render, delete it afterwards
            from ..store.borrow import borrow_hd  # lazy: store.borrow imports this module
            with borrow_hd(config, ws.episode_id, ws.dir):
                if enhance_state.hd_fingerprint(ws.dir) is None:
                    raise RenderError(f"episode {ws.episode_id!r}: bản HD lấy từ kho không khớp enhance.json; "
                                      "không render từ bản gốc")
                return run_render(episode_id, config, force=force, run=run, _hd_borrowed=True)
        raise RenderError(f"episode {ws.episode_id!r}: {enhance_state.RELEASED_MESSAGE} (HD1); "
                          "không render lại từ bản gốc — lấy lại nguồn HD trước")
    out_dir = (cfg.output_dir / ws.episode_id).resolve()
    prior = list((manifest["stages"].get(STAGE) or {}).get("artifacts", []))

    def fail(msg: str) -> RenderError:
        # T5: nothing was written by this run; the previous render (if any) stays as it was.
        record_failure(ws, manifest, STAGE, msg)
        return RenderError(msg)

    ti_entry = manifest["stages"].get("titling") or {}
    paths = {n: ws.dir / n for n in (CLIPS_NAME, TITLES_NAME, CANDIDATES_NAME, METADATA_NAME)}
    if ti_entry.get("status") != DONE or not all(p.is_file() for p in paths.values()):
        raise fail(f"titling is not done for {episode_id!r} (status: {ti_entry.get('status', 'pending')}); "
                   "run 'auto-short titling' first")

    fpath = font_path(cfg)
    if not fpath.is_file():
        raise fail(f"font file not found: {fpath} (config render.font_file)")
    font_sha = hashing.sha256_file(fpath)
    src = manifest["source"]
    media = ws.resolve(src["path"]).absolute()
    hd_fp = enhance_state.hd_fingerprint(ws.dir)  # CP13.1 E6: the enhanced source, when there is one, replaces it
    try:
        if hd_fp is not None:
            media, media_fp = hd_fp.path, hd_fp
        else:
            media_fp = hashing.fingerprint(media, ws.source_fingerprint(manifest))
    except OSError as exc:
        raise fail(f"cannot read source media {media}: {exc}") from exc
    review_path = ws.dir / REVIEW_NAME
    input_paths = list(paths.values()) + ([review_path] if review_path.is_file() else [])
    inputs = [{"path": ws.relpath(p), "sha256": hashing.sha256_file(p)} for p in input_paths]
    inputs.append({"path": ws.relpath(media), "sha256": media_fp.sha256})
    for cid, image in sorted(images.items()):
        inputs.append({"clip_intro": cid, **clip_intro.metadata(image)})
    cfg_hash = hashing.config_hash(used_config(cfg, font_sha, kt))
    workspace_manifest_sha = hashing.sha256_file(ws.manifest_path)
    outcome: dict = {}

    def action() -> list[str]:
        files = _RunFiles({}, [])
        try:
            doc = _render_all(ws, cfg, fpath, font_sha, media, media_fp.sha256, cfg_hash, paths, review_path,
                              out_dir, runner, force=force, old_outputs=previous_outputs(out_dir, prior),
                              files=files, intro_images=images, workspace_manifest_sha=workspace_manifest_sha,
                              hd_source=enhance_state.hd_source(ws.dir, media_fp.sha256, media)
                              if hd_fp is not None else None)
        except BaseException:
            # Only files of this run; once the commit has started the previous manifest no longer
            # describes the files on disk, so it goes too.
            _remove(list(files.staged.values()) + files.committed
                    + ([out_dir / RENDER_MANIFEST_NAME] if files.committing else []))
            raise
        st = doc["stats"]
        outcome.update(rendered=st["rendered"], clips=st["clips"], encoded=len(files.staged),
                       reused=st["rendered"] - len(files.staged))
        return [str(out_dir / RENDER_MANIFEST_NAME)] + [str(out_dir / s["file"]) for s in doc["shorts"]
                                                         if s["status"] == RENDERED]

    try:
        ran = run_stage(ws, manifest, STAGE, inputs=inputs, cfg_hash=cfg_hash, force=force, action=action)
    except StageError as exc:
        raise RenderError(str(exc)) from exc
    return RenderResult(ws.episode_id, out_dir / RENDER_MANIFEST_NAME, ran, outcome.get("rendered"),
                        outcome.get("clips"), outcome.get("encoded"), outcome.get("reused"))


def _render_all(ws: Workspace, cfg: RenderConfig, fpath: Path, font_sha: str, media: Path, source_sha: str,
                cfg_hash: str, paths: dict[str, Path], review_path: Path, out_dir: Path, run: Runner, *,
                force: bool, old_outputs: list[Path], files: _RunFiles,
                intro_images: dict[str, Path] | None = None, workspace_manifest_sha: str | None = None,
                hd_source: enhance_state.EffectiveSource | None = None) -> dict:
    intro_images = intro_images or {}
    clips_doc = read_stage_json(paths[CLIPS_NAME], "selection", RenderError)
    titles_doc = read_stage_json(paths[TITLES_NAME], "titling", RenderError)
    cand_doc = read_stage_json(paths[CANDIDATES_NAME], "analysis", RenderError)
    check_inputs(clips_doc, titles_doc, cand_doc)
    try:
        review = review_logic.read_review(review_path, ws.episode_id)
    except review_logic.ReviewError as exc:
        raise RenderError(f"{exc}; fix it or reset the override with 'auto-short title … --reset'") from exc
    resolved, warnings = review_logic.resolve_titles(titles_doc["titles"] + review_logic.added_entries(review),
                                                     review)
    targets, cut_warnings = render_targets(clips_doc, review, cand_doc, lambda: load_silences(ws, cand_doc))
    for w in warnings + cut_warnings:
        log.warning("%s: WARNING: %s", STAGE, w)

    font = Font(fpath)
    try:
        geo = plan.geometry(cfg, khaithi=is_khaithi(ws.dir))
    except plan.PlanError as exc:
        raise RenderError(str(exc)) from exc
    info = probe_media(media, run)
    if info["video"] is None or info["audio"] is None:
        raise RenderError(f"source media needs a video and an audio stream: {media}")
    src_w, src_h = int(info["video"]["width"]), int(info["video"]["height"])
    fps = plan.output_fps(_rate(info["video"]))
    video_end = enhance_state.hd_duration(hd_source, video_end_seconds(info["video"], fps))

    header_lines = [nfc(x) for x in titles_doc["header"]["lines"]]
    try:
        header = fit_header(font, header_lines, size0=plan.px(cfg.header_font_size), line_spacing=cfg.line_spacing,
                            inner_width=geo.header_w - 2 * cfg.panel_padding_x * plan.WIDTH,
                            panel_height=geo.header_h, padding_y=cfg.panel_padding_y * plan.WIDTH,
                            min_font_scale=cfg.min_font_scale)
    except TextError as exc:
        raise RenderError(str(exc)) from exc
    plans = plan_clips(targets, resolved, font=font, cfg=cfg, geo=geo, src_w=src_w, src_h=src_h)
    base_layout = plan.layout(geo, geo.title_h, src_w, src_h)

    log.info("%s: font %s (%s), fps %s, source %dx%d, dissolve %g s (%d frames)%s", STAGE, font.family,
             cfg.font_file, plan.fps_text(fps), src_w, src_h, cfg.dissolve, 2 * plan.dissolve_half(cfg.dissolve, fps),
             f", jobs {cfg.jobs}" if cfg.jobs > 1 else "")
    log.info("%s: layout header %s, video %s crop %s, title %s (max h %d)", STAGE, base_layout.header,
             base_layout.video, base_layout.crop, base_layout.title, geo.title_max_h)
    log.info("%s: header %s (%d px)", STAGE, " / ".join(header.lines), header.font_size)

    previous = {} if force else previous_shorts(out_dir, ws.episode_id)
    shorts_dir = out_dir / SHORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    shorts = []
    tasks: list[_Encode] = []  # Shorts to encode, in clip order (J3)
    t_all = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="auto-short-render-") as tmpname:
        tmp = Path(tmpname)
        h_lines = _write_lines(tmp, "h", header.lines, baselines(len(header.lines), font=font,
                                                                 size=header.font_size, pitch=header.line_pitch,
                                                                 panel_height=geo.header_h))
        for cp in plans:
            clip = cp.clip
            record = {"clip_id": clip["id"], "candidate_id": clip["candidate_id"], "status": SKIPPED,
                      "skip_reason": None, "file": None, "sha256": None, "title": cp.text,
                      "title_display_lines": None, "title_font_size": None, "layout": None,
                      "source_start": clip["source_start"], "source_end": clip["source_end"],
                      "segments": plan.segments_seconds(cp.segments), "duration": clip["duration"],
                      "dissolves": None, "title_origin": cp.origin, "render_key": None,
                      "origin": clip["origin"], "cut": clip["cut"]}  # CP9 C5 (last keys)
            if clip["cut"] is not None or clip["origin"] != review_logic.ORIGIN_AI:
                log.info("%s: clip %s: %s range %.3f-%.3f (%.3f s)", STAGE, clip["id"],
                         "manual cut" if clip["cut"] else "added", clip["source_start"], clip["source_end"],
                         clip["duration"])
            if cp.rejected:
                record["skip_reason"] = REJECTED
                log.info("%s: clip %s skipped: rejected (deleted in review)", STAGE, clip["id"])
                shorts.append(record)
                continue
            if cp.title is None:
                record["skip_reason"] = UNTITLED
                log.warning("%s: WARNING: clip %s skipped: untitled (no approved title)", STAGE, clip["id"])
                shorts.append(record)
                continue
            fit, lay = cp.title, cp.layout
            dissolves = plan.dissolves(cp.segments, fps, cfg.dissolve)
            key = render_key(cfg_hash=cfg_hash, font_sha=font_sha, source_sha=source_sha, fps=fps,
                             segments=record["segments"], dissolves=dissolves, layout=lay.as_dict(), header=header,
                             title=fit)
            image = intro_images.get(clip["id"])
            if image is not None:
                record.update(content_render_key=key,
                              intro=clip_intro.metadata(image))
                key = _sha({"content_render_key": key, "intro": record["intro"]})
            rel = f"{SHORTS_DIR}/{clip['id']}.mp4"
            record.update(status=RENDERED, file=rel, title_display_lines=fit.lines, title_font_size=fit.font_size,
                          layout=lay.as_dict(), dissolves=dissolves, render_key=key)
            shorts.append(record)
            if reusable(previous.get(clip["id"]), key, rel, out_dir):
                record["sha256"] = previous[clip["id"]]["sha256"]
                if image is not None:
                    for field in ("content_sha256", "content_offset"):
                        record[field] = previous[clip["id"]][field]
                log.info("%s: clip %s: reuse (render_key unchanged): %s (%s)", STAGE, clip["id"],
                         " / ".join(fit.lines), cp.origin)
                continue
            tail = plan.tail_missing(plan.frame_plan(cp.segments, fps), fps, video_end)
            if tail > plan.tail_clone_limit(fps):  # FIX-render-video-tail T2: no encode, no .part
                raise RenderError(f"clip {clip['id']}: video stream ends at {video_end:.3f} s, before the clip end "
                                  f"{cp.segments[-1][1] / 1000:.3f} s")
            t_lines = _write_lines(tmp, f"t{clip['id']}_", fit.lines,
                                   baselines(len(fit.lines), font=font, size=fit.font_size, pitch=fit.line_pitch,
                                             panel_height=fit.panel_height))
            script = tmp / f"{clip['id']}.filter"
            script.write_text(plan.filter_graph(segments=cp.segments, fps=fps, lay=lay, font_file=fpath,
                                                header_lines=h_lines, header_size=header.font_size,
                                                title_lines=t_lines, title_size=fit.font_size,
                                                dissolve=cfg.dissolve, tail=tail), encoding="utf-8")
            shorts_dir.mkdir(exist_ok=True)
            part = shorts_dir / f".{clip['id']}.mp4.part"
            files.staged[rel] = part
            cmd = plan.ffmpeg_command(ffmpeg="ffmpeg", source=media, output=part, graph_script=script,
                                      segments=cp.segments, fps=fps, crf=cfg.crf, preset=cfg.preset,
                                      audio_bitrate=cfg.audio_bitrate, threads=cfg.threads)
            cmd = enhance_state.hd_input_command(hd_source, cmd, media)
            tasks.append(_Encode(clip, cp, record, fit, dissolves, part, cmd, image, cfg))
        _encode_all(tasks, run, fps, cfg.jobs)

    rendered = [s for s in shorts if s["status"] == RENDERED]
    base = base_layout.as_dict()
    doc = {
        "schema_version": SCHEMA_VERSION, "episode_id": ws.episode_id,
        "source_sha256": source_sha,
        "clips_sha256": _sha(clips_doc), "titles_sha256": _sha(titles_doc), "candidates_sha256": _sha(cand_doc),
        "render_config_hash": cfg_hash, "title_source": cfg.title_source,
        "font": {"family": font.family, "file": cfg.font_file, "sha256": font_sha},
        "layout": {"width": plan.WIDTH, "height": plan.HEIGHT, "background": plan.BACKGROUND,
                   "panel_color": plan.PANEL_COLOR, **base},
        "encode": {"vcodec": plan.VCODEC, "crf": cfg.crf, "preset": cfg.preset, "pix_fmt": plan.PIX_FMT,
                   "fps": plan.fps_text(fps), "acodec": plan.ACODEC, "sample_rate": plan.SAMPLE_RATE,
                   "channels": plan.CHANNELS, "audio_bitrate": cfg.audio_bitrate, "dissolve": cfg.dissolve},
        "header": {"lines": header_lines, "display_lines": header.lines, "font_size": header.font_size},
        "stats": {"clips": len(shorts), "rendered": len(rendered), "skipped": len(shorts) - len(rendered),
                  "seconds": round(sum(s["duration"] for s in rendered), 3)},
        "shorts": shorts,
    }
    # T5 cleanup: previous files that are neither reused nor replaced by this run's Shorts.
    manifest_path = out_dir / RENDER_MANIFEST_NAME
    if intro_images:
        old = read_json_dict(manifest_path)
        if old and clip_intro.content_manifest(old) == clip_intro.content_manifest(doc):
            doc["content_workspace_manifest_sha256"] = old.get("content_workspace_manifest_sha256") or workspace_manifest_sha
    keep = {(out_dir / s["file"]).resolve() for s in rendered} | {manifest_path.resolve()}
    removing = [p for p in old_outputs if p.resolve() not in keep]
    validate_render(doc, targets, out_dir, staged=files.staged,
                    removing=frozenset(p.resolve() for p in removing))

    files.committing = True
    for rel, part in files.staged.items():
        os.replace(part, out_dir / rel)
        files.committed.append(out_dir / rel)
    _remove(removing)
    atomic_write_json(manifest_path, doc)

    st = doc["stats"]
    encoded = len(files.staged)
    log.info("%s: rendered %d/%d clips (%d encoded, %d reused), %.1f s of Shorts in %.1f s", STAGE, st["rendered"],
             st["clips"], encoded, st["rendered"] - encoded, st["seconds"], time.monotonic() - t_all)
    untitled = [s["clip_id"] for s in shorts if s["status"] == SKIPPED and s["skip_reason"] != REJECTED]
    if untitled:
        log.warning("%s: WARNING: %d clip(s) skipped: %s", STAGE, len(untitled),
                    ", ".join(f"{c} ({UNTITLED})" for c in untitled))
    if st["skipped"] > len(untitled):
        log.info("%s: %d clip(s) deleted in review (rejected): %s", STAGE, st["skipped"] - len(untitled),
                 ", ".join(s["clip_id"] for s in shorts if s["skip_reason"] == REJECTED))
    if not rendered:
        log.warning("%s: WARNING: no titled clip, no Short rendered", STAGE)
    return doc
