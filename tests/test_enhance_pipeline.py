"""CP13.1b: the pipeline with enhance (E1 decision after ingest, E6 "đợi HD" after titling, auto render when the HD is
ready, "Render bằng bản gốc", already rendered / published episodes, khai thị, restart) - AC1, AC4, AC9. Fake stages,
real ffmpeg for the tiny sources / segments."""

import json
import os
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.enhance import state as st  # noqa: E402
from auto_short.enhance.service import EnhanceService  # noqa: E402
from auto_short.pipeline import PIPELINE_STAGES, StageDeps, run_pipeline  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.auth import COOKIE_NAME  # noqa: E402
from auto_short.web.jobs import JobRunner  # noqa: E402

from enhance_helpers import FRAMES, SRC_H, T1, enhance_cfg, make_clip, make_segment, sha  # noqa: E402
from web_helpers import write_episode  # noqa: E402

pytestmark = pytest.mark.usefixtures("_video_template")
PW = "mật-khẩu"
H1 = {"Authorization": f"Bearer {T1}"}
VID, VID2 = "vid00000001", "vid00000002"
HIGH = "hi000000001"  # a 720p source: not enhanced


@pytest.fixture(autouse=True)
def _fast_login_delay(monkeypatch):
    monkeypatch.setattr(app_mod, "LOGIN_DELAY", 0.05)


@pytest.fixture(scope="module")
def segments(tmp_path_factory):
    d = tmp_path_factory.mktemp("segments")
    return [make_segment(d / f"s{n}.mp4", n) for n in range(4)]


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    d = tmp_path_factory.mktemp("sources")
    return {"low": make_clip(d / "low.mp4", w=320, h=SRC_H, frames=FRAMES, audio=True),
            "high": make_clip(d / "high.mp4", w=960, h=720, frames=FRAMES, audio=True)}


def wait_for(pred, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.02)


class Env:
    """The web app with fake pipeline stages (ingest builds a real tiny YouTube-like workspace) and a fake render."""

    def __init__(self, tmp_path, sources, **cfg_kw):
        self.cfg = enhance_cfg(tmp_path, **cfg_kw)
        self.sources = sources
        self.render_calls: list[str] = []
        self.stage_calls: list[tuple[str, str]] = []
        self.svc = EnhanceService(self.cfg)
        self.runner = JobRunner()
        self.app = app_mod.create_app(self.cfg, PW, runner=self.runner, preflight=lambda c: None,
                                      pipeline=self.pipeline(), render=self.fake_render,
                                      enhance_tokens={"w": T1}, enhance_service=self.svc)
        self.client = TestClient(self.app, follow_redirects=False)

    def fake_render(self, eid, cfg, **kw):
        self.render_calls.append(eid)
        write_episode(cfg, eid)
        make_youtube(cfg, eid, self.sources["low"], keep_render=True)
        return SimpleNamespace(episode_id=eid, ran=True, rendered=2, clips=2, encoded=2, reused=0)

    def pipeline(self):
        def runner(stage):
            def run(target_or_id, config, **kw):
                self.stage_calls.append((stage, kw.get("episode_id") or target_or_id))
                if stage == "ingest":
                    eid = kw.get("episode_id") or target_or_id.rsplit("/", 1)[-1]
                    make_youtube(config, eid, self.sources["high" if eid.startswith("hi") else "low"],
                                 stages=("ingest",))
                    return SimpleNamespace(episode_id=eid, ran=True, workspace=Path(config.workspace.dir) / eid)
                if stage == "titling":
                    ws = Path(config.workspace.dir) / target_or_id
                    m = json.loads((ws / "manifest.json").read_text())
                    for s in ("transcript", "analysis", "selection", "titling"):
                        m["stages"][s] = {"status": "done", "artifacts": [], "inputs": [], "config_hash": "x",
                                          "started_at": None, "finished_at": None, "error": None}
                    (ws / "manifest.json").write_text(json.dumps(m))
                if stage == "render":
                    self.render_calls.append(target_or_id)
                    write_episode(config, target_or_id)
                    make_youtube(config, target_or_id, self.sources["low"], keep_render=True)
                    path = Path(config.render.output_dir) / target_or_id / "render_manifest.json"
                    return SimpleNamespace(episode_id=target_or_id, ran=True, path=path, rendered=2, clips=2,
                                           encoded=2, reused=0)
                return SimpleNamespace(episode_id=target_or_id, ran=True, path=None)
            return run

        return partial(run_pipeline, deps=StageDeps(runners={s: runner(s) for s in PIPELINE_STAGES}))

    def login(self):
        r = self.client.post("/login", json={"password": PW})
        return {COOKIE_NAME: r.cookies[COOKIE_NAME]}

    def submit(self, vid, cookie, **body):
        r = self.client.post("/api/episodes", json={"url": f"https://youtu.be/{vid}", "kinds": ["short"], **body},
                             cookies=cookie)
        assert r.status_code in (200, 202), r.text
        return r

    def episode(self, eid, cookie):
        return self.client.get(f"/api/episodes/{eid}", cookies=cookie).json()

    def finish_hd(self, eid, segments):
        """Play the worker: lease the video, upload every segment."""
        r = self.client.post("/api/enhance/lease", json={"worker": "w", "gpu": "g"}, headers=H1)
        assert r.status_code == 200 and r.json()["episode_id"] == eid, r.text
        lid = r.json()["lease_id"]
        for n, data in enumerate(segments):
            r = self.client.put(f"/api/enhance/{lid}/seg/{n}", content=data,
                                headers={**H1, "X-Sha256": sha(data)})
            assert r.status_code == 200, r.text


