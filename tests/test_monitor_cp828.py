"""CP8.28 "Theo dõi" tab (docs/tasks/CP8.28-monitor.md AC1-AC5): detailed queue (3 lanes running, waiting for HD / GPU /
YouTube, pending order with priority, limit), CPU / RAM / disk / top processes from a fake ``/proc``, one-hour history
cap, Ollama ``/api/ps`` (down = reported, no crash), GPU numbers sent by the worker (new field optional both ways),
page + API behind the login. Fake lane steps, fake ``/proc``, no network."""

import json
import sys
import threading
import time
import urllib.error
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.enhance.service import EnhanceService, clean_gpu_stats  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web import monitor as mon  # noqa: E402
from auto_short.web.auth import COOKIE_NAME  # noqa: E402
from auto_short.web.jobs import AI, KIND_PIPELINE, PREPARE, RENDER, Job, JobRunner, Step  # noqa: E402

from enhance_helpers import T1, T2, enhance_cfg  # noqa: E402

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "enhance_worker"
sys.path.insert(0, str(TOOLS))

import fake_server  # noqa: E402
import worker as W  # noqa: E402

PW = "pw"
H1 = {"Authorization": f"Bearer {T1}"}
STATS = {"name": "NVIDIA GeForce RTX 3090", "util_pct": 87.0, "mem_used_mb": 9000.0, "mem_total_mb": 24576.0,
         "temp_c": 71.0, "power_w": 310.5}


def wait_for(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


class Gate:
    """A one-step job in ``lane`` that waits on a gate."""

    def __init__(self, lane, gate=None, download=False):
        self.lane, self.gate = lane, gate
        if download:
            self.needs_download = lambda: True

    def lane_steps(self):
        return [Step(self.lane, self.run)]

    def run(self, job):
        job.stage = "render" if self.lane == RENDER else None
        if self.gate is not None:
            assert self.gate.wait(10)


def make_app(tmp_path, *, runner=None, **kw):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 web=WebConfig(session_days=30))
    runner = runner or JobRunner()
    app = app_mod.create_app(cfg, PW, runner=runner, disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9), **kw)
    client = TestClient(app, follow_redirects=False)
    r = client.post("/login", json={"password": PW})
    return app, client, {COOKIE_NAME: r.cookies[COOKIE_NAME]}, runner


# --- AC1: queue detail -------------------------------------------------------------------------------------------

def test_queue_detail_running_waiting_and_order(tmp_path):
    runner = JobRunner()
    app, client, cookie, _ = make_app(tmp_path, runner=runner)
    runner.start()
    gate = threading.Event()
    try:
        for lane in (PREPARE, AI, RENDER):
            runner.submit(f"run-{lane}", KIND_PIPELINE, Gate(lane, gate))
        wait_for(lambda: len(runner.running()) == 3)
        runner.submit("y1", KIND_PIPELINE, Gate(PREPARE, gate, download=True))
        runner.submit("a1", KIND_PIPELINE, Gate(AI, gate))
        for i in range(30):
            runner.submit(f"r{i:02d}", KIND_PIPELINE, Gate(RENDER, gate))
        runner.priority.mark(["r29", "r05"])
        parked = Job(id="999", episode_id="hold1", kind=KIND_PIPELINE, target=lambda j: None, hd_wait=True)
        with runner._lock:
            runner._parked["hold1"] = parked
            runner._set_gpu_down_locked("ollama down")
            runner._set_yt_blocked_locked("bot check")

        data = client.get("/api/monitor/queue", cookies=cookie).json()
        lanes = data["lanes"]
        assert {lane: info["running"]["episode_id"] for lane, info in lanes.items()} == \
            {"prepare": "run-prepare", "ai": "run-ai", "render": "run-render"}
        run = lanes["render"]["running"]
        assert run["stage"] == "render" and run["elapsed_seconds"] >= 0 and run["started_at"] and run["id"]
        assert run["episode"]["episode_id"] == "run-render" and run["episode"]["label"]
        render = lanes["render"]
        assert render["pending_total"] == 30 and len(render["pending"]) == 20  # default limit 20 per lane
        order = [e["episode_id"] for e in render["pending"]]
        assert order[:4] == ["r29", "r05", "r00", "r01"] and order[-1] == "r18"  # priority first, then FIFO
        assert [e["position"] for e in render["pending"]] == list(range(1, 21))
        assert [e["priority"] for e in render["pending"][:3]] == [True, True, False]
        assert [runner.queue_position(runner.latest(e)) for e in order[:3]] == [1, 2, 3]
        reasons = {(w["episode_id"], w["reason"]) for w in data["waiting"]}
        assert {("hold1", "hd"), ("a1", "gpu"), ("y1", "youtube")} <= reasons
        assert all(w["retry_at"] for w in data["waiting"] if w["reason"] in ("gpu", "youtube"))
        assert data["gpu"]["state"] == "down" and data["youtube"]["blocked"] and data["paused"] is False
        more = client.get("/api/monitor/queue?limit=100", cookies=cookie).json()["lanes"]["render"]["pending"]
        assert len(more) == 30
        runner.pause("after")
        assert client.get("/api/monitor/queue", cookies=cookie).json()["paused"] is True
    finally:
        gate.set()
        runner.resume()
        with runner._lock:  # let the queue drain: stop() interrupts whatever still runs
            runner._gpu.update(state="ok")
            runner._yt.update(blocked=False, failures=0)
            runner._parked.clear()
        runner.wait_idle(30)
        runner.stop(timeout=5)


