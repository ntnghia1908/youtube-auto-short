"""Enhance state of an episode (CP13.1 E1, E5): ``work/<id>/enhance.json`` + the HD source ``source_hd.mp4``.

Pure file logic (no HTTP, no job runner): the decision after ingest (E1), the ``config_hash`` of the segments (E2),
the validated HD source the render reads (E5, E6) and the khai thị mirror (E1: ``<id>.kt`` shares the video's single
enhance, its ``source_hd.mp4`` is a hard link). Canonical contract: docs/decisions/CP13.1-enhance-worker-contract.md.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from .. import hashing, khaithi
from ..config import Config, EnhanceConfig
from ..hashing import FileFingerprint
from ..render import plan
from ..workspace import Workspace, WorkspaceError, atomic_write_json, validate_episode_id

log = logging.getLogger("auto_short")

ENHANCE_NAME = "enhance.json"
HD_NAME = "source_hd.mp4"
ENHANCED_DIR = "enhanced"
SCHEMA_VERSION = 1
PLAN_VERSION = 1  # bump when the segment format changes (part of the config_hash)
FACE_PLAN_VERSION = 2  # CP13.4: plan version of segments with a face-restoration step (``params.face`` != none)
FACE_NONE = "none"
FACE_GFPGAN = "gfpgan_v1.4"
FACE_MODELS = (FACE_NONE, FACE_GFPGAN)

PENDING, ASSEMBLING, DONE, FAILED = "pending", "assembling", "done", "failed"


class EnhanceError(Exception):
    """A request / state problem; ``status`` is the HTTP status the API answers with."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def now_iso(clock: float | None = None) -> str:
    when = datetime.fromtimestamp(clock, timezone.utc) if clock is not None else datetime.now(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


# --- paths + file ------------------------------------------------------------------------------------------------

def enhance_path(ws_dir: Path) -> Path:
    return Path(ws_dir) / ENHANCE_NAME


def hd_path(ws_dir: Path) -> Path:
    return Path(ws_dir) / HD_NAME


def segments_dir(ws_dir: Path, config_hash: str) -> Path:
    return Path(ws_dir) / ENHANCED_DIR / config_hash


def read(ws_dir: Path) -> dict | None:
    """The enhance.json of a workspace dir, or None (missing / unreadable: the episode simply is not enhanced)."""
    path = enhance_path(ws_dir)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("enhance: cannot read %s: %s", path, exc)
        return None
    return doc if isinstance(doc, dict) and doc.get("schema_version") == SCHEMA_VERSION else None


def write(ws_dir: Path, doc: dict) -> None:
    atomic_write_json(enhance_path(ws_dir), doc)


def new_doc(episode_id: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "wanted": False, "reason": "", "override": False,
            "follows": None, "state": PENDING, "waiting_hd": False, "wanted_at": None, "height": None, "width": None,
            "fps": None, "frames": None, "segment_frames": None, "source_sha256": None, "config_hash": None,
            "params": None, "lease": None, "segments": {}, "profile": None, "error": None,
            "redo": False, "hd_config_hash": None, "source_hd_sha256": None, "source_hd_size": None, "source_hd_mtime_ns": None, "finished_at": None,
            "workers": []}


def params_of(cfg: EnhanceConfig) -> dict:
    """The model parameters the worker gets in the lease. ``face`` = none keeps the original four keys (CP13.4: the
    ``config_hash`` of an episode enhanced before stays valid); another ``face`` adds ``face`` + ``face_weight``."""
    params = {"model": cfg.model, "denoise": cfg.denoise, "pre_height": cfg.pre_height, "out_height": cfg.out_height}
    if cfg.face != FACE_NONE:
        params.update(face=cfg.face, face_weight=cfg.face_weight, face_detect_every=cfg.face_detect_every)
    return params


def has_face(params: dict | None) -> bool:
    """Do these params ask the worker for a face-restoration step (CP13.4)?"""
    return bool(params) and (params.get("face") or FACE_NONE) != FACE_NONE


def segment_frames_of(fps: Fraction, seconds: int) -> int:
    return max(1, round(fps * seconds))


def config_hash_of(params: dict, segment_frames: int, source_sha256: str | None) -> str:
    """E2: hash of everything that decides the segment bytes: model parameters, segment length, the source."""
    plan = FACE_PLAN_VERSION if has_face(params) else PLAN_VERSION
    return hashing.config_hash({"plan": plan, "params": params, "segment_frames": segment_frames,
                                "source_sha256": source_sha256})


def total_segments(doc: dict) -> int:
    frames, seg = int(doc.get("frames") or 0), int(doc.get("segment_frames") or 0)
    return -(-frames // seg) if frames > 0 and seg > 0 else 0


def expected_size(src_w: int, src_h: int, pre_h: int, out_h: int, scale: int = 4) -> tuple[int, int]:
    """Frame size of a segment (same formula as the worker, ``tools/enhance_worker/worker.py`` ``out_size``)."""
    if pre_h > 0 and pre_h != src_h:
        pre_w = int(round(src_w * pre_h / src_h / 2) * 2)
    else:
        pre_w, pre_h = src_w, src_h
    uw, uh = pre_w * scale, pre_h * scale
    if out_h > 0 and uh != out_h:
        return int(round(uw * out_h / uh / 2) * 2), out_h
    return uw, uh


def source_file(ws: Workspace, manifest: dict | None) -> Path | None:
    """The downloaded source video inside the workspace (never a local file outside it), or None."""
    rel = ((manifest or {}).get("source") or {}).get("path")
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        return None
    path = ws.dir / rel
    return path if path.is_file() else None


# --- ffprobe -----------------------------------------------------------------------------------------------------

def probe_video(path: Path, ffprobe: str = "ffprobe", *, count: bool = True) -> dict:
    """``{width, height, fps (Fraction, CP7 rule), frames, duration, codec, pix_fmt, audio_codec}`` of the first video
    stream; ``frames`` = packets (demux only: fast, no decode). Raises :class:`EnhanceError` (400) when unreadable."""
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    if count:
        cmd += ["-count_packets"]
    cmd.append(str(path))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise EnhanceError(f"ffprobe cannot read {path.name}: {exc}", 400) from exc
    if proc.returncode != 0:
        raise EnhanceError(f"ffprobe cannot read {path.name}", 400)
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise EnhanceError(f"{path.name}: no video stream", 400)
    try:
        fps = plan.source_fps(video)
    except ValueError:
        raise EnhanceError(f"{path.name}: cannot determine the frame rate", 400) from None
    frames = video.get("nb_read_packets")
    return {"width": int(video.get("width") or 0), "height": int(video.get("height") or 0), "fps": fps,
            "frames": int(frames) if frames is not None else None,
            "duration": float((data.get("format") or {}).get("duration") or 0), "codec": video.get("codec_name"),
            "pix_fmt": video.get("pix_fmt"), "audio_codec": audio.get("codec_name") if audio else None,
            "streams": len(streams)}


# --- E1: decision ------------------------------------------------------------------------------------------------

def video_parts(config: Config, episode_id: str) -> list[str]:
    """Episodes of the same video that exist: ``<id>`` first, then ``<id>.kt`` (CP8.9)."""
    root = Path(config.workspace.dir)
    base = episode_id[:-len(khaithi.SUFFIX)] if episode_id.endswith(khaithi.SUFFIX) \
        and len(episode_id) > len(khaithi.SUFFIX) else episode_id
    out = []
    for eid in (base, base + khaithi.SUFFIX):
        if (root / eid / "manifest.json").is_file():
            out.append(eid)
    return out


def base_of(config: Config, episode_id: str) -> str | None:
    """The base Short episode a khai thị episode follows (its enhance.json exists), else None."""
    if not episode_id.endswith(khaithi.SUFFIX) or len(episode_id) <= len(khaithi.SUFFIX):
        return None
    base = episode_id[:-len(khaithi.SUFFIX)]
    return base if read(Path(config.workspace.dir) / base) is not None else None


def decide(config: Config, episode_id: str, *, force: bool | None = None, ffprobe: str = "ffprobe",
           clock: float | None = None) -> dict | None:
    """E1 after ingest: write / refresh ``enhance.json``. ``force`` (the per-episode button): True = wanted
    (``override``), False = not wanted (``override``), None = decide by resolution (an ``override`` is kept).
    Returns the document, or None when nothing is written: feature off, not a YouTube source, no source file."""
    enh = config.enhance
    if not enh.enabled and force is None:
        return None
    try:
        ws = Workspace(Path(config.workspace.dir), validate_episode_id(episode_id))
        manifest = ws.load_manifest()
    except WorkspaceError:
        return None
    if manifest is None or (manifest.get("source") or {}).get("kind") != "youtube":
        return None
    base_id = base_of(config, episode_id)
    if base_id is not None:  # a khai thị episode shares the enhance of its Short episode (E1)
        return mirror(config, base_id, only=episode_id)
    doc = read(ws.dir) or new_doc(ws.episode_id)
    source_sha = (manifest.get("source") or {}).get("sha256")
    changed_source = doc.get("source_sha256") not in (None, source_sha)
    if changed_source:  # another download: nothing of the old enhance applies
        shutil.rmtree(ws.dir / ENHANCED_DIR, ignore_errors=True)
        hd_path(ws.dir).unlink(missing_ok=True)
        keep = {k: doc[k] for k in ("override", "wanted", "wanted_at")}
        doc = {**new_doc(ws.episode_id), **keep}
    meta = _read_json(ws.dir / "metadata.json") or {}
    height = meta.get("height") if isinstance(meta.get("height"), int) else None
    src = source_file(ws, manifest)
    if force is True or (force is None and doc["override"] and doc["wanted"]):
        wanted, reason, override = True, "override", True
    elif force is False or (force is None and doc["override"] and not doc["wanted"]):
        wanted, reason, override = False, "override", True
    elif height is None:
        wanted, reason, override = False, "height unknown", False
    elif height >= enh.min_height:
        wanted, reason, override = False, f"height {height} >= {enh.min_height}", False
    else:
        wanted, reason, override = True, f"height {height} < {enh.min_height}", False
    if wanted and src is None:
        if force is True:
            raise EnhanceError("không còn video nguồn trong workspace để enhance (đã dọn?)", 409)
        wanted, reason = False, "no source file"
    facts: dict = {}
    if wanted and not (doc["fps"] and doc["frames"] and doc["source_sha256"] == source_sha):
        try:
            facts = _source_facts(src, meta, ffprobe)
        except EnhanceError as exc:
            if force is True:
                raise
            wanted, reason = False, str(exc)
    doc.update(wanted=wanted, reason=reason, override=override, source_sha256=source_sha, height=height,
               follows=None)
    if wanted:
        doc.update(facts)
        if doc["wanted_at"] is None:
            doc["wanted_at"] = now_iso(clock)
        params = params_of(enh)
        seg = segment_frames_of(Fraction(doc["fps"]), enh.segment_seconds)
        new_hash = config_hash_of(params, seg, source_sha)
        if doc["config_hash"] not in (None, new_hash):  # [enhance] parameters changed: segments of the old hash are useless
            if doc["state"] == DONE and not doc.get("hd_config_hash"):
                doc["hd_config_hash"] = doc["config_hash"]  # CP13.4 G3: the HD source keeps the config it was made with
            shutil.rmtree(segments_dir(ws.dir, doc["config_hash"]), ignore_errors=True)
            doc.update(segments={}, profile=None, lease=None)
            if doc["state"] != DONE:
                doc["state"] = PENDING
        doc.update(params=params, segment_frames=seg, config_hash=new_hash)
        if doc["state"] == FAILED and force is True:
            doc.update(state=PENDING, error=None)
    else:
        doc.update(lease=None, redo=False)  # the workers lose the video: their next call answers 409
    write(ws.dir, doc)
    log.info("enhance: %s wanted=%s (%s)", ws.episode_id, wanted, reason)
    mirror(config, ws.episode_id)
    return doc


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _source_facts(src: Path, meta: dict, ffprobe: str) -> dict:
    info = probe_video(src, ffprobe)
    if info["frames"] is None or info["frames"] <= 0:
        raise EnhanceError("cannot count the source frames")
    dur = info["duration"] or float(meta.get("duration") or 0)
    # the worker numbers frames at the nominal rate: a variable frame rate would drift against the audio
    if dur > 0 and abs(info["frames"] / float(info["fps"]) - dur) > max(2.0, 0.005 * dur):
        raise EnhanceError(f"frame count does not match the duration ({info['frames']} frames at "
                           f"{float(info['fps']):.3f} fps vs {dur:.1f} s: variable frame rate?)")
    return {"width": info["width"], "height": info["height"], "fps": plan.fps_text(info["fps"]),
            "frames": info["frames"], "audio_codec": info["audio_codec"]}


def mirror(config: Config, base_id: str, *, only: str | None = None) -> dict | None:
    """Write the enhance.json of the khai thị episode ``<base_id>.kt`` (when its workspace exists) as a copy of the
    video's; a finished HD source is hard-linked into it (copy on failure). Returns the khai thị document."""
    kid = base_id + khaithi.SUFFIX
    if only is not None and only != kid:
        return None
    root = Path(config.workspace.dir)
    base = read(root / base_id)
    if base is None or not (root / kid / "manifest.json").is_file():
        return None
    old = read(root / kid)
    doc = {**new_doc(kid), **(old or {})}
    for key in ("wanted", "reason", "override", "state", "wanted_at", "height", "width", "fps", "frames",
                "segment_frames", "source_sha256", "config_hash", "params", "error", "source_hd_sha256",
                "source_hd_size", "source_hd_mtime_ns", "finished_at", "redo", "hd_config_hash"):
        doc[key] = base.get(key)
    doc.update(follows=base_id, lease=None, segments={}, profile=None, workers=[])
    if _hd_usable(base) and hd_path(root / base_id).is_file():
        link_hd(root / base_id, root / kid, doc)
    elif not _hd_usable(base):
        hd_path(root / kid).unlink(missing_ok=True)
    write(root / kid, doc)
    return doc


def _hd_usable(doc: dict | None) -> bool:
    """Is the HD source of the document one the render may read? Done, or a "Enhance lại" (CP13.4 G3: ``redo``) keeps the
    previous HD source in use until the new one is assembled."""
    return bool(doc) and (doc.get("state") == DONE or (doc.get("state") == PENDING and bool(doc.get("redo"))))


def hd_is_old_config(config: Config, doc: dict | None, ws_dir: Path | None = None) -> bool:
    """CP13.4 G3: is the HD source made with another ``[enhance]`` configuration than the current one ("HD cấu hình cũ")?
    False when there is no usable HD source or the video does not want enhance."""
    if not doc or not doc.get("wanted") or not _hd_usable(doc) or not (doc.get("fps") and doc.get("source_sha256")):
        return False
    try:
        cur = config_hash_of(params_of(config.enhance),
                             segment_frames_of(Fraction(doc["fps"]), config.enhance.segment_seconds),
                             doc.get("source_sha256"))
    except (ValueError, ZeroDivisionError):
        return False
    made = doc.get("hd_config_hash") or doc.get("config_hash")
    return bool(made) and made != cur


def link_hd(src_dir: Path, dst_dir: Path, doc: dict) -> None:
    """Hard link ``source_hd.mp4`` into another workspace (copy when the filesystem refuses); fills the size / mtime
    fields of ``doc`` for the link."""
    src, dst = hd_path(src_dir), hd_path(dst_dir)
    try:
        if dst.exists() and os.path.samefile(src, dst):
            pass
        else:
            dst.unlink(missing_ok=True)
            os.link(src, dst)
    except OSError as exc:
        log.info("enhance: hard link failed (%s); copying the HD source", exc)
        tmp = dst.with_name(f".{HD_NAME}.part")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    st = dst.stat()
    doc.update(source_hd_size=st.st_size, source_hd_mtime_ns=st.st_mtime_ns)


# --- E6: the HD source the render reads --------------------------------------------------------------------------

def hd_fingerprint(ws_dir: Path) -> FileFingerprint | None:
    """The finished HD source of the workspace as a fingerprint (sha256 recorded in enhance.json), or None when there
    is none or the file does not match the record (then the render uses the original source)."""
    doc = read(ws_dir)
    path = hd_path(ws_dir)
    if not doc or not _hd_usable(doc) or not doc.get("source_hd_sha256") or not path.is_file():
        return None
    try:
        st = path.stat()
        if st.st_size == doc.get("source_hd_size") and st.st_mtime_ns == doc.get("source_hd_mtime_ns"):
            return FileFingerprint(path.resolve(), st.st_size, st.st_mtime_ns, doc["source_hd_sha256"])
        fp = hashing.fingerprint(path)
    except OSError:
        return None
    if fp.sha256 != doc["source_hd_sha256"]:
        log.warning("enhance: %s does not match enhance.json (sha256); the render uses the original source", path)
        return None
    return fp


def has_hd(ws_dir: Path) -> bool:
    return hd_path(ws_dir).is_file()


def is_pending(doc: dict | None) -> bool:
    """The video wants an HD source that is not there yet (the pipeline parks before render, auto clean-up waits)."""
    return bool(doc and doc.get("wanted") and doc.get("state") in (PENDING, ASSEMBLING))


def stored_segments(ws_dir: Path, doc: dict) -> dict[int, dict]:
    """Segments recorded in ``doc`` whose file exists in the segment dir of the current ``config_hash``."""
    seg_dir = segments_dir(ws_dir, doc["config_hash"]) if doc.get("config_hash") else None
    out = {}
    for key, rec in (doc.get("segments") or {}).items():
        try:
            n = int(key)
        except ValueError:
            continue
        if seg_dir is not None and (seg_dir / f"seg_{n:05d}.mp4").is_file():
            out[n] = rec
    return out


def sha256_file(path: Path) -> str:
    return hashing.sha256_file(path)
