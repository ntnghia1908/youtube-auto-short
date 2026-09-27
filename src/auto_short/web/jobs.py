"""W5: in-memory FIFO job queue with one worker thread; per-job log ring buffer (stdlib only).

One job runs at a time (pipeline now; per-Short render jobs later), so the CPU/GPU is not shared and no two
jobs write the same manifest. A second job for an episode that already has a queued/running job is refused.
The queue lives in memory: a server restart forgets it (manifests stay; resubmitting resumes, CP8 E3).
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
from ..pipeline import PIPELINE_STAGES, PreflightError, StageRun, ollama_preflight, run_pipeline
from ..render import RenderError, run_render

log = logging.getLogger("auto_short")

QUEUED, RUNNING, DONE, FAILED, INTERRUPTED = "queued", "running", "done", "failed", "interrupted"
ACTIVE = (QUEUED, RUNNING)
LOG_LINES = 200
KIND_PIPELINE = "pipeline"
KIND_RENDER = "render"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobFailed(Exception):
    """Raised by a job target to finish the job as ``failed`` with this message."""


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
    stage: str | None = None  # stage currently running (set by the target)
    stages: list[dict] = field(default_factory=list)  # finished stages: {stage, ran, seconds}
    error: str | None = None
    summary: str | None = None
    clip_ids: list[str] = field(default_factory=list)  # render job: Shorts whose title was just changed
    logs: deque = field(default_factory=lambda: deque(maxlen=LOG_LINES), repr=False)

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    def to_dict(self, *, logs: bool = True) -> dict:
        out = {
            "id": self.id, "episode_id": self.episode_id, "kind": self.kind, "status": self.status,
            "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at,
            "stage": self.stage, "stages": list(self.stages), "error": self.error, "summary": self.summary,
            "clip_ids": list(self.clip_ids),
        }
        if logs:
            out["logs"] = list(self.logs)
        return out


class _JobLogHandler(logging.Handler):
    """Copies ``auto_short`` log records emitted on the worker thread into the running job's ring buffer."""

    def __init__(self, runner: "JobRunner"):
        super().__init__(logging.INFO)
        self._runner = runner

    def emit(self, record: logging.LogRecord) -> None:
        job = self._runner.current
        if job is None or record.thread != self._runner.worker_ident:
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


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.Condition()
        self._queue: deque[Job] = deque()
        self._jobs: dict[str, Job] = {}
        self._latest: dict[str, Job] = {}  # episode_id -> newest job
        self._ids = itertools.count(1)
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._handler = _JobLogHandler(self)
        self.current: Job | None = None
        self.worker_ident: int | None = None

    # --- lifecycle -----------------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        if log.level == logging.NOTSET:
            log.setLevel(logging.INFO)
        log.addHandler(self._handler)
        self._thread = threading.Thread(target=self._work, name="auto-short-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        """Stop the worker. A running job gets KeyboardInterrupt (the stage records ``failed`` /
        ``interrupted``, CP2) and its child processes SIGINT; waits up to ``timeout`` seconds. A stage blocked
        in a long call that ignores the interrupt keeps ``running`` in the manifest and resumes on resubmit."""
        with self._lock:
            self._stopping = True
            self._lock.notify_all()
            running = self.current
        thread = self._thread
        if thread is not None and running is not None and thread.ident is not None:
            log.info("web: stopping, interrupting job %s [%s]", running.id, running.episode_id)
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread.ident),
                                                       ctypes.py_object(KeyboardInterrupt))
            for pid in _child_pids():
                try:
                    os.kill(pid, signal.SIGINT)
                except OSError:
                    pass
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                log.warning("web: job still running after %.0f s; exiting anyway", timeout)
        log.removeHandler(self._handler)
        self._thread = None

    # --- queue ---------------------------------------------------------------------------------

    def submit(self, episode_id: str, kind: str, target: Callable[[Job], None], *,
               clip_ids: list[str] | None = None) -> tuple[Job, bool]:
        """Queue a job; returns ``(job, True)``, or ``(existing active job, False)`` for a duplicate."""
        with self._lock:
            latest = self._latest.get(episode_id)
            if latest is not None and latest.active:
                return latest, False
            job = Job(id=str(next(self._ids)), episode_id=episode_id, kind=kind, target=target,
                      clip_ids=list(clip_ids or []))
            self._jobs[job.id] = job
            self._latest[episode_id] = job
            self._queue.append(job)
            self._lock.notify_all()
        log.info("web: queued %s job %s [%s]", kind, job.id, episode_id)
        return job, True

    def latest(self, episode_id: str) -> Job | None:
        with self._lock:
            return self._latest.get(episode_id)

    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def queue_position(self, job: Job) -> int | None:
        """1-based position among queued jobs, None when not queued."""
        with self._lock:
            for i, j in enumerate(self._queue, 1):
                if j is job:
                    return i
        return None

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """Test helper: wait until no job is queued or running."""
        deadline = time.monotonic() + timeout
        with self._lock:
            while self._queue or self.current is not None:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._lock.wait(left)
        return True

    # --- worker --------------------------------------------------------------------------------

    def _work(self) -> None:
        self.worker_ident = threading.get_ident()
        try:
            self._loop()
        except KeyboardInterrupt:  # stop() raced with the end of a job
            pass

    def _loop(self) -> None:
        while True:
            with self._lock:
                while not self._queue and not self._stopping:
                    self._lock.wait()
                if self._stopping:
                    return
                job = self._queue.popleft()
                job.status, job.started_at = RUNNING, _now()
                self.current = job
            t0 = time.monotonic()
            try:
                log.info("web: start %s job %s [%s]", job.kind, job.id, job.episode_id)
                job.target(job)
                job.status = DONE
                log.info("web: job %s done in %.1f s [%s]%s", job.id, time.monotonic() - t0, job.episode_id,
                         f": {job.summary}" if job.summary else "")
            except KeyboardInterrupt:
                job.status, job.error = INTERRUPTED, f"interrupted during {job.stage or 'start'}"
                log.info("web: job %s interrupted [%s]", job.id, job.episode_id)
            except JobFailed as exc:
                job.status, job.error = FAILED, str(exc)
                log.error("web: job %s failed [%s]: %s", job.id, job.episode_id, exc)
            except Exception as exc:  # a bug must not kill the worker
                job.status, job.error = FAILED, f"{type(exc).__name__}: {exc}"
                log.exception("web: job %s crashed [%s]", job.id, job.episode_id)
            finally:
                job.finished_at = _now()
                with self._lock:
                    self.current = None
                    self._lock.notify_all()


# --- pipeline job (W4) ---------------------------------------------------------------------------

def pipeline_target(url: str, config: Config, *, series: str | None = None, episode: str | None = None,
                    pipeline: Callable = run_pipeline,
                    preflight: Callable[[Config], None] | None = ollama_preflight) -> Callable[[Job], None]:
    """Job target running the CP8 pipeline on ``url`` (preflight again when the job starts, E8)."""

    def target(job: Job) -> None:
        def checked_preflight(cfg: Config) -> None:
            job.stage = "preflight"
            preflight(cfg)
            job.stage = PIPELINE_STAGES[0]

        def on_stage(run: StageRun) -> None:
            job.stages.append({"stage": run.stage, "ran": run.ran, "seconds": run.seconds})
            i = PIPELINE_STAGES.index(run.stage)
            job.stage = PIPELINE_STAGES[i + 1] if i + 1 < len(PIPELINE_STAGES) else None

        job.stage = PIPELINE_STAGES[0]
        try:
            result = pipeline(url, config, series=series, episode=episode,
                              preflight=checked_preflight if preflight is not None else None, on_stage=on_stage)
        except PreflightError as exc:
            raise JobFailed(f"ollama preflight: {exc}") from exc
        if not result.ok:
            job.stage = result.failed_stage
            raise JobFailed(f"{result.failed_stage}: {result.error}")
        job.stage = None
        job.summary = f"{result.rendered}/{result.clips} Shorts"
        render = result.stages[-1].result if result.stages else None
        if render is not None and render.ran and getattr(render, "encoded", None) is not None:
            job.summary += f" ({render.encoded} encoded, {render.reused} reused)"

    return target


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
