"""CP8.29 prepare lane with several workers (docs/tasks/CP8.29-parallel-prepare.md AC1-AC3, AC5, Amendment 1).
Fake steps held by events; the only timing is a short settle before a negative assertion."""

import os
import subprocess
import threading
import time
from dataclasses import replace

import pytest

from auto_short.config import Config, ConfigError, WebConfig, WhisperConfig, from_dict, whisper_threads_per_job
from auto_short.web import jobs as jobs_mod
from auto_short.web.jobs import KIND_PIPELINE, PREPARE, JobRunner, Step, YoutubeWait


def wait_for(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


class Gate:
    """One prepare step that records its start and waits for its own gate."""

    def __init__(self, name, log, *, download=False, raises=None):
        self.name, self.log, self.download, self.raises = name, log, download, raises
        self.gate = threading.Event()
        self.nice = None

    def needs_download(self):
        return self.download

    def lane_steps(self):
        return [Step(PREPARE, self.run)]

    def run(self, job):
        self.log.append(self.name)
        self.nice = os.getpriority(os.PRIO_PROCESS, threading.get_native_id())
        deadline = time.monotonic() + 10
        while not self.gate.wait(0.02):  # short waits: the "pause now" interrupt lands between them
            assert time.monotonic() < deadline
        if self.raises is not None:
            raise self.raises

    def __call__(self, job):
        self.run(job)


@pytest.fixture
def mk():
    made = []

    def factory(**kw):
        r = JobRunner(**kw)
        r.start()
        made.append(r)
        return r

    yield factory
    for r in made:
        r.stop(timeout=5)


def release(*gates):
    for g in gates:
        g.gate.set()


def test_three_workers_start_in_queue_order_and_never_more_than_three(mk):
    log = []
    gates = {n: Gate(n, log) for n in "abcdef"}
    r = mk(prepare_workers=3)
    for n in "abcdef":
        r.submit(n, KIND_PIPELINE, gates[n])
    wait_for(lambda: len(log) == 3)
    time.sleep(0.1)
    assert sorted(log) == ["a", "b", "c"] and len(r.running_slots()) == 3
    assert r.monitor_queue()["lanes"]["prepare"]["workers"] == 3
    gates["b"].gate.set()
    wait_for(lambda: len(log) == 4)
    assert log[3] == "d"
    release(*gates.values())
    assert r.wait_idle(10) and sorted(log) == list("abcdef")


def test_priority_order_applies_to_the_next_start(mk):
    log = []
    gates = {n: Gate(n, log) for n in "abcde"}
    r = mk(prepare_workers=2)
    for n in "abcde":
        r.submit(n, KIND_PIPELINE, gates[n])
    wait_for(lambda: len(log) == 2)
    r.priority.mark(["e"])
    gates["a"].gate.set()
    wait_for(lambda: len(log) == 3)
    assert log[2] == "e"
    release(*gates.values())
    assert r.wait_idle(10)


def test_one_worker_is_the_old_behaviour(mk):
    log = []
    gates = {n: Gate(n, log) for n in "ab"}
    r = mk()
    for n in "ab":
        r.submit(n, KIND_PIPELINE, gates[n])
    wait_for(lambda: log == ["a"])
    time.sleep(0.1)
    assert log == ["a"] and list(r.running_slots()) == [PREPARE]
    release(*gates.values())
    assert r.wait_idle(10)


def test_same_video_never_prepares_twice_at_once(mk):
    log = []
    gates = {n: Gate(n, log) for n in ("v", "v.kt", "w")}
    r = mk(prepare_workers=3)
    for n in ("v", "v.kt", "w"):
        r.submit(n, KIND_PIPELINE, gates[n])
    wait_for(lambda: len(log) == 2)
    time.sleep(0.1)
    assert log == ["v", "w"]  # the khai thị episode waits for the ingest of its base episode
    gates["v"].gate.set()
    wait_for(lambda: "v.kt" in log)
    release(*gates.values())
    assert r.wait_idle(10)


def test_pause_after_stops_new_starts_and_pause_now_requeues_every_running_job(mk):
    log = []
    gates = {n: Gate(n, log) for n in "abcd"}
    r = mk(prepare_workers=2)
    for n in "abcd":
        r.submit(n, KIND_PIPELINE, gates[n])
    wait_for(lambda: len(log) == 2)
    r.pause("after")
    gates["a"].gate.set()
    wait_for(lambda: len(r.running_slots()) == 1)
    time.sleep(0.1)
    assert log == ["a", "b"]
    r.pause("now")
    wait_for(lambda: not r.running_slots())
    state = r.queue_state()
    assert state["pending"] == 3 and state["running"] == 0  # b back at the head, c, d
    assert [e["episode_id"] for e in r.monitor_queue()["lanes"]["prepare"]["pending"]][0] == "b"
    r.resume()
    release(*gates.values())
    assert r.wait_idle(10)


def test_youtube_block_only_stops_download_jobs_and_one_try_counts_once(mk):
    class Clock:
        t = 1000.0

        def mono(self):
            return self.t

        def wall(self):
            return 1.7e9 + self.t

    clock = Clock()
    log = []
    d1 = Gate("d1", log, download=True, raises=YoutubeWait("blocked"))
    d2 = Gate("d2", log, download=True, raises=YoutubeWait("blocked"))
    free = Gate("free", log)
    r = mk(prepare_workers=3, monotonic=clock.mono, wall=clock.wall, youtube_retry_seconds=900.0)
    r.submit("d1", KIND_PIPELINE, d1)
    r.submit("d2", KIND_PIPELINE, d2)
    wait_for(lambda: len(log) == 2)
    d1.gate.set()
    wait_for(lambda: r.youtube_status()["failures"] == 1)
    d2.gate.set()  # was already running when the block came: returns, does not count a second failure
    wait_for(lambda: r.queue_state()["running"] == 0)
    assert r.youtube_status()["failures"] == 1
    r.submit("free", KIND_PIPELINE, free)
    wait_for(lambda: "free" in log)  # no download needed: starts although YouTube is blocked
    assert log.count("d1") == 1 and log.count("d2") == 1
    free.gate.set()
    clock.t += 901
    d1.gate.clear()
    d2.gate.clear()
    d1.raises = d2.raises = None
    with r._lock:
        r._lock.notify_all()
    wait_for(lambda: log.count("d1") + log.count("d2") == 3)  # one try at the retry time ..
    time.sleep(0.1)
    assert log.count("d1") + log.count("d2") == 3  # .. the other download job waits for its outcome
    release(d1, d2)
    assert r.wait_idle(10)


def test_persistence_restores_all_running_jobs(mk, tmp_path):
    log = []
    gates = {n: Gate(n, log) for n in "ab"}
    r = mk(prepare_workers=2)
    state = tmp_path / "q.json"
    r.configure_persistence(state, lambda kind, eid, spec, clips: gates[eid])
    for n in "ab":
        r.submit(n, KIND_PIPELINE, gates[n])
    wait_for(lambda: len(log) == 2)
    with r._lock:
        snap = r._snapshot_locked()
    assert [e["episode_id"] for e in snap["lanes"]["prepare"]] == ["a", "b"]
    release(*gates.values())
    assert r.wait_idle(10)


def test_monitor_lists_every_running_prepare_job(mk):
    log = []
    gates = {n: Gate(n, log) for n in "abc"}
    r = mk(prepare_workers=2)
    for n in "abc":
        r.submit(n, KIND_PIPELINE, gates[n])
    wait_for(lambda: len(log) == 2)
    lane = r.monitor_queue()["lanes"]["prepare"]
    assert [e["episode_id"] for e in lane["running_all"]] == ["a", "b"] and lane["running"] is lane["running_all"][0]
    assert lane["pending_total"] == 1 and set(r.lane_tids().values()) >= {"prepare", "prepare#1"}
    release(*gates.values())
    assert r.wait_idle(10)


def test_logs_go_to_the_job_of_the_thread(mk):
    import logging
    class Talk(Gate):
        def run(self, job):
            logging.getLogger("auto_short").info("hello from %s", self.name)
            super().run(job)
    log = []
    gates = {n: Talk(n, log) for n in "ab"}
    r = mk(prepare_workers=2)
    jobs = {n: r.submit(n, KIND_PIPELINE, gates[n])[0] for n in "ab"}
    wait_for(lambda: len(log) == 2)
    wait_for(lambda: all(any("hello" in line for line in j.logs) for j in jobs.values()))
    for n, j in jobs.items():
        assert any(f"hello from {n}" in line for line in j.logs) and not any(f"from {'b' if n == 'a' else 'a'}" in line for line in j.logs)
    release(*gates.values())
    assert r.wait_idle(10)


# --- config ---------------------------------------------------------------------------------------------------

def test_whisper_threads_per_job():
    wh = WhisperConfig(cpu_threads=24)
    assert whisper_threads_per_job(wh, 1) == 24 and whisper_threads_per_job(wh, 3) == 8
    assert whisper_threads_per_job(WhisperConfig(cpu_threads=2), 8) == 1
    assert whisper_threads_per_job(WhisperConfig(cpu_threads=24, cpu_threads_per_job=5), 3) == 5
    assert whisper_threads_per_job(WhisperConfig(cpu_threads=0), 1) == 0  # 0 stays "all CPUs"


def test_config_keys_and_hash_unchanged():
    cfg = from_dict({"web": {"prepare_workers": 3, "worker_nice": 12},
                     "transcript": {"whisper": {"cpu_threads": 24, "cpu_threads_per_job": 8}}})
    assert cfg.web.prepare_workers == 3 and cfg.web.worker_nice == 12
    assert cfg.transcript.whisper.cpu_threads_per_job == 8
    assert Config().web.prepare_workers == 1
    for bad in ({"web": {"prepare_workers": 0}}, {"web": {"prepare_workers": 9}}, {"web": {"worker_nice": 20}},
                {"transcript": {"whisper": {"cpu_threads_per_job": -1}}}):
        with pytest.raises(ConfigError):
            from_dict(bad)
    from auto_short.transcript.stage import used_config
    base = Config()
    other = replace(base, transcript=replace(base.transcript, whisper=replace(base.transcript.whisper,
                                                                          cpu_threads_per_job=4, cpu_threads=3)))
    assert used_config(base) == used_config(other)


def test_app_gives_each_prepare_job_its_share_of_whisper_threads(tmp_path):
    from fastapi.testclient import TestClient
    from auto_short.config import RenderConfig, WorkspaceConfig, TranscriptConfig
    from auto_short.web import app as app_mod
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "w"), render=RenderConfig(output_dir=tmp_path / "o"),
                 web=WebConfig(prepare_workers=3),
                 transcript=TranscriptConfig(whisper=WhisperConfig(cpu_threads=24)))
    runner = JobRunner(prepare_workers=3)
    seen = []
    orig = app_mod.replace

    def spy(obj, **kw):
        out = orig(obj, **kw)
        if isinstance(out, WhisperConfig):
            seen.append(out.cpu_threads)
        return out

    app_mod.replace = spy
    try:
        app_mod.create_app(cfg, "pw", runner=runner)
    finally:
        app_mod.replace = orig
    assert seen == [8]


