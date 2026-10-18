"""CP8.36 render lane with several slots (docs/tasks/CP8.36-render-parallel.md AC1-AC7). Fake steps held by events; the
CPU load is injected, so nothing depends on the real machine."""

import json
import threading
import time

import pytest

from auto_short.config import Config, ConfigError, from_dict
from auto_short.web.jobs import (KIND_COMPILATION, KIND_ENHANCE, KIND_RENDER, KIND_VERTICAL, RENDER, JobRunner,
                                 compilation_key)


def wait_for(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


def settle() -> None:
    time.sleep(0.15)


class Gate:
    def __init__(self, name, log):
        self.name, self.log = name, log
        self.gate = threading.Event()

    def spec(self):
        return {"name": self.name}

    def __call__(self, job):
        self.log.append(self.name)
        deadline = time.monotonic() + 10
        while not self.gate.wait(0.02):
            assert time.monotonic() < deadline


class Load:
    def __init__(self, value=1.0):
        self.value = value

    def __call__(self):
        return self.value


@pytest.fixture
def mk():
    made = []

    def factory(**kw):
        kw.setdefault("render_workers", 2)
        kw.setdefault("load_check_seconds", 0.05)
        r = JobRunner(**kw)
        r.start()
        made.append(r)
        return r

    yield factory
    for r in made:
        r.stop(timeout=5)


def gates(*names, log=None):
    log = [] if log is None else log
    return log, {n: Gate(n, log) for n in names}


def release(g):
    for x in g.values():
        x.gate.set()


def test_two_videos_render_at_once_when_idle(mk):  # AC1
    load = Load(0.1)
    r = mk(cpu_source=load)
    log, g = gates("a", "b", "c")
    for n in "abc":
        r.submit(n, KIND_RENDER, g[n])
    wait_for(lambda: len(log) == 2)
    settle()
    assert sorted(log) == ["a", "b"] and set(r.running_slots()) == {"render", "render#1"}
    assert r.queue_state()["running"] == 2
    assert r.monitor_queue()["lanes"]["render"]["workers"] == 2
    assert len(r.monitor_queue()["lanes"]["render"]["running_all"]) == 2
    g["a"].gate.set()
    wait_for(lambda: len(log) == 3)
    release(g)
    assert r.wait_idle(10)


def test_busy_cpu_holds_back_the_extra_slot_only(mk):  # AC2
    load = Load(0.9)
    r = mk(cpu_source=load)
    log, g = gates("a", "b")
    r.submit("a", KIND_RENDER, g["a"])
    r.submit("b", KIND_RENDER, g["b"])
    wait_for(lambda: log == ["a"])
    settle()
    assert log == ["a"] and list(r.running_slots()) == ["render"]
    load.value = 0.59
    wait_for(lambda: log == ["a", "b"])  # re-checked without any new job
    load.value = 1.0  # a running job is never stopped
    settle()
    assert len(r.running_slots()) == 2
    release(g)
    assert r.wait_idle(10)


def test_busy_cpu_first_slot_still_takes_the_next_job(mk):
    r = mk(cpu_source=Load(1.0))
    log, g = gates("a", "b")
    r.submit("a", KIND_RENDER, g["a"])
    r.submit("b", KIND_RENDER, g["b"])
    wait_for(lambda: log == ["a"])
    g["a"].gate.set()
    wait_for(lambda: log == ["a", "b"])
    release(g)
    assert r.wait_idle(10)


@pytest.mark.parametrize("first,second,fid,sid", [
    (KIND_RENDER, KIND_VERTICAL, "v", "v"),
    (KIND_ENHANCE, KIND_VERTICAL, "v", "v"),
    (KIND_RENDER, KIND_RENDER, "v", "v.kt"),
    (KIND_ENHANCE, KIND_RENDER, "v", "v.kt"),
])
def test_same_video_never_overlaps(mk, first, second, fid, sid):  # AC3
    r = mk(cpu_source=Load(0.0))
    log, g = gates("x", "y", "z")
    r.submit(fid, first, g["x"])
    r.submit(sid, second, g["y"])
    r.submit("other", KIND_RENDER, g["z"])
    wait_for(lambda: len(log) == 2)
    settle()
    assert sorted(log) == ["x", "z"]  # y waits for its video, the next video runs
    g["x"].gate.set()
    wait_for(lambda: "y" in log)
    release(g)
    assert r.wait_idle(10)


def test_compilation_runs_alone_both_ways(mk):  # AC4
    r = mk(cpu_source=Load(0.0))
    key = compilation_key("pl", "c1")
    # compilation first: nothing starts next to it
    log, g = gates("c", "a", "b")
    r.submit(key, KIND_COMPILATION, g["c"])
    r.submit("a", KIND_RENDER, g["a"])
    wait_for(lambda: log == ["c"])
    settle()
    assert log == ["c"]
    g["c"].gate.set()
    wait_for(lambda: log == ["c", "a"])
    # compilation behind a running job waits for it, and holds back later jobs (drain)
    key2 = compilation_key("pl", "c2")
    log2, g2 = gates("c2", "x")
    r.submit(key2, KIND_COMPILATION, g2["c2"])
    r.submit("x", KIND_RENDER, g2["x"])
    settle()
    assert log2 == []
    g["a"].gate.set()
    wait_for(lambda: log2 == ["c2"])
    settle()
    assert log2 == ["c2"]
    release(g2)
    assert r.wait_idle(10)
    assert log2 == ["c2", "x"]


def test_one_worker_is_the_old_behaviour(mk):  # AC5
    r = mk(render_workers=1, cpu_source=Load(0.0))
    log, g = gates("a", "b")
    r.submit("a", KIND_RENDER, g["a"])
    r.submit("b", KIND_RENDER, g["b"])
    wait_for(lambda: log == ["a"])
    settle()
    assert log == ["a"] and list(r.running_slots()) == ["render"]
    assert r.monitor_queue()["lanes"]["render"]["workers"] == 1
    g["a"].gate.set()
    wait_for(lambda: log == ["a", "b"])
    release(g)
    assert r.wait_idle(10)


def test_order_priority_and_pause_with_two_slots(mk):  # AC6
    r = mk(cpu_source=Load(0.0))
    log, g = gates("a", "b", "v", "c", "d")
    r.submit("a", KIND_RENDER, g["a"])
    r.submit("b", KIND_RENDER, g["b"])
    wait_for(lambda: len(log) == 2)
    r.submit("v", KIND_VERTICAL, g["v"])  # V1: after every other job
    r.submit("c", KIND_RENDER, g["c"])
    r.submit("d", KIND_RENDER, g["d"])
    r.priority.mark(["d"])
    r.pause("after")
    release({"a": g["a"], "b": g["b"]})
    settle()
    assert sorted(log) == ["a", "b"]  # paused: nothing new
    r.resume()
    wait_for(lambda: len(log) == 4)
    assert sorted(log[2:]) == ["c", "d"]  # both free slots take the two waiting non-vertical jobs (v stays last)
    release(g)
    assert r.wait_idle(10)
    assert log[4] == "v"


def test_vertical_is_last_even_with_a_free_slot(mk):
    r = mk(cpu_source=Load(0.0))
    log, g = gates("v", "a", "b")
    r.pause("after")  # hold the slots until all three are queued (V1 orders only jobs queued together)
    r.submit("v", KIND_VERTICAL, g["v"])
    r.submit("a", KIND_RENDER, g["a"])
    r.submit("b", KIND_RENDER, g["b"])
    r.resume()
    wait_for(lambda: len(log) == 2)
    assert set(log) == {"a", "b"}
    release(g)
    assert r.wait_idle(10)
    assert log[2] == "v"


def test_saved_queue_keeps_both_running_jobs_first(mk, tmp_path):  # AC6 / D6
    path = tmp_path / "queue.json"
    log, g = gates("a", "b", "c")
    r = mk(cpu_source=Load(0.0))
    r.configure_persistence(path, lambda kind, eid, spec, clips: g[spec["name"]])
    for n in "abc":
        r.submit(n, KIND_RENDER, g[n])
    wait_for(lambda: len(log) == 2)
    r.stop(timeout=5)
    saved = json.loads(path.read_text(encoding="utf-8"))["lanes"][RENDER]
    assert [e["episode_id"] for e in saved] == ["a", "b", "c"]
    r2 = JobRunner(render_workers=2)
    r2.configure_persistence(path, lambda kind, eid, spec, clips: g[spec["name"]])
    assert r2.restore() == 3
    assert r2.queue_state()["pending"] == 3


def test_unreadable_or_unsampled_cpu_counts_as_busy(mk):
    r = mk(cpu_source=Load(None))
    log, g = gates("a", "b")
    r.submit("a", KIND_RENDER, g["a"])
    r.submit("b", KIND_RENDER, g["b"])
    wait_for(lambda: log == ["a"])
    settle()
    assert log == ["a"]
    release(g)
    assert r.wait_idle(10)


def test_cpu_average_uses_proc_stat_over_the_window(tmp_path):
    from auto_short.web.jobs import CpuAverage
    t = [0.0]
    m = CpuAverage(tmp_path, window=60.0, clock=lambda: t[0])
    assert m.value() is None  # unreadable
    m.sample()
    assert m.value() is None

    def stat(total_idle):
        (tmp_path / "stat").write_text("cpu  %d 0 0 %d 0 0 0 0 0 0\n" % total_idle, encoding="utf-8")
    stat((0, 0)); m.sample()
    assert m.value() is None  # not enough span yet
    t[0] = 40.0; stat((60, 40)); m.sample()  # 60 busy, 40 idle ticks
    assert m.value() == pytest.approx(0.6)
    t[0] = 100.0; stat((60, 140)); m.sample()  # window slides: first sample dropped, 0 busy of last 100
    assert m.value() == pytest.approx(0.0)


def test_config_values():  # AC7
    cfg = from_dict({"web": {"render_workers": 3, "render_max_cpu": 0.8}})
    assert cfg.web.render_workers == 3 and cfg.web.render_max_cpu == 0.8
    assert Config().web.render_workers == 2 and Config().web.render_max_cpu == 0.6
    for bad in ({"render_workers": 0}, {"render_workers": 5}, {"render_workers": True}, {"render_workers": 1.5},
                {"render_max_cpu": 0}, {"render_max_cpu": -1}, {"render_max_cpu": 1.5}, {"render_max_cpu": "x"},
                {"render_max_load": 6}):
        with pytest.raises(ConfigError, match="web.render_"):
            from_dict({"web": bad})


def test_app_passes_config_to_the_runner(tmp_path):
    from auto_short.config import RenderConfig, WebConfig, WorkspaceConfig
    from auto_short.web import app as app_mod
    seen = {}
    orig = app_mod.JobRunner

    def spy(*a, **kw):
        seen.update(kw)
        return orig(*a, **kw)

    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "w"), render=RenderConfig(output_dir=tmp_path / "o"),
                 web=WebConfig(render_workers=3, render_max_cpu=0.7))
    app_mod.JobRunner = spy
    try:
        app_mod.create_app(cfg, "pw")
    finally:
        app_mod.JobRunner = orig
    assert seen["render_workers"] == 3 and seen["render_max_cpu"] == 0.7
