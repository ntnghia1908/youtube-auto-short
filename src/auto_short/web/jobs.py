"""W5 job queue (CP8.10): in-memory FIFO lanes ``prepare`` / ``ai`` / ``render``, one worker thread per lane;
per-job log ring buffer (stdlib only).

``queue_mode = "lanes"`` (default): a pipeline job goes lane by lane (ingest → transcript → analysis, then
preflight → selection → titling, then render), joining the tail of the next lane's queue after each lane; a
``render`` job (title edit / Short deletion) goes straight to the render lane. Each lane runs one job at a time, so
the AI of one episode overlaps with the render (CPU) of another and the next episodes are prepared in advance.
``queue_mode = "serial"``: one worker runs each job through all six stages (W5 before CP8.10).

An episode has at most one queued/running job (also while it waits between two lanes), so two jobs never write the
same manifest. The community-post compose job (``post``, CP8.16 R3) is the exception: it runs under its own key
:func:`post_key` (at most one per episode too), so it never blocks editing a Short. The queue lives in memory: a
server restart no longer forgets it (CP8.22): the queue is saved to a state file (``JobRunner.configure_persistence``)
and restored at start-up through the same targets; a global pause stops the lanes taking new steps. FIX-ollama-wait: when Ollama is
unreachable the ``ai`` lane does not fail jobs; it keeps them at the head of its queue and re-checks every
``GPU_RETRY_SECONDS`` (docs/tasks/FIX-ollama-wait.md O5). FIX-youtube-botcheck-wait: when YouTube blocks the download
(bot check / 429) the job goes back to the head of the ``prepare`` queue, the lane starts no job that needs a download
until a retry time that doubles at each consecutive block (``[web] youtube_retry_minutes`` ..), kept in the queue file.
Contract: docs/decisions/CP8.3-web-contract.md W5.
"""

from __future__ import annotations

import ctypes
import itertools
import json
import logging
import os
import signal
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..ingest import IngestBlocked, needs_download
from ..pipeline import (PIPELINE_STAGES, OllamaUnavailable, PipelineError, PreflightError, StageRun,
                        ollama_preflight, run_pipeline)
from ..post import fetch as post_fetch
from ..post import stage as post_stage
from ..render import RenderError, run_render
from ..workspace import atomic_write_json
from . import prepared
from .priority import Priority
from ..selection.client import ChatUnavailable

log = logging.getLogger("auto_short")

QUEUED, RUNNING, DONE, FAILED, INTERRUPTED = "queued", "running", "done", "failed", "interrupted"
ACTIVE = (QUEUED, RUNNING)
LOG_LINES = 200
KIND_PIPELINE = "pipeline"
KIND_RENDER = "render"
KIND_ADD = "add"  # CP9 C7: AI title of a Short added by hand (lane ai), then render (lane render)
KIND_POST = "post"  # CP8.15 P1: compose / recompose community post text (lane ai; no render)
KIND_POST_SEARCH = "post_search"  # CP8.15 P5b: find images from a link (lane prepare; no Ollama)
KIND_ENHANCE = "enhance"  # CP13.1b: assemble ``source_hd.mp4`` from the received segments (lane render; runs under enhance_key)
POST_IMAGES_KEY = "_post_images"  # CP8.15 P9: pseudo episode id for the (single, global) image search job
EPISODE_KINDS = (KIND_PIPELINE, KIND_RENDER, KIND_ADD)  # jobs of an episode that run the render step (CP8.16 R2a)


def post_key(episode_id: str) -> str:
    """CP8.16 R3: the runner key of the ``post`` job of an episode (separate from the episode's own job)."""
    return f"{episode_id}#post"

def enhance_key(episode_id: str) -> str:
    """CP13.1b: the runner key of the assembly job of an episode (separate from the episode's own job, which may be
    parked waiting for this very HD source)."""
    return f"{episode_id}#hd"


def job_key(kind: str, episode_id: str) -> str:
    return post_key(episode_id) if kind == KIND_POST else enhance_key(episode_id) if kind == KIND_ENHANCE \
        else episode_id


MODE_LANES, MODE_SERIAL = "lanes", "serial"
PREPARE, AI, RENDER = "prepare", "ai", "render"
LANES = (PREPARE, AI, RENDER)
LANE_STAGES: dict[str, tuple[str, ...]] = {
    PREPARE: ("ingest", "transcript", "analysis"), AI: ("selection", "titling"), RENDER: ("render",)}
PREFETCH_LIMIT = 2  # Q2: prepare starts no new job while this many prepared jobs wait for the ai lane
GPU_RETRY_SECONDS = 60.0  # FIX-ollama-wait O5: the ai lane re-checks Ollama this often while it is down
GPU_OK, GPU_DOWN = "ok", "down"
YT_RETRY_SECONDS = 15 * 60.0  # FIX-youtube-botcheck-wait Y2: first wait after YouTube blocked the download ..
YT_RETRY_MAX_SECONDS = 120 * 60.0  # .. doubled at each consecutive block up to this
_ISO = "%Y-%m-%dT%H:%M:%SZ"
_SERIAL = "serial"  # internal lane of queue_mode "serial" (reported as lane null)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobFailed(Exception):
    """Raised by a job target to finish the job as ``failed`` with this message."""


class StageFailed(JobFailed):
    """A pipeline stage failed (as opposed to the preflight)."""


class GpuUnavailable(JobFailed):
    """FIX-ollama-wait O5: raised by a target of the ``ai`` lane when Ollama is unreachable. In lanes mode the runner
    puts the job back at the head of the ``ai`` queue and waits for the GPU; anywhere else it is a plain failure."""


class YoutubeWait(JobFailed):
    """FIX-youtube-botcheck-wait Y1: raised by a pipeline target of the ``prepare`` lane when YouTube blocked the
    download. In lanes mode the runner puts the job back at the head of the ``prepare`` queue and backs off; anywhere
    else it is a plain failure."""


def run_preflight(job: "Job", preflight: Callable[[Config], None], config: Config) -> None:
    """Run ``preflight`` for a job of the ``ai`` lane and tell the runner whether Ollama answered (the GPU is back
    on success or on a "model missing" error; :class:`OllamaUnavailable` propagates)."""
    reachable = getattr(job, "reachable", None)  # test doubles of Job may lack it
    try:
        preflight(config)
    except OllamaUnavailable:
        raise
    except PreflightError:
        if reachable is not None:
            reachable()
        raise
    if reachable is not None:
        reachable()


@dataclass(frozen=True)
class Step:
    """One part of a job, run by the worker of ``lane``."""

    lane: str
    run: Callable[["Job"], None]


@dataclass
class Job:
    id: str
    episode_id: str
    kind: str
    target: Callable[["Job"], None] = field(repr=False)
    status: str = QUEUED
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    stage: str | None = None  # stage currently running (set by the target), or the next one while waiting
    stages: list[dict] = field(default_factory=list)  # finished stages: {stage, ran, seconds}
    error: str | None = None
    summary: str | None = None
    clip_ids: list[str] = field(default_factory=list)  # render job: Shorts whose title / deletion just changed
    logs: deque = field(default_factory=lambda: deque(maxlen=LOG_LINES), repr=False)
    # CP8.10: lane running the job or the lane it waits for (None: not started yet / finished / serial mode)
    lane: str | None = None
    waiting: bool = False  # running, waiting between two lanes
    steps: list[Step] = field(default_factory=list, repr=False)
    key: str = ""  # runner key: the episode id, or :func:`post_key` for a ``post`` job (CP8.16 R3)
    gpu_wait: bool = False  # O7: waiting in the ai queue while Ollama is unreachable
    yt_wait: bool = False  # FIX-youtube-botcheck-wait: waiting in the prepare queue while YouTube blocks the download
    _yt_ok: Callable[[], None] | None = field(default=None, repr=False)  # set by the runner (prepare lane)
    _reachable: Callable[[], None] | None = field(default=None, repr=False)  # set by the runner (ai lane)
    again: bool = field(default=False, repr=False)  # post job: a new trigger arrived while running (R3)
    requeued: bool = field(default=False, repr=False)  # came back to the ai queue via GpuUnavailable (O5)
    step: int = field(default=0, repr=False)  # index of the running / next step
    t0: float = field(default=0.0, repr=False)  # monotonic start
    pause_requeue: bool = field(default=False, repr=False)  # CP8.22: interrupted by "pause now" -> back to the head
    resume: tuple[str, int] | None = field(default=None, repr=False)  # CP8.22: (lane, step) interrupted by stop()
    step_t0: float = field(default=0.0, repr=False)  # CP8.28: monotonic start of the running step
    step_started_at: str | None = field(default=None, repr=False)  # CP8.28: the same, ISO (monitor tab)
    hd_wait: bool = False  # CP13.1b: parked after titling until the HD source is ready ("đợi HD"): in no lane queue

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    def reachable(self) -> None:
        """A target of the ``ai`` lane got an answer from Ollama (preflight passed / model missing)."""
        cb = self._reachable
        if cb is not None:
            cb()

    def youtube_ok(self) -> None:
        """A YouTube download of this job just succeeded (the block is over)."""
        cb = self._yt_ok
        if cb is not None:
            cb()

    def to_dict(self, *, logs: bool = True) -> dict:
        out = {
            "id": self.id, "episode_id": self.episode_id, "kind": self.kind, "status": self.status,
            "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at,
            "stage": self.stage, "stages": list(self.stages), "error": self.error, "summary": self.summary,
            "clip_ids": list(self.clip_ids), "lane": self.lane, "waiting": self.waiting,
            "gpu_wait": self.gpu_wait, "hd_wait": self.hd_wait, "yt_wait": self.yt_wait,
        }
        if logs:
            out["logs"] = list(self.logs)
        return out