# --- Amendment 1: low priority of the heavy lanes ----------------------------------------------------------------

def test_lower_thread_priority_is_per_thread_and_inherited_by_children():
    out = {}

    def body():
        out["ok"] = jobs_mod.lower_thread_priority(10)
        out["nice"] = os.getpriority(os.PRIO_PROCESS, threading.get_native_id())
        out["child"] = int(subprocess.run(["sh", "-c", "ps -o ni= -p $$"], capture_output=True, text=True).stdout)

    before = os.getpriority(os.PRIO_PROCESS, 0)
    t = threading.Thread(target=body)
    t.start()
    t.join()
    assert out["ok"] and out["nice"] == before + 10 or out["nice"] == 10
    assert out["child"] == out["nice"]
    assert os.getpriority(os.PRIO_PROCESS, 0) == before  # the calling (web) thread is untouched


def test_heavy_lanes_run_niced_and_ai_lane_does_not(mk):
    log = []
    g = Gate("p", log)
    r = mk(worker_nice=10)
    r.submit("p", KIND_PIPELINE, g)
    wait_for(lambda: g.nice is not None)
    assert g.nice >= 10
    g.gate.set()
    plain = Gate("q", log)
    r2 = mk()
    r2.submit("q", KIND_PIPELINE, plain)
    wait_for(lambda: plain.nice is not None)
    assert plain.nice == os.getpriority(os.PRIO_PROCESS, 0)
    plain.gate.set()