def make_youtube(cfg, eid, template, *, stages=("ingest", "transcript", "analysis", "selection", "titling"),
                 keep_render=False):
    """Make / refresh the workspace ``eid`` as a YouTube episode with the real (tiny) source ``template``; with
    ``keep_render`` the render manifest / output written by ``write_episode`` stay."""
    root = Path(cfg.workspace.dir) / eid
    root.mkdir(parents=True, exist_ok=True)
    if (root / "manifest.json").is_file() and not keep_render:
        return
    from auto_short.hashing import fingerprint
    from auto_short.workspace import Workspace
    import shutil
    ws = Workspace(Path(cfg.workspace.dir), eid)
    src = ws.dir / "source.mp4"
    if not src.exists():
        shutil.copy2(template, src)
    fp = fingerprint(src)
    info = st.probe_video(src)
    (ws.dir / "metadata.json").write_text(json.dumps({"schema_version": 1, "episode_id": eid, "title": "T",
                                                      "duration": info["duration"], "width": info["width"],
                                                      "height": info["height"]}), encoding="utf-8")
    manifest = ws.load_manifest() or ws.new_manifest({})
    manifest["source"] = {"kind": "youtube", "uri": f"https://youtu.be/{eid.split('.')[0]}", "path": "source.mp4",
                          "sha256": fp.sha256, "size": fp.size, "mtime_ns": fp.mtime_ns}
    for s in stages:
        manifest["stages"].setdefault(s, {"status": "done", "artifacts": [], "inputs": [], "config_hash": "x",
                                          "started_at": None, "finished_at": None, "error": None})
    ws.save_manifest(manifest)


@pytest.fixture
def env(tmp_path, sources):
    e = Env(tmp_path, sources)
    with e.client:
        yield e


# --- E1 / E6 / AC1, AC4 ------------------------------------------------------------------------------------------

