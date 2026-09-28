"""CP8.3 phase B: title edit through the web (CP8.2 review functions) + per-Short render job. No ffmpeg: the
render is a fake recording its calls."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.render import RenderError  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from render_helpers import EID, TITLES, make_render_episode  # noqa: E402
from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
ALTS = {"k01": ["Tâm từ bi hiện ra nơi tướng mạo", "Tướng do tâm sinh"], "k02": []}
NEW = "Tướng mạo đổi theo tâm thiện"
BASE = f"/api/episodes/{EID}/shorts"


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"))


@pytest.fixture
def episode(tcfg, tmp_path):
    """Titling done (clips.json + titles.json with alternatives) and a finished render of k01, k02."""
    tmpl = tmp_path / "fake.mp4"
    tmpl.write_bytes(b"not a video")
    from render_helpers import write_docs
    ws = make_render_episode(tcfg.workspace.dir, tmpl)
    write_docs(ws, alternatives=ALTS)
    write_episode(tcfg, EID, titles=TITLES)  # manifest (all done), metadata, render_manifest + files
    return ws


class FakeRender:
    def __init__(self, gate=None, error=None):
        self.calls, self.gate, self.error = [], gate, error

    def __call__(self, episode_id, config):
        self.calls.append(episode_id)
        if self.gate is not None:
            assert self.gate.wait(10)
        if self.error:
            raise RenderError(self.error)
        return SimpleNamespace(ran=True, rendered=2, clips=2, encoded=1, reused=1)


def client(cfg, render=None, pipeline=None):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, render=render or FakeRender(),
                             pipeline=pipeline or fake_pipeline([]))
    c = TestClient(app, follow_redirects=False)
    return c


def _login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def _review(ws):
    p = ws.dir / "review.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def test_episode_view_has_title_data(tcfg, episode):
    with client(tcfg) as c:
        _login(c)
        d = c.get(f"/api/episodes/{EID}").json()
        assert d["max_title_chars"] == 60 and d["titles_error"] is None
        k01, k02 = d["shorts"]
        assert k01["editable"] and k01["ai_title"] == TITLES["k01"] and k01["override"] is None
        assert k01["alternatives"] == [{"n": 1, "title": ALTS["k01"][0]}, {"n": 2, "title": ALTS["k01"][1]}]
        assert k01["title"]["origin"] == "ai" and k01["pending_title"] is None and k01["rendering"] is False
        assert k02["alternatives"] == []


def test_preview_valid_and_invalid(tcfg, episode):
    with client(tcfg) as c:
        _login(c)
        r = c.post(f"{BASE}/k01/title/preview", json={"text": "  " + NEW + " "})
        assert r.status_code == 200
        p = r.json()
        assert p["title"] == NEW and p["origin"] == "manual" and p["chars"] == len(NEW)
        assert " ".join(p["display_lines"]) == NEW and 1 <= len(p["display_lines"]) <= 3
        assert p["font_size"] > 0 and p["panel_height"] > 0
        for text, msg in (("x" * 61, "too long"), ("Tâm 🙏", "emoji"), ("", "empty"), ("TÂM THIỆN", "all caps"),
                          ("Tâm 心", "not in the font")):
            r = c.post(f"{BASE}/k01/title/preview", json={"text": text})
            assert r.status_code == 422 and msg in r.json()["detail"], text
        assert c.post(f"{BASE}/k99/title/preview", json={"text": NEW}).status_code == 422
        assert c.post(f"{BASE}/..%2Fx/title/preview", json={"text": NEW}).status_code == 404
        assert _review(episode) is None  # preview never writes


def test_set_alternative_reset_queue_render(tcfg, episode):
    render = FakeRender()
    with client(tcfg, render=render) as c:
        _login(c)
        r = c.post(f"{BASE}/k01/title", json={"set": NEW})
        assert r.status_code == 202
        body = r.json()
        assert body["preview"]["title"] == NEW and body["job"]["kind"] == "render"
        assert body["job"]["clip_ids"] == ["k01"]
        assert c.app.state.runner.wait_idle(5)
        assert render.calls == [EID]
        assert _review(episode)["titles"] == [{"clip_id": "k01", "candidate_id": "c00001", "title": NEW,
                                               "origin": "manual"}]
        d = c.get(f"/api/episodes/{EID}").json()
        assert d["job"]["status"] == "done" and d["job"]["summary"] == "2/2 Shorts (1 encoded, 1 reused)"
        k01 = d["shorts"][0]
        assert k01["override"] == {"title": NEW, "origin": "manual"}
        # the fake render did not rewrite render_manifest.json -> the file still has the AI title
        assert k01["pending_title"] == {"text": NEW, "origin": "manual"}

        r = c.post(f"{BASE}/k01/title", json={"alternative": 2})
        assert r.status_code == 202 and r.json()["preview"]["origin"] == "alternative"
        assert c.app.state.runner.wait_idle(5)
        assert _review(episode)["titles"][0]["title"] == ALTS["k01"][1]

        r = c.post(f"{BASE}/k01/title", json={"reset": True})
        assert r.status_code == 202 and r.json()["preview"]["origin"] == "ai"
        assert c.app.state.runner.wait_idle(5)
        assert _review(episode)["titles"] == [] and len(render.calls) == 3
        assert c.get(f"/api/episodes/{EID}").json()["shorts"][0]["pending_title"] is None


@pytest.mark.parametrize("body", [{}, {"reset": False}, {"set": NEW, "reset": True}, {"set": NEW, "alternative": 1},
                                  {"alternative": 9}, {"alternative": 0}, {"set": "x" * 61}, {"set": "Tâm 🙏"},
                                  {"set": ""}])
def test_invalid_title_requests_do_not_write(tcfg, episode, body):
    render = FakeRender()
    with client(tcfg, render=render) as c:
        _login(c)
        r = c.post(f"{BASE}/k01/title", json=body)
        assert r.status_code == 422 and r.json()["detail"]
        assert _review(episode) is None and render.calls == [] and c.app.state.runner.jobs() == []


def test_title_write_refused_while_job_active(tcfg, episode):
    gate = threading.Event()
    render = FakeRender(gate=gate)
    with client(tcfg, render=render) as c:
        _login(c)
        assert c.post(f"{BASE}/k01/title", json={"set": NEW}).status_code == 202
        before = _review(episode)
        r = c.post(f"{BASE}/k02/title", json={"set": "Mỗi suy nghĩ đều có quả báo"})
        assert r.status_code == 409 and r.json()["job"]["kind"] == "render"
        assert _review(episode) == before
        d = c.get(f"/api/episodes/{EID}").json()
        assert d["job"]["status"] in ("queued", "running")
        assert [s["rendering"] for s in d["shorts"]] == [True, False]
        # resubmitting the URL (Short) while the render job runs -> the same job, no pipeline job
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["short"]})
        assert r.status_code == 200 and r.json()["created"] is False and r.json()["job"]["kind"] == "render"
        # preview stays available
        assert c.post(f"{BASE}/k02/title/preview", json={"text": "Mỗi suy nghĩ"}).status_code == 200
        gate.set()
        assert c.app.state.runner.wait_idle(5)
        assert c.post(f"{BASE}/k02/title", json={"set": "Mỗi suy nghĩ đều có quả báo"}).status_code == 202
        assert c.app.state.runner.wait_idle(5)


def test_title_write_refused_while_pipeline_runs(tcfg, episode):
    gate = threading.Event()
    with client(tcfg, pipeline=fake_pipeline([], gate=gate)) as c:
        _login(c)
        assert c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}"}).status_code == 202
        r = c.post(f"{BASE}/k01/title", json={"set": NEW})
        assert r.status_code == 409 and r.json()["job"]["kind"] == "pipeline"
        assert _review(episode) is None
        gate.set()
        assert c.app.state.runner.wait_idle(5)


def test_render_failure_reported(tcfg, episode):
    with client(tcfg, render=FakeRender(error="clip k01: ffmpeg failed: boom")) as c:
        _login(c)
        assert c.post(f"{BASE}/k01/title", json={"set": NEW}).status_code == 202
        assert c.app.state.runner.wait_idle(5)
        job = c.get(f"/api/episodes/{EID}").json()["job"]
        assert job["status"] == "failed" and job["error"] == "render: clip k01: ffmpeg failed: boom"


def test_titling_not_done_not_editable(tcfg, episode):
    m = json.loads(episode.manifest_path.read_text())
    m["stages"]["titling"]["status"] = "stale"
    episode.manifest_path.write_text(json.dumps(m))
    with client(tcfg) as c:
        _login(c)
        d = c.get(f"/api/episodes/{EID}").json()
        assert "titling is not done" in d["titles_error"]
        assert all(not s["editable"] for s in d["shorts"]) and len(d["shorts"]) == 2
        r = c.post(f"{BASE}/k01/title", json={"set": NEW})
        assert r.status_code == 422 and "titling is not done" in r.json()["detail"]


def test_title_endpoints_need_login(tcfg, episode):
    with client(tcfg) as c:
        assert c.post(f"{BASE}/k01/title", json={"set": NEW}).status_code == 401
        assert c.post(f"{BASE}/k01/title/preview", json={"text": NEW}).status_code == 401
        assert _review(episode) is None


def test_pipeline_summary_counts_encoded(tcfg):
    calls = []
    with client(tcfg, pipeline=fake_pipeline(calls)) as c:
        _login(c)
        c.post("/api/episodes", json={"url": "https://youtu.be/abcdefghijk"})
        assert c.app.state.runner.wait_idle(5)
        assert c.get("/api/episodes/abcdefghijk").json()["job"]["summary"] == "2/2 Shorts (2 encoded, 0 reused)"
    assert Path(tcfg.workspace.dir, "abcdefghijk", "manifest.json").is_file()


# --- real render (ffmpeg): only the edited Short is encoded (AC4) ------------------------------------------------

@pytest.fixture(scope="module")
def real_source(tmp_path_factory):
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    from render_helpers import make_source
    return make_source(tmp_path_factory.mktemp("web-render") / "src.mp4")


def test_title_edit_reencodes_only_that_short(tmp_path, real_source):
    from dataclasses import replace as dc_replace

    from auto_short.hashing import sha256_file
    from auto_short.render import run_render
    from render_helpers import write_docs

    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                 render=dc_replace(RenderConfig(), output_dir=tmp_path / "output", preset="ultrafast"))
    ws = make_render_episode(cfg.workspace.dir, real_source)
    write_docs(ws, alternatives=ALTS)
    first = run_render(EID, cfg)
    assert (first.encoded, first.reused) == (2, 0)
    shorts = Path(cfg.render.output_dir) / EID / "shorts"
    before = {p.name: sha256_file(p) for p in shorts.glob("*.mp4")}

    app = app_mod.create_app(cfg, PW, preflight=None)  # real run_render
    with TestClient(app, follow_redirects=False) as c:
        _login(c)
        old_url = c.get(f"/api/episodes/{EID}").json()["shorts"][0]["video_url"]
        assert c.post(f"{BASE}/k01/title", json={"set": NEW}).status_code == 202
        assert c.app.state.runner.wait_idle(60)
        d = c.get(f"/api/episodes/{EID}").json()
        job = d["job"]
        assert job["status"] == "done" and job["summary"] == "2/2 Shorts (1 encoded, 1 reused)"
        assert any("clip k02: reuse (render_key unchanged)" in line for line in job["logs"])
        after = {p.name: sha256_file(p) for p in shorts.glob("*.mp4")}
        assert after["k02.mp4"] == before["k02.mp4"] and after["k01.mp4"] != before["k01.mp4"]
        k01 = d["shorts"][0]
        assert k01["title"] == {"text": NEW, "origin": "manual", "display_lines": k01["title"]["display_lines"]}
        assert k01["pending_title"] is None and k01["video_url"] != old_url
        assert c.get(k01["video_url"]).content == (shorts / "k01.mp4").read_bytes()

        assert c.post(f"{BASE}/k01/title", json={"reset": True}).status_code == 202
        assert c.app.state.runner.wait_idle(60)
        assert {p.name: sha256_file(p) for p in shorts.glob("*.mp4")} == before  # back byte-identical
