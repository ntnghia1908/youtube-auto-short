"""CP13.2 "Chuẩn bị + HD" (docs/tasks/CP13.2-hd-first.md AC1-AC6): a prepare-only job per entry of a bộ kinh (episode
order), the enhance decision after ingest, the state "Đã chuẩn bị — chờ cắt" (not an error), "Chạy tiếp" (one entry /
the whole bộ) running AI -> render for the Short and the khai thị (render waits for the HD), the lease order by episode
number, the state surviving a restart. Fake stages, real tiny sources."""

import json
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

from enhance_helpers import FRAMES, SRC_H, T1, enhance_cfg, make_clip, make_segment, make_yt_episode, sha  # noqa: E402
from web_helpers import write_episode  # noqa: E402

PW = "pw"
PL = "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp"
V1, V2, V3 = "vid00000001", "vid00000002", "vid00000003"  # episodes 1, 2, 3
H1 = {"Authorization": f"Bearer {T1}"}
DONE_STAGE = {"status": "done", "artifacts": [], "inputs": [], "config_hash": "x", "started_at": None,
              "finished_at": None, "error": None}
EPISODE_OF = {V1: 1, V2: 2, V3: 3}


@pytest.fixture(autouse=True)
def _fast_login_delay(monkeypatch):
    monkeypatch.setattr(app_mod, "LOGIN_DELAY", 0.05)


@pytest.fixture(scope="module")
def low_source(tmp_path_factory):
    return make_clip(tmp_path_factory.mktemp("src") / "low.mp4", w=320, h=SRC_H, frames=FRAMES, audio=True)


@pytest.fixture(scope="module")
def segments(tmp_path_factory):
    d = tmp_path_factory.mktemp("segments")
    return [make_segment(d / f"s{n}.mp4", n) for n in range(4)]


def wait_for(pred, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.02)


def _mark(cfg, eid, *stages):
    ws = Path(cfg.workspace.dir) / eid
    m = json.loads((ws / "manifest.json").read_text())
    for s in stages:
        m["stages"][s] = dict(DONE_STAGE)
    (ws / "manifest.json").write_text(json.dumps(m))