def test_low_resolution_video_waits_for_hd_and_does_not_hold_a_lane(env, segments):
    cookie = env.login()
    env.submit(VID, cookie)
    wait_for(lambda: (j := env.runner.latest(VID)) is not None and j.hd_wait)
    job = env.runner.latest(VID)
    doc = st.read(env.cfg.workspace.dir / VID)
    assert doc["wanted"] is True and doc["waiting_hd"] is True and doc["reason"].startswith("height 240")
    assert job.status == "running" and job.lane is None and job.waiting and job.stage == "render"
    assert env.runner.wait_idle(5) and env.runner.running() == {}  # no lane is occupied
    assert not env.render_calls
    view = env.episode(VID, cookie)
    assert view["job"]["hd_wait"] is True and view["enhance"]["state"] == "queued" and view["enhance"]["waiting_hd"]
    assert env.client.get("/api/enhance/status", cookies=cookie).json()["counts"]["waiting_hd"] == 1
    assert env.client.get("/api/queue", cookies=cookie).json()["pending"] == 0
    # a video that needs no enhance goes straight through meanwhile (the lanes are free)
    env.submit(HIGH, cookie)
    wait_for(lambda: env.runner.latest(HIGH).status == "done")
    assert st.read(env.cfg.workspace.dir / HIGH)["wanted"] is False and HIGH in env.render_calls
    # the same video cannot be submitted twice, nor edited, while it waits
    assert env.client.post("/api/episodes", json={"url": f"https://youtu.be/{VID}", "kinds": ["short"]},
                           cookies=cookie).status_code == 200  # existing active job returned
    # the HD arrives -> the parked job joins the render queue, renders (the fake render uses the HD source) and ends
    env.finish_hd(VID, segments)
    wait_for(lambda: env.runner.latest(VID).status == "done")
    assert env.render_calls.count(VID) == 1 and env.runner.latest(VID).hd_wait is False
    doc = st.read(env.cfg.workspace.dir / VID)
    assert doc["state"] == st.DONE and doc["waiting_hd"] is False
    assert st.hd_fingerprint(env.cfg.workspace.dir / VID) is not None
    assert env.client.get("/api/enhance/status", cookies=cookie).json()["counts"]["waiting_hd"] == 0


def test_render_with_the_original_runs_at_once(env):
    cookie = env.login()
    env.submit(VID, cookie)
    wait_for(lambda: (j := env.runner.latest(VID)) is not None and j.hd_wait)
    r = env.client.post(f"/api/episodes/{VID}/enhance/render-original", cookies=cookie)
    assert r.status_code == 200 and r.json()["outcome"][VID] == "unparked"
    wait_for(lambda: env.runner.latest(VID).status == "done")
    doc = st.read(env.cfg.workspace.dir / VID)
    assert doc["wanted"] is False and doc["override"] is True and doc["waiting_hd"] is False
    assert env.render_calls == [VID] and not st.hd_path(env.cfg.workspace.dir / VID).exists()
    # a later ingest of the same video keeps the choice
    assert st.decide(env.cfg, VID)["wanted"] is False


def test_switching_enhance_off_releases_the_waiting_job_and_on_again(env):
    cookie = env.login()
    env.submit(VID, cookie)
    wait_for(lambda: (j := env.runner.latest(VID)) is not None and j.hd_wait)
    r = env.client.post(f"/api/episodes/{VID}/enhance", json={"enabled": False}, cookies=cookie)
    assert r.status_code == 200 and r.json()["enhance"]["wanted"] is False
    wait_for(lambda: env.runner.latest(VID).status == "done")
    assert env.client.post(f"/api/episodes/{VID}/enhance", json={"enabled": True}, cookies=cookie) \
        .json()["enhance"]["state"] == "queued"
    assert env.client.post(f"/api/episodes/{VID}/enhance", json="x", cookies=cookie).status_code == 422
    assert env.client.post("/api/episodes/nope000000x/enhance", json={"enabled": True}, cookies=cookie).status_code == 404


def test_enhance_off_in_config_changes_nothing(tmp_path, sources):
    e = Env(tmp_path, sources, enabled=False)
    with e.client:
        cookie = e.login()
        e.submit(VID, cookie)
        wait_for(lambda: e.runner.latest(VID).status == "done")
        assert st.read(e.cfg.workspace.dir / VID) is None and e.render_calls == [VID]
        view = e.episode(VID, cookie)["enhance"]
        assert view["enabled"] is False and view["exists"] is False and view["can_enable"] is False
        assert e.client.post(f"/api/episodes/{VID}/enhance", json={"enabled": True}, cookies=cookie).status_code == 409


