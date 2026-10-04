"""FIX-youtube-botcheck-wait AC1-AC6: YouTube blocks the download (bot check / 429) -> the prepare lane keeps the job at
its head and backs off 15 -> 30 -> 60 -> 120 min (fake clocks, no real sleeps); other download errors still fail;
the block survives a restart; ``youtube`` in the API; jobs that need no download still run."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short import hashing
from auto_short.config import Config, RenderConfig, WebConfig, WorkspaceConfig
from auto_short.ingest import IngestBlocked, IngestError, needs_download
from auto_short.ingest.stage import STAGE, _used_config
from auto_short.ingest.source import classify
from auto_short.ingest.youtube import is_blocked_message
from auto_short.web.jobs import DONE, FAILED, KIND_PIPELINE, PREPARE, QUEUED, JobRunner, pipeline_target
from auto_short.workspace import Workspace

MIN = 60.0
A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


def wait_for(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


class Clock:
    """Fake monotonic + wall clocks sharing one offset."""

    def __init__(self, wall0: float = 1_800_000_000.0):
        self.t, self.wall0 = 0.0, wall0

    def mono(self) -> float:
        return self.t

    def wall(self) -> float:
        return self.wall0 + self.t


def advance(runner: JobRunner, clock: Clock, seconds: float) -> None:
    clock.t += seconds
    with runner._lock:
        runner._lock.notify_all()


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"))


class Net:
    """Fake ``run_pipeline``: ``error`` (None | IngestBlocked | IngestError) is what the ingest stage hits."""

    def __init__(self, error=None):
        self.error, self.log, self.lock = error, [], threading.Lock()
        self.skip: set[str] = set()  # episodes whose ingest skips (source already there): no download, no error

    def __call__(self, url, config, *, series=None, episode=None, preflight=None, on_stage=None, stages=None,
                 episode_id=None, **kw):
        eid = episode_id or url.rsplit("/", 1)[-1]
        for st in stages or ("ingest", "transcript", "analysis", "selection", "titling", "render"):
            with self.lock:
                self.log.append((st, eid))
            if st == "ingest" and eid in self.skip:
                if on_stage is not None:
                    on_stage(SimpleNamespace(stage=st, ran=False, seconds=0.0, result=None))
                continue
            if st == "ingest" and self.error is not None:
                return SimpleNamespace(ok=False, failed_stage=st, error=self.error, episode_id=eid, stages=[])
            if on_stage is not None:
                on_stage(SimpleNamespace(stage=st, ran=True, seconds=0.0, result=None))
        return SimpleNamespace(ok=True, failed_stage=None, error=None, episode_id=eid, rendered=1, clips=1, stages=[])

    def ingests(self):
        return [e for s, e in self.log if s == "ingest"]


def blocked_error():
    return IngestBlocked("ingest failed: yt-dlp download failed: ERROR: Sign in to confirm you’re not a bot.")


@pytest.fixture
def mk():
    runners = []

    def factory(clock, **kw):
        r = JobRunner(youtube_retry_seconds=15 * MIN, youtube_retry_max_seconds=120 * MIN,
                      monotonic=clock.mono, wall=clock.wall, **kw)
        r.start()
        runners.append(r)
        return r

    yield factory
    for r in runners:
        r.stop(timeout=5)


def submit(runner, tcfg, eid, net, **kw):
    return runner.submit(eid, KIND_PIPELINE, pipeline_target(f"https://youtu.be/{eid}", tcfg, pipeline=net,
                                                             preflight=None, **kw))[0]


def blocked_n(runner, n):
    return lambda: runner.youtube_status()["failures"] == n


# --- Y1 detector ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "yt-dlp download failed: ERROR: [youtube] X4zNKG7XGoI: Sign in to confirm you’re not a bot. Use --cookies",
    "\x1b[0;31mERROR:\x1b[0m [youtube] x: Sign in to confirm you're not a bot",
    "ERROR: unable to download: HTTP Error 429: Too Many Requests",
    "too many requests"])
def test_detector_blocked(text):
    assert is_blocked_message(text)


@pytest.mark.parametrize("text", ["ERROR: [youtube] x: Video unavailable", "Private video. Sign in if you've been granted",
                                  "HTTP Error 404: Not Found"])
def test_detector_other_errors(text):
    assert not is_blocked_message(text)


def test_ytdlp_download_raises_blocked_vs_plain(tmp_path, monkeypatch):
    yt_dlp = pytest.importorskip("yt_dlp")
    from auto_short.config import IngestConfig
    from auto_short.ingest import youtube

    def fake(msg):
        class Y:
            def __init__(self, opts): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def sanitize_info(self, info): return info
            def extract_info(self, url, download=True): raise yt_dlp.utils.DownloadError(msg)
        return Y
    monkeypatch.setattr(yt_dlp, "YoutubeDL", fake("ERROR: [youtube] x: Sign in to confirm you’re not a bot."))
    with pytest.raises(youtube.YoutubeBlocked):
        youtube.ytdlp_download("https://youtu.be/x", tmp_path, IngestConfig())
    monkeypatch.setattr(yt_dlp, "YoutubeDL", fake("ERROR: [youtube] x: Video unavailable"))
    with pytest.raises(youtube.DownloadError) as ei:
        youtube.ytdlp_download("https://youtu.be/x", tmp_path, IngestConfig())
    assert not isinstance(ei.value, youtube.YoutubeBlocked)


def test_run_ingest_raises_ingest_blocked(tcfg, tmp_path):
    from auto_short.ingest import run_ingest
    from auto_short.ingest.youtube import DownloadError, YoutubeBlocked

    def blocked(url, dest, cfg):
        raise YoutubeBlocked("yt-dlp download failed: bot")

    def gone(url, dest, cfg):
        raise DownloadError("yt-dlp download failed: Video unavailable")
    with pytest.raises(IngestBlocked):
        run_ingest(f"https://youtu.be/{A}", tcfg, downloader=blocked)
    with pytest.raises(IngestError) as ei:
        run_ingest(f"https://youtu.be/{B}", tcfg, downloader=gone)
    assert not isinstance(ei.value, IngestBlocked)


# --- AC1 / AC3 -----------------------------------------------------------------------------------------------

def test_block_requeues_head_lane_waits_then_all_done_in_order(mk, tcfg):
    clock, net = Clock(), Net(blocked_error())
    runner = mk(clock)
    jobs = [submit(runner, tcfg, e, net) for e in (A, B, C)]
    wait_for(blocked_n(runner, 1))
    time.sleep(0.1)  # the lane does not take job 2 / 3
    assert net.ingests() == [A]
    assert [j.status for j in jobs] == [QUEUED] * 3 and all(j.error is None for j in jobs)
    assert jobs[0].yt_wait and jobs[1].yt_wait and jobs[0].to_dict()["yt_wait"] is True
    assert runner.queue_position(jobs[0]) == 1
    st = runner.youtube_status()
    assert st["blocked"] and st["since"] and st["next_check"] and "not a bot" in st["error"]
    advance(runner, clock, 14 * MIN)  # not due yet
    time.sleep(0.1)
    assert net.ingests() == [A]
    net.error = None
    advance(runner, clock, 1 * MIN)
    assert runner.wait_idle(10)
    assert [j.status for j in jobs] == [DONE] * 3
    assert net.ingests() == [A, A, B, C]
    assert runner.youtube_status() == {"blocked": False, "since": None, "error": None, "next_check": None,
                                       "failures": 0}
    assert not any(j.yt_wait for j in jobs)


def test_consecutive_blocks_back_off_15_30_60_120_120_and_success_resets(mk, tcfg):
    clock, net = Clock(), Net(blocked_error())
    runner = mk(clock)
    job = submit(runner, tcfg, A, net)
    for n, minutes in enumerate((15, 30, 60, 120, 120), 1):
        wait_for(blocked_n(runner, n))
        assert runner._yt_next - clock.mono() == minutes * MIN
        assert job.status == QUEUED
        advance(runner, clock, minutes * MIN)
    wait_for(blocked_n(runner, 6))  # the 6th attempt also blocked: still capped at 120
    assert runner._yt_next - clock.mono() == 120 * MIN
    net.error = None
    advance(runner, clock, 120 * MIN)
    assert runner.wait_idle(10) and job.status == DONE
    assert runner.youtube_status()["failures"] == 0
    net.error = blocked_error()
    job2 = submit(runner, tcfg, B, net)
    wait_for(blocked_n(runner, 1))
    assert runner._yt_next - clock.mono() == 15 * MIN and job2.status == QUEUED


# --- AC2 -----------------------------------------------------------------------------------------------------

def test_other_download_error_fails_and_lane_goes_on(mk, tcfg):
    clock, net = Clock(), Net(IngestError("ingest failed: yt-dlp download failed: ERROR: Video unavailable"))
    runner = mk(clock)
    j1 = submit(runner, tcfg, A, net)
    wait_for(lambda: j1.status == FAILED)
    net.error = None
    j2 = submit(runner, tcfg, B, net)
    assert runner.wait_idle(10)
    assert j1.status == FAILED and "Video unavailable" in j1.error and j2.status == DONE
    assert not runner.youtube_status()["blocked"]


# --- AC6 -----------------------------------------------------------------------------------------------------

def test_job_without_download_runs_while_blocked(mk, tcfg, monkeypatch):
    clock, net = Clock(), Net(blocked_error())
    runner = mk(clock)
    jobs = {e: submit(runner, tcfg, e, net) for e in (A, B)}
    wait_for(blocked_n(runner, 1))
    # B has its source already: its ingest would skip
    from auto_short.web import jobs as jobs_mod
    real = jobs_mod.needs_download
    monkeypatch.setattr(jobs_mod, "needs_download", lambda url, cfg, eid=None: False if url.endswith(B) else real(url, cfg, eid))
    net.skip.add(B)  # B's ingest skips: no download, so it must not reset the block
    with runner._lock:
        runner._lock.notify_all()
    wait_for(lambda: jobs[B].status == DONE)
    assert jobs[A].status == QUEUED and net.ingests().count(A) == 1  # A still waits for its retry time
    net.error = None
    advance(runner, clock, 15 * MIN)
    assert runner.wait_idle(10) and jobs[A].status == DONE


def test_needs_download_checks(tcfg):
    root = Path(tcfg.workspace.dir)
    url = f"https://youtu.be/{A}"
    assert needs_download(url, tcfg) is True  # nothing there
    assert needs_download("/some/local/video.mp4", tcfg) is False
    ws = Workspace(root, A)
    manifest = ws.new_manifest({"kind": "youtube", "uri": url, "path": "source.mp4", "sha256": None, "size": None,
                                "mtime_ns": None})
    ws.dir.mkdir(parents=True, exist_ok=True)
    (ws.dir / "source.mp4").write_bytes(b"x")
    manifest["stages"][STAGE] = {"status": "done", "artifacts": ["source.mp4"], "inputs": [],
                                 "config_hash": hashing.config_hash(_used_config(classify(url), tcfg))}
    ws.save_manifest(manifest)
    assert needs_download(url, tcfg) is False  # ingest would skip
    (ws.dir / "source.mp4").unlink()
    assert needs_download(url, tcfg) is True


# --- AC4 -----------------------------------------------------------------------------------------------------

def test_block_survives_restart_job_stays_at_head(tcfg, tmp_path):
    net = Net(blocked_error())
    path = tmp_path / "queue.json"

    def rebuild(kind, eid, spec, clip_ids):
        return pipeline_target(spec["url"], tcfg, pipeline=net, preflight=None, episode_id=spec.get("episode_id"))

    clock1 = Clock()
    r1 = JobRunner(youtube_retry_seconds=15 * MIN, monotonic=clock1.mono, wall=clock1.wall)
    r1.configure_persistence(path, rebuild)
    r1.start()
    for e in (A, B):
        submit(r1, tcfg, e, net)
    wait_for(blocked_n(r1, 1))
    next_check = r1.youtube_status()["next_check"]
    r1.stop(timeout=5)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["youtube"]["next_check"] == next_check and [e["episode_id"] for e in saved["lanes"]["prepare"]] == [A, B]

    clock2 = Clock(clock1.wall0 + 5 * MIN)  # restarted 5 minutes later
    r2 = JobRunner(youtube_retry_seconds=15 * MIN, monotonic=clock2.mono, wall=clock2.wall)
    r2.configure_persistence(path, rebuild)
    assert r2.restore() == 2
    st = r2.youtube_status()
    assert st["blocked"] and st["next_check"] == next_check and st["failures"] == 1
    assert 9 * MIN - 1 <= r2._yt_next - clock2.mono() <= 10 * MIN + 1
    assert [j.episode_id for j in r2._queues[PREPARE]] == [A, B] and all(j.yt_wait for j in r2._queues[PREPARE])
    r2.start()
    try:
        time.sleep(0.1)
        assert net.ingests().count(A) == 1  # no attempt before the saved retry time
        net.error = None
        advance(r2, clock2, 10 * MIN + 1)
        assert r2.wait_idle(10)
        assert not r2.youtube_status()["blocked"]
        assert "youtube" not in json.loads(path.read_text(encoding="utf-8"))
    finally:
        r2.stop(timeout=5)


# --- Y4: pause / resume --------------------------------------------------------------------------------------

def test_pause_while_blocked_and_resume(mk, tcfg):
    clock, net = Clock(), Net(blocked_error())
    runner = mk(clock)
    job = submit(runner, tcfg, A, net)
    wait_for(blocked_n(runner, 1))
    runner.pause("after")
    net.error = None
    advance(runner, clock, 15 * MIN)
    time.sleep(0.1)
    assert job.status == QUEUED and net.ingests() == [A]  # paused: nothing starts even when the retry is due
    runner.resume()
    assert runner.wait_idle(10) and job.status == DONE


# --- AC5: API ------------------------------------------------------------------------------------------------

def test_api_youtube_status_and_banner(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from auto_short.web import app as app_mod

    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 web=WebConfig(session_days=30))
    clock, net = Clock(), Net(blocked_error())
    runner = JobRunner(youtube_retry_seconds=15 * MIN, monotonic=clock.mono, wall=clock.wall)
    monkeypatch.setattr(app_mod, "LOGIN_DELAY", 0.01)
    app = app_mod.create_app(cfg, "pw", runner=runner, preflight=lambda c: None, post_preflight=lambda c: None,
                             pipeline=net)
    with TestClient(app, follow_redirects=False) as c:
        assert c.post("/login", data={"password": "pw"}).status_code == 303
        assert c.get("/api/episodes").json()["youtube"]["blocked"] is False
        assert c.post("/api/episodes", json={"url": f"https://youtu.be/{A}", "kinds": ["short"]}).status_code == 202
        wait_for(blocked_n(runner, 1))
        yt = c.get("/api/episodes").json()["youtube"]
        assert yt["blocked"] is True and yt["since"] and yt["next_check"]
        ep = c.get(f"/api/episodes/{A}").json()
        assert ep["youtube"]["blocked"] is True and ep["job"]["yt_wait"] is True and ep["job"]["status"] == "queued"
        net.error = None
        advance(runner, clock, 15 * MIN)
        assert runner.wait_idle(10)
        assert c.get("/api/episodes").json()["youtube"]["blocked"] is False
        assert c.get(f"/api/episodes/{A}").json()["youtube"]["blocked"] is False
        js = c.get("/static/app.js").text
        assert js.count("showYoutube(") >= 5 and "yt-banner" in js


def test_config_keys():
    assert WebConfig().youtube_retry_minutes == 15 and WebConfig().youtube_retry_max_minutes == 120