class Env:
    def __init__(self, tmp_path, source):
        self.cfg = enhance_cfg(tmp_path)
        self.source = source
        self.calls: list[tuple[str, str]] = []  # (stage, episode id)
        self.preflights = 0
        self.render_hd: dict[str, bool] = {}  # episode id -> was the HD source there at render time
        self.svc = EnhanceService(self.cfg)
        self.runner = JobRunner()
        self.app = app_mod.create_app(self.cfg, PW, runner=self.runner, preflight=self._preflight,
                                      pipeline=self.pipeline(), render=lambda *a, **k: None,
                                      enhance_tokens={"w": T1}, enhance_service=self.svc,
                                      disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9))
        self.client = TestClient(self.app, follow_redirects=False)
        self._write_playlist()

    def _preflight(self, cfg):
        self.preflights += 1

    def _write_playlist(self):
        path = Path(self.cfg.workspace.dir) / "_playlists" / f"{PL}.json"
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = [{"index": i, "video_id": v, "title": f"Địa Tạng Kinh tập {EPISODE_OF[v]}/102 - Pháp Sư Tịnh Không",
                    "duration": 3000.0, "episode": str(EPISODE_OF[v]), "available": True}
                   for i, v in enumerate((V3, V1, V2), 1)]  # playlist order != episode order
        path.write_text(json.dumps({"schema_version": 1, "playlist_id": PL, "title": "Địa Tạng", "url": "u",
                                    "fetched_at": "2026-10-04T00:00:00Z", "entries": entries}), encoding="utf-8")

    def pipeline(self):
        def runner(stage):
            def run(target_or_id, config, **kw):
                eid = kw.get("episode_id") or (target_or_id.rsplit("/", 1)[-1] if stage == "ingest" else target_or_id)
                self.calls.append((stage, eid))
                if stage == "ingest":
                    if not (Path(config.workspace.dir) / eid / "manifest.json").is_file():
                        base = eid.split(".")[0]
                        ws = make_yt_episode(config, eid, with_enhance=False, ingest_only=True,
                                             template=self.source)
                        meta = ws.dir / "metadata.json"
                        doc = json.loads(meta.read_text())
                        doc["title"] = f"Địa Tạng Kinh tập {EPISODE_OF[base]}/102 - Pháp Sư Tịnh Không"
                        meta.write_text(json.dumps(doc, ensure_ascii=False))
                    return SimpleNamespace(episode_id=eid, ran=True, workspace=Path(config.workspace.dir) / eid)
                if stage == "render":
                    self.render_hd[eid] = st.has_hd(Path(config.workspace.dir) / eid)
                    write_episode(config, eid)
                    path = Path(config.render.output_dir) / eid / "render_manifest.json"
                    return SimpleNamespace(episode_id=eid, ran=True, path=path, rendered=2, clips=2, encoded=2,
                                           reused=0)
                if stage in ("transcript", "analysis", "selection", "titling"):
                    _mark(config, eid, stage)
                return SimpleNamespace(episode_id=eid, ran=True, path=None)
            return run

        return partial(run_pipeline, deps=StageDeps(runners={s: runner(s) for s in PIPELINE_STAGES}))

    def login(self):
        r = self.client.post("/login", json={"password": PW})
        return {COOKIE_NAME: r.cookies[COOKIE_NAME]}

    def view(self, cookie):
        return self.client.get(f"/api/playlists/{PL}", cookies=cookie).json()

    def entry(self, cookie, vid):
        return next(e for e in self.view(cookie)["entries"] if e["video_id"] == vid)

    def stages(self, eid):
        return [s for s, e in self.calls if e == eid]

    def prepare_all(self, cookie):
        r = self.client.post(f"/api/playlists/{PL}/prepare", cookies=cookie)
        assert r.status_code == 202, r.text
        return r.json()

    def finish_hd(self, eid, segments):
        r = self.client.post("/api/enhance/lease", json={"worker": "w", "gpu": "g"}, headers=H1)
        assert r.status_code == 200 and r.json()["episode_id"] == eid, r.text
        lid = r.json()["lease_id"]
        for n, data in enumerate(segments):
            r = self.client.put(f"/api/enhance/{lid}/seg/{n}", content=data, headers={**H1, "X-Sha256": sha(data)})
            assert r.status_code == 200, r.text


@pytest.fixture
def env(tmp_path, low_source):
    e = Env(tmp_path, low_source)
    with e.client:
        yield e


def _prepared(env, cookie):
    env.prepare_all(cookie)
    wait_for(lambda: all(env.entry(cookie, v)["state"] == "prepared" for v in (V1, V2, V3)))


# --- AC1, AC2, AC3 -----------------------------------------------------------------------------------------------

def test_prepare_queues_prepare_only_jobs_in_episode_order(env):
    cookie = env.login()
    out = env.prepare_all(cookie)
    assert out["episodes"] == 3 and out["queued"] == 3 and out["errors"] == []
    wait_for(lambda: all(env.entry(cookie, v)["state"] == "prepared" for v in (V1, V2, V3)))
    assert env.runner.wait_idle(5)
    assert [e for s, e in env.calls if s == "ingest"] == [V1, V2, V3]  # episode order, not playlist order
    assert {s for s, _ in env.calls} == {"ingest", "transcript", "analysis"}  # no selection / titling / render
    assert env.preflights == 0  # no Ollama
    assert sorted(j.episode_id for j in env.runner.jobs()) == [V1, V2, V3]  # no khai thị job
    for v in (V1, V2, V3):
        job = env.runner.latest(v)
        assert job.status == "done" and job.summary == "Đã chuẩn bị — chờ cắt"
        assert [s["stage"] for s in job.stages] == ["ingest", "transcript", "analysis"]
        doc = st.read(env.cfg.workspace.dir / v)  # E1 decision after ingest (a 240p source)
        assert doc["wanted"] is True and doc["reason"].startswith("height 240")
        assert not (env.cfg.workspace.dir / f"{v}.kt").exists()


