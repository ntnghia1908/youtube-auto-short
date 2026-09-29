"""CP9 C7 web routes: transcript, proposals, cut preview, save / reset a cut (render job), add a Short (job: AI
title in lane ai, then render), source video for "Nghe thử"; 409 while a job runs or on an archived episode,
422 invalid range (review.json unchanged), 503 Ollama preflight. Render and AI are fakes."""

import json
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.pipeline import PreflightError  # noqa: E402
from auto_short.titling.added import AddedTitle  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from cp9_helpers import EID, make_cp9_episode  # noqa: E402
from web_helpers import fake_pipeline  # noqa: E402

PW = "pw"
API = f"/api/episodes/{EID}"


@pytest.fixture(params=["lanes", "serial"])
def tcfg(tmp_path, request) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "out"),
                  web=WebConfig(queue_mode=request.param))


@pytest.fixture
def ws(tcfg):
    ws = make_cp9_episode(tcfg.workspace.dir)
    out = tcfg.render.output_dir / EID
    (out / "shorts").mkdir(parents=True)
    shorts = []
    for n, cid in enumerate(("k01", "k02"), 1):
        (out / "shorts" / f"{cid}.mp4").write_bytes(b"mp4" + cid.encode())
        shorts.append({"clip_id": cid, "candidate_id": f"c0000{n}", "status": "rendered", "skip_reason": None,
                       "file": f"shorts/{cid}.mp4", "sha256": f"{n:064x}", "title": f"Tiêu đề {cid}",
                       "title_display_lines": [f"Tiêu đề {cid}"], "duration": 40.0, "source_start": 10.0,
                       "source_end": 50.0, "title_origin": "ai", "render_key": "k" * 64, "origin": "ai",
                       "cut": {"start": 10.0, "end": 50.0} if cid == "k02" else None})
    (out / "render_manifest.json").write_text(json.dumps({"schema_version": 1, "episode_id": EID, "shorts": shorts,
                                                          "header": {"lines": ["A"]}}), encoding="utf-8")
    return ws


class FakeRender:
    def __init__(self, gate=None):
        self.calls, self.gate = [], gate

    def __call__(self, episode_id, config):
        self.calls.append(episode_id)
        if self.gate is not None:
            assert self.gate.wait(10)
        return SimpleNamespace(ran=True, rendered=3, clips=3, encoded=1, reused=2)


class FakeTitler:
    def __init__(self, title="Tiêu đề AI cho Short thêm", error=None):
        self.calls, self.title, self.error = [], title, error

    def __call__(self, episode_id, config, clip_id):
        self.calls.append((episode_id, clip_id))
        return AddedTitle(clip_id, "titled" if self.title else "untitled", self.title, [], self.error, bool(self.title))


def make_client(cfg, *, render=None, titler=None, preflight=lambda c: None):
    app = app_mod.create_app(cfg, PW, preflight=preflight, render=render or FakeRender(),
                             pipeline=fake_pipeline([]), titler=titler or FakeTitler())
    c = TestClient(app, follow_redirects=False)
    return c, app


def _login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def _bytes(ws):
    p = ws.dir / "review.json"
    return p.read_bytes() if p.is_file() else None


def _wait(app):
    assert app.state.runner.wait_idle(10)


def test_read_routes(ws, tcfg):
    c, app = make_client(tcfg)
    with c:
        assert c.get(f"{API}/transcript").status_code == 401
        _login(c)
        tv = c.get(f"{API}/transcript").json()
        assert len(tv["segments"]) == 91 and [s["clip_id"] for s in tv["shorts"]] == ["k01", "k02"]
        props = c.get(f"{API}/proposals").json()["proposals"]
        assert [p["candidate_id"] for p in props] == ["c00003", "c00004", "c00005"]
        assert c.get("/api/episodes/..%2Fx/transcript").status_code == 404
        pv = c.post(f"{API}/cut/preview", json={"start_segment": "s00002", "end_segment": "s00009"}).json()
        assert pv["error"] is None and pv["clip_id"] is None and pv["duration"] > 30
        pv = c.post(f"{API}/cut/preview", json={"clip_id": "k01", "start_segment": "s00005",
                                                 "end_segment": "s00009"}).json()
        assert "cần 30–180 s" in pv["error"]  # C4 violation shown, not an HTTP error
        r = c.post(f"{API}/cut/preview", json={"start_segment": "s00002", "end_segment": "s00009",
                                               "start_nudge": 0.3})
        assert r.status_code == 422 and "0.2" in r.json()["detail"]
        # the episode view carries origin / cut from the render manifest
        d = c.get(API).json()
        assert [(s["origin"], s["cut"]) for s in d["shorts"]] == [("ai", None), ("ai", {"start": 10.0, "end": 50.0})]


