"""Render stage (CP7): titling done -> ``<output_dir>/<episode_id>/shorts/<clip_id>.mp4`` + ``render_manifest.json``.

Canonical contract: docs/decisions/CP7-render-contract.md; title overrides (``review.json``) and per-Short reuse
(``render_key``): docs/decisions/CP8.2-title-override-contract.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .. import hashing
from ..config import Config, RenderConfig
from ..workspace import (
    DONE,
    StageError,
    Workspace,
    WorkspaceError,
    atomic_write_json,
    record_failure,
    run_stage,
    validate_episode_id,
)
from ..review import logic as review_logic
from . import plan
from .text import MAX_LINES, Font, TextError, TextFit, baselines, fit_header, fit_title, nfc

log = logging.getLogger("auto_short")

STAGE = "render"
SCHEMA_VERSION = 1
METADATA_NAME = "metadata.json"
CANDIDATES_NAME = "candidates.json"
CLIPS_NAME = "clips.json"
TITLES_NAME = "titles.json"
REVIEW_NAME = review_logic.REVIEW_NAME
RENDER_MANIFEST_NAME = "render_manifest.json"
SHORTS_DIR = "shorts"
TITLE_ORIGINS = (review_logic.AI, review_logic.MANUAL, review_logic.ALTERNATIVE)
RENDERED, SKIPPED = "rendered", "skipped"
PACKAGE_DIR = Path(__file__).resolve().parent

# [render] keys outside the config hash (R10): execution-only.
EXEC_KEYS = ("output_dir", "threads")
HASH_KEYS = tuple(k for k in RenderConfig.__dataclass_fields__ if k not in EXEC_KEYS)
DURATION_TOLERANCE = 0.1  # s, R9


class RenderError(Exception):
    """Render failed; the manifest records status ``failed`` (except for invalid arguments)."""


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


def used_config(cfg: RenderConfig, font_sha256: str) -> dict:
    used = {f"render.{k}": getattr(cfg, k) for k in HASH_KEYS}
    used["render.font_sha256"] = font_sha256
    return used


def _sha(doc: dict) -> str:
    return hashlib.sha256(hashing.canonical_json(doc).encode("utf-8")).hexdigest()


def _read_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RenderError(f"cannot read {path}: {exc}; re-run 'auto-short {what}'") from exc


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
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            value = Fraction(stream.get(key) or "0/0")
        except (ValueError, ZeroDivisionError):
            continue
        if value > 0:
            return value
    raise RenderError("cannot determine the source frame rate")


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
    clip: dict
    text: str | None  # title rendered (T4: override > AI title); None = untitled without override
    origin: str | None  # ai | manual | alternative
    segments: list[tuple[int, int]]
    title: TextFit | None
    layout: plan.Layout | None


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


def plan_clips(clips_doc: dict, titles: list[review_logic.ResolvedTitle], cand_doc: dict, *, font: Font,
               cfg: RenderConfig, geo: plan.Geometry, src_w: int, src_h: int) -> list[ClipPlan]:
    """``titles``: the title of each clip after overrides (T4), in clips.json order."""
    trims = {c["id"]: c.get("trims", []) for c in cand_doc.get("candidates", [])}
    out = []
    for clip, rt in zip(clips_doc["clips"], titles):
        if clip["candidate_id"] not in trims:
            raise RenderError(f"clip {clip['id']}: candidate {clip['candidate_id']} not in candidates.json")
        try:
            segs = plan.kept_segments(clip["source_start"], clip["source_end"], trims[clip["candidate_id"]])
            plan.check_duration(clip["id"], segs, clip["duration"])
        except plan.PlanError as exc:
            raise RenderError(str(exc)) from exc
        fit = lay = None
        if rt.title is not None:
            try:
                fit = fit_clip_title(font, rt.title, cfg, geo)
            except TextError as exc:
                raise RenderError(f"clip {clip['id']}: {exc}") from exc
            lay = plan.layout(geo, fit.panel_height, src_w, src_h)
        out.append(ClipPlan(clip, rt.title, rt.origin, segs, fit, lay))
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

def validate_render(doc: dict, clips_doc: dict, cand_doc: dict, out_dir: Path, *,
                    staged: dict[str, Path] | None = None, removing: frozenset[Path] = frozenset()) -> None:
    """R9 on the state after commit: ``staged`` maps the ``file`` of a Short encoded by this run to the .part
    holding it; ``removing`` = previous output files the commit deletes (T5)."""
    staged = staged or {}

    def exists_after(rel: str) -> bool:
        p = out_dir / rel
        return rel in staged or (p.exists() and p.resolve() not in removing)

    clips = clips_doc["clips"]
    fps = Fraction(doc["encode"]["fps"])
    shorts = doc["shorts"]
    if [(s["clip_id"], s["candidate_id"]) for s in shorts] != [(c["id"], c["candidate_id"]) for c in clips]:
        raise RenderError("render_manifest shorts do not match clips.json (ids/order)")
    trims = {c["id"]: c.get("trims", []) for c in cand_doc.get("candidates", [])}
    if len(doc["header"]["display_lines"]) > MAX_LINES:
        raise RenderError("header has more than 3 display lines")
    for s, c in zip(shorts, clips):
        segs = plan.segments_seconds(plan.kept_segments(c["source_start"], c["source_end"], trims[c["candidate_id"]]))
        if s["segments"] != segs or s["duration"] != c["duration"]:
            raise RenderError(f"clip {s['clip_id']}: segments do not match R3")
        if s["status"] == RENDERED:
            planned = plan.dissolves(plan.kept_segments(c["source_start"], c["source_end"], trims[c["candidate_id"]]),
                                     fps, doc["encode"]["dissolve"])
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


# --- stage -------------------------------------------------------------------------------------------------------

def run_render(episode_id: str, config: Config, *, force: bool = False, run: Runner | None = None) -> RenderResult:
    """Render the episode's Shorts (CP7), applying ``review.json`` title overrides and reusing every Short whose
    render_key is unchanged (CP8.2 T4/T5); ``force`` re-runs the stage and encodes every Short."""
    cfg = config.render
    runner = run or _run
    try:
        ws = Workspace(config.workspace.dir, validate_episode_id(episode_id))
        manifest = ws.load_manifest()
    except WorkspaceError as exc:
        raise RenderError(str(exc)) from exc
    if manifest is None:
        raise RenderError(f"no manifest for episode {episode_id!r} in {ws.dir}; run 'auto-short ingest' first")
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
    try:
        media_fp = hashing.fingerprint(media, ws.source_fingerprint(manifest))
    except OSError as exc:
        raise fail(f"cannot read source media {media}: {exc}") from exc
    review_path = ws.dir / REVIEW_NAME
    input_paths = list(paths.values()) + ([review_path] if review_path.is_file() else [])
    inputs = [{"path": ws.relpath(p), "sha256": hashing.sha256_file(p)} for p in input_paths]
    inputs.append({"path": ws.relpath(media), "sha256": media_fp.sha256})
    cfg_hash = hashing.config_hash(used_config(cfg, font_sha))
    outcome: dict = {}

    def action() -> list[str]:
        files = _RunFiles({}, [])
        try:
            doc = _render_all(ws, cfg, fpath, font_sha, media, media_fp.sha256, cfg_hash, paths, review_path,
                              out_dir, runner, force=force, old_outputs=previous_outputs(out_dir, prior),
                              files=files)
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
                force: bool, old_outputs: list[Path], files: _RunFiles) -> dict:
    clips_doc = _read_json(paths[CLIPS_NAME], "selection")
    titles_doc = _read_json(paths[TITLES_NAME], "titling")
    cand_doc = _read_json(paths[CANDIDATES_NAME], "analysis")
    check_inputs(clips_doc, titles_doc, cand_doc)
    try:
        review = review_logic.read_review(review_path, ws.episode_id)
    except review_logic.ReviewError as exc:
        raise RenderError(f"{exc}; fix it or reset the override with 'auto-short title … --reset'") from exc
    resolved, warnings = review_logic.resolve_titles(titles_doc["titles"], review)
    for w in warnings:
        log.warning("%s: WARNING: %s", STAGE, w)

    font = Font(fpath)
    try:
        geo = plan.geometry(cfg)
    except plan.PlanError as exc:
        raise RenderError(str(exc)) from exc
    info = probe_media(media, run)
    if info["video"] is None or info["audio"] is None:
        raise RenderError(f"source media needs a video and an audio stream: {media}")
    src_w, src_h = int(info["video"]["width"]), int(info["video"]["height"])
    fps = plan.output_fps(_rate(info["video"]))

    header_lines = [nfc(x) for x in titles_doc["header"]["lines"]]
    try:
        header = fit_header(font, header_lines, size0=plan.px(cfg.header_font_size), line_spacing=cfg.line_spacing,
                            inner_width=geo.header_w - 2 * cfg.panel_padding_x * plan.WIDTH,
                            panel_height=geo.header_h, padding_y=cfg.panel_padding_y * plan.WIDTH,
                            min_font_scale=cfg.min_font_scale)
    except TextError as exc:
        raise RenderError(str(exc)) from exc
    plans = plan_clips(clips_doc, resolved, cand_doc, font=font, cfg=cfg, geo=geo, src_w=src_w, src_h=src_h)
    base_layout = plan.layout(geo, geo.title_h, src_w, src_h)

    log.info("%s: font %s (%s), fps %s, source %dx%d, dissolve %g s (%d frames)", STAGE, font.family,
             cfg.font_file, plan.fps_text(fps), src_w, src_h, cfg.dissolve, 2 * plan.dissolve_half(cfg.dissolve, fps))
    log.info("%s: layout header %s, video %s crop %s, title %s (max h %d)", STAGE, base_layout.header,
             base_layout.video, base_layout.crop, base_layout.title, geo.title_max_h)
    log.info("%s: header %s (%d px)", STAGE, " / ".join(header.lines), header.font_size)

    previous = {} if force else previous_shorts(out_dir, ws.episode_id)
    shorts_dir = out_dir / SHORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    shorts = []
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
                      "dissolves": None, "title_origin": cp.origin, "render_key": None}
            if cp.title is None:
                record["skip_reason"] = "untitled"
                log.warning("%s: WARNING: clip %s skipped: untitled (no approved title)", STAGE, clip["id"])
                shorts.append(record)
                continue
            fit, lay = cp.title, cp.layout
            dissolves = plan.dissolves(cp.segments, fps, cfg.dissolve)
            key = render_key(cfg_hash=cfg_hash, font_sha=font_sha, source_sha=source_sha, fps=fps,
                             segments=record["segments"], dissolves=dissolves, layout=lay.as_dict(), header=header,
                             title=fit)
            rel = f"{SHORTS_DIR}/{clip['id']}.mp4"
            record.update(status=RENDERED, file=rel, title_display_lines=fit.lines, title_font_size=fit.font_size,
                          layout=lay.as_dict(), dissolves=dissolves, render_key=key)
            shorts.append(record)
            if reusable(previous.get(clip["id"]), key, rel, out_dir):
                record["sha256"] = previous[clip["id"]]["sha256"]
                log.info("%s: clip %s: reuse (render_key unchanged): %s (%s)", STAGE, clip["id"],
                         " / ".join(fit.lines), cp.origin)
                continue
            t_lines = _write_lines(tmp, f"t{clip['id']}_", fit.lines,
                                   baselines(len(fit.lines), font=font, size=fit.font_size, pitch=fit.line_pitch,
                                             panel_height=fit.panel_height))
            script = tmp / f"{clip['id']}.filter"
            script.write_text(plan.filter_graph(segments=cp.segments, fps=fps, lay=lay, font_file=fpath,
                                                header_lines=h_lines, header_size=header.font_size,
                                                title_lines=t_lines, title_size=fit.font_size,
                                                dissolve=cfg.dissolve), encoding="utf-8")
            shorts_dir.mkdir(exist_ok=True)
            part = shorts_dir / f".{clip['id']}.mp4.part"
            files.staged[rel] = part
            cmd = plan.ffmpeg_command(ffmpeg="ffmpeg", source=media, output=part, graph_script=script,
                                      segments=cp.segments, fps=fps, crf=cfg.crf, preset=cfg.preset,
                                      audio_bitrate=cfg.audio_bitrate, threads=cfg.threads)
            t0 = time.monotonic()
            proc = run(cmd)
            if proc.returncode != 0 or not part.is_file():
                raise RenderError(f"clip {clip['id']}: ffmpeg failed: "
                                  f"{_last_line(proc.stderr) or f'exit {proc.returncode}'}")
            verify_output(part, fps, plan.planned_frames(cp.segments, fps), run)
            record["sha256"] = hashing.sha256_file(part)
            log.info("%s: clip %s: %s (%d px, panel %d px, %s), %d segment(s), %d dissolve(s), %.3f s, "
                     "rendered in %.1f s", STAGE, clip["id"], " / ".join(fit.lines), fit.font_size,
                     fit.panel_height, cp.origin, len(cp.segments), sum(1 for d in dissolves if d["frames"]),
                     clip["duration"], time.monotonic() - t0)

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
    keep = {(out_dir / s["file"]).resolve() for s in rendered} | {manifest_path.resolve()}
    removing = [p for p in old_outputs if p.resolve() not in keep]
    validate_render(doc, clips_doc, cand_doc, out_dir, staged=files.staged,
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
    if st["skipped"]:
        log.warning("%s: WARNING: %d clip(s) skipped: %s", STAGE, st["skipped"],
                    ", ".join(f"{s['clip_id']} ({s['skip_reason']})" for s in shorts if s["status"] == SKIPPED))
    if not rendered:
        log.warning("%s: WARNING: no titled clip, no Short rendered", STAGE)
    return doc
