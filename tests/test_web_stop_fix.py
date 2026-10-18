"""FIX-runner-stop (docs/tasks/FIX-runner-stop.md AC1-AC4): stopping the runner starts nothing new, leaves no child
process (children, grandchildren, processes started after the interrupt), never leaks the runner lock and never hangs.
Real child processes; steps that must be interruptible poll with ``time.sleep``."""

import json
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from auto_short.web import jobs as jobs_mod
from auto_short.web.jobs import (INTERRUPTED, KIND_RENDER, PREPARE, QUEUED, RENDER, JobFailed, JobRunner, Step,
                                 _interrupt)

TIMEOUT = 4.0
BOUND = TIMEOUT + 5.0


def wait_for(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


def gone(pid: int) -> bool:
    """No such process, or only a zombie waiting to be reaped."""
    try:
        stat = open(f"/proc/{pid}/stat").read()
    except OSError:
        return True
    return stat[stat.rindex(")") + 2] in "ZX"


# a child that ignores SIGINT and SIGTERM-free sleeps, plus a grandchild (its own sleep) it never waits for
STUBBORN = ("import signal, subprocess, sys, time\n"
            "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "g = subprocess.Popen(['sleep', '120'])\n"
            "open(sys.argv[1], 'w').write(str(g.pid))\n"
            "time.sleep(120)\n")


class Blocker:
    """A render step that polls until interrupted; ``ran`` records that it started."""

    def __init__(self, body=None):
        self.ran = threading.Event()
        self.body = body

    def __call__(self, job):
        self.ran.set()
        if self.body is not None:
            self.body(job)
        while True:
            time.sleep(0.005)


@pytest.fixture
def runner():
    r = JobRunner()
    yield r
    r.stop(timeout=2)


def test_ac1_nothing_starts_after_stop_began(runner):
    first, second = Blocker(), Blocker()
    runner.start()
    a, _ = runner.submit("ep-a", KIND_RENDER, first)
    b, _ = runner.submit("ep-b", KIND_RENDER, second)
    wait_for(first.ran.is_set)
    logs: list[str] = []
    handler = type("H", (jobs_mod.logging.Handler,), {"emit": lambda self, rec: logs.append(rec.getMessage())})()
    jobs_mod.log.addHandler(handler)
    try:
        runner.stop(timeout=TIMEOUT)
    finally:
        jobs_mod.log.removeHandler(handler)
    assert not second.ran.is_set()
    assert b.status == QUEUED
    assert a.status == INTERRUPTED
    assert not [m for m in logs if m.startswith("web: start ")]


def test_ac1_begin_stop_job_ending_by_itself_does_not_let_the_lane_take_the_next(runner):
    """The terminal's Ctrl-C kills ffmpeg before stop(): the job fails, then begin_stop() must already forbid the next."""
    release = threading.Event()
    second = Blocker()

    def failing(job):
        release.wait(5)
        raise JobFailed("ffmpeg failed: exit 255")

    runner.start()
    a, _ = runner.submit("ep-a", KIND_RENDER, failing)
    b, _ = runner.submit("ep-b", KIND_RENDER, second)
    wait_for(lambda: a.status == "running")
    runner.begin_stop()
    release.set()
    wait_for(lambda: a.status != "running")
    time.sleep(0.2)
    assert a.status == INTERRUPTED and a.resume == (RENDER, 0)  # cut by the stop, comes back at the next start
    assert not second.ran.is_set() and b.status == QUEUED
    runner.stop(timeout=TIMEOUT)


def test_ac1_next_step_of_a_multi_step_job_does_not_start(runner):
    ran: list[str] = []

    class Two:
        def lane_steps(self):
            def one(job):
                runner.begin_stop()
                ran.append("one")

            return [Step(PREPARE, one), Step(RENDER, lambda job: ran.append("two"))]

    runner.start()
    job, _ = runner.submit("ep", KIND_RENDER, Two())
    wait_for(lambda: ran == ["one"])
    time.sleep(0.2)
    runner.stop(timeout=TIMEOUT)
    assert ran == ["one"]
    assert job.status == INTERRUPTED


def test_ac2_no_child_survives_stop(runner, tmp_path):
    pids: dict[str, int] = {}
    gpid_file = tmp_path / "grandchild.pid"

    def spawn(job):
        pids["sleep"] = subprocess.Popen(["sleep", "120"]).pid
        stubborn = subprocess.Popen([sys.executable, "-c", STUBBORN, str(gpid_file)])
        pids["stubborn"] = stubborn.pid
        wait_for(gpid_file.exists)
        pids["grandchild"] = int(gpid_file.read_text())
        pids["ready"] = 1

    runner.start()
    runner.submit("ep", KIND_RENDER, Blocker(spawn))
    wait_for(lambda: "ready" in pids)
    t0 = time.monotonic()
    runner.stop(timeout=TIMEOUT)
    assert time.monotonic() - t0 < BOUND
    for name in ("sleep", "stubborn", "grandchild"):
        assert gone(pids[name]), name


def test_ac2_orphaned_grandchild_and_children_started_after_the_interrupt(runner, tmp_path):
    """The job swallows the interrupt and keeps starting processes; the stubborn child dies leaving its child orphaned."""
    seen: list[int] = []
    orphan_file = tmp_path / "orphan.pid"
    parent = ("import subprocess, sys\n"
              "g = subprocess.Popen(['sleep', '120'])\n"
              "open(sys.argv[1], 'w').write(str(g.pid))\n")  # exits at once: the sleep is re-parented

    def stubborn_job(job):
        subprocess.run([sys.executable, "-c", parent, str(orphan_file)], check=True)
        seen.append(int(orphan_file.read_text()))
        swallowed = 0
        while True:
            try:
                seen.append(subprocess.Popen(["sleep", "120"]).pid)
                time.sleep(0.3)
            except KeyboardInterrupt:  # a job that ignores the stop (the first two times)
                swallowed += 1
                if swallowed > 2:
                    raise

    runner.start()
    runner.submit("ep", KIND_RENDER, stubborn_job)
    wait_for(lambda: len(seen) >= 2)
    t0 = time.monotonic()
    runner.stop(timeout=TIMEOUT)
    assert time.monotonic() - t0 < BOUND
    time.sleep(0.2)
    assert all(gone(pid) for pid in seen), [p for p in seen if not gone(p)]
    assert jobs_mod._descendants() == []


def test_ac3_interrupts_around_the_runner_lock_never_leak_it():
    """Async KeyboardInterrupts hammering a thread that enters / leaves ``with runner._lock`` must leave it free.
    (Plain flags, not ``threading.Event``: its own ``with`` on a Condition would leak under the same hammering.)"""
    runner = JobRunner()
    flags = {"stop": False, "entered": False}

    def spin():
        while not flags["stop"]:
            try:
                flags["entered"] = True
                for _ in range(200):
                    with runner._lock:
                        pass
                    with runner._lock:
                        runner._lock.notify_all()
            except KeyboardInterrupt:
                continue

    def outer():  # an interrupt may also land in spin's own handler: absorb it, so pytest sees no thread exception
        while True:
            try:
                spin()
                return
            except KeyboardInterrupt:
                continue

    def outermost():
        while True:
            try:
                outer()
                return
            except KeyboardInterrupt:
                continue

    thread = threading.Thread(target=outermost, daemon=True)
    thread.start()
    wait_for(lambda: flags["entered"])
    for i in range(1500):
        _interrupt(thread.ident)
        if i % 10 == 0:
            time.sleep(0.0005)
    time.sleep(0.1)  # the last interrupts are delivered
    flags["stop"] = True
    thread.join(5)
    assert not thread.is_alive()
    assert runner._lock.acquire(timeout=2), "runner lock leaked by an interrupted thread"
    runner._lock.release()


def test_ac3_wait_cut_by_an_interrupt_still_owns_the_lock_for_its_with():
    runner = JobRunner()
    result = {}

    def waiter():
        try:
            with runner._lock:
                runner._lock.wait(5)
        except KeyboardInterrupt:
            result["interrupted"] = True

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.2)
    _interrupt(thread.ident)
    thread.join(5)
    assert result == {"interrupted": True} and not thread.is_alive()
    assert runner._lock.acquire(timeout=2)
    runner._lock.release()


