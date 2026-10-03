"""CP8.5 web review workflow: delete / restore a Short (X2), delete an episode (X3), "Đã đăng" + filters (X4),
download names in the episode view (X1). Fake render except the last test (real ffmpeg)."""

import io
import json
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.episodes import publish_group  # noqa: E402

from render_helpers import EID, TITLES, make_render_episode, write_docs  # noqa: E402
from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
BASE = f"/api/episodes/{EID}/shorts"


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"))


@pytest.fixture
def episode(tcfg, tmp_path):
    tmpl = tmp_path / "fake.mp4"
    tmpl.write_bytes(b"not a video")
    ws = make_render_episode(tcfg.workspace.dir, tmpl)
    write_docs(ws)
    write_episode(tcfg, EID, titles=TITLES)
    return ws


class FakeRender:
    def __init__(self, gate=None):
        self.calls, self.gate = [], gate

    def __call__(self, episode_id, config):
        self.calls.append(episode_id)
        if self.gate is not None:
            assert self.gate.wait(10)
        return SimpleNamespace(ran=True, rendered=2, clips=2, encoded=0, reused=2)


def client(cfg, render=None, pipeline=None, preflight=lambda c: None):
    app = app_mod.create_app(cfg, PW, preflight=preflight, render=render or FakeRender(),
                             pipeline=pipeline or fake_pipeline([]))
    c = TestClient(app, follow_redirects=False)
    return c


def _login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def _review(ws):
    p = ws.dir / "review.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


# --- X2 delete / restore a Short -------------------------------------------------------------------------------

def test_delete_restore_short_queue_render(tcfg, episode):
    render = FakeRender()
    with client(tcfg, render=render) as c:
        _login(c)
        r = c.post(f"{BASE}/k02/delete")
        assert r.status_code == 202 and r.json()["changed"] is True
        assert r.json()["job"]["kind"] == "render" and r.json()["job"]["clip_ids"] == ["k02"]
        assert c.app.state.runner.wait_idle(5) and render.calls == [EID]
        assert _review(episode)["rejected"] == [{"clip_id": "k02", "candidate_id": "c00002"}]
        k02 = c.get(f"/api/episodes/{EID}").json()["shorts"][1]
        # the fake render did not rewrite render_manifest.json: review says deleted, the file is still there
        assert k02["rejected"] is True and k02["deleted"] is False

        r = c.post(f"{BASE}/k02/delete")
        assert r.status_code == 202 and r.json()["changed"] is False
        assert c.app.state.runner.wait_idle(5)
        r = c.post(f"{BASE}/k02/restore")
        assert r.status_code == 202 and r.json()["changed"] is True
        assert c.app.state.runner.wait_idle(5)
        assert "rejected" not in _review(episode) and len(render.calls) == 3

        assert c.post(f"{BASE}/k99/delete").status_code == 422
        assert c.post(f"{BASE}/..%2Fx/delete").status_code == 404
        assert c.post(f"/api/episodes/..%2F..%2Fetc/shorts/k01/restore").status_code == 404
    with client(tcfg) as c:  # needs login
        assert c.post(f"{BASE}/k01/delete").status_code == 401


def test_delete_short_refused_while_job_active_but_publish_allowed(tcfg, episode):
    gate = threading.Event()
    with client(tcfg, render=FakeRender(gate=gate)) as c:
        _login(c)
        assert c.post(f"{BASE}/k01/delete").status_code == 202
        before = _review(episode)
        for path in (f"{BASE}/k02/delete", f"{BASE}/k01/restore"):
            r = c.post(path)
            assert r.status_code == 409 and r.json()["job"]["kind"] == "render"
        assert _review(episode) == before
        assert c.get(f"/api/episodes/{EID}").json()["shorts"][0]["rendering"] is True
        # "Đã đăng" is user state: allowed while a job runs, no job
        r = c.post(f"{BASE}/k02/published", json={"value": True})
        assert r.status_code == 200 and r.json()["published"] is True
        assert len(c.app.state.runner.jobs()) == 1
        # deleting the episode is refused too
        r = c.delete(f"/api/episodes/{EID}")
        assert r.status_code == 409 and episode.dir.is_dir()
        gate.set()
        assert c.app.state.runner.wait_idle(5)


# --- X4 published --------------------------------------------------------------------------------------------

