"""Enhance service (CP13.1 E2, E3, E5, E7): leases, received segments, assembly, worker registry, global pause.

Everything that touches ``enhance.json`` runs under one lock; the HTTP layer (``web/app.py``) only authenticates,
streams request bodies to temp files and calls these methods. Workers never run inside the web process: they pull
work through the API (E3). Canonical contract: docs/decisions/CP13.1-enhance-worker-contract.md.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from ..config import Config
from ..hashing import sha256_file
from ..review.archive import is_archived
from ..titling.logic import match_title
from ..workspace import Workspace, WorkspaceError, atomic_write_json, validate_episode_id
from . import state as st
from .state import EnhanceError

log = logging.getLogger("auto_short")

STATE_FILE = ".enhance_state.json"  # global "Tạm dừng enhance" (workspace root, next to ``.web_queue.json``)
MAX_PROGRESS_KEYS = ("segments_uploaded", "segments_encoded", "segments_total")


GPU_STATS_KEYS = ("util_pct", "mem_used_mb", "mem_total_mb", "temp_c", "power_w")


def clean_gpu_stats(obj: object) -> dict | None:
    """CP8.28 M4: the optional ``gpu_stats`` a worker sends (``nvidia-smi`` numbers). Anything unusable -> None (the worker
    entry then keeps its previous numbers); only the known keys are kept, numbers as floats, ``name`` as short text."""
    if not isinstance(obj, dict):
        return None
    out: dict = {"name": obj["name"][:80] if isinstance(obj.get("name"), str) else None}
    for key in GPU_STATS_KEYS:
        v = obj.get(key)
        out[key] = round(float(v), 1) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v \
            and abs(v) < 1e9 else None
    return out if any(v is not None for v in out.values()) else None


@dataclass
class PutContext:
    """A validated ``PUT seg``: where the body goes (a temp file inside the segment dir of the lease's episode)."""

    episode_id: str
    lease_id: str
    n: int
    tmp: Path
    token: str

    def cleanup(self) -> None:
        self.tmp.unlink(missing_ok=True)


class EnhanceService:
    def __init__(self, config: Config, *, ai_busy: Callable[[], bool] | None = None,
                 on_complete: Callable[[str], None] | None = None, clock: Callable[[], float] = time.time,
                 ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        self.config = config
        self.root = Path(config.workspace.dir)
        self.ai_busy = ai_busy or (lambda: False)
        # CP8.26 P3: ``episode_id -> mark order`` (None = not marked), set by the web app
        self.priority_rank: Callable[[str], int | None] = lambda _eid: None
        self.on_complete = on_complete  # called (after the lock is released) when the last segment arrived
        self.clock = clock
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self.lock = threading.RLock()
        self._workers: dict[str, dict] = {}
        self._warned_caps: set[tuple[str, str]] = set()  # (worker, video) pairs already logged "cần cập nhật worker"
        self._paused = self._load_paused()

    # --- global switches ---------------------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self.config.enhance.enabled

    @property
    def paused(self) -> bool:
        return self._paused

    def _load_paused(self) -> bool:
        try:
            return bool(json.loads((self.root / STATE_FILE).read_text(encoding="utf-8")).get("paused"))
        except (OSError, ValueError, AttributeError):
            return False

    def set_paused(self, paused: bool) -> None:
        with self.lock:
            self._paused = bool(paused)
            try:
                atomic_write_json(self.root / STATE_FILE, {"paused": self._paused})
            except OSError as exc:
                log.warning("enhance: cannot save %s: %s", STATE_FILE, exc)
        log.info("enhance: %s", "paused by HUMAN LEAD" if paused else "resumed")

    def ping(self, name: str, label: str | None = None, gpu_stats: object = None) -> None:
        """A worker called an API route: record the contact (worker panel) and its optional GPU numbers (CP8.28)."""
        with self.lock:
            self._touch(name, label, gpu_stats=gpu_stats)

    def may_run_info(self, name: str) -> tuple[bool, str, bool]:
        """E7 + FIX-enhance-yield: ``(run, reason, preempt)``. ``preempt`` is true only when ``run`` is false because
        Ollama is busy and ``name`` is a yield worker: the worker must then stop mid-segment and free its VRAM.
        Pause / ``enabled = false`` give ``preempt = False`` (the worker finishes the current segment)."""
        if not self.enabled:
            return False, "enhance is off ([enhance] enabled = false)", False
        if self._paused:
            return False, "enhance paused", False
        if name in self.config.enhance.yield_workers and self.ai_busy():
            return False, "Ollama busy (ai lane)", True
        return True, "", False

    def may_run(self, name: str) -> tuple[bool, str]:
        """E7: may the worker ``name`` (token name) enhance now?"""
        run, reason, _preempt = self.may_run_info(name)
        return run, reason

    # --- documents ---------------------------------------------------------------------------------------------

    def _dir(self, episode_id: str) -> Path:
        return self.root / validate_episode_id(episode_id)

    def _docs(self) -> Iterator[tuple[str, Path, dict]]:
        try:
            names = sorted(p.name for p in self.root.iterdir() if p.is_dir())
        except OSError:
            return
        for eid in names:
            doc = st.read(self.root / eid)
            if doc is not None and doc.get("episode_id") == eid:
                yield eid, self.root / eid, doc

    def _now_iso(self) -> str:
        return st.now_iso(self.clock())

    def _lease_valid(self, lease: dict | None) -> bool:
        if not lease:
            return False
        exp = st.parse_iso(lease.get("expires_at"))
        return exp is not None and exp > self.clock()

    def _expires(self) -> str:
        return st.now_iso(self.clock() + self.config.enhance.lease_hours * 3600)

    def _touch(self, name: str, label: str | None = None, gpu: str | None = None, gpu_stats: object = None,
               **extra) -> dict:
        w = self._workers.setdefault(name, {"name": name, "label": name, "gpu": None, "last_seen": None,
                                            "episode_id": None, "lease_id": None, "progress": None,
                                            "gpu_stats": None, "gpu_stats_at": None, "capabilities": []})
        stats = clean_gpu_stats(gpu_stats)  # CP8.28: optional; an old worker never sends it
        if stats is not None:
            w["gpu_stats"], w["gpu_stats_at"] = stats, self._now_iso()
        if label:
            w["label"] = label[:80]
        if gpu:
            w["gpu"] = gpu[:80]
        w["last_seen"] = self._now_iso()
        w.update(extra)
        return w

    # --- eligibility + lease (E2) -------------------------------------------------------------------------------

    def _eligible(self, eid: str, d: Path, doc: dict) -> dict | None:
        """The (possibly refreshed) document when the video can be given to a worker now, else None."""
        if not doc.get("wanted") or doc.get("follows") or doc.get("state") != st.PENDING:
            return None
        if is_archived(d) or self._lease_valid(doc.get("lease")):
            return None
        cfg = self.config.enhance
        if doc.get("params") != st.params_of(cfg) or doc.get("segment_frames") is None \
                or doc.get("config_hash") != st.config_hash_of(
                    st.params_of(cfg), st.segment_frames_of(Fraction(doc["fps"]), cfg.segment_seconds),
                    doc.get("source_sha256")):
            try:  # [enhance] parameters changed since the decision: refresh (drops the segments of the old hash)
                doc = st.decide(self.config, eid, ffprobe=self.ffprobe, clock=self.clock())
            except EnhanceError:
                return None
            if doc is None or not doc.get("wanted") or doc.get("state") != st.PENDING:
                return None
        try:
            ws = Workspace(self.root, eid)
            manifest = ws.load_manifest()
        except WorkspaceError:
            return None
        src = st.source_file(ws, manifest)
        if src is None:
            return None
        want = ((manifest or {}).get("source") or {}).get("size")
        if isinstance(want, int) and src.stat().st_size != want:
            return None
        return doc

    def _lease_info(self, eid: str, d: Path, doc: dict) -> dict:
        ws = Workspace(self.root, eid)
        src = st.source_file(ws, ws.load_manifest())
        lease = doc["lease"]
        return {"episode_id": eid, "lease_id": lease["lease_id"], "expires_at": lease["expires_at"],
                "source_url": f"/api/enhance/{lease['lease_id']}/source", "source_sha256": doc["source_sha256"],
                "source_size": src.stat().st_size if src else 0, "fps": doc["fps"], "frames": doc["frames"],
                "segment_frames": doc["segment_frames"], "params": doc["params"], "config_hash": doc["config_hash"],
                "done_segments": sorted(st.stored_segments(d, doc))}

    def _series_episode(self, d: Path) -> tuple[str | None, int | None]:
        """(series, episode number) of a video from the title in its ``metadata.json`` (the CP6 ``title_patterns``);
        (None, None) when no pattern recognizes it."""
        meta = st._read_json(d / "metadata.json") or {}
        m = match_title(self.config.titling.header.title_patterns, meta.get("title"))
        if m is None:
            return None, None
        groups = m.re.groupindex
        series = " ".join(m.group("series").split()) if "series" in groups and m.group("series") else None
        ep = m.group("episode") if "episode" in groups else None
        return series, int(ep) if ep is not None and ep.isdigit() else None

    def _lease_order(self, cands: list[tuple[str, Path, dict]]) -> list[tuple[str, Path, dict]]:
        """CP13.2 H3: videos waiting for HD first (as in CP13.1b), then (CP8.26 P3) the videos marked "ưu tiên" in mark
        order, then the others grouped by series (the series whose
        first video asked for HD earliest first) and, inside a series, by episode number; videos whose episode number
        is unknown follow the numbered ones of their series by ``wanted_at``; a video of no known series is its own
        group (plain ``wanted_at`` order)."""
        info = {eid: self._series_episode(d) for eid, d, _doc in cands}
        first: dict[str, str] = {}
        for eid, _d, doc in cands:
            key = info[eid][0] or eid
            at = doc.get("wanted_at") or ""
            if key not in first or at < first[key]:
                first[key] = at

        def sort_key(c):
            eid, _d, doc = c
            series, num = info[eid]
            rank = self.priority_rank(eid)
            return (not doc.get("waiting_hd"), rank is None, rank or 0, first[series or eid], series or eid, num is None, num or 0,
                    doc.get("wanted_at") or "", eid)

        return sorted(cands, key=sort_key)

    @staticmethod
    def clean_capabilities(obj: object) -> list[str]:
        """CP13.4: the optional ``capabilities`` a worker sends with ``POST lease`` (``["face:gfpgan_v1.4"]``); anything
        unusable -> []. An old worker (v2) sends none: it can only do the plain model."""
        if not isinstance(obj, list):
            return []
        return sorted({x[:40] for x in obj[:20] if isinstance(x, str) and x})

    def _can_take(self, name: str, params: dict | None, caps: list[str], eid: str) -> bool:
        """CP13.4 G2: may the worker (with ``caps``) take a video enhanced with ``params``? A face step needs the matching
        capability; an old worker is never given one (it would silently skip the step)."""
        if not st.has_face(params):
            return True
        if f"face:{params.get('face')}" in caps:
            return True
        key = (name, eid)
        if key not in self._warned_caps:
            self._warned_caps.add(key)
            log.warning("enhance: worker %s không hỗ trợ face=%s của %s - cần cập nhật worker (setup-enhance-worker.ps1); "
                        "video này chỉ giao cho worker hỗ trợ", name, params.get("face"), eid)
        return False

    def lease(self, name: str, label: str | None = None, gpu: str | None = None,
              gpu_stats: object = None, capabilities: object = None) -> dict | None:
        """E3 ``POST lease``: the worker's own valid lease, else the next video (waiting for HD first, then by
        ``wanted_at``); None = 204 (nothing to do, or the worker may not run now). ``capabilities`` (CP13.4): what the
        worker can do beyond the plain model; a video with a face step goes only to a worker that can."""
        completed: list[str] = []
        caps = self.clean_capabilities(capabilities)
        with self.lock:
            self._touch(name, label, gpu, gpu_stats=gpu_stats, capabilities=caps)
            ok, _reason = self.may_run(name)
            if not ok:
                return None
            ours = None
            cands: list[tuple[tuple, str, Path, dict]] = []
            for eid, d, doc in self._docs():
                lease = doc.get("lease")
                if lease and lease.get("token") == name and self._lease_valid(lease) and doc.get("wanted") \
                        and doc.get("state") == st.PENDING:
                    if self._can_take(name, doc.get("params"), caps, eid):
                        ours = (eid, d, doc)
                        break
                    doc["lease"] = None  # the worker lost a capability (downgraded): the video goes to another one
                    st.write(d, doc)
                    continue
                if not doc.get("wanted") or doc.get("follows") or doc.get("state") != st.PENDING:
                    continue
                cands.append((eid, d, doc))
            if ours is None:
                for eid, d, doc in self._lease_order(cands):
                    doc = self._eligible(eid, d, doc)
                    if doc is None or not self._can_take(name, doc.get("params"), caps, eid):
                        continue
                    if len(st.stored_segments(d, doc)) >= st.total_segments(doc):  # complete but never assembled
                        doc.update(state=st.ASSEMBLING, lease=None)
                        st.write(d, doc)
                        completed.append(eid)
                        continue
                    doc["lease"] = {"lease_id": secrets.token_hex(16), "worker": (label or name)[:80], "token": name,
                                    "gpu": (gpu or "")[:80], "started_at": self._now_iso(),
                                    "expires_at": self._expires(), "last_seen": self._now_iso(), "progress": None}
                    st.write(d, doc)
                    ours = (eid, d, doc)
                    log.info("enhance: lease %s of %s to %s (%s), %d / %d segments already there",
                             doc["lease"]["lease_id"], eid, name, gpu or "?", len(st.stored_segments(d, doc)),
                             st.total_segments(doc))
                    break
            result = None
            if ours is not None:
                eid, d, doc = ours
                result = self._lease_info(eid, d, doc)
                self._touch(name, episode_id=eid, lease_id=doc["lease"]["lease_id"],
                            progress=doc["lease"].get("progress"))
            else:
                self._touch(name, episode_id=None, lease_id=None, progress=None)
        for eid in completed:
            self._complete(eid)
        return result

    def _find(self, lease_id: str, name: str | None = None) -> tuple[str, Path, dict]:
        """The episode holding a *valid* lease ``lease_id`` (409 otherwise). Caller holds the lock."""
        for eid, d, doc in self._docs():
            lease = doc.get("lease")
            if lease and lease.get("lease_id") == lease_id:
                if not self._lease_valid(lease) or not doc.get("wanted") or doc.get("state") != st.PENDING \
                        or not self.enabled:
                    break
                if name is not None and lease.get("token") != name:
                    break
                return eid, d, doc
        raise EnhanceError("lease không hợp lệ hoặc đã hết hạn", 409)

    def _renew(self, d: Path, doc: dict, **extra) -> str:
        doc["lease"]["expires_at"] = self._expires()
        doc["lease"]["last_seen"] = self._now_iso()
        doc["lease"].update(extra)
        st.write(d, doc)
        return doc["lease"]["expires_at"]

    def heartbeat(self, name: str, lease_id: str, progress: object, gpu_stats: object = None) -> dict:
        with self.lock:
            eid, d, doc = self._find(lease_id, name)
            prog = {k: progress[k] for k in MAX_PROGRESS_KEYS
                    if isinstance(progress, dict) and isinstance(progress.get(k), int)
                    and not isinstance(progress.get(k), bool)} if isinstance(progress, dict) else None
            expires = self._renew(d, doc, progress=prog)
            self._touch(name, episode_id=eid, lease_id=lease_id, progress=prog, gpu_stats=gpu_stats)
            return {"ok": True, "expires_at": expires}

    def release(self, name: str, lease_id: str, reason: object) -> dict:
        with self.lock:
            eid, d, doc = self._find(lease_id, name)
            doc["lease"] = None
            st.write(d, doc)
            self._touch(name, episode_id=None, lease_id=None, progress=None)
        log.info("enhance: %s released lease %s of %s: %s", name, lease_id, eid, str(reason)[:200] or "-")
        return {"ok": True}

    def source_path(self, name: str, lease_id: str) -> Path:
        with self.lock:
            eid, _d, _doc = self._find(lease_id, name)
            self._touch(name, episode_id=eid, lease_id=lease_id)
            ws = Workspace(self.root, eid)
            src = st.source_file(ws, ws.load_manifest())
        if src is None:
            raise EnhanceError("video nguồn không còn", 404)
        return src

    # --- segments (E3 PUT) --------------------------------------------------------------------------------------

    def check_put(self, name: str, lease_id: str, n: int) -> PutContext:
        with self.lock:
            eid, d, doc = self._find(lease_id, name)
            total = st.total_segments(doc)
            if not 0 <= n < total:
                raise EnhanceError(f"đoạn {n} ngoài khoảng 0..{total - 1}", 400)
            seg_dir = st.segments_dir(d, doc["config_hash"])
            seg_dir.mkdir(parents=True, exist_ok=True)
            tmp = seg_dir / f".put-{n:05d}-{secrets.token_hex(4)}.part"
        return PutContext(eid, lease_id, n, tmp, name)

    def accept(self, ctx: PutContext, claimed_sha: str | None, got_sha: str) -> dict:
        """Check the body already written to ``ctx.tmp`` (sha256 header, readable H.264, frame count, size, same
        profile as the segments before) and store it. Idempotent for the same sha256. Raises :class:`EnhanceError`."""
        if (claimed_sha or "").strip().lower() != got_sha:
            raise EnhanceError("sha256 không khớp (X-Sha256)", 400)
        with self.lock:
            eid, d, doc = self._find(ctx.lease_id, ctx.token)
            rec = (doc.get("segments") or {}).get(str(ctx.n))
            seg_file = st.segments_dir(d, doc["config_hash"]) / f"seg_{ctx.n:05d}.mp4"
            if rec and rec.get("sha256") == got_sha and seg_file.is_file():
                expires = self._renew(d, doc)
                self._touch(ctx.token, episode_id=eid, lease_id=ctx.lease_id)
                ctx.cleanup()
                return {"ok": True, "idempotent": True, "expires_at": expires}
            frames, seg, params = doc["frames"], doc["segment_frames"], doc["params"]
            src_w, src_h = doc["width"], doc["height"]
            fps = Fraction(doc["fps"])
            known = doc.get("profile")
        info = st.probe_video(ctx.tmp, self.ffprobe)  # slow part: outside the lock
        start = ctx.n * seg
        want = min(seg, frames - start)
        w, h = st.expected_size(src_w, src_h, params["pre_height"], params["out_height"])
        problems = []
        if info["codec"] != "h264":
            problems.append(f"codec {info['codec']} (cần h264)")
        if info["streams"] != 1:
            problems.append("đoạn chỉ được có luồng video")
        if info["frames"] != want:
            problems.append(f"{info['frames']} khung (cần {want})")
        if (info["width"], info["height"]) != (w, h):
            problems.append(f"kích thước {info['width']}x{info['height']} (cần {w}x{h})")
        if info["fps"] != fps:
            problems.append(f"fps {info['fps']} (cần {fps})")
        profile = {"codec": info["codec"], "width": info["width"], "height": info["height"],
                   "pix_fmt": info["pix_fmt"], "fps": st.plan.fps_text(info["fps"])}
        if known and known != profile:
            problems.append(f"khác các đoạn đã nhận ({profile} so với {known})")
        if problems:
            raise EnhanceError("; ".join(problems), 400)
        size = ctx.tmp.stat().st_size
        with self.lock:
            eid, d, doc = self._find(ctx.lease_id, ctx.token)  # the lease may have gone while ffprobe ran
            seg_file = st.segments_dir(d, doc["config_hash"]) / f"seg_{ctx.n:05d}.mp4"
            os.replace(ctx.tmp, seg_file)
            doc.setdefault("segments", {})[str(ctx.n)] = {
                "sha256": got_sha, "size": size, "worker": doc["lease"].get("worker"),
                "gpu": doc["lease"].get("gpu"), "at": self._now_iso()}
            doc["profile"] = doc.get("profile") or profile
            have = len(st.stored_segments(d, doc))
            complete = have >= st.total_segments(doc)
            if complete:
                doc.update(state=st.ASSEMBLING)
                expires = doc["lease"]["expires_at"]
                doc["lease"] = None  # the VM ends the lease itself when the segments are all there (E3)
                st.write(d, doc)
            else:
                expires = self._renew(d, doc, progress=doc["lease"].get("progress"))
            self._touch(ctx.token, episode_id=None if complete else eid, lease_id=None if complete else ctx.lease_id)
        log.info("enhance: %s segment %d/%d (%d bytes) from %s%s", eid, have, st.total_segments(doc), size,
                 ctx.token, " - complete" if complete else "")
        if complete:
            self._complete(eid)
        return {"ok": True, "expires_at": expires}

    def _complete(self, eid: str) -> None:
        if self.on_complete is not None:
            try:
                self.on_complete(eid)
            except Exception:
                log.exception("enhance: on_complete hook failed for %s", eid)

    # --- assembly (E3) ------------------------------------------------------------------------------------------

    def assemble(self, eid: str) -> dict:
        """Concat the segments (stream copy) + the original audio into ``source_hd.mp4`` (temp file + rename), verify the
        frame count / size / fps, record the sha256 and delete the segment dir. Blocking (runs in the render lane).
        Raises :class:`EnhanceError` and records ``state: failed`` when it cannot (segments are kept: the button
        "Bật enhance" tries again)."""
        d = self._dir(eid)
        with self.lock:
            doc = st.read(d)
            if doc is None or doc.get("follows"):
                raise EnhanceError("không có enhance.json để ghép", 409)
            if doc.get("state") == st.DONE and st.hd_fingerprint(d) is not None:
                return doc
            segs = st.stored_segments(d, doc)
            total = st.total_segments(doc)
            if len(segs) < total:
                raise EnhanceError(f"mới có {len(segs)}/{total} đoạn", 409)
            ws = Workspace(self.root, eid)
            src = st.source_file(ws, ws.load_manifest())
            seg_dir = st.segments_dir(d, doc["config_hash"])
            frames, fps = doc["frames"], Fraction(doc["fps"])
            w, h = st.expected_size(doc["width"], doc["height"], doc["params"]["pre_height"],
                                    doc["params"]["out_height"])
        try:
            if src is None:
                raise EnhanceError("video nguồn không còn (cần cho âm thanh)", 409)
            tmp = d / f".{st.HD_NAME}.part"
            listing = seg_dir / "concat.txt"
            listing.write_text("".join(f"file 'seg_{n:05d}.mp4'\n" for n in range(total)), encoding="utf-8")
            cmd = [self.ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(src),
                   "-map", "0:v:0", "-map", "1:a:0?", "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(tmp)]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0 or not tmp.is_file():
                raise EnhanceError(f"ffmpeg ghép lỗi: {(proc.stderr or '').strip().splitlines()[-1:] or proc.returncode}")
            info = st.probe_video(tmp, self.ffprobe)
            problems = []
            if info["frames"] != frames:
                problems.append(f"{info['frames']} khung (cần {frames})")
            if (info["width"], info["height"]) != (w, h):
                problems.append(f"kích thước {info['width']}x{info['height']} (cần {w}x{h})")
            if info["fps"] != fps:
                problems.append(f"fps {info['fps']} (cần {fps})")
            if doc.get("audio_codec") and info["audio_codec"] is None:
                problems.append("mất âm thanh")
            if problems:
                raise EnhanceError("bản ghép sai: " + "; ".join(problems))
            sha = sha256_file(tmp)
            os.replace(tmp, st.hd_path(d))
        except EnhanceError as exc:
            (d / f".{st.HD_NAME}.part").unlink(missing_ok=True)
            with self.lock:
                cur = st.read(d) or doc
                cur.update(state=st.FAILED, error=str(exc))
                st.write(d, cur)
            log.error("enhance: assembling %s failed: %s", eid, exc)
            raise
        with self.lock:
            cur = st.read(d) or doc
            stat = st.hd_path(d).stat()
            workers = sorted({f"{r.get('worker')} ({r.get('gpu')})" for r in (cur.get("segments") or {}).values()
                              if r.get("worker")})
            cur.update(state=st.DONE, error=None, lease=None, source_hd_sha256=sha, source_hd_size=stat.st_size,
                       source_hd_mtime_ns=stat.st_mtime_ns, finished_at=self._now_iso(), workers=workers,
                       waiting_hd=cur.get("waiting_hd", False), redo=False, hd_config_hash=cur.get("config_hash"))
            st.write(d, cur)
            shutil.rmtree(d / st.ENHANCED_DIR, ignore_errors=True)
            st.mirror(self.config, eid)
        log.info("enhance: %s HD source ready (%d frames, %d bytes, %s)", eid, frames, stat.st_size,
                 ", ".join(workers) or "?")
        return cur

    def resume_assembly(self) -> list[str]:
        """Start-up: videos whose segments are all there but never assembled (a restart cut the job)."""
        out = []
        with self.lock:
            for eid, d, doc in self._docs():
                if doc.get("follows") or not doc.get("wanted") or doc.get("state") == st.DONE:
                    continue
                if doc.get("state") == st.ASSEMBLING:
                    out.append(eid)
                elif doc.get("state") == st.PENDING and doc.get("config_hash") \
                        and len(st.stored_segments(d, doc)) >= st.total_segments(doc) > 0:
                    doc.update(state=st.ASSEMBLING, lease=None)
                    st.write(d, doc)
                    out.append(eid)
        return out

    # --- pipeline hooks + UI toggles ----------------------------------------------------------------------------

    def decide(self, eid: str) -> dict | None:
        """E1 after ingest (a decision problem never fails the job)."""
        try:
            with self.lock:
                return st.decide(self.config, eid, ffprobe=self.ffprobe, clock=self.clock())
        except EnhanceError as exc:
            log.warning("enhance: %s: %s", eid, exc)
        except Exception:
            log.exception("enhance: decision of %s failed", eid)
        return None

    def hold(self, eid: str) -> bool:
        """E6: should the pipeline of ``eid`` wait for its HD source instead of rendering? Marks ``waiting_hd``."""
        with self.lock:
            d = self._dir(eid)
            doc = st.read(d)
            if doc is None:
                return False
            hold = self.enabled and st.is_pending(doc) and not doc.get("redo")  # redo: the previous HD source is in use
            if bool(doc.get("waiting_hd")) != hold:
                doc["waiting_hd"] = hold
                st.write(d, doc)
            return hold

    def clear_waiting(self, eid: str) -> None:
        with self.lock:
            d = self._dir(eid)
            doc = st.read(d)
            if doc is not None and doc.get("waiting_hd"):
                doc["waiting_hd"] = False
                st.write(d, doc)

    def set_wanted(self, eid: str, wanted: bool) -> dict:
        """The per-episode button: ``wanted`` True = "Bật enhance", False = "Tắt enhance" (applies to the whole video;
        ``override``). Raises :class:`EnhanceError` (409) when it cannot be done."""
        with self.lock:
            base = st.base_of(self.config, eid)
            owner = base or eid
            if wanted and not self.enabled:
                raise EnhanceError("enhance đang tắt ([enhance] enabled = false)", 409)
            if wanted and is_archived(self._dir(owner)):
                raise EnhanceError("đã dọn video nguồn: không còn gì để enhance", 409)
            doc = st.decide(self.config, owner, force=wanted, ffprobe=self.ffprobe, clock=self.clock())
            if doc is None:
                raise EnhanceError("tập này không enhance được (nguồn không phải YouTube / thiếu video nguồn)", 409)
            d = self._dir(owner)
            if wanted and not doc.get("follows") and doc.get("state") == st.PENDING \
                    and doc.get("config_hash") and len(st.stored_segments(d, doc)) >= st.total_segments(doc) > 0:
                doc.update(state=st.ASSEMBLING, lease=None)
                st.write(d, doc)
                st.mirror(self.config, owner)
            return doc

    def redo(self, eid: str) -> dict:
        """CP13.4 G3 "Enhance lại": queue the video again with the *current* ``[enhance]`` configuration. The previous HD
        source stays in use (renders keep reading it) until the new one is assembled; segments of another ``config_hash``
        are never reused. Raises :class:`EnhanceError` (409) when there is nothing to redo."""
        with self.lock:
            owner = st.base_of(self.config, eid) or eid
            d = self._dir(owner)
            doc = st.read(d)
            if not self.enabled:
                raise EnhanceError("enhance đang tắt ([enhance] enabled = false)", 409)
            if doc is None or not doc.get("wanted") or doc.get("follows"):
                raise EnhanceError("video này không (còn) enhance", 409)
            if is_archived(d):
                raise EnhanceError("đã dọn video nguồn: không còn gì để enhance", 409)
            if doc.get("state") != st.DONE:
                raise EnhanceError("video đang chờ / đang enhance: chưa cần làm lại", 409)
            doc = st.decide(self.config, owner, force=True if doc.get("override") else None, ffprobe=self.ffprobe,
                            clock=self.clock())
            if doc is None or not doc.get("wanted"):
                raise EnhanceError("video này không (còn) enhance", 409)
            if doc.get("state") != st.DONE:
                return doc
            if not st.hd_is_old_config(self.config, doc):
                raise EnhanceError("bản HD đã theo cấu hình hiện hành", 409)
            doc.update(state=st.PENDING, redo=True, error=None, lease=None, segments={}, waiting_hd=False)
            st.write(d, doc)
            st.mirror(self.config, owner)
            log.info("enhance: redo %s with %s", owner, doc.get("params"))
            return doc

    # --- views --------------------------------------------------------------------------------------------------

    def _summary(self, eid: str, d: Path, doc: dict) -> dict:
        lease = doc.get("lease") if self._lease_valid(doc.get("lease")) else None
        prog = (lease or {}).get("progress") or {}
        done_n = len(st.stored_segments(d, doc))
        state = doc.get("state")
        if not doc.get("wanted"):
            kind = "off"
        elif state == st.DONE:
            kind = "done"
        elif state == st.FAILED:
            kind = "failed"
        elif state == st.ASSEMBLING:
            kind = "assembling"
        elif lease:
            kind = "running"
        else:
            kind = "queued"
        return {"episode_id": eid, "state": kind, "wanted": bool(doc.get("wanted")), "override": bool(doc.get("override")),
                "reason": doc.get("reason"), "waiting_hd": bool(doc.get("waiting_hd")), "follows": doc.get("follows"),
                "segments_done": done_n, "segments_total": st.total_segments(doc),
                "segments_uploaded": prog.get("segments_uploaded"), "segments_encoded": prog.get("segments_encoded"),
                "worker": (lease or {}).get("worker"), "gpu": (lease or {}).get("gpu"),
                "lease_expires_at": (lease or {}).get("expires_at"), "error": doc.get("error"),
                "finished_at": doc.get("finished_at"), "workers": doc.get("workers") or [],
                "hd_old_config": st.hd_is_old_config(self.config, doc), "redo": bool(doc.get("redo")),
                "face": (doc.get("params") or {}).get("face") if st.has_face(doc.get("params")) else None}

    def episode_view(self, eid: str) -> dict:
        """What the episode page shows (E10); ``exists`` False = no enhance.json yet."""
        d = self._dir(eid)
        doc = st.read(d)
        out = {"enabled": self.enabled, "paused": self._paused, "exists": doc is not None}
        if doc is None:
            ws = Workspace(self.root, eid)
            try:
                manifest = ws.load_manifest()
            except WorkspaceError:
                manifest = None
            out["can_enable"] = bool(self.enabled and manifest and (manifest.get("source") or {}).get("kind") == "youtube"
                                     and not is_archived(d) and st.source_file(ws, manifest) is not None)
            return out
        with self.lock:
            out.update(self._summary(eid, d, doc))
        out["hd_ready"] = st.hd_fingerprint(d) is not None
        out["can_enable"] = bool(self.enabled and not out["wanted"] and not is_archived(d))
        return out

    def status(self) -> dict:
        """The worker panel (cookie-authenticated, read-only): switches, workers, videos by state."""
        with self.lock:
            counts = {"queued": 0, "running": 0, "assembling": 0, "failed": 0, "done": 0, "waiting_hd": 0}
            items = []
            for eid, d, doc in self._docs():
                if doc.get("follows") or not doc.get("wanted"):
                    continue
                s = self._summary(eid, d, doc)
                counts[s["state"]] = counts.get(s["state"], 0) + 1
                if s["waiting_hd"] and s["state"] != "done":
                    counts["waiting_hd"] += 1
                if s["state"] != "done":
                    items.append(s)
            workers = []
            for w in self._workers.values():
                face = self.config.enhance.face
                workers.append({**w, "yield": w["name"] in self.config.enhance.yield_workers,
                                "outdated": face != st.FACE_NONE and f"face:{face}" not in (w.get("capabilities") or [])})
            return {"enabled": self.enabled, "paused": self._paused, "ai_busy": bool(self.ai_busy()),
                    "workers": sorted(workers, key=lambda w: w["name"]), "counts": counts, "items": items[:100]}