def test_render_progress_from_log_and_clips(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"))
    d = Path(cfg.workspace.dir) / "ep1"
    d.mkdir(parents=True)
    (d / "clips.json").write_text(json.dumps({"clips": [{"id": f"c{i}"} for i in range(5)]}))
    lines = ["12:00:01 render: clip c0: reuse (render_key unchanged): x", "12:00:09 render: clip c1: title (1080 px)",
             "12:00:09 render: clip c1: again", "12:00:10 render: clip c2 skipped: rejected"]
    assert mon.render_progress(cfg, lines, "ep1") == {"done": 2, "total": 5}
    assert mon.render_progress(cfg, lines, "nope") is None


# --- AC2: /proc ---------------------------------------------------------------------------------------------------

def write_proc(root: Path, *, cpu, cores, mem_avail_kb, procs, children=None):
    root.mkdir(parents=True, exist_ok=True)
    fmt = lambda v: "cpu " if v is None else v  # noqa: E731
    lines = ["cpu  " + " ".join(map(str, cpu))] + [f"cpu{i} " + " ".join(map(str, c)) for i, c in enumerate(cores)]
    (root / "stat").write_text("\n".join(lines) + "\nintr 0\n")
    (root / "meminfo").write_text(f"MemTotal:       16000000 kB\nMemFree: 100 kB\nMemAvailable:   {mem_avail_kb} kB\n")
    (root / "loadavg").write_text("1.50 1.00 0.50 2/300 999\n")
    for pid, (ppid, comm, ticks) in procs.items():
        d = root / str(pid)
        d.mkdir(exist_ok=True)
        rest = f"S {ppid} " + " ".join(["0"] * 9) + f" {ticks} 0 " + " ".join(["0"] * 8) + " 2560"  # rss = field 21
        (d / "stat").write_text(f"{pid} ({comm} x) {rest}\n")
        (d / "cmdline").write_text(f"/usr/bin/{comm}\0-i\0in.mp4\0")
    for tid, kids in (children or {}).items():
        t = root / "100" / "task" / str(tid)
        t.mkdir(parents=True, exist_ok=True)
        (t / "children").write_text(" ".join(map(str, kids)))


class FakeClock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def test_cpu_ram_disk_and_top_processes_from_fake_proc(tmp_path):
    proc, clock = tmp_path / "proc", FakeClock()
    write_proc(proc, cpu=[0, 0, 0, 1000, 0, 0, 0, 0], cores=[[0, 0, 0, 500, 0, 0, 0, 0], [0, 0, 0, 500, 0, 0, 0, 0]],
               mem_avail_kb=8000000, children={555: [200]},
               procs={100: (1, "python", 0), 200: (100, "ffmpeg", 0), 201: (200, "x264", 0), 300: (1, "other", 0)})
    s = mon.Sampler(proc=proc, workdir=tmp_path, clock=clock, clk_tck=100, pid=100,
                    disk_usage=lambda p: (1000, 400, 600), lane_tids=lambda: {555: "render"},
                    lane_jobs=lambda: {"render": {"id": "7", "episode_id": "epX", "kind": "pipeline", "stage": "render"}})
    first = s.sample()
    assert first["cpu"] is None and first["top"] == []  # a first sample has nothing to compare with
    clock.t += 10
    write_proc(proc, cpu=[600, 0, 0, 1400, 0, 0, 0, 0], cores=[[100, 0, 0, 500, 0, 0, 0, 0], [0, 0, 0, 600, 0, 0, 0, 0]],
               mem_avail_kb=4000000, children={555: [200]},
               procs={100: (1, "python", 200), 200: (100, "ffmpeg", 500), 201: (200, "x264", 300), 300: (1, "other", 100)})
    s.sample()
    snap = s.snapshot()
    assert snap["cpu_pct"] == 60.0 and snap["cores"] == [100.0, 0.0] and snap["ncpu"] == 2
    assert snap["load"] == [1.5, 1.0, 0.5] and snap["ram_pct"] == 75.0
    assert snap["mem"]["total"] == 16000000 * 1024 and snap["mem"]["used"] == 12000000 * 1024
    assert snap["disk"] == {"total": 1000, "used": 400, "free": 600, "path": str(tmp_path)}
    top = snap["top"]
    assert [(p["pid"], p["cpu_pct"]) for p in top] == [(200, 50.0), (201, 30.0), (100, 20.0), (300, 10.0)]
    assert top[0]["lane"] == "render" and top[0]["job"]["episode_id"] == "epX"
    assert top[1]["lane"] == "render"  # a grandchild belongs to the same job
    assert top[2]["lane"] == "web" and top[2]["job"]["jobs"][0]["id"] == "7" and top[2]["comm"] == "auto-short web"
    assert top[3]["lane"] is None and top[3]["job"] is None
    assert top[0]["rss_mb"] > 0
    assert len(snap["history"]) == 2 and snap["history"][1][1] == 60.0


def test_history_is_capped_to_about_an_hour(tmp_path):
    proc, clock = tmp_path / "proc", FakeClock()
    write_proc(proc, cpu=[0, 0, 0, 1000, 0, 0, 0, 0], cores=[[0] * 8], mem_avail_kb=1, procs={})
    s = mon.Sampler(proc=proc, workdir=tmp_path, clock=clock, interval=5.0, history_seconds=3600)
    for _ in range(800):
        clock.t += 5
        s.sample()
    assert len(s.history) == 720 and s.history[-1]["t"] == clock.t


def test_missing_proc_does_not_break(tmp_path):
    s = mon.Sampler(proc=tmp_path / "nope", workdir=tmp_path, disk_usage=lambda p: (1, 1, 0))
    snap = s.snapshot()
    assert snap["cpu_pct"] is None and snap["mem"] is None and snap["top"] == []


def test_system_api_uses_the_injected_proc(tmp_path):
    proc = tmp_path / "proc"
    write_proc(proc, cpu=[0, 0, 0, 1000, 0, 0, 0, 0], cores=[[0] * 8], mem_avail_kb=4000000, procs={})
    app, client, cookie, _ = make_app(tmp_path, proc_dir=str(proc))
    d = client.get("/api/monitor/system", cookies=cookie).json()
    assert d["ram_pct"] == 75.0 and d["disk"]["free"] == 50 * 10**9 and d["history"]
    assert app.state.monitor_sampler.proc == proc


# --- AC3: Ollama --------------------------------------------------------------------------------------------------

class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_ollama_ps_models_and_connection_error():
    body = json.dumps({"models": [{"name": "qwen3:30b", "size": 20 * 2**30, "size_vram": 19 * 2**30,
                                   "expires_at": "2026-10-04T12:00:00Z"}, "junk"]}).encode()
    ok = mon.fetch_ollama_ps("http://h:11437/", opener=lambda req, timeout: Resp(body))
    assert ok["connected"] and ok["models"] == [{"name": "qwen3:30b", "size_mb": 20480, "vram_mb": 19456,
                                                  "expires_at": "2026-10-04T12:00:00Z"}]

    def boom(req, timeout):
        raise urllib.error.URLError("refused")

    down = mon.fetch_ollama_ps("http://h:11437", opener=boom)
    assert down["connected"] is False and down["models"] == [] and "refused" in down["error"]
    assert mon.fetch_ollama_ps("http://h", opener=lambda r, timeout: Resp(b"not json"))["connected"] is False
    frac = json.dumps({"models": [{"name": "m", "expires_at": "2026-10-04T18:03:22.9236555+07:00"}]}).encode()
    assert mon.fetch_ollama_ps("http://h", opener=lambda r, timeout: Resp(frac))["models"][0]["expires_at"] == \
        "2026-10-04T18:03:22+07:00"  # no sub-second digits: every browser parses it


def test_ollama_api_reports_models_job_and_dead_ollama(tmp_path):
    runner = JobRunner()
    state = {"ps": {"connected": True, "host": "h", "models": [{"name": "m", "size_mb": 1, "vram_mb": 1,
                                                                 "expires_at": None}], "error": None}}

    def ps():
        if state["ps"] is None:
            raise RuntimeError("boom")
        return state["ps"]

    app, client, cookie, _ = make_app(tmp_path, runner=runner, ollama_ps=ps)
    runner.start()
    gate = threading.Event()
    try:
        runner.submit("ai-ep", KIND_PIPELINE, Gate(AI, gate))
        wait_for(lambda: runner.running().get("ai") is not None)
        d = client.get("/api/monitor/ollama", cookies=cookie).json()
        assert d["connected"] and d["models"][0]["name"] == "m" and d["job"]["episode"]["episode_id"] == "ai-ep"
        assert d["gpu"]["state"] == "ok"
        state["ps"] = None
        # a fresh view (the cache is a few seconds): build a new app instead of sleeping
        app2, client2, cookie2, _ = make_app(tmp_path, runner=runner, ollama_ps=ps)
        d2 = client2.get("/api/monitor/ollama", cookies=cookie2)
        assert d2.status_code == 200 and d2.json()["connected"] is False and "boom" in d2.json()["error"]
    finally:
        gate.set()
        runner.wait_idle(10)
        runner.stop(timeout=5)


# --- AC4: GPU numbers (VM side) ------------------------------------------------------------------------------------

class Ctx:
    def __init__(self, tmp_path):
        self.cfg = enhance_cfg(tmp_path, yield_workers=("w3090",))
        self.clock = FakeClock()
        self.svc = EnhanceService(self.cfg, clock=self.clock)
        self.runner = JobRunner()
        self.app = app_mod.create_app(self.cfg, PW, runner=self.runner, preflight=lambda c: None,
                                      enhance_tokens={"w3090": T1, "w3050": T2}, enhance_service=self.svc,
                                      ollama_ps=lambda: {"connected": False, "models": [], "error": "x"})
        self.client = TestClient(self.app, follow_redirects=False)
        r = self.client.post("/login", json={"password": PW})
        self.cookie = {COOKIE_NAME: r.cookies[COOKIE_NAME]}

    def gpu(self):
        return {w["name"]: w for w in self.client.get("/api/monitor/gpu", cookies=self.cookie).json()["workers"]}


def test_gpu_stats_via_lease_and_may_run_and_stale(tmp_path):
    c = Ctx(tmp_path)
    assert c.gpu()["w3090"]["connected"] is False and c.gpu()["w3090"]["gpu_stats"] is None  # never connected
    r = c.client.post("/api/enhance/lease", json={"worker": "w", "gpu": "RTX 3090", "gpu_stats": STATS}, headers=H1)
    assert r.status_code == 204  # nothing to do, the numbers still arrive
    w = c.gpu()["w3090"]
    assert w["connected"] and w["gpu_stats"] == STATS and w["gpu_stats_stale"] is False
    c.clock.t += 400
    assert c.gpu()["w3090"]["gpu_stats_stale"] is True
    newer = dict(STATS, util_pct=12.0)
    q = json.dumps(newer, separators=(",", ":"))
    assert c.client.get("/api/enhance/may-run", params={"worker": "w", "gpu_stats": q}, headers=H1).status_code == 200
    w = c.gpu()["w3090"]
    assert w["gpu_stats"]["util_pct"] == 12.0 and w["gpu_stats_stale"] is False
    # unusable numbers are ignored, the previous ones stay; the call still works
    for bad in ("not json", "[1,2]", json.dumps({"util_pct": "x"})):
        r = c.client.get("/api/enhance/may-run", params={"gpu_stats": bad}, headers=H1)
        assert r.status_code == 200 and r.json() == {"run": True, "reason": ""}
    assert c.gpu()["w3090"]["gpu_stats"]["util_pct"] == 12.0


def test_old_worker_without_gpu_stats_shows_no_numbers(tmp_path):
    c = Ctx(tmp_path)
    assert c.client.post("/api/enhance/lease", json={"worker": "w", "gpu": "RTX 3050"}, headers={"Authorization": f"Bearer {T2}"}
                         ).status_code == 204
    w = c.gpu()["w3050"]
    assert w["connected"] and w["gpu_stats"] is None and w["gpu"] == "RTX 3050"
    # the status the storage page reads still has the worker (new keys are additive)
    assert c.client.get("/api/enhance/status", cookies=c.cookie).json()["workers"][0]["name"] == "w3050"


def test_clean_gpu_stats():
    assert clean_gpu_stats(STATS) == STATS
    assert clean_gpu_stats({"name": "x" * 200, "util_pct": True, "temp_c": float("nan")}) == {
        "name": "x" * 80, "util_pct": None, "mem_used_mb": None, "mem_total_mb": None, "temp_c": None, "power_w": None}
    assert clean_gpu_stats({}) is None and clean_gpu_stats("x") is None and clean_gpu_stats(None) is None


@pytest.mark.usefixtures("_video_template")
def test_gpu_stats_via_heartbeat(tmp_path):
    from enhance_helpers import make_yt_episode
    c = Ctx(tmp_path)
    make_yt_episode(c.cfg, "vid00000001")
    with c.client:
        lease = c.client.post("/api/enhance/lease", json={"worker": "w"}, headers=H1).json()
        r = c.client.post(f"/api/enhance/{lease['lease_id']}/heartbeat", headers=H1,
                          json={"progress": {"segments_uploaded": 1, "segments_total": 4}, "gpu_stats": STATS})
        assert r.status_code == 200
        w = c.gpu()["w3090"]
        assert w["gpu_stats"] == STATS and w["episode"]["episode_id"] == "vid00000001"
        assert w["progress"]["segments_total"] == 4
        # a heartbeat of an old worker (no field) keeps the last numbers
        assert c.client.post(f"/api/enhance/{lease['lease_id']}/heartbeat", json={}, headers=H1).status_code == 200
        assert c.gpu()["w3090"]["gpu_stats"] == STATS


# --- AC4: worker side ---------------------------------------------------------------------------------------------

class Run:
    def __init__(self, stdout="", exc=None):
        self.stdout, self.exc, self.calls = stdout, exc, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if self.exc:
            raise self.exc
        return type("R", (), {"stdout": self.stdout})()


def test_read_gpu_stats_parses_nvidia_smi_and_ignores_failures():
    run = Run("NVIDIA GeForce RTX 3090, 87, 9000, 24576, 71, 310.52\n")
    assert W.read_gpu_stats({"device": "cuda", "cuda_device": 0}, run) == {
        "name": "NVIDIA GeForce RTX 3090", "util_pct": 87.0, "mem_used_mb": 9000.0, "mem_total_mb": 24576.0,
        "temp_c": 71.0, "power_w": 310.5}
    assert "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw" in run.calls[0]
    na = W.read_gpu_stats({"device": "cuda"}, Run("GPU, 5, 100, 200, [N/A], [N/A]\n"))
    assert na["util_pct"] == 5.0 and na["temp_c"] is None and na["power_w"] is None
    assert W.read_gpu_stats({"device": "cuda"}, Run(exc=FileNotFoundError("nvidia-smi"))) is None
    assert W.read_gpu_stats({"device": "cuda"}, Run("")) is None
    assert W.read_gpu_stats({"device": "cuda"}, Run("garbage")) is None
    run_cpu = Run("x")
    assert W.read_gpu_stats({"device": "cpu"}, run_cpu) is None and run_cpu.calls == []


@pytest.fixture
def fake(tmp_path):
    import shutil
    import subprocess
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg")
    src = tmp_path / "tiny.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=25:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    srv = fake_server.FakeServer(src, token="tok", segment_frames=20, seg_dir=tmp_path / "segs").start()
    yield srv
    srv.stop()


def make_worker(tmp_path, srv, stats):
    cfg = W.load_config(None, {"server_url": f"http://127.0.0.1:{srv.port}", "token": "tok", "worker_name": "w",
                               "work_dir": str(tmp_path / "w"), "log_file": str(tmp_path / "w.log"),
                               "device": "cuda"})
    w = W.Worker(cfg, once=True)
    w._gpu = "RTX test"
    w.gpu_stats = lambda: stats  # nvidia-smi is not there in CI
    return w


def test_worker_sends_gpu_stats_with_lease_heartbeat_and_may_run(tmp_path, fake):
    w = make_worker(tmp_path, fake, STATS)
    lease = w.acquire_lease()
    assert lease and fake.lease_bodies[-1]["gpu_stats"] == STATS and fake.lease_bodies[-1]["gpu"] == "RTX test"
    w.heartbeat_once(lease)
    assert fake.heartbeat_bodies[-1]["gpu_stats"] == STATS and "progress" in fake.heartbeat_bodies[-1]
    assert w.wait_may_run(None) is True
    q = fake.may_run_queries[-1]
    assert "worker=w" in q and json.loads(__import__("urllib.parse", fromlist=["x"]).parse_qs(q)["gpu_stats"][0]) == STATS


def test_worker_without_numbers_still_works_and_old_vm_ignores_them(tmp_path, fake):
    # no numbers (nvidia-smi failed): the bodies simply do not carry the field
    w = make_worker(tmp_path, fake, None)
    lease = w.acquire_lease()
    assert lease and "gpu_stats" not in fake.lease_bodies[-1]
    w.heartbeat_once(lease)
    assert "gpu_stats" not in fake.heartbeat_bodies[-1]
    assert w.wait_may_run(None) is True and "gpu_stats" not in fake.may_run_queries[-1]
    # the fake server is an "old VM": it knows nothing of the field and answers normally (lease / heartbeat / may-run OK)
    w2 = make_worker(tmp_path / "2", fake, STATS)
    assert w2.acquire_lease() and fake.heartbeats == 1


def test_gpu_stats_is_cached_for_a_moment(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(W, "read_gpu_stats", lambda cfg: calls.append(1) or STATS)
    cfg = W.load_config(None, {"work_dir": str(tmp_path / "w"), "log_file": str(tmp_path / "l"), "device": "cuda"})
    w = W.Worker(cfg, once=True)
    assert w.gpu_stats() == STATS and w.gpu_stats() == STATS and len(calls) == 1


# --- AC5: page + login ---------------------------------------------------------------------------------------------

def test_page_links_and_login_required(tmp_path):
    app, client, cookie, _ = make_app(tmp_path)
    anon = TestClient(app, follow_redirects=False)
    assert anon.get("/monitor").status_code == 303
    for path in ("/api/monitor/queue", "/api/monitor/system", "/api/monitor/ollama", "/api/monitor/gpu"):
        assert anon.get(path).status_code == 401, path
    page = client.get("/monitor", cookies=cookie)
    assert page.status_code == 200 and "Theo dõi" in page.text and "initMonitor" in page.text
    static = Path(app_mod.STATIC_DIR)
    for name in ("index.html", "playlist.html", "episode.html", "posts.html", "storage.html", "monitor.html"):
        assert 'href="/monitor"' in (static / name).read_text(encoding="utf-8"), name
    js = (static / "app.js").read_text(encoding="utf-8")
    assert 'href: "/monitor"' in js and "initMonitor" in js  # the queue summary bar opens the tab