def test_published_tick_persists_filters_and_is_not_a_render_input(tcfg, episode):
    manifest_before = episode.manifest_path.read_bytes()
    with client(tcfg) as c:
        _login(c)
        assert c.post(f"{BASE}/k01/published", json={"value": True}).json()["published"] is True
        assert c.post(f"{BASE}/k02/published", json={"value": True}).status_code == 200
        assert c.post(f"{BASE}/k02/published", json={"value": False}).json()["published"] is False
        assert c.post(f"{BASE}/k02/published", json={"value": "yes"}).status_code == 422
        assert c.post(f"{BASE}/k02/published", json={}).status_code == 422
        assert c.post(f"{BASE}/k99/published", json={"value": True}).status_code == 422
        assert c.app.state.runner.jobs() == []  # no job
    assert episode.manifest_path.read_bytes() == manifest_before  # render not stale
    assert not (episode.dir / "review.json").exists()
    with client(tcfg) as c:  # new server (restart): the tick is still there
        _login(c)
        d = c.get(f"/api/episodes/{EID}").json()
        k01, k02 = d["shorts"]
        assert (k01["published"], k01["published_stale"]) == (True, False) and k01["published_at"]
        assert k02["published"] is False and d["published"] == 1 and d["rendered"] == 2
        item = c.get("/api/episodes").json()["episodes"][0]
        assert (item["published"], item["shorts"], item["publish_group"]) == (1, 2, "todo")
        c.post(f"{BASE}/k02/published", json={"value": True})
        item = c.get("/api/episodes").json()["episodes"][0]
        assert (item["published"], item["publish_group"]) == (2, "done")

    # the title of k01 changes in the file (re-render) -> "đã đăng bản cũ"
    rm_path = Path(tcfg.render.output_dir) / EID / "render_manifest.json"
    rm = json.loads(rm_path.read_text(encoding="utf-8"))
    rm["shorts"][0]["sha256"] = "f" * 64
    rm["shorts"][0]["title"] = "Tiêu đề mới"
    rm_path.write_text(json.dumps(rm, ensure_ascii=False), encoding="utf-8")
    with client(tcfg) as c:
        _login(c)
        k01 = c.get(f"/api/episodes/{EID}").json()["shorts"][0]
        assert (k01["published"], k01["published_stale"]) == (True, True)
        r = c.post(f"{BASE}/k01/published", json={"value": True}).json()  # tick the new version
        assert (r["published"], r["stale"]) == (True, False)


@pytest.mark.parametrize("item, group", [
    # CP8.7: "done" = the derived Xong (L4, ``complete``), not only x = y
    ({"shorts": 3, "published": 3, "complete": True, "stages_done": 6, "stages_total": 6}, "done"),
    ({"shorts": 3, "published": 3, "complete": False, "stages_done": 6, "stages_total": 6}, "todo"),
    ({"shorts": 0, "published": 0, "complete": True, "stages_done": 6, "stages_total": 6}, "done"),
    ({"shorts": 3, "published": 1, "stages_done": 6, "stages_total": 6}, "todo"),
    ({"shorts": 0, "published": 0, "stages_done": 6, "stages_total": 6, "job": None}, None),
    ({"shorts": 0, "published": 0, "stages_done": 2, "stages_total": 6, "failed": "selection"}, "todo"),
    ({"shorts": 0, "published": 0, "stages_done": 0, "stages_total": 6, "job": {"status": "queued"}}, "todo"),
    ({"shorts": 0, "published": 0, "stages_done": 6, "stages_total": 6, "job": {"status": "running"}}, "todo"),
])
def test_publish_group(item, group):
    assert publish_group(item) == group


# --- X1 names in the view, deleted Shorts hidden from the zip ----------------------------------------------------

def test_view_download_names_and_deleted_short(tcfg, episode):
    titles_doc = json.loads((episode.dir / "titles.json").read_text(encoding="utf-8"))
    titles_doc["header"]["fields"] = {"episode": "9"}
    (episode.dir / "titles.json").write_text(json.dumps(titles_doc, ensure_ascii=False), encoding="utf-8")
    rm_path = Path(tcfg.render.output_dir) / EID / "render_manifest.json"
    rm = json.loads(rm_path.read_text(encoding="utf-8"))
    rm["shorts"][0].update(status="skipped", skip_reason="rejected", file=None, sha256=None)
    rm_path.write_text(json.dumps(rm, ensure_ascii=False), encoding="utf-8")
    with client(tcfg) as c:
        _login(c)
        d = c.get(f"/api/episodes/{EID}").json()
        k01, k02 = d["shorts"]
        assert k01["deleted"] is True and k01["video_url"] is None and k01["download_name"] is None
        assert k02["download_name"] == "T9_S02_Mỗi suy nghĩ đều là tội lỗi.mp4"  # number kept, '?' dropped
        assert (d["deleted"], d["rendered"], d["zip_name"]) == (1, 1, "Tập9_Shorts.zip")
        with zipfile.ZipFile(io.BytesIO(c.get(d["zip_url"]).content)) as zf:
            assert zf.namelist() == ["T9_S02_Mỗi suy nghĩ đều là tội lỗi.mp4"]
        assert c.get(f"/files/{EID}/k01.mp4").status_code == 404
        r = c.post(f"{BASE}/k01/published", json={"value": True})
        assert r.status_code == 422 and "no rendered file" in r.json()["detail"]


# --- X3 delete an episode ------------------------------------------------------------------------------------