def test_prepared_entry_is_not_an_error_and_offers_resume(env):
    cookie = env.login()
    _prepared(env, cookie)
    d = env.view(cookie)
    assert d["counts"]["prepared"] == 3 and d["counts"]["failed"] == 0 and d["counts"]["todo"] == 0
    for e in d["entries"]:
        assert e["state"] == "prepared" and e["group"] == "prepared" and e["action"] == "resume"
        assert e["resume_kinds"] == ["short", "khaithi"] and e["error"] is None
        assert e["hd"]["state"] == "queued" and e["hd"]["segments_total"] == 4
    assert env.client.get("/api/playlists", cookies=cookie).json()["playlists"][0]["failed"] == 0
    # a second "Chuẩn bị + HD" has nothing left to do
    again = env.client.post(f"/api/playlists/{PL}/prepare", cookies=cookie)
    assert again.status_code == 200 and again.json()["episodes"] == 0


def test_prepare_skips_entries_already_processed(env, low_source):
    cookie = env.login()
    write_episode(env.cfg, V2)
    out = env.prepare_all(cookie)
    assert out["episodes"] == 2
    wait_for(lambda: env.entry(cookie, V1)["state"] == "prepared" and env.entry(cookie, V3)["state"] == "prepared")
    assert V2 not in [e for _, e in env.calls]


# --- AC4 ---------------------------------------------------------------------------------------------------------

def test_resume_one_runs_ai_then_render_after_the_hd(env, segments):
    cookie = env.login()
    _prepared(env, cookie)
    entry = env.entry(cookie, V1)
    r = env.client.post("/api/episodes", json={"url": f"https://youtu.be/{V1}", "kinds": entry["resume_kinds"]},
                        cookies=cookie)
    assert r.status_code == 202
    kt = V1 + ".kt"
    wait_for(lambda: all((j := env.runner.latest(e)) is not None and j.hd_wait for e in (V1, kt)))
    assert {s for s, e in env.calls if e == V1} >= {"selection", "titling"} and "render" not in env.stages(V1)
    assert not (env.cfg.workspace.dir / V1 / "prepared.json").exists()
    assert env.entry(cookie, V1)["state"] == "processing" or env.entry(cookie, V1)["job"]["hd_wait"]
    env.finish_hd(V1, segments)  # the HD arrives: Short + khai thị render from it
    wait_for(lambda: all(env.runner.latest(e).status == "done" for e in (V1, kt)))
    assert env.render_hd == {V1: True, kt: True}
    assert env.entry(cookie, V2)["state"] == "prepared"  # the other episodes still wait


def test_resume_all_runs_every_prepared_entry_in_order(env):
    cookie = env.login()
    _prepared(env, cookie)
    before = len(env.calls)
    r = env.client.post(f"/api/playlists/{PL}/resume-prepared", json={}, cookies=cookie)
    assert r.status_code == 202 and r.json()["episodes"] == 3 and r.json()["queued"] == 6, r.text
    wait_for(lambda: all((j := env.runner.latest(e)) is not None and j.hd_wait
                         for v in (V1, V2, V3) for e in (v, v + ".kt")))
    selection = [e for s, e in env.calls[before:] if s == "selection"]
    assert [e for e in selection if not e.endswith(".kt")] == [V1, V2, V3]
    assert {e for e in selection if e.endswith(".kt")} == {V1 + ".kt", V2 + ".kt", V3 + ".kt"}
    assert env.client.post(f"/api/playlists/{PL}/resume-prepared", json={"min_minutes": 9, "max_minutes": 3},
                           cookies=cookie).status_code == 422
    assert env.client.post("/api/playlists/PLnotexistnotexistnotexist00/resume-prepared",
                           cookies=cookie).status_code == 404


# --- AC5 ---------------------------------------------------------------------------------------------------------