def test_deleting_an_episode_that_waits_for_hd(env):
    cookie = env.login()
    env.submit(VID, cookie)
    wait_for(lambda: (j := env.runner.latest(VID)) is not None and j.hd_wait)
    r = env.client.delete(f"/api/episodes/{VID}", cookies=cookie)
    assert r.status_code == 200 and not (env.cfg.workspace.dir / VID).exists()
    assert env.runner.parked() == []
    # a worker holding a lease of it is told 409
    assert env.client.post("/api/enhance/lease", json={}, headers=H1).status_code == 204


# --- E1: khai thị shares the video's enhance ----------------------------------------------------------------------

def test_khaithi_waits_with_its_video_and_gets_the_hd_by_hard_link(env, segments):
    cookie = env.login()
    r = env.client.post("/api/episodes", json={"url": f"https://youtu.be/{VID}", "kinds": ["short", "khaithi"]},
                        cookies=cookie)
    assert r.status_code == 202
    kt = VID + ".kt"
    wait_for(lambda: all((j := env.runner.latest(e)) is not None and j.hd_wait for e in (VID, kt)))
    kdoc = st.read(env.cfg.workspace.dir / kt)
    assert kdoc["follows"] == VID and kdoc["wanted"] is True and kdoc["waiting_hd"] is True
    # a single enhance for the video: the worker is offered only the Short episode
    env.finish_hd(VID, segments)
    wait_for(lambda: all(env.runner.latest(e).status == "done" for e in (VID, kt)))
    assert os.path.samefile(st.hd_path(env.cfg.workspace.dir / VID), st.hd_path(env.cfg.workspace.dir / kt))
    assert st.read(env.cfg.workspace.dir / kt)["state"] == st.DONE
    assert sorted(env.render_calls) == sorted([VID, kt])


# --- restart ------------------------------------------------------------------------------------------------------

def test_waiting_job_survives_a_restart(tmp_path, sources, segments):
    first = Env(tmp_path, sources)
    with first.client:
        cookie = first.login()
        first.submit(VID, cookie)
        wait_for(lambda: (j := first.runner.latest(VID)) is not None and j.hd_wait)
    saved = json.loads((first.cfg.workspace.dir / ".web_queue.json").read_text())
    assert [e["episode_id"] for e in saved["parked"]] == [VID] and saved["lanes"]["render"] == []
    second = Env(tmp_path, sources)
    with second.client:
        cookie = second.login()
        job = second.runner.latest(VID)
        assert job is not None and job.hd_wait and job.status == "running"
        assert second.episode(VID, cookie)["job"]["hd_wait"] is True
        second.finish_hd(VID, segments)
        wait_for(lambda: second.runner.latest(VID).status == "done")
        assert second.render_calls == [VID]


def test_parked_job_whose_hd_is_already_there_continues_at_start(tmp_path, sources, segments):
    first = Env(tmp_path, sources)
    with first.client:
        cookie = first.login()
        first.submit(VID, cookie)
        wait_for(lambda: (j := first.runner.latest(VID)) is not None and j.hd_wait)
        first.runner.pause("after")  # nothing else may start: the assembly will run only after the restart
        first.finish_hd(VID, segments)
        assert st.read(first.cfg.workspace.dir / VID)["state"] == st.ASSEMBLING
    second = Env(tmp_path, sources)
    with second.client:
        second.runner.resume()
        wait_for(lambda: second.runner.latest(VID) is not None and second.runner.latest(VID).status == "done")
        assert st.read(second.cfg.workspace.dir / VID)["state"] == st.DONE


# --- already rendered episodes (E6 last paragraph) ----------------------------------------------------------------

def _rendered(env, eid="old00000001"):
    write_episode(env.cfg, eid)
    make_youtube(env.cfg, eid, env.sources["low"], keep_render=True)
    return eid


def test_rendered_episode_is_rendered_again_when_nothing_is_published(env, segments):
    cookie = env.login()
    eid = _rendered(env)
    r = env.client.post(f"/api/episodes/{eid}/enhance", json={"enabled": True}, cookies=cookie)
    assert r.status_code == 200 and r.json()["enhance"]["state"] == "queued" and not env.render_calls
    env.finish_hd(eid, segments)
    wait_for(lambda: env.render_calls == [eid])  # re-rendered by itself
    wait_for(lambda: env.runner.latest(eid).status == "done")
    assert st.read(env.cfg.workspace.dir / eid)["state"] == st.DONE


