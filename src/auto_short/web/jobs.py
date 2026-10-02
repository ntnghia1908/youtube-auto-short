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
server restart forgets it (manifests stay; resubmitting resumes, CP8 E3). FIX-ollama-wait: when Ollama is
unreachable the ``ai`` lane does not fail jobs; it keeps them at the head of its queue and re-checks every
``GPU_RETRY_SECONDS`` (docs/tasks/FIX-ollama-wait.md O5). Contract: docs/decisions/CP8.3-web-contract.md W5.
"""

from __future__ import annotations

import ctypes
import itertools
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
from ..pipeline import (PIPELINE_STAGES, OllamaUnavailable, PipelineError, PreflightError, StageRun,
                        ollama_preflight, run_pipeline)
from ..post import fetch as post_fetch
from ..post import stage as post_stage
from ..render import RenderError, run_render
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
POST_IMAGES_KEY = "_post_images"  # CP8.15 P9: pseudo episode id for the (single, global) image search job
EPISODE_KINDS = (KIND_PIPELINE, KIND_RENDER, KIND_ADD)  # jobs of an episode that run the render step (CP8.16 R2a)


def post_key(episode_id: str) -> str:
    """CP8.16 R3: the runner key of the ``post`` job of an episode (separate from the episode's own job)."""
    return f"{episode_id}#post"

MODE_LANES, MODE_SERIAL = "lanes", "serial"
PREPARE, AI, RENDER = "prepare", "ai", "render"
LANES = (PREPARE, AI, RENDER)
LANE_STAGES: dict[str, tuple[str, ...]] = {
    PREPARE: ("ingest", "transcript", "analysis"), AI: ("selection", "titling"), RENDER: ("render",)}
PREFETCH_LIMIT = 2  # Q2: prepare starts no new job while this many prepared jobs wait for the ai lane
GPU_RETRY_SECONDS = 60.0  # FIX-ollama-wait O5: the ai lane re-checks Ollama this often while it is down
GPU_OK, GPU_DOWN = "ok", "down"
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
    _reachable: Callable[[], None] | None = field(default=None, repr=False)  # set by the runner (ai lane)
    again: bool = field(default=False, repr=False)  # post job: a new trigger arrived while running (R3)
    step: int = field(default=0, repr=False)  # index of the running / next step
    t0: float = field(default=0.0, repr=False)  # monotonic start

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    def reachable(self) -> None:
        """A target of the ``ai`` lane got an answer from Ollama (preflight passed / model missing)."""
        cb = self._reachable
        if cb is not None:
            cb()

    def to_dict(self, *, logs: bool = True) -> dict:
        out = {
            "id": self.id, "episode_id": self.episode_id, "kind": self.kind, "status": self.status,
            "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at,
            "stage": self.stage, "stages": list(self.stages), "error": self.error, "summary": self.summary,
            "clip_ids": list(self.clip_ids), "lane": self.lane, "waiting": self.waiting,
            "gpu_wait": self.gpu_wait,
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

    def __init__(self, mode: str = MODE_LANES, *, gpu_retry_seconds: float = GPU_RETRY_SECONDS) -> None:
        if mode not in (MODE_LANES, MODE_SERIAL):
            raise ValueError(f"unknown queue mode {mode!r}")
        self.mode = mode
        self._lane_names = LANES if mode == MODE_LANES else (_SERIAL,)
        self._lock = threading.Condition()
        self._queues: dict[str, deque[Job]] = {lane: deque() for lane in self._lane_names}
        self._current: dict[str, Job | None] = {lane: None for lane in self._lane_names}
        self._threads: dict[str, threading.Thread] = {}
        self._idents: dict[int, str] = {}  # worker thread ident -> lane
        self._jobs: dict[str, Job] = {}
        self._latest: dict[str, Job] = {}  # episode_id -> newest job
        self._ids = itertools.count(1)
        # CP8.16 R2a: called (on the lane worker thread) with an episode job (pipeline / render / add) that ended
        # ``done`` or ``failed``; set by the web app, which submits the ``post`` job.
        self.on_finished: Callable[[Job], None] | None = None
        self._stopping = False
        self._handler = _JobLogHandler(self)
        # FIX-ollama-wait O5: state of the ai lane's Ollama connection (under ``_lock``); "down" only after a job of
        # the lane hit OllamaUnavailable, back to "ok" as soon as a later check gets an answer.
        self.gpu_retry_seconds = gpu_retry_seconds
        self._gpu: dict = {"state": GPU_OK, "since": None, "error": None, "next_check": None}
        self._gpu_next = 0.0  # monotonic deadline of the next check while down

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
        resubmit. Jobs waiting between two lanes end ``interrupted``; queued jobs are forgotten with the process."""
        with self._lock:
            self._stopping = True
            self._lock.notify_all()
            running = [(lane, job) for lane, job in self._current.items() if job is not None]
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
                            else f"interrupted while waiting for {job.lane}"
                        job.finished_at, job.waiting, job.gpu_wait = _now(), False, False
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
        return [Step(RENDER if kind == KIND_RENDER else PREPARE, target)]

    def _enqueue_locked(self, episode_id: str, kind: str, target: Callable[[Job], None],
                        clip_ids: list[str] | None) -> Job:
        key = post_key(episode_id) if kind == KIND_POST else episode_id
        job = Job(id=str(next(self._ids)), episode_id=episode_id, kind=kind, target=target, key=key,
                  clip_ids=list(clip_ids or []), steps=self._steps(kind, target))
        self._jobs[job.id] = job
        self._latest[key] = job
        self._queues[job.steps[0].lane].append(job)
        self._sync_gpu_wait_locked()
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
        key = post_key(episode_id) if kind == KIND_POST else episode_id
        with self._lock:
            latest = self._latest.get(key)
            if latest is not None and latest.active:
                new = getattr(target, "clips", None)
                if latest.kind == KIND_POST and new is not None:
                    if latest.status == QUEUED or (latest.status == RUNNING and latest.waiting):
                        latest.target.merge(new)  # not started yet (or back in the queue waiting for the GPU)
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

    def job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def forget(self, episode_id: str) -> bool:
        """Drop the finished jobs of a deleted episode (CP8.5 X3) so it leaves every view; refused (False) while
        one of its jobs is queued/running."""
        with self._lock:
            for key in (episode_id, post_key(episode_id)):
                latest = self._latest.get(key)
                if latest is not None and latest.active:
                    return False
            self._latest.pop(episode_id, None)
            self._latest.pop(post_key(episode_id), None)
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
                for i, j in enumerate(queue, 1):
                    if j is job:
                        return i
        return None

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

    def _gpu_down(self) -> bool:
        return self._gpu["state"] == GPU_DOWN

    def _sync_gpu_wait_locked(self) -> None:
        down = self._gpu_down()
        for j in self._queues.get(AI, ()):
            j.gpu_wait = down

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
            if lane == AI and queue and self._gpu_down():
                add = next((j for j in queue if j.kind == KIND_ADD), None)
                if add is not None:
                    queue.remove(add)
                    return add
                left = self._gpu_next - time.monotonic()
                if left > 0:
                    self._lock.wait(left)
                    continue
                return queue.popleft()
            if self._can_start(lane):
                return queue.popleft()
            self._lock.wait()
        return None

    def _work(self, lane: str) -> None:
        self._idents[threading.get_ident()] = lane
        try:
            self._loop(lane)
        except KeyboardInterrupt:  # stop() raced with the end of a job
            pass

    def _loop(self, lane: str) -> None:
        while True:
            with self._lock:
                job = self._take_locked(lane)
                if job is None:
                    return
                first = job.status == QUEUED
                if first:
                    job.status, job.started_at, job.t0 = RUNNING, _now(), time.monotonic()
                job.lane = None if lane == _SERIAL else lane
                job.waiting, job.gpu_wait = False, False
                job._reachable = self._gpu_reachable if lane == AI else None
                self._current[lane] = job
                self._lock.notify_all()  # a shorter ai queue may let the prepare lane start (Q2)
            ok = False
            requeue: str | None = None
            try:
                if first:
                    log.info("web: start %s job %s [%s]", job.kind, job.id, job.episode_id)
                else:
                    log.info("web: job %s continues in lane %s [%s]", job.id, lane, job.episode_id)
                job.steps[job.step].run(job)
                ok = True
            except KeyboardInterrupt:
                job.status, job.error = INTERRUPTED, f"interrupted during {job.stage or 'start'}"
                log.info("web: job %s interrupted [%s]", job.id, job.episode_id)
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
                if requeue is not None:
                    self._requeue(lane, job, requeue)
                else:
                    self._after(lane, job, ok)

    def _requeue(self, lane: str, job: Job, error: str) -> None:
        with self._lock:
            self._current[lane] = None
            job.lane, job.waiting, job._reachable = lane, True, None
            if job.kind == KIND_PIPELINE:
                job.stage = LANE_STAGES[lane][0]
            self._queues[lane].appendleft(job)
            self._set_gpu_down_locked(error)
            self._lock.notify_all()

    def _after(self, lane: str, job: Job, ok: bool) -> None:
        last = not ok or job.step + 1 >= len(job.steps)
        job._reachable = None
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
            if last:
                job.finished_at, job.lane, job.waiting = _now(), None, False
                if job.again and job.kind == KIND_POST and job.status != INTERRUPTED and not self._stopping:
                    follow = getattr(job.target, "followup", None)
                    follow = follow() if follow is not None else None
                    if follow is not None:  # R3: one more pass for the trigger that arrived meanwhile
                        self._enqueue_locked(job.episode_id, KIND_POST, follow, None)
            else:  # tail of the next lane's queue
                job.step += 1
                nxt = job.steps[job.step].lane
                job.lane, job.waiting = nxt, True
                job.stage = LANE_STAGES[nxt][0]
                self._queues[nxt].append(job)
                self._sync_gpu_wait_locked()
            self._lock.notify_all()


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
                 episode_id: str | None = None, disk_blocked: Callable[[], str | None] | None = None):
        self.url, self.config, self.series, self.episode = url, config, series, episode
        self.pipeline, self.preflight, self.episode_id = pipeline, preflight, episode_id
        self.disk_blocked = disk_blocked
        self._resolved: str | None = episode_id  # episode id for the ai / render lanes

    def _run(self, job: Job, stages: tuple[str, ...] | None, *, preflight: bool, episode_id: str | None):
        def checked_preflight(cfg: Config) -> None:
            job.stage = "preflight"
            run_preflight(job, self.preflight, cfg)
            job.stage = (stages or PIPELINE_STAGES)[0]

        def on_stage(run: StageRun) -> None:
            job.stages.append({"stage": run.stage, "ran": run.ran, "seconds": run.seconds})
            i = PIPELINE_STAGES.index(run.stage)
            job.stage = PIPELINE_STAGES[i + 1] if i + 1 < len(PIPELINE_STAGES) else None

        job.stage = (stages or PIPELINE_STAGES)[0]
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
        self._finish(job, self._run(job, None, preflight=True, episode_id=self.episode_id))

    # lanes (CP8.10)

    def prepare(self, job: Job) -> None:
        job.stage = LANE_STAGES[PREPARE][0]
        if self.disk_blocked is not None:  # Q2: W9 threshold again right before a download
            message = self.disk_blocked()
            if message:
                raise JobFailed(message)
        result = self._run(job, LANE_STAGES[PREPARE], preflight=False, episode_id=self.episode_id)
        self._resolved = result.episode_id or self._resolved

    def _later_id(self, job: Job) -> str:
        return self._resolved or job.episode_id

    def ai(self, job: Job) -> None:
        # a run after waiting for the GPU repeats the lane: forget the stages the interrupted run reported
        job.stages[:] = [st for st in job.stages if st["stage"] not in LANE_STAGES[AI]]
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

    def lane_steps(self) -> list[Step]:
        return [Step(PREPARE, self.prepare), Step(AI, self.ai), Step(RENDER, self.render)]


def pipeline_target(url: str, config: Config, *, series: str | None = None, episode: str | None = None,
                    pipeline: Callable = run_pipeline,
                    preflight: Callable[[Config], None] | None = ollama_preflight,
                    episode_id: str | None = None,
                    disk_blocked: Callable[[], str | None] | None = None) -> PipelineTarget:
    """See :class:`PipelineTarget`."""
    return PipelineTarget(url, config, series=series, episode=episode, pipeline=pipeline, preflight=preflight,
                          episode_id=episode_id, disk_blocked=disk_blocked)


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
            if self.preflight is not None:
                job.stage = "preflight"
                run_preflight(job, self.preflight, self.config)
            job.stage = "post"
            self.result = self.compose(job.episode_id, self.config, self.clips, lock=self.lock)
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


def image_search_target(config: Config, url: str, *, search: Callable | None = None) -> ImageSearchTarget:
    """See :class:`ImageSearchTarget`."""
    return ImageSearchTarget(config, url, search=search)