def test_ac3_stop_with_a_job_hammering_the_lock_returns_in_time():
    runner = JobRunner()
    started = threading.Event()

    def hammer(job):
        started.set()
        while True:
            with runner._lock:
                runner._lock.notify_all()
            runner.latest("x")

    runner.start()
    runner.submit("ep", KIND_RENDER, hammer)
    assert started.wait(5)
    t0 = time.monotonic()
    runner.stop(timeout=TIMEOUT)
    assert time.monotonic() - t0 < BOUND
    assert runner._lock.acquire(timeout=2)
    runner._lock.release()


def test_ac4_interrupted_job_is_saved_and_restored(tmp_path):
    state = tmp_path / "queue.json"
    runner = JobRunner()
    targets = {}

    class Spec(Blocker):
        def lane_steps(self):
            return [Step(RENDER, self)]

        def spec(self):
            return {"x": 1}

    def rebuild(kind, episode_id, spec, clip_ids):
        targets[episode_id] = Spec()
        return targets[episode_id]

    runner.configure_persistence(state, rebuild)
    runner.start()
    target = Spec()
    runner.submit("ep", KIND_RENDER, target)
    wait_for(target.ran.is_set)
    runner.stop(timeout=TIMEOUT)
    saved = json.loads(state.read_text())
    assert [e["episode_id"] for e in saved["lanes"][RENDER]] == ["ep"]
    again = JobRunner()
    again.configure_persistence(state, rebuild)
    assert again.restore() == 1
    again.start()
    wait_for(lambda: "ep" in targets and targets["ep"].ran.is_set())
    again.stop(timeout=TIMEOUT)