def test_published_shorts_are_kept_and_the_button_renders_the_hd(env, segments):
    cookie = env.login()
    eid = _rendered(env)
    assert env.client.post(f"/api/episodes/{eid}/shorts/k01/published", json={"value": True}, cookies=cookie) \
        .status_code == 200
    env.client.post(f"/api/episodes/{eid}/enhance", json={"enabled": True}, cookies=cookie)
    env.finish_hd(eid, segments)
    wait_for(lambda: st.hd_fingerprint(env.cfg.workspace.dir / eid) is not None)
    wait_for(lambda: env.runner.latest_enhance(eid).status == "done")
    assert env.runner.wait_idle(10) and env.render_calls == []  # no automatic render
    view = env.episode(eid, cookie)["enhance"]
    assert view["state"] == "done" and view["can_rerender"] is True and view["rendered_from_hd"] is False
    r = env.client.post(f"/api/episodes/{eid}/enhance/rerender", cookies=cookie)
    assert r.status_code == 202
    wait_for(lambda: env.render_calls == [eid])
    # nothing to re-render without an HD source
    other = _rendered(env, "old00000002")
    assert env.client.post(f"/api/episodes/{other}/enhance/rerender", cookies=cookie).status_code == 409


# --- W9 S5 / E5 / AC6: clean-up ---------------------------------------------------------------------------------

def test_auto_cleanup_skips_enhanced_videos_and_manual_cleanup_keeps_the_hd(tmp_path, sources):
    from dataclasses import replace
    from auto_short.config import StorageConfig
    e = Env(tmp_path, sources)
    e.cfg = replace(e.cfg, storage=StorageConfig(auto_archive=True, auto_archive_grace_minutes=0))
    e.app = app_mod.create_app(e.cfg, PW, runner=e.runner, preflight=lambda c: None, pipeline=e.pipeline(),
                               render=e.fake_render, enhance_tokens={"w": T1}, enhance_service=e.svc)
    e.client = TestClient(e.app, follow_redirects=False)
    with e.client:
        cookie = e.login()
        ids = {"plain": "pla00000001", "hd": "hd000000001", "pending": "pen00000001"}
        for eid in ids.values():
            _rendered(e, eid)
            for clip in ("k01", "k02"):
                assert e.client.post(f"/api/episodes/{eid}/shorts/{clip}/published", json={"value": True},
                                     cookies=cookie).status_code == 200
        root = e.cfg.workspace.dir
        # "hd": a finished HD source; "pending": enhance wanted, not finished (decision exists, no HD yet)
        doc = st.decide(replace(e.cfg, enhance=replace(e.cfg.enhance, enabled=True)), ids["hd"], force=True)
        hd = st.hd_path(root / ids["hd"])
        make_clip(hd, w=640, h=480, frames=FRAMES, audio=True)
        from auto_short.hashing import sha256_file
        doc.update(state=st.DONE, source_hd_sha256=sha256_file(hd), source_hd_size=hd.stat().st_size,
                   source_hd_mtime_ns=hd.stat().st_mtime_ns)
        st.write(root / ids["hd"], doc)
        st.decide(e.cfg, ids["pending"], force=True)
        done = e.app.state.auto_archive_pass()
        assert done == [ids["plain"]]  # only the video without HD / pending enhance
        assert not (root / ids["plain"] / "source.mp4").exists()
        assert (root / ids["hd"] / "source.mp4").exists() and (root / ids["pending"] / "source.mp4").exists()
        # the manual "Dọn video nguồn" removes only the original source: the HD source stays
        r = e.client.post(f"/api/episodes/{ids['hd']}/archive", cookies=cookie)
        assert r.status_code == 200 and r.json()["removed"] == ["source.mp4"]
        assert hd.is_file() and st.hd_fingerprint(root / ids["hd"]) is not None
        assert e.app.state.auto_archive_pass() == []