def test_delete_episode(tcfg, episode, tmp_path):
    write_episode(tcfg, "otherEpisode1")
    out = Path(tcfg.render.output_dir) / EID
    with client(tcfg) as c:
        _login(c)
        c.post(f"{BASE}/k01/published", json={"value": True})
        for eid in ("..", ".hidden", "a" * 200, "x%2F..%2Fy", "nope"):
            assert c.delete(f"/api/episodes/{eid}").status_code == 404, eid
        assert c.delete("/api/episodes/..%2F..%2Ftmp").status_code == 404
        r = c.delete(f"/api/episodes/{EID}")
        assert r.status_code == 200 and r.json() == {"deleted": EID}
        assert not episode.dir.exists() and not out.exists()
        assert [e["id"] for e in c.get("/api/episodes").json()["episodes"]] == ["otherEpisode1"]
        assert c.get(f"/api/episodes/{EID}").status_code == 404
        assert c.delete(f"/api/episodes/{EID}").status_code == 404
        assert (Path(tcfg.workspace.dir) / "otherEpisode1").is_dir()
        assert (Path(tcfg.workspace.dir) / ".web_secret").is_file()  # the session key stays
    with client(tcfg) as c:
        assert c.delete("/api/episodes/otherEpisode1").status_code == 401
    assert (Path(tcfg.workspace.dir) / "otherEpisode1").is_dir()


def test_delete_episode_after_pipeline_job_forgets_it(tcfg):
    with client(tcfg) as c:
        _login(c)
        assert c.post("/api/episodes", json={"url": "https://youtu.be/abcdefghijk", "kinds": ["short"]}
                      ).status_code == 202
        assert c.app.state.runner.wait_idle(5)
        assert c.get("/api/episodes/abcdefghijk").json()["job"]["status"] == "done"
        assert c.delete("/api/episodes/abcdefghijk").status_code == 200
        assert c.get("/api/episodes/abcdefghijk").status_code == 404
        assert c.get("/api/episodes").json()["episodes"] == []


def test_delete_episode_refused_while_pipeline_queued(tcfg, episode):
    gate = threading.Event()
    with client(tcfg, pipeline=fake_pipeline([], gate=gate)) as c:
        _login(c)
        assert c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}"}).status_code == 202
        r = c.delete(f"/api/episodes/{EID}")
        assert r.status_code == 409 and r.json()["job"]["kind"] == "pipeline"
        assert episode.dir.is_dir()
        gate.set()
        assert c.app.state.runner.wait_idle(5)


# --- real render (ffmpeg): delete -> skipped/rejected, others reused; restore byte-identical --------------------

@pytest.fixture(scope="module")
def real_source(tmp_path_factory):
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    from render_helpers import make_source
    return make_source(tmp_path_factory.mktemp("web-cp85") / "src.mp4")


def test_delete_restore_real_render(tmp_path, real_source):
    from dataclasses import replace as dc_replace

    from auto_short.hashing import sha256_file
    from auto_short.render import run_render

    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                 render=dc_replace(RenderConfig(), output_dir=tmp_path / "output", preset="ultrafast"))
    ws = make_render_episode(cfg.workspace.dir, real_source)
    write_docs(ws)
    run_render(EID, cfg)
    shorts = Path(cfg.render.output_dir) / EID / "shorts"
    before = {p.name: sha256_file(p) for p in shorts.glob("*.mp4")}
    app = app_mod.create_app(cfg, PW, preflight=None)  # real run_render
    with TestClient(app, follow_redirects=False) as c:
        _login(c)
        c.post(f"{BASE}/k01/published", json={"value": True})
        assert c.post(f"{BASE}/k02/delete").status_code == 202
        assert c.app.state.runner.wait_idle(60)
        d = c.get(f"/api/episodes/{EID}").json()
        assert d["job"]["summary"] == "1/2 Shorts (0 encoded, 1 reused)"
        k01, k02 = d["shorts"]
        assert (k02["status"], k02["skip_reason"], k02["deleted"], k02["rejected"]) == \
            ("skipped", "rejected", True, True)
        assert not (shorts / "k02.mp4").exists() and sha256_file(shorts / "k01.mp4") == before["k01.mp4"]
        rm = json.loads((shorts.parent / "render_manifest.json").read_text(encoding="utf-8"))
        assert rm["shorts"][1]["title"] == TITLES["k02"] and rm["shorts"][1]["title_origin"] == "ai"
        assert rm["stats"] == {**rm["stats"], "rendered": 1, "skipped": 1}
        with zipfile.ZipFile(io.BytesIO(c.get(d["zip_url"]).content)) as zf:
            assert len(zf.namelist()) == 1
        assert k01["published"] is True

        assert c.post(f"{BASE}/k02/restore").status_code == 202
        assert c.app.state.runner.wait_idle(60)
        assert c.get(f"/api/episodes/{EID}").json()["job"]["summary"] == "2/2 Shorts (1 encoded, 1 reused)"
        assert {p.name: sha256_file(p) for p in shorts.glob("*.mp4")} == before  # byte-identical
        # ticking never makes the render stale
        c.post(f"{BASE}/k02/published", json={"value": True})
    assert run_render(EID, cfg).ran is False