def test_lease_order_follows_the_episode_number_within_a_series(tmp_path, low_source):
    cfg = enhance_cfg(tmp_path)
    times = iter(f"2026-10-04T00:00:{n:02d}Z" for n in range(60))
    order = {"vidB0000003": 3, "vidB0000001": 1, "vidB0000002": 2}  # asked for HD in this (wrong) order: 3, 1, 2
    for eid, n in order.items():
        ws = make_yt_episode(cfg, eid, template=low_source)
        meta = ws.dir / "metadata.json"
        doc = json.loads(meta.read_text())
        doc["title"] = f"Địa Tạng Kinh tập {n}/102 - Pháp Sư Tịnh Không"
        meta.write_text(json.dumps(doc, ensure_ascii=False))
        d = st.read(ws.dir)
        d["wanted_at"] = next(times)
        st.write(ws.dir, d)
    other = make_yt_episode(cfg, "vidC0000001", template=low_source)  # no known series: its own group, asked last
    d = st.read(other.dir)
    d["wanted_at"] = next(times)
    st.write(other.dir, d)
    svc = EnhanceService(cfg)
    got = []
    for _ in range(4):
        lease = svc.lease("w1")
        assert lease is not None
        got.append(lease["episode_id"])
        svc.release("w1", lease["lease_id"], "done")  # frees it; mark finished so the next lease takes another one
        d = st.read(cfg.workspace.dir / lease["episode_id"])
        d.update(state=st.DONE, lease=None)
        st.write(cfg.workspace.dir / lease["episode_id"], d)
    assert got == ["vidB0000001", "vidB0000002", "vidB0000003", "vidC0000001"]


def test_waiting_for_hd_still_goes_first(tmp_path, low_source):
    cfg = enhance_cfg(tmp_path)
    for eid, n, at in (("vidB0000001", 1, "00"), ("vidB0000002", 2, "01")):
        ws = make_yt_episode(cfg, eid, template=low_source)
        meta = ws.dir / "metadata.json"
        doc = json.loads(meta.read_text())
        doc["title"] = f"Địa Tạng Kinh tập {n}/102 - Pháp Sư Tịnh Không"
        meta.write_text(json.dumps(doc, ensure_ascii=False))
        d = st.read(ws.dir)
        d.update(wanted_at=f"2026-10-04T00:00:{at}Z", waiting_hd=(n == 2))
        st.write(ws.dir, d)
    assert EnhanceService(cfg).lease("w1")["episode_id"] == "vidB0000002"


# --- AC6 ---------------------------------------------------------------------------------------------------------

def test_queued_prepare_jobs_survive_a_restart(tmp_path, low_source):
    first = Env(tmp_path, low_source)
    with first.client:
        cookie = first.login()
        first.runner.pause("after")  # nothing starts: the three jobs stay queued
        first.prepare_all(cookie)
    saved = json.loads((first.cfg.workspace.dir / ".web_queue.json").read_text())
    assert [e["episode_id"] for e in saved["lanes"]["prepare"]] == [V1, V2, V3]
    assert all(e["spec"]["prepare_only"] is True for e in saved["lanes"]["prepare"])
    second = Env(tmp_path, low_source)
    with second.client:
        cookie = second.login()
        second.runner.resume()
        wait_for(lambda: all(second.entry(cookie, v)["state"] == "prepared" for v in (V1, V2, V3)))
        assert {s for s, _ in second.calls} == {"ingest", "transcript", "analysis"}  # still no AI / render


def test_prepared_state_survives_a_restart(tmp_path, low_source):
    first = Env(tmp_path, low_source)
    with first.client:
        cookie = first.login()
        _prepared(first, cookie)
    second = Env(tmp_path, low_source)
    with second.client:
        cookie = second.login()
        d = second.view(cookie)
        assert d["counts"]["prepared"] == 3 and d["counts"]["failed"] == 0
        assert all(e["state"] == "prepared" and e["action"] == "resume" for e in d["entries"])