class _JobLogHandler(logging.Handler):
    """Copies ``auto_short`` log records emitted on a lane's worker thread into the job that lane runs."""

    def __init__(self, runner: "JobRunner"):
        super().__init__(logging.INFO)
        self._runner = runner

    def emit(self, record: logging.LogRecord) -> None:
        job = self._runner.job_on_thread(record.thread)
        if job is None:
            return
        try:
            stamp = time.strftime("%H:%M:%S", time.localtime(record.created))
            level = "" if record.levelno < logging.WARNING else f"{record.levelname} "
            job.logs.append(f"{stamp} {level}{record.getMessage()}")
        except Exception:  # never break the job because of logging
            self.handleError(record)


def _child_pids() -> list[int]:
    """Direct child processes of this server (ffmpeg, ...); Linux ``/proc`` only, else empty."""
    pids: list[int] = []
    try:
        for task in Path("/proc/self/task").iterdir():
            text = (task / "children").read_text()
            pids += [int(p) for p in text.split()]
    except (OSError, ValueError):
        return []
    return pids


def _interrupt(thread_ident: int) -> None:
    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread_ident), ctypes.py_object(KeyboardInterrupt))


class JobRunner:
    """``mode`` = ``[web] queue_mode``: ``"lanes"`` (CP8.10) or ``"serial"`` (one worker, whole job)."""

    def __init__(self, mode: str = MODE_LANES, *, gpu_retry_seconds: float = GPU_RETRY_SECONDS,
                 youtube_retry_seconds: float = YT_RETRY_SECONDS, youtube_retry_max_seconds: float = YT_RETRY_MAX_SECONDS,
                 monotonic: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 priority: Priority | None = None) -> None:
        if mode not in (MODE_LANES, MODE_SERIAL):
            raise ValueError(f"unknown queue mode {mode!r}")
        self.mode = mode
        # CP8.26: per-video priority mark (P1); a lane starts the marked videos' jobs first (P2)
        self.priority = priority if priority is not None else Priority()
        self.priority.on_change = self._priority_changed
        self._lane_names = LANES if mode == MODE_LANES else (_SERIAL,)
        self._lock = threading.Condition()
        self._queues: dict[str, deque[Job]] = {lane: deque() for lane in self._lane_names}
        self._current: dict[str, Job | None] = {lane: None for lane in self._lane_names}
        self._threads: dict[str, threading.Thread] = {}
        self._idents: dict[int, str] = {}  # worker thread ident -> lane
        self._tids: dict[int, str] = {}  # CP8.28: worker thread native id (/proc task id) -> lane
        self._jobs: dict[str, Job] = {}
        self._latest: dict[str, Job] = {}  # episode_id -> newest job
        self._ids = itertools.count(1)
        # CP8.16 R2a: called (on the lane worker thread) with an episode job (pipeline / render / add) that ended
        # ``done`` or ``failed``; set by the web app, which submits the ``post`` job.
        self.on_finished: Callable[[Job], None] | None = None
        self._stopping = False
        # CP13.1b: pipeline jobs parked after titling until their HD source is ready (key -> job); in no lane queue,
        # so they hold no lane; ``on_parked(job)`` (set by the web app) re-checks the HD right after a job parks.
        self._parked: dict[str, Job] = {}
        self.on_parked: Callable[[Job], None] | None = None
        self._handler = _JobLogHandler(self)
        # FIX-ollama-wait O5: state of the ai lane's Ollama connection (under ``_lock``); "down" only after a job of
        # the lane hit OllamaUnavailable, back to "ok" as soon as a later check gets an answer.
        self.gpu_retry_seconds = gpu_retry_seconds
        self._gpu: dict = {"state": GPU_OK, "since": None, "error": None, "next_check": None}
        self._gpu_next = 0.0  # monotonic deadline of the next check while down
        # FIX-youtube-botcheck-wait Y2: YouTube block state of the prepare lane (under ``_lock``); the clocks are
        # injectable so tests need no real sleeps
        self.youtube_retry_seconds, self.youtube_retry_max_seconds = youtube_retry_seconds, youtube_retry_max_seconds
        self._mono, self._wall = monotonic, wall
        self._yt: dict = {"blocked": False, "since": None, "error": None, "next_check": None, "failures": 0}
        self._yt_next = 0.0  # monotonic deadline of the next download attempt while blocked
        # CP8.22: global pause (``None`` | ``"now"`` | ``"after"``), kept on disk with the queue
        self._paused: str | None = None
        self._in_step: dict[str, Job] = {}  # lane -> job whose step may be interrupted by "pause now"
        self._state_path: Path | None = None
        self._rebuild: Callable[[str, str, dict, list[str]], Callable[[Job], None] | None] | None = None
        self._restoring = False

    # --- lifecycle -----------------------------------------------------------------------------

    def start(self) -> None:
        if self._threads:
            return
        if log.level == logging.NOTSET:
            log.setLevel(logging.INFO)
        log.addHandler(self._handler)
        self._stopping = False
        for lane in self._lane_names:
            name = "auto-short-jobs" if lane == _SERIAL else f"auto-short-{lane}"
            thread = threading.Thread(target=self._work, args=(lane,), name=name, daemon=True)
            self._threads[lane] = thread
            thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        """Stop every lane. Each running job gets KeyboardInterrupt on its lane thread (the stage records
        ``failed`` / ``interrupted``, CP2) and the child processes SIGINT; waits up to ``timeout`` seconds in total.
        A stage blocked in a long call that ignores the interrupt keeps ``running`` in the manifest and resumes on
        resubmit. Jobs waiting between two lanes end ``interrupted``. CP8.22: the queue is saved first and again
        at the end, so every job that did not finish is restored at the next start."""
        with self._lock:
            self._stopping = True
            self._lock.notify_all()
            running = [(lane, job) for lane, job in self._current.items() if job is not None]
            self._save_locked()  # Q3: the queue (running jobs at the head of their lane) is on disk before any interrupt
        for lane, job in running:
            thread = self._threads.get(lane)
            if thread is not None and thread.ident is not None:
                log.info("web: stopping, interrupting job %s [%s]%s", job.id, job.episode_id,
                         "" if lane == _SERIAL else f" (lane {lane})")
                _interrupt(thread.ident)
        if running:
            for pid in _child_pids():
                try:
                    os.kill(pid, signal.SIGINT)
                except OSError:
                    pass
        deadline = time.monotonic() + timeout
        for thread in self._threads.values():
            thread.join(max(0.0, deadline - time.monotonic()))
        if any(t.is_alive() for t in self._threads.values()):
            log.warning("web: job still running after %.0f s; exiting anyway", timeout)
        with self._lock:
            for queue in self._queues.values():
                for job in queue:
                    if job.status == RUNNING:  # waiting between two lanes (or for the GPU)
                        job.status = INTERRUPTED
                        job.error = "interrupted while waiting for GPU" if job.gpu_wait \
                            else "interrupted while waiting for YouTube" if job.yt_wait \
                            else f"interrupted while waiting for {job.lane}"
                        job.finished_at, job.waiting, job.gpu_wait, job.yt_wait = _now(), False, False, False
            self._save_locked()  # jobs cut by the stop come back first; those that finished meanwhile are gone
            self._lock.notify_all()
        log.removeHandler(self._handler)
        self._threads = {}

    # --- queue ---------------------------------------------------------------------------------

    def _steps(self, kind: str, target: Callable[[Job], None]) -> list[Step]:
        if self.mode == MODE_SERIAL:
            return [Step(_SERIAL, target)]
        lane_steps = getattr(target, "lane_steps", None)
        if lane_steps is not None:
            return list(lane_steps())
        return [Step(RENDER if kind in (KIND_RENDER, KIND_ENHANCE) else PREPARE, target)]

    def _enqueue_locked(self, episode_id: str, kind: str, target: Callable[[Job], None],
                        clip_ids: list[str] | None) -> Job:
        key = job_key(kind, episode_id)
        job = Job(id=str(next(self._ids)), episode_id=episode_id, kind=kind, target=target, key=key,
                  clip_ids=list(clip_ids or []), steps=self._steps(kind, target))
        self._jobs[job.id] = job
        self._latest[key] = job
        self._queues[job.steps[0].lane].append(job)
        self._sync_gpu_wait_locked()
        self._save_locked()
        self._lock.notify_all()
        return job

    def submit(self, episode_id: str, kind: str, target: Callable[[Job], None], *,
               clip_ids: list[str] | None = None) -> tuple[Job, bool]:
        """Queue a job; returns ``(job, True)``, or ``(existing active job, False)`` for a duplicate. In lanes mode
        a target with ``lane_steps()`` (:class:`PipelineTarget`) runs lane by lane; any other callable is one step in
        the render lane (``render`` job) or the prepare lane.

        A ``post`` job is keyed by :func:`post_key` (CP8.16 R3), independent of the episode's own job. A second
        ``post`` request never gets lost: while the job *waits* its ``clips`` are merged into that job; while it
        *runs* they are kept for one more pass (``auto`` + those clips) queued right after it. The existing job is
        returned either way."""
        key = job_key(kind, episode_id)
        with self._lock:
            latest = self._latest.get(key)
            if latest is not None and latest.active:
                new = getattr(target, "clips", None)
                if latest.kind == KIND_POST and new is not None:
                    if latest.status == QUEUED or (latest.status == RUNNING and latest.waiting):
                        latest.target.merge(new)  # not started yet (or back in the queue waiting for the GPU)
                        self._save_locked()
                    elif latest.status == RUNNING:
                        latest.again = True
                        latest.target.merge_pending(new)
                return latest, False
            job = self._enqueue_locked(episode_id, kind, target, clip_ids)
        log.info("web: queued %s job %s [%s]", kind, job.id, episode_id)
        return job, True

    def latest(self, episode_id: str) -> Job | None:
        """The newest job of the episode itself (pipeline / render / add), not its ``post`` job."""
        with self._lock:
            return self._latest.get(episode_id)

    def latest_post(self, episode_id: str) -> Job | None:
        """The newest ``post`` job of the episode (CP8.16 R3)."""
        with self._lock:
            return self._latest.get(post_key(episode_id))

    def latest_enhance(self, episode_id: str) -> Job | None:
        """The newest HD assembly job of the episode (CP13.1b)."""
        with self._lock:
            return self._latest.get(enhance_key(episode_id))

    def job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def forget(self, episode_id: str) -> bool:
        """Drop the finished jobs of a deleted episode (CP8.5 X3) so it leaves every view; refused (False) while
        one of its jobs is queued/running."""
        with self._lock:
            for key in (episode_id, post_key(episode_id), enhance_key(episode_id)):
                latest = self._latest.get(key)
                if latest is not None and latest.active:
                    return False
            self._latest.pop(episode_id, None)
            self._latest.pop(post_key(episode_id), None)
            self._latest.pop(enhance_key(episode_id), None)
            for job_id in [j.id for j in self._jobs.values() if j.episode_id == episode_id]:
                del self._jobs[job_id]
        return True

    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def queue_position(self, job: Job) -> int | None:
        """1-based position in the queue of the lane the job waits for (queued, or waiting between two lanes);
        None when it runs or has finished."""
        with self._lock:
            for queue in self._queues.values():
                for i, j in enumerate(self._ordered(queue), 1):
                    if j is job:
                        return i
        return None

    # --- CP8.26: priority order of a lane queue ---------------------------------------------------

    def _rank(self, job: Job) -> float:
        rank = self.priority.rank(job.episode_id)
        return float("inf") if rank is None else rank

    def _ordered(self, queue: "deque[Job]") -> list[Job]:
        """The queue in start order: marked videos first (mark order), then the others; stable inside each group."""
        return sorted(queue, key=self._rank)

    def _pick(self, queue: "deque[Job]", pred: Callable[[Job], bool] | None = None) -> Job | None:
        """The job of ``queue`` that starts first (optionally among those accepted by ``pred``); not removed."""
        best, best_rank = None, float("inf")
        for j in queue:
            if pred is not None and not pred(j):
                continue
            rank = self._rank(j)
            if best is None or rank < best_rank:
                best, best_rank = j, rank
        return best

    def _pop(self, queue: "deque[Job]", pred: Callable[[Job], bool] | None = None) -> Job | None:
        job = self._pick(queue, pred)
        if job is not None:
            queue.remove(job)
        return job

    def _priority_changed(self) -> None:
        with self._lock:
            self._lock.notify_all()

    def job_on_thread(self, thread_ident: int | None) -> Job | None:
        """The job the lane worker ``thread_ident`` is running (log handler)."""
        lane = self._idents.get(thread_ident) if thread_ident is not None else None
        return self._current.get(lane) if lane is not None else None

    def running(self) -> dict[str, Job]:
        """Lane -> job it is running (test / diagnostics)."""
        with self._lock:
            return {lane: job for lane, job in self._current.items() if job is not None}

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """Test helper: wait until no job is queued, running in a lane or waiting between two lanes."""
        deadline = time.monotonic() + timeout
        with self._lock:
            while any(self._queues.values()) or any(j is not None for j in self._current.values()):
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._lock.wait(left)
        return True

    # --- workers -------------------------------------------------------------------------------

    # --- FIX-ollama-wait: GPU state --------------------------------------------------------------

    def gpu_status(self) -> dict:
        """O7: ``{state, since, error, next_check}`` of the ai lane's last Ollama check (``ok`` at start)."""
        with self._lock:
            return dict(self._gpu)

    def ai_busy(self) -> bool:
        """CP13.1b E7: does the ``ai`` lane (Ollama) run a job or have one waiting? (jobs waiting while the whole queue is
        paused do not count: nothing uses Ollama then.) In serial mode every running job counts."""
        with self._lock:
            lane = AI if AI in self._queues else _SERIAL
            running = self._current.get(lane) is not None
            if lane == _SERIAL:
                return running
            return running or (bool(self._queues[AI]) and self._paused is None)

    def _gpu_down(self) -> bool:
        return self._gpu["state"] == GPU_DOWN

    def _sync_gpu_wait_locked(self) -> None:
        down = self._gpu_down()
        for j in self._queues.get(AI, ()):
            j.gpu_wait = down
        blocked = self._yt["blocked"]
        for j in self._queues.get(PREPARE, ()):
            j.yt_wait = blocked

    def _set_gpu_down_locked(self, error: str) -> None:
        if not self._gpu_down():
            self._gpu["since"] = _now()
            log.warning("web: ollama unavailable (%s); ai lane waits for the GPU, re-checking every %g s", error,
                        self.gpu_retry_seconds)
        self._gpu["state"], self._gpu["error"] = GPU_DOWN, error
        self._gpu_next = time.monotonic() + self.gpu_retry_seconds
        self._gpu["next_check"] = datetime.fromtimestamp(time.time() + self.gpu_retry_seconds, timezone.utc) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        self._sync_gpu_wait_locked()

    def _gpu_reachable(self) -> None:
        with self._lock:
            if not self._gpu_down():
                return
            self._gpu.update(state=GPU_OK, since=None, error=None, next_check=None)
            log.info("web: ollama is back")
            self._sync_gpu_wait_locked()
            self._lock.notify_all()  # the prepare lane's prefetch limit applies again

    # --- FIX-youtube-botcheck-wait: YouTube block state ------------------------------------------

    def youtube_status(self) -> dict:
        """Y3: ``{blocked, since, error, next_check, failures}`` of the prepare lane's downloads."""
        with self._lock:
            return dict(self._yt)

    def _yt_blocked(self) -> bool:
        return bool(self._yt["blocked"])

    def _yt_wait_seconds(self, failures: int) -> float:
        return min(self.youtube_retry_seconds * 2 ** max(0, failures - 1), self.youtube_retry_max_seconds)

    def _set_yt_blocked_locked(self, error: str) -> None:
        failures = int(self._yt["failures"]) + 1
        wait = self._yt_wait_seconds(failures)
        if not self._yt_blocked():
            self._yt["since"] = datetime.fromtimestamp(self._wall(), timezone.utc).strftime(_ISO)
        self._yt.update(blocked=True, error=error, failures=failures,
                        next_check=datetime.fromtimestamp(self._wall() + wait, timezone.utc).strftime(_ISO))
        self._yt_next = self._mono() + wait
        log.warning("web: YouTube blocked the download (%s); prepare lane waits %g min (block #%d)", error,
                    wait / 60, failures)
        self._sync_gpu_wait_locked()

    def _youtube_ok(self) -> None:
        with self._lock:
            if not self._yt_blocked() and not self._yt["failures"]:
                return
            self._yt.update(blocked=False, since=None, error=None, next_check=None, failures=0)
            log.info("web: YouTube downloads work again")
            self._sync_gpu_wait_locked()
            self._save_locked()
            self._lock.notify_all()

    def _no_download(self, job: Job) -> bool:
        """Y2: may ``job`` run in the prepare lane while YouTube blocks downloads? True when it needs none."""
        check = getattr(job.target, "needs_download", None)
        if check is None:
            return True  # not a pipeline job (image search ..): no YouTube
        try:
            return not check()
        except Exception:
            return False

    # --- workers -------------------------------------------------------------------------------

    def _can_start(self, lane: str) -> bool:
        if not self._queues[lane]:
            return False
        if lane == PREPARE:  # Q2: bounded prefetch (O6: not while the GPU is down)
            return len(self._queues[AI]) < PREFETCH_LIMIT or self._gpu_down()
        return True

    def _take_locked(self, lane: str) -> Job | None:
        """Next job for ``lane`` (blocks); None when stopping. While the ai lane is down it waits until the next
        check time (``Condition.wait``, so ``stop()`` never waits it out), but an ``add`` job (CP9) never waits."""
        queue = self._queues[lane]
        while not self._stopping:
            if self._paused is not None:  # CP8.22: nothing new starts while paused
                self._lock.wait()
                continue
            if lane == PREPARE and queue and self._yt_blocked():
                left = self._yt_next - self._mono()
                if left > 0:  # Y2: only jobs that need no download may start (and only within the prefetch limit)
                    free = self._pop(queue, self._no_download) if self._can_start(lane) else None
                    if free is not None:
                        return free
                    self._lock.wait(left)
                    continue
                return self._pop(queue)  # time to try again
            if lane == AI and queue and self._gpu_down():
                # an ``add`` job never waits; nor does a ``post`` job that has not run yet (it may need no AI:
                # FIX-post-doc-no-gpu F3). A job that came back via GpuUnavailable waits for the next check.
                free = self._pop(queue, lambda j: j.kind == KIND_ADD) or \
                    self._pop(queue, lambda j: j.kind == KIND_POST and not j.requeued)
                if free is not None:
                    return free
                left = self._gpu_next - time.monotonic()
                if left > 0:
                    self._lock.wait(left)
                    continue
                return self._pop(queue)
            if self._can_start(lane):
                return self._pop(queue)
            self._lock.wait()
        return None

    def _work(self, lane: str) -> None:
        self._idents[threading.get_ident()] = lane
        self._tids[threading.get_native_id()] = lane
        while True:
            try:
                self._loop(lane)
                return
            except KeyboardInterrupt:  # stop() raced with the end of a job
                if self._stopping:
                    return
                # CP8.22: a late "pause now" interrupt landed outside the job; the lane must survive it

    def _loop(self, lane: str) -> None:
        while True:
            ok = False
            requeue: str | None = None
            blocked: str | None = None
            paused_back = False
            with self._lock:
                job = self._take_locked(lane)
                if job is None:
                    return
                job.pause_requeue = False
                self._in_step[lane] = job
                first = job.status == QUEUED
                if first:
                    job.status, job.started_at, job.t0 = RUNNING, _now(), time.monotonic()
                job.lane = None if lane == _SERIAL else lane
                job.waiting, job.gpu_wait, job.yt_wait = False, False, False
                job._reachable = self._gpu_reachable if lane == AI else None
                job._yt_ok = self._youtube_ok if lane == PREPARE else None
                job.step_t0, job.step_started_at = time.monotonic(), _now()
                self._current[lane] = job
                self._lock.notify_all()  # a shorter ai queue may let the prepare lane start (Q2)
            try:
                if first:
                    log.info("web: start %s job %s [%s]", job.kind, job.id, job.episode_id)
                else:
                    log.info("web: job %s continues in lane %s [%s]", job.id, lane, job.episode_id)
                job.steps[job.step].run(job)
                ok = True
            except KeyboardInterrupt:
                if job.pause_requeue and not self._stopping:  # CP8.22: "pause now": back to the head of the lane
                    paused_back = True
                    log.info("web: job %s paused during %s [%s]", job.id, job.stage or "start", job.episode_id)
                else:
                    job.status, job.error = INTERRUPTED, f"interrupted during {job.stage or 'start'}"
                    if self._stopping:
                        job.resume = (lane, job.step)
                    log.info("web: job %s interrupted [%s]", job.id, job.episode_id)
            except YoutubeWait as exc:
                if lane == PREPARE and not self._stopping:  # Y2: back to the head of the queue, wait for YouTube
                    blocked = str(exc)
                    log.info("web: job %s [%s] waits for YouTube: %s", job.id, job.episode_id, exc)
                else:
                    job.status, job.error = FAILED, str(exc)
                    log.error("web: job %s failed [%s]: %s", job.id, job.episode_id, exc)
            except GpuUnavailable as exc:
                if lane == AI and not self._stopping:  # O5: back to the head of the queue, wait for the GPU
                    requeue = str(exc)
                    log.info("web: job %s [%s] waits for the GPU: %s", job.id, job.episode_id, exc)
                else:
                    job.status, job.error = FAILED, str(exc)
                    log.error("web: job %s failed [%s]: %s", job.id, job.episode_id, exc)
            except JobFailed as exc:
                job.status, job.error = FAILED, str(exc)
                log.error("web: job %s failed [%s]: %s", job.id, job.episode_id, exc)
            except Exception as exc:  # a bug must not kill the worker
                job.status, job.error = FAILED, f"{type(exc).__name__}: {exc}"
                log.exception("web: job %s crashed [%s]", job.id, job.episode_id)
            finally:
                for _attempt in range(3):  # a late "pause now" interrupt must not skip the bookkeeping
                    try:
                        if paused_back:
                            self._requeue_paused(lane, job)
                        elif blocked is not None:
                            self._requeue_blocked(lane, job, blocked)
                        elif requeue is not None:
                            self._requeue(lane, job, requeue)
                        else:
                            self._after(lane, job, ok)
                        break
                    except KeyboardInterrupt:
                        if self._stopping:
                            break

    def _requeue_paused(self, lane: str, job: Job) -> None:
        """CP8.22: a step cut by "pause now" returns to the head of its lane (not failed); its stages rerun later."""
        with self._lock:
            self._current[lane] = None
            self._in_step.pop(lane, None)
            job.pause_requeue, job._reachable, job.error = False, None, None
            lane_stages = LANE_STAGES.get(lane, ())
            job.stages[:] = [st for st in job.stages if lane_stages and st["stage"] not in lane_stages] \
                if lane != _SERIAL else []
            if job.step == 0:
                job.status, job.started_at, job.lane, job.waiting, job.stage = QUEUED, None, None, False, None
            else:
                job.lane, job.waiting = lane, True
                job.stage = LANE_STAGES[lane][0] if lane in LANE_STAGES else None
            self._queues[lane].appendleft(job)
            self._sync_gpu_wait_locked()
            self._save_locked()
            self._lock.notify_all()

    def _requeue(self, lane: str, job: Job, error: str) -> None:
        with self._lock:
            self._current[lane] = None
            self._in_step.pop(lane, None)
            job.lane, job.waiting, job._reachable = lane, True, None
            job.requeued = True
            if job.kind == KIND_PIPELINE:
                job.stage = LANE_STAGES[lane][0]
            self._queues[lane].appendleft(job)
            self._set_gpu_down_locked(error)
            self._save_locked()
            self._lock.notify_all()

    def _requeue_blocked(self, lane: str, job: Job, error: str) -> None:
        """Y2: YouTube blocked the download: the job returns, not failed, to the head of the prepare queue (like a job
        cut by "pause now": its prepare stages rerun later) and the lane backs off."""
        with self._lock:
            self._current[lane] = None
            self._in_step.pop(lane, None)
            job._yt_ok, job.error = None, None
            job.stages[:] = [st for st in job.stages if st["stage"] not in LANE_STAGES[PREPARE]]
            if job.step == 0:
                job.status, job.started_at, job.lane, job.waiting, job.stage = QUEUED, None, None, False, None
            else:
                job.lane, job.waiting, job.stage = lane, True, LANE_STAGES[lane][0]
            self._queues[lane].appendleft(job)
            self._set_yt_blocked_locked(error)
            self._save_locked()
            self._lock.notify_all()

    def _after(self, lane: str, job: Job, ok: bool) -> None:
        last = not ok or job.step + 1 >= len(job.steps)
        job._reachable = job._yt_ok = None
        park = False
        if not last and job.kind == KIND_PIPELINE and job.steps[job.step + 1].lane == RENDER \
                and not self._stopping:
            hold = getattr(job.target, "hd_hold", None)  # CP13.1b E6: "đợi HD" - the render waits for the HD source
            if hold is not None:
                try:
                    park = bool(hold(job))
                except Exception:  # a bug in the hook must not strand the job
                    log.exception("web: hd hold hook failed for job %s [%s]", job.id, job.episode_id)
        if ok and last:
            job.status = DONE
            log.info("web: job %s done in %.1f s [%s]%s", job.id, time.monotonic() - job.t0,
                     job.episode_id, f": {job.summary}" if job.summary else "")
        if last and job.kind in EPISODE_KINDS and job.status in (DONE, FAILED) \
                and self.on_finished is not None and not self._stopping:
            # before the lane is released: ``wait_idle`` never sees a gap between the job and its follow-up
            try:
                self.on_finished(job)
            except Exception:  # a bug in the hook must not kill the worker
                log.exception("web: on_finished hook failed for job %s [%s]", job.id, job.episode_id)
        with self._lock:
            self._current[lane] = None
            self._in_step.pop(lane, None)
            if last:
                job.finished_at, job.lane, job.waiting = _now(), None, False
                if job.again and job.kind == KIND_POST and job.status != INTERRUPTED and not self._stopping:
                    follow = getattr(job.target, "followup", None)
                    follow = follow() if follow is not None else None
                    if follow is not None:  # R3: one more pass for the trigger that arrived meanwhile
                        self._enqueue_locked(job.episode_id, KIND_POST, follow, None)
            elif park:  # CP13.1b: waits outside every lane queue until unpark()
                job.step += 1
                job.lane, job.waiting, job.hd_wait = None, True, True
                job.stage = LANE_STAGES[job.steps[job.step].lane][0]
                self._parked[job.key] = job
                log.info("web: job %s [%s] waits for the HD source", job.id, job.episode_id)
            else:  # tail of the next lane's queue
                job.step += 1
                nxt = job.steps[job.step].lane
                job.lane, job.waiting = nxt, True
                job.stage = LANE_STAGES[nxt][0]
                self._queues[nxt].append(job)
                self._sync_gpu_wait_locked()
            self._save_locked()
            self._lock.notify_all()
        if park and self.on_parked is not None and not self._stopping:
            try:  # the HD may have become ready between the hold check and the parking
                self.on_parked(job)
            except Exception:
                log.exception("web: on_parked hook failed for job %s [%s]", job.id, job.episode_id)

    # --- CP13.1b: parked ("đợi HD") jobs -------------------------------------------------------------------------

    def parked(self) -> list[Job]:
        with self._lock:
            return list(self._parked.values())

    def unpark(self, episode_id: str) -> Job | None:
        """The HD source is ready (or the user chose the original): the parked job joins the tail of the ``render`` queue.
        Returns the job, or None when the episode has none parked."""
        with self._lock:
            job = self._parked.pop(episode_id, None)
            if job is None:
                return None
            job.hd_wait, job.lane, job.waiting = False, RENDER, True
            self._queues[RENDER].append(job)
            self._sync_gpu_wait_locked()
            self._save_locked()
            self._lock.notify_all()
        log.info("web: job %s [%s] leaves the HD wait -> render queue", job.id, episode_id)
        return job

    def drop_parked(self, episode_id: str) -> bool:
        """Cancel the parked job of an episode (the episode is being deleted); its stages stay done on disk."""
        with self._lock:
            job = self._parked.pop(episode_id, None)
            if job is None:
                return False
            job.status, job.error, job.finished_at = INTERRUPTED, "hủy khi đợi HD", _now()
            job.hd_wait, job.waiting, job.lane = False, False, None
            self._save_locked()
            self._lock.notify_all()
        return True

    def recheck_parked(self) -> None:
        """Start-up: ask ``on_parked`` about every restored parked job (its HD may be ready by now)."""
        if self.on_parked is None:
            return
        for job in self.parked():
            try:
                self.on_parked(job)
            except Exception:
                log.exception("web: on_parked hook failed for job %s [%s]", job.id, job.episode_id)

    # --- CP8.22: pause / resume ------------------------------------------------------------------

    def pause(self, mode: str = "after") -> dict:
        """Global pause: no lane starts a new step (a job finishing a step keeps waiting in the next lane's queue).
        ``"after"`` lets the running steps finish; ``"now"`` interrupts them like :meth:`stop` (KeyboardInterrupt +
        SIGINT to the child processes) and each job returns, not failed, to the head of its lane. Pausing again with
        ``"now"`` after ``"after"`` interrupts what still runs."""
        if mode not in ("now", "after"):
            raise ValueError(f"unknown pause mode {mode!r}")
        cut: list[tuple[str, Job]] = []
        with self._lock:
            if self._paused != "now":
                self._paused = mode
            log.info("web: queue paused (%s): %d waiting", mode, self._pending_locked())
            self._save_locked()
            if mode == "now":
                for lane, job in self._in_step.items():
                    thread = self._threads.get(lane)
                    if job is self._current.get(lane) and thread is not None and thread.ident is not None:
                        job.pause_requeue = True
                        cut.append((lane, job))
                        _interrupt(thread.ident)
            self._lock.notify_all()
        if cut:
            for pid in _child_pids():
                try:
                    os.kill(pid, signal.SIGINT)
                except OSError:
                    pass
        return self.queue_state()

    def resume(self) -> dict:
        """Lanes take work again, in their old order."""
        with self._lock:
            if self._paused is not None:
                log.info("web: queue resumed: %d waiting", self._pending_locked())
            self._paused = None
            self._save_locked()
            self._lock.notify_all()
        return self.queue_state()

    def _pending_locked(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def queue_state(self) -> dict:
        """``{paused, mode, running, pending}``: ``mode`` = ``"now"`` | ``"after"`` | None; ``running`` = steps in
        progress; ``pending`` = jobs waiting in a lane queue (also between two lanes)."""
        with self._lock:
            return {"paused": self._paused is not None, "mode": self._paused,
                    "running": sum(1 for j in self._current.values() if j is not None),
                    "pending": self._pending_locked()}

    # --- CP8.28: monitor tab ---------------------------------------------------------------------

    def lane_tids(self) -> dict[int, str]:
        """Native thread id (``/proc/<pid>/task/<tid>``) of each lane worker -> lane (monitor: which child process
        belongs to which lane)."""
        return dict(self._tids)

    def _monitor_entry(self, job: Job, *, running: bool = False) -> dict:
        rank = self.priority.rank(job.episode_id)
        out = {"id": job.id, "episode_id": job.episode_id, "kind": job.kind, "status": job.status, "stage": job.stage,
               "lane": job.lane, "waiting": job.waiting, "priority": rank is not None,
               "priority_rank": rank, "requeued": job.requeued, "started_at": job.started_at,
               "created_at": job.created_at, "step": job.step + 1, "steps": len(job.steps) or 1}
        if running:
            out["step_started_at"] = job.step_started_at
            out["elapsed_seconds"] = round(max(0.0, time.monotonic() - job.step_t0), 1)
            out["job_elapsed_seconds"] = round(max(0.0, time.monotonic() - job.t0), 1) if job.t0 else None
        return out

    def monitor_queue(self, limit: int = 20) -> dict:
        """CP8.28 M1: what every lane runs, what waits (and why) and the order the lanes will start the rest in.
        ``lanes[lane] = {running, pending (first ``limit``, in start order), pending_total}``; ``waiting`` = jobs that
        hold no lane: ``hd`` (parked, "đợi HD"), ``gpu`` (ai queue while Ollama is down), ``youtube`` (prepare queue
        job that needs a download while YouTube blocks them), with the retry time when known."""
        limit = max(1, int(limit))
        with self._lock:
            lanes: dict[str, dict] = {}
            waiting: list[dict] = []
            for lane in self._lane_names:
                cur = self._current.get(lane)
                ordered = self._ordered(self._queues[lane])
                pend = []
                for i, j in enumerate(ordered[:limit], 1):
                    e = self._monitor_entry(j)
                    e["position"] = i
                    pend.append(e)
                lanes[lane] = {"running": self._monitor_entry(cur, running=True) if cur is not None else None,
                               "pending": pend, "pending_total": len(ordered)}
                if lane == AI and self._gpu_down():
                    waiting += [dict(self._monitor_entry(j), reason="gpu", retry_at=self._gpu["next_check"])
                                for j in ordered if j.gpu_wait]
                if lane == PREPARE and self._yt_blocked():
                    waiting += [dict(self._monitor_entry(j), reason="youtube", retry_at=self._yt["next_check"])
                                for j in ordered if not self._no_download(j)]
            waiting += [dict(self._monitor_entry(j), reason="hd", retry_at=None)
                        for j in sorted(self._parked.values(), key=lambda j: int(j.id))]
            return {"mode": self.mode, "paused": self._paused is not None, "pause_mode": self._paused,
                    "lanes": lanes, "waiting": waiting[:limit * 3], "waiting_total": len(waiting),
                    "gpu": dict(self._gpu), "youtube": dict(self._yt)}

    # --- CP8.22: persistence ---------------------------------------------------------------------

    def configure_persistence(self, path: Path,
                              rebuild: Callable[[str, str, dict, list[str]], Callable[[Job], None] | None]) -> None:
        """Keep the queue in ``path`` (written atomically each time it changes). ``rebuild(kind, episode_id, spec,
        clip_ids)`` returns the target of a saved job, or None when it cannot be recreated."""
        self._state_path, self._rebuild = Path(path), rebuild

    def _entry(self, job: Job, step: int) -> dict:
        spec = getattr(job.target, "spec", None)
        try:
            spec = spec() if callable(spec) else {}
        except Exception:  # a broken spec must not stop the queue from being saved
            spec = {}
        return {"kind": job.kind, "episode_id": job.episode_id, "spec": spec, "clip_ids": list(job.clip_ids),
                "step": step}

    def _snapshot_locked(self) -> dict:
        lanes: dict[str, list[dict]] = {}
        for lane in self._lane_names:
            heads: list[Job] = []
            current = self._current.get(lane)
            if current is not None:
                heads.append(current)
            heads += sorted((j for j in self._jobs.values() if j.resume is not None and j.resume[0] == lane
                             and j.status == INTERRUPTED and j is not current), key=lambda j: int(j.id))
            entries = [self._entry(j, j.resume[1] if j.resume is not None and j.status == INTERRUPTED else j.step)
                       for j in heads]
            entries += [self._entry(j, j.step) for j in self._queues[lane]]
            lanes[lane] = entries
        parked = [self._entry(j, j.step) for j in sorted(self._parked.values(), key=lambda j: int(j.id))]
        out = {"version": 1, "mode": self.mode, "paused": self._paused is not None, "lanes": lanes,
               "parked": parked}
        if self._yt_blocked():  # Y3: the block (and its retry time) survives a restart
            out["youtube"] = {k: self._yt[k] for k in ("since", "error", "next_check", "failures")}
        return out

    def _save_locked(self) -> None:
        if self._state_path is None or self._restoring:
            return
        try:
            atomic_write_json(self._state_path, self._snapshot_locked())
        except Exception as exc:  # disk full etc.: the queue keeps running in memory
            log.warning("web: không ghi được hàng đợi %s: %s", self._state_path, exc)

    def restore(self) -> int:
        """Recreate the saved queue (call before :meth:`start`); returns the number of jobs restored. A job that
        cannot be recreated is skipped with a log line; a missing / unreadable file restores nothing."""
        if self._state_path is None or self._rebuild is None:
            return 0
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            lanes = data["lanes"]
            if not isinstance(lanes, dict):
                raise ValueError("lanes is not an object")
        except FileNotFoundError:
            return 0
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("web: hàng đợi đã lưu %s không đọc được, bỏ qua: %s", self._state_path, exc)
            return 0
        same_mode = data.get("mode") == self.mode
        parked_entries = data.get("parked") if isinstance(data.get("parked"), list) and same_mode \
            and self.mode == MODE_LANES else []
        entries: list[tuple[str, dict]] = []
        for lane in (self._lane_names if same_mode else LANES + (_SERIAL,)):
            for entry in lanes.get(lane) or []:
                entries.append((lane, entry))
        restored = 0
        with self._lock:
            self._restoring = True
            try:
                self._paused = "after" if data.get("paused") else None
                self._restore_youtube_locked(data.get("youtube"))
                for lane, entry in entries:
                    try:
                        job = self._restore_one_locked(lane, entry, same_mode)
                    except Exception as exc:
                        log.warning("web: bỏ qua việc đã lưu %r: %s: %s", entry, type(exc).__name__, exc)
                        continue
                    restored += 1 if job is not None else 0
                for entry in parked_entries:  # CP13.1b: "đợi HD" jobs stay parked until their HD source is ready
                    try:
                        job = self._restore_one_locked(RENDER, entry, same_mode, parked=True)
                    except Exception as exc:
                        log.warning("web: bỏ qua việc đợi HD đã lưu %r: %s: %s", entry, type(exc).__name__, exc)
                        continue
                    restored += 1 if job is not None else 0
            finally:
                self._restoring = False
            self._sync_gpu_wait_locked()
            self._save_locked()
        if restored or self._paused:
            log.info("web: khôi phục hàng đợi: %d việc%s", restored, ", đang tạm ngưng" if self._paused else "")
        return restored

    def _restore_youtube_locked(self, saved) -> None:
        if not isinstance(saved, dict):
            return
        try:
            due = datetime.strptime(saved["next_check"], _ISO).replace(tzinfo=timezone.utc).timestamp()
            failures = max(1, int(saved.get("failures") or 1))
        except (KeyError, TypeError, ValueError):
            return
        self._yt.update(blocked=True, since=saved.get("since"), error=saved.get("error"),
                        next_check=saved["next_check"], failures=failures)
        self._yt_next = self._mono() + max(0.0, due - self._wall())
        log.info("web: khôi phục trạng thái YouTube chặn tải, thử lại lúc %s", saved["next_check"])

    def _restore_one_locked(self, lane: str, entry: dict, same_mode: bool, parked: bool = False) -> Job | None:
        kind, episode_id = entry["kind"], entry["episode_id"]
        spec, clip_ids = entry.get("spec") or {}, list(entry.get("clip_ids") or [])
        if not isinstance(kind, str) or not isinstance(episode_id, str) or not isinstance(spec, dict):
            raise ValueError("malformed entry")
        key = job_key(kind, episode_id)
        latest = self._latest.get(key)
        if latest is not None and latest.active:
            log.warning("web: bỏ qua việc đã lưu trùng [%s] (%s)", episode_id, kind)
            return None
        target = self._rebuild(kind, episode_id, spec, clip_ids)
        if target is None:
            log.warning("web: bỏ qua việc đã lưu [%s] (%s): không tạo lại được", episode_id, kind)
            return None
        job = Job(id=str(next(self._ids)), episode_id=episode_id, kind=kind, target=target, key=key,
                  clip_ids=clip_ids, steps=self._steps(kind, target))
        step = entry.get("step", 0)
        if parked:  # the step after the ``ai`` lane: the render
            if kind != KIND_PIPELINE or not isinstance(step, int) or not 0 < step < len(job.steps) \
                    or job.steps[step].lane != RENDER:
                raise ValueError("a parked job must be a pipeline job waiting for its render step")
            job.step = step
            job.status, job.started_at, job.t0 = RUNNING, _now(), time.monotonic()
            job.lane, job.waiting, job.hd_wait, job.stage = None, True, True, LANE_STAGES[RENDER][0]
            self._jobs[job.id] = job
            self._latest[key] = job
            self._parked[key] = job
            return job
        if not (same_mode and isinstance(step, int) and 0 <= step < len(job.steps) and job.steps[step].lane == lane):
            step = 0
        job.step = step
        if step > 0:  # finished its earlier lanes: waiting for this one
            job.status, job.started_at, job.t0 = RUNNING, _now(), time.monotonic()
            job.lane, job.waiting, job.stage = job.steps[step].lane, True, LANE_STAGES.get(job.steps[step].lane, (None,))[0]
        self._jobs[job.id] = job
        self._latest[key] = job
        self._queues[job.steps[step].lane].append(job)
        return job


# --- pipeline job (W4) ---------------------------------------------------------------------------

class PipelineTarget:
    """Job target running the CP8 pipeline on ``url``. ``episode_id``: the khai thị episode ``<video_id>.kt``
    (CP8.9 K7; its ``khaithi.json`` is written before the job is queued), None = the id ingest derives (a Short).

    Called directly (``queue_mode = "serial"``): all six stages, preflight again when the job starts (E8).
    ``lane_steps()`` (lanes, CP8.10): ``prepare`` = W9 disk check then ingest → transcript → analysis, ``ai`` =
    preflight → selection → titling, ``render`` = render; the later lanes use the episode id ingest returned.
    ``disk_blocked`` (None = no check) returns the W9 message when the drive is below the block threshold."""

    def __init__(self, url: str, config: Config, *, series: str | None = None, episode: str | None = None,
                 pipeline: Callable = run_pipeline,
                 preflight: Callable[[Config], None] | None = ollama_preflight,
                 episode_id: str | None = None, disk_blocked: Callable[[], str | None] | None = None,
                 enhance=None, prepare_only: bool = False):
        self.url, self.config, self.series, self.episode = url, config, series, episode
        self.prepare_only = prepare_only  # CP13.2 H1: "Chuẩn bị + HD": only the prepare lane, then stop
        self.pipeline, self.preflight, self.episode_id = pipeline, preflight, episode_id
        self.disk_blocked = disk_blocked
        self.enhance = enhance  # CP13.1b: object with ``decide(episode_id)`` / ``hold(episode_id) -> bool``, or None
        self._resolved: str | None = episode_id  # episode id for the ai / render lanes

    def _run(self, job: Job, stages: tuple[str, ...] | None, *, preflight: bool, episode_id: str | None):
        def checked_preflight(cfg: Config) -> None:
            job.stage = "preflight"
            run_preflight(job, self.preflight, cfg)
            job.stage = (stages or PIPELINE_STAGES)[0]

        def on_stage(run: StageRun) -> None:
            job.stages.append({"stage": run.stage, "ran": run.ran, "seconds": run.seconds})
            if run.stage == "ingest" and run.ran and downloads and getattr(job, "youtube_ok", None) is not None:
                job.youtube_ok()  # Y2: a download really went to YouTube and worked: the block (if any) is over
            if run.stage == "ingest" and self.enhance is not None:  # CP13.1b E1: decide right after the download
                eid = getattr(run.result, "episode_id", None) or episode_id
                if eid:
                    self.enhance.decide(eid)
            i = PIPELINE_STAGES.index(run.stage)
            job.stage = PIPELINE_STAGES[i + 1] if i + 1 < len(PIPELINE_STAGES) else None

        job.stage = (stages or PIPELINE_STAGES)[0]
        # decided before the run: afterwards the source is there. A reused / skipped ingest must not reset the block.
        downloads = "ingest" in (stages or PIPELINE_STAGES) and self.needs_download()
        kw: dict = {"episode_id": episode_id} if episode_id is not None else {}
        if stages is not None:
            kw["stages"] = stages
        try:
            result = self.pipeline(self.url, self.config, series=self.series, episode=self.episode,
                                   preflight=checked_preflight if preflight and self.preflight is not None else None,
                                   on_stage=on_stage, **kw)
        except OllamaUnavailable as exc:
            raise GpuUnavailable(f"ollama preflight: {exc}") from exc
        except PreflightError as exc:
            raise JobFailed(f"ollama preflight: {exc}") from exc
        except PipelineError as exc:
            raise JobFailed(str(exc)) from exc
        if not result.ok:
            job.stage = result.failed_stage
            if isinstance(result.error, IngestBlocked):  # Y1: temporary, the web queue waits and retries
                raise YoutubeWait(f"{result.failed_stage}: {result.error}")
            raise StageFailed(f"{result.failed_stage}: {result.error}")
        return result

    def _finish(self, job: Job, result) -> None:
        job.stage = None
        job.summary = f"{result.rendered}/{result.clips} Shorts"
        render = result.stages[-1].result if result.stages else None
        if render is not None and render.ran and getattr(render, "encoded", None) is not None:
            job.summary += f" ({render.encoded} encoded, {render.reused} reused)"

    def __call__(self, job: Job) -> None:
        """Whole pipeline in one call (serial mode, W5 before CP8.10)."""
        if self.prepare_only:
            self.prepare_only_step(job)
            return
        result = self._run(job, None, preflight=True, episode_id=self.episode_id)
        eid = getattr(result, "episode_id", None) or self.episode_id
        if eid:
            prepared.clear(self.config, eid)  # CP13.2: a full run takes the episode out of "chờ cắt"
        self._finish(job, result)

    # lanes (CP8.10)

    def prepare(self, job: Job) -> None:
        job.stage = LANE_STAGES[PREPARE][0]
        if self.disk_blocked is not None:  # Q2: W9 threshold again right before a download
            message = self.disk_blocked()
            if message:
                raise JobFailed(message)
        result = self._run(job, LANE_STAGES[PREPARE], preflight=False, episode_id=self.episode_id)
        self._resolved = result.episode_id or self._resolved

    def needs_download(self) -> bool:
        """Y2: would this job's ingest go to YouTube (False: the source is already there / not a YouTube URL)?"""
        return needs_download(self.url, self.config, self.episode_id)

    def prepare_only_step(self, job: Job) -> None:
        """CP13.2 H1 "Chuẩn bị + HD": ingest → transcript → analysis (+ the enhance decision after ingest), then the job
        ends ``done`` with the marker :mod:`prepared`: no AI, no render, no khai thị."""
        self.prepare(job)
        prepared.mark(self.config, self._later_id(job))
        job.stage = None
        job.summary = "Đã chuẩn bị — chờ cắt"

    def _later_id(self, job: Job) -> str:
        return self._resolved or job.episode_id

    def ai(self, job: Job) -> None:
        # a run after waiting for the GPU repeats the lane: forget the stages the interrupted run reported
        job.stages[:] = [st for st in job.stages if st["stage"] not in LANE_STAGES[AI]]
        prepared.clear(self.config, self._later_id(job))  # CP13.2: "Chạy tiếp" took the episode out of "chờ cắt"
        try:
            self._run(job, LANE_STAGES[AI], preflight=True, episode_id=self._later_id(job))
        except StageFailed as exc:  # O5: a stage failed - was it Ollama going away, or a real error?
            if self.preflight is not None:
                try:
                    run_preflight(job, self.preflight, self.config)
                except OllamaUnavailable as pre:
                    raise GpuUnavailable(f"{exc} (ollama preflight: {pre})") from exc
                except PreflightError:
                    pass
            raise

    def render(self, job: Job) -> None:
        self._finish(job, self._run(job, LANE_STAGES[RENDER], preflight=False, episode_id=self._later_id(job)))

    def hd_hold(self, job: Job) -> bool:
        """CP13.1b E6: the runner asks after the ``ai`` lane whether the render must wait for the HD source ("đợi HD")."""
        return self.enhance is not None and bool(self.enhance.hold(self._later_id(job)))

    def lane_steps(self) -> list[Step]:
        if self.prepare_only:
            return [Step(PREPARE, self.prepare_only_step)]
        return [Step(PREPARE, self.prepare), Step(AI, self.ai), Step(RENDER, self.render)]

    def spec(self) -> dict:
        """CP8.22: what a restart needs to recreate this target."""
        out = {"url": self.url, "series": self.series, "episode": self.episode, "episode_id": self.episode_id}
        if self.prepare_only:
            out["prepare_only"] = True
        return out


def pipeline_target(url: str, config: Config, *, series: str | None = None, episode: str | None = None,
                    pipeline: Callable = run_pipeline,
                    preflight: Callable[[Config], None] | None = ollama_preflight,
                    episode_id: str | None = None,
                    disk_blocked: Callable[[], str | None] | None = None, enhance=None,
                    prepare_only: bool = False) -> PipelineTarget:
    """See :class:`PipelineTarget`."""
    return PipelineTarget(url, config, series=series, episode=episode, pipeline=pipeline, preflight=preflight,
                          episode_id=episode_id, disk_blocked=disk_blocked, enhance=enhance,
                          prepare_only=prepare_only)


# --- render job (W4 title edit) ------------------------------------------------------------------------

def render_target(config: Config, *, render: Callable = run_render) -> Callable[[Job], None]:
    """Job target re-running the render stage after a title change: CP8.2 T5 re-encodes only the Shorts whose
    render_key changed and reuses the others."""

    def target(job: Job) -> None:
        job.stage = "render"
        t0 = time.monotonic()
        try:
            result = render(job.episode_id, config)
        except RenderError as exc:
            raise JobFailed(f"render: {exc}") from exc
        job.stages.append({"stage": "render", "ran": bool(result.ran), "seconds": round(time.monotonic() - t0, 3)})
        job.stage = None
        if result.ran:
            job.summary = f"{result.rendered}/{result.clips} Shorts ({result.encoded} encoded, {result.reused} reused)"
        else:
            job.summary = "render up to date (nothing to encode)"

    target.spec = lambda: {}  # type: ignore[attr-defined]  # CP8.22: nothing but the episode id is needed
    return target


# --- add-Short job (CP9 C6, C7) ------------------------------------------------------------------------------

class AddShortTarget:
    """Job target after a Short was added to ``review.json`` (C1): lane ``ai`` = Ollama preflight + the AI title
    of that one Short (C6), lane ``render`` = render (every other Short reused, CP8.2 T5). When the AI gives no
    title (preflight / connection / no valid option) the Short stays ``untitled``; the render still runs so it
    shows up (skipped, waiting for a manual title) and the job ends ``failed`` with the AI error, if any.
    Called directly (``queue_mode = "serial"``): both steps."""

    def __init__(self, config: Config, clip_id: str, *, render: Callable = run_render,
                 preflight: Callable[[Config], None] | None = ollama_preflight, titler: Callable | None = None):
        self.config, self.clip_id, self.render_fn, self.preflight = config, clip_id, render, preflight
        self.titler = titler
        self.title_error: str | None = None
        self.title: str | None = None

    def ai(self, job: Job) -> None:
        if self.titler is None:
            from ..titling.added import title_added
            titler = title_added
        else:
            titler = self.titler
        try:
            if self.preflight is not None:
                job.stage = "preflight"
                run_preflight(job, self.preflight, self.config)
            job.stage = "titling"
            t0 = time.monotonic()
            result = titler(job.episode_id, self.config, self.clip_id)
            job.stages.append({"stage": "titling", "ran": True, "seconds": round(time.monotonic() - t0, 3)})
            self.title = result.title
            if result.error:
                self.title_error = f"titling {self.clip_id}: {result.error}"
            elif result.title is None:
                self.title_error = f"titling {self.clip_id}: AI không đưa ra tiêu đề hợp lệ"
        except PreflightError as exc:
            self.title_error = f"ollama preflight: {exc}"
        job.stage = "render"

    def render(self, job: Job) -> None:
        render_target(self.config, render=self.render_fn)(job)
        if self.title_error:
            raise JobFailed(f"{self.title_error} — Short {self.clip_id} đã thêm nhưng chưa có tiêu đề: gõ tiêu đề tay")
        job.summary = f"{self.clip_id}: {self.title!r}; {job.summary}"

    def __call__(self, job: Job) -> None:
        self.ai(job)
        self.render(job)

    def lane_steps(self) -> list[Step]:
        return [Step(AI, self.ai), Step(RENDER, self.render)]

    def spec(self) -> dict:
        return {"clip_id": self.clip_id}


def add_short_target(config: Config, clip_id: str, *, render: Callable = run_render,
                     preflight: Callable[[Config], None] | None = ollama_preflight,
                     titler: Callable | None = None) -> AddShortTarget:
    """See :class:`AddShortTarget`."""
    return AddShortTarget(config, clip_id, render=render, preflight=preflight, titler=titler)


# --- post-compose job (CP8.15 P1) -----------------------------------------------------------------------------

class PostComposeTarget:
    """Job target composing (or recomposing) the community post text of one or more Shorts of an episode: lane
    ``ai`` (Ollama preflight, like W4, but only the ``[post]`` model), no render afterwards (``posts.json`` is user
    state, CP8.15 P7). Called directly (``queue_mode = "serial"``): the one step."""

    def __init__(self, config: Config, clips: "list[str] | str", *, compose: Callable | None = None,
                 preflight: Callable[[Config], None] | None = post_stage.preflight, lock: object | None = None):
        self.config, self.clips = config, clips
        self.compose = compose or post_stage.compose_posts
        self.preflight = preflight
        self.lock = lock
        self.result: post_stage.ComposeSummary | None = None
        self._compose_kw = compose
        self.pending: "list[str] | str" = []  # requests that arrived while running (R3), for the follow-up pass

    def merge(self, clips: "list[str] | str") -> None:
        """R3: a request that arrived while the job still waits joins it (the set is resolved when it starts)."""
        self.clips = post_stage.merge_clips(self.clips, clips)

    def merge_pending(self, clips: "list[str] | str") -> None:
        self.pending = post_stage.merge_clips(self.pending, clips)

    def followup(self) -> "PostComposeTarget":
        """R3: the extra pass queued when a request arrived while this job ran: ``auto`` plus the explicit clips /
        ``"all"`` asked meanwhile."""
        return PostComposeTarget(self.config, post_stage.merge_clips("auto", self.pending), compose=self._compose_kw,
                                 preflight=self.preflight, lock=self.lock)

    def run(self, job: Job) -> None:
        try:
            def before_ai() -> None:  # F1: Ollama is only needed from the first Short that takes the AI path
                if self.preflight is not None:
                    job.stage = "preflight"
                    run_preflight(job, self.preflight, self.config)
                job.stage = "post"

            job.stage = "post"
            self.result = self.compose(job.episode_id, self.config, self.clips, lock=self.lock, before_ai=before_ai)
        except OllamaUnavailable as exc:
            raise GpuUnavailable(f"ollama preflight: {exc}") from exc
        except PreflightError as exc:
            raise JobFailed(f"ollama preflight: {exc}") from exc
        except ChatUnavailable as exc:  # O2 / O5: Ollama went away mid-compose (nothing written for that Short)
            if self.preflight is not None:
                try:
                    run_preflight(job, self.preflight, self.config)
                except OllamaUnavailable as pre:
                    raise GpuUnavailable(f"{exc} (ollama preflight: {pre})") from exc
                except PreflightError:
                    pass
            raise JobFailed(f"post: {exc}") from exc
        except post_stage.PostComposeError as exc:
            raise JobFailed(str(exc)) from exc
        job.stage = None
        st = self.result
        job.summary = f"{len(st.clip_ids)} Short: {st.ai} AI, {st.raw} raw" + \
            (f", {st.doc} văn bản gốc" if getattr(st, "doc", 0) else "") + \
            (f", {len(st.errors)} lỗi text nguồn" if st.errors else "")

    def __call__(self, job: Job) -> None:
        self.run(job)

    def lane_steps(self) -> list[Step]:
        return [Step(AI, self.run)]

    def spec(self) -> dict:
        return {"clips": self.clips}


def post_compose_target(config: Config, clips: "list[str] | str", *, compose: Callable | None = None,
                        preflight: Callable[[Config], None] | None = post_stage.preflight,
                        lock: object | None = None) -> PostComposeTarget:
    """See :class:`PostComposeTarget`."""
    return PostComposeTarget(config, clips, compose=compose, preflight=preflight, lock=lock)


# --- image search job (CP8.15 P5b) ----------------------------------------------------------------------------

class ImageSearchTarget:
    """Job target finding images from a link (P5b): lane ``prepare`` (no Ollama). Runs under the pseudo episode id
    :data:`POST_IMAGES_KEY` (the job runner keys "one active job" by episode; image search is not tied to one).
    Called directly (``queue_mode = "serial"``): the one step."""

    def __init__(self, config: Config, url: str, *, search: Callable | None = None):
        self.config, self.url = config, url
        self.search = search or post_fetch.search_images
        self.result: post_fetch.SearchResult | None = None

    def run(self, job: Job) -> None:
        cfg = self.config.post
        try:
            self.result = self.search(self.url, cfg.image_dir, cfg.image_dir / "sources.tsv")
        except post_fetch.FetchError as exc:
            raise JobFailed(str(exc)) from exc
        job.summary = f"+{len(self.result.added)} ảnh" + (f", {len(self.result.duplicate)} trùng"
                                                           if self.result.duplicate else "")

    def __call__(self, job: Job) -> None:
        self.run(job)

    def lane_steps(self) -> list[Step]:
        return [Step(PREPARE, self.run)]

    def spec(self) -> dict:
        return {"url": self.url}


def image_search_target(config: Config, url: str, *, search: Callable | None = None) -> ImageSearchTarget:
    """See :class:`ImageSearchTarget`."""
    return ImageSearchTarget(config, url, search=search)


# --- HD assembly job (CP13.1b E3) ----------------------------------------------------------------------------------

class EnhanceAssembleTarget:
    """Job target assembling the received segments of a video into ``source_hd.mp4`` (lane ``render``: CPU-light stream
    copy), then calling ``after(episode_id)`` (the web app: unpark the waiting jobs / re-render, E6). Runs under
    :func:`enhance_key`, so it never collides with the episode's own (possibly parked) job."""

    def __init__(self, service, after: Callable[[str], None] | None = None):
        self.service, self.after_hd = service, after

    def run(self, job: Job) -> None:
        from ..enhance.state import EnhanceError
        job.stage = "enhance"
        t0 = time.monotonic()
        try:
            doc = self.service.assemble(job.episode_id)
        except EnhanceError as exc:
            raise JobFailed(f"enhance: {exc}") from exc
        job.stages.append({"stage": "enhance", "ran": True, "seconds": round(time.monotonic() - t0, 3)})
        job.stage = None
        job.summary = f"HD {doc.get('frames')} khung" + (f" ({', '.join(doc.get('workers') or [])})"
                                                          if doc.get("workers") else "")
        if self.after_hd is not None:
            self.after_hd(job.episode_id)

    def __call__(self, job: Job) -> None:
        self.run(job)

    def lane_steps(self) -> list[Step]:
        return [Step(RENDER, self.run)]

    def spec(self) -> dict:
        return {}


def enhance_assemble_target(service, after: Callable[[str], None] | None = None) -> EnhanceAssembleTarget:
    """See :class:`EnhanceAssembleTarget`."""
    return EnhanceAssembleTarget(service, after)