def test_cut_save_reset_and_409(ws, tcfg):
    gate = threading.Event()
    render = FakeRender(gate)
    c, app = make_client(tcfg, render=render)
    with c:
        _login(c)
        r = c.post(f"{API}/shorts/k01/cut", json={"start_segment": "s00005", "end_segment": "s00009"})
        assert r.status_code == 422 and "đoạn không hợp lệ" in r.json()["detail"] and _bytes(ws) is None  # AC3
        r = c.post(f"{API}/shorts/k01/cut", json={"reset": True, "start_segment": "s00002", "end_segment": "s00009"})
        assert r.status_code == 422
        r = c.post(f"{API}/shorts/k01/cut", json={"start_segment": "s00002"})
        assert r.status_code == 422
        r = c.post(f"{API}/shorts/k01/cut", json={"start_segment": "s00002", "end_segment": "s00009",
                                                  "end_nudge": -0.2})
        assert r.status_code == 202
        body = r.json()
        assert body["preview"]["end"] == 51.6 and body["job"]["kind"] == "render"
        assert body["job"]["clip_ids"] == ["k01"]
        before = _bytes(ws)
        assert json.loads(before)["cuts"][0]["clip_id"] == "k01"
        # AC8: a job is queued / running -> 409, nothing written
        for req in (lambda: c.post(f"{API}/shorts/k02/cut", json={"reset": True}),
                    lambda: c.post(f"{API}/shorts", json={"candidate_id": "c00003"})):
            r = req()
            assert r.status_code == 409 and r.json()["job"]["id"] == body["job"]["id"]
        assert _bytes(ws) == before
        # preview still works during a job
        assert c.post(f"{API}/cut/preview", json={"clip_id": "k01", "start_segment": "s00002",
                                                  "end_segment": "s00009"}).status_code == 200
        d = c.get(API).json()
        assert [s["rendering"] for s in d["shorts"]] == [True, False]
        gate.set()
        _wait(app)
        r = c.post(f"{API}/shorts/k01/cut", json={"reset": True})
        assert r.status_code == 202 and r.json()["preview"]["changed"] is True
        _wait(app)
        assert json.loads(_bytes(ws)) == {"schema_version": 1, "episode_id": EID, "titles": []}
        assert render.calls == [EID, EID]


def test_add_short_job_titles_then_renders(ws, tcfg):
    render, titler = FakeRender(), FakeTitler()
    c, app = make_client(tcfg, render=render, titler=titler)
    with c:
        _login(c)
        r = c.post(f"{API}/shorts", json={"candidate_id": "c00004"})
        assert r.status_code == 422 and _bytes(ws) is None
        r = c.post(f"{API}/shorts", json={"candidate_id": "c00003"})
        assert r.status_code == 202
        body = r.json()
        assert body["clip_id"] == "m01" and body["job"]["kind"] == "add" and body["job"]["clip_ids"] == ["m01"]
        assert body["preview"]["overlaps"] == ["k02"]
        _wait(app)
        job = c.get(API).json()["job"]
        assert job["status"] == "done" and titler.calls == [(EID, "m01")] and render.calls == [EID]
        assert [s["stage"] for s in job["stages"]] == ["titling", "render"]
        assert job["summary"].startswith("m01: 'Tiêu đề AI cho Short thêm'; 3/3 Shorts")
        r = c.post(f"{API}/shorts", json={"start_segment": "s00062", "end_segment": "s00070"})
        assert r.status_code == 202 and r.json()["clip_id"] == "m02"
        _wait(app)
        added = json.loads(_bytes(ws))["added"]
        assert [(a["clip_id"], a["source"]) for a in added] == [("m01", "proposal"), ("m02", "transcript")]


def test_add_short_ai_failure_still_renders_then_fails(ws, tcfg):
    """C6: AI error -> the Short stays untitled, the render still runs (it shows up waiting for a title)."""
    render = FakeRender()
    c, app = make_client(tcfg, render=render, titler=FakeTitler(title=None, error="clip m01: boom (after 3 attempts)"))
    with c:
        _login(c)
        assert c.post(f"{API}/shorts", json={"candidate_id": "c00003"}).status_code == 202
        _wait(app)
        job = c.get(API).json()["job"]
        assert job["status"] == "failed" and "titling m01: clip m01: boom" in job["error"]
        assert "gõ tiêu đề tay" in job["error"] and render.calls == [EID]


def test_add_short_preflight_503(ws, tcfg):
    def down(cfg):
        raise PreflightError("ollama not reachable")
    c, app = make_client(tcfg, preflight=down)
    with c:
        _login(c)
        r = c.post(f"{API}/shorts", json={"candidate_id": "c00003"})
        assert r.status_code == 503 and "ollama preflight" in r.json()["detail"] and _bytes(ws) is None


def test_archived_409_and_source_file(ws, tcfg):
    c, app = make_client(tcfg)
    with c:
        _login(c)
        r = c.get(f"/files/{EID}/source.mp4", headers={"Range": "bytes=0-9"})
        assert r.status_code == 206 and r.content == b"\x00" * 10 and r.headers["content-type"] == "video/mp4"
        assert c.get(f"/files/{EID}/source.mp4").status_code == 200
        (ws.dir / "archive.json").write_text("{}", encoding="utf-8")
        assert c.get(f"/files/{EID}/source.mp4").status_code == 404
        for req in (lambda: c.post(f"{API}/shorts/k01/cut", json={"start_segment": "s00002", "end_segment": "s00009"}),
                    lambda: c.post(f"{API}/shorts/k01/cut", json={"reset": True}),
                    lambda: c.post(f"{API}/shorts", json={"candidate_id": "c00003"})):
            r = req()
            assert r.status_code == 409 and "đã dọn video nguồn" in r.json()["detail"]
        assert _bytes(ws) is None


def test_source_file_only_inside_workspace(ws, tcfg, tmp_path):
    outside = tmp_path / "local.mp4"
    outside.write_bytes(b"local")
    m = json.loads(ws.manifest_path.read_text(encoding="utf-8"))
    m["source"]["path"] = str(outside)
    ws.manifest_path.write_text(json.dumps(m), encoding="utf-8")
    c, app = make_client(tcfg)
    with c:
        _login(c)
        assert c.get(f"/files/{EID}/source.mp4").status_code == 404
