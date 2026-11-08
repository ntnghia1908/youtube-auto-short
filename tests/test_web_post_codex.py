"""PCX1 AC4–5 TestClient coverage. ORCHESTRATOR runs this file outside the no-loopback sandbox."""
import json
import threading
from dataclasses import replace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from auto_short.post import codex_text as ct, store
from auto_short.web import jobs
from post_helpers import EID
from test_post_codex_helpers import Codex, Media, Whisper, seed
from test_web_post_cp815 import FakeComposeAI
from web_helpers import login, make_app

API = f"/api/episodes/{EID}/posts"


def client_for(cfg, *, runner=None, gate=None, jobs_runner=None):
    def rewrite(eid, config, clips, **kwargs):
        if gate:
            assert gate.wait(5)
        return ct.rewrite_posts(eid, config, clips, media_runner=Media(), whisper=Whisper(), **kwargs)
    app = make_app(cfg, runner=jobs_runner, post_compose=FakeComposeAI(), post_preflight=lambda c: None,
                   post_codex_rewrite=rewrite, codex_runner=runner or Codex())
    return TestClient(app, follow_redirects=False), app


@pytest.mark.parametrize("origin,posted,body,status", [
    ("ai", False, {"clips": ["k01"]}, 202),
    ("raw", True, {"clips": ["k01"]}, 409),
    ("raw", True, {"clips": ["k01"], "include_posted": True}, 202),
    ("doc", False, {"clips": ["k01"]}, 422),
    ("manual", False, {"clips": ["k01"]}, 422),
    ("codex", False, {"clips": ["k01"]}, 422),
    ("ai", False, {"clips": []}, 422),
    ("ai", False, {"clips": ["../k01"]}, 422),
    ("ai", False, {"clips": ["k99"]}, 422),
    ("ai", False, {"include_posted": True}, 422),
])
def test_api_manual_confirmation_and_protected_origins(tmp_path, origin, posted, body, status):
    cfg, path = seed(tmp_path)
    cfg = replace(cfg, post=replace(cfg.post, codex_auto=False))
    doc = store.read_posts(path, EID)
    doc["posts"][0].update(origin=origin, posted_at="2026-11-08T00:00:00Z" if posted else None)
    store.write(path, doc)
    c, app = client_for(cfg)
    with c:
        assert c.post(API + "/codex", json=body).status_code == 401
        login(c)
        response = c.post(API + "/codex", json=body)
        assert response.status_code == status
        assert app.state.runner.wait_idle(5)
        p = c.get(API).json()["posts"][0]
        assert p["origin"] == ("codex" if status == 202 else origin)
        assert p["posted"] == posted
        if status == 202:
            assert p["low_punctuation"] is False and p["stale"] is False
            assert p["paragraphs"] == ["Cứ Nha, huống chi!", "Giữ đủ lời giảng."]
        assert c.post("/api/episodes/../bad/posts/codex", json={}).status_code in (404, 422)


@pytest.mark.parametrize("auto", [True, False])
def test_compose_auto_and_bulk_only_unposted_ai(tmp_path, auto):
    cfg, path = seed(tmp_path)
    cfg = replace(cfg, post=replace(cfg.post, codex_auto=auto))
    doc = store.read_posts(path, EID)
    doc["posts"][0]["posted_at"] = "2026-11-08T00:00:00Z"
    store.write(path, doc)
    c, app = client_for(cfg)
    with c:
        login(c)
        assert c.post(API, json={"clips": ["k01", "k02"]}).status_code == 202
        assert app.state.runner.wait_idle(5)
        posts = c.get(API).json()["posts"]
        assert posts[0]["origin"] == "ai" and posts[0]["posted"]
        assert posts[1]["origin"] == ("codex" if auto else "ai")
        if not auto:
            assert c.post(API + "/codex", json={}).status_code == 202
            assert app.state.runner.wait_idle(5)
            assert c.get(API).json()["posts"][1]["origin"] == "codex"
        assert c.get(API).json()["posts"][0]["origin"] == "ai"


def test_api_running_error_and_restart_status_keeps_old_post(tmp_path):
    cfg, path = seed(tmp_path)
    gate = threading.Event()
    before = path.read_bytes()
    c, app = client_for(cfg, runner=Codex(code=1, log="server_overloaded tokens used\n42"), gate=gate)
    try:
        with c:
            login(c)
            response = c.post(API + "/codex", json={"clips": ["k01"]})
            assert response.status_code == 202
            status = c.get(API + "/codex").json()
            assert status["job"]["kind"] == jobs.KIND_POST_CODEX
            assert status["job"]["status"] in jobs.ACTIVE
            gate.set()
            assert app.state.runner.wait_idle(5)
            state = c.get(API + "/codex").json()
            assert state["job"]["status"] == jobs.FAILED and "quá tải" in state["errors"]["k01"]
            assert path.read_bytes() == before
    finally:
        gate.set()
    c2, app2 = client_for(cfg)
    with c2:
        login(c2)
        assert "quá tải" in c2.get(API + "/codex").json()["errors"]["k01"]
        assert c2.post(API + "/codex", json={"clips": ["k01"]}).status_code == 202
        assert app2.state.runner.wait_idle(5)
        assert c2.get(API + "/codex").json()["errors"]["k01"] is None
        # Editing a Codex post by hand retains the existing P7 manual transition.
        assert c2.put(API + "/k01", json={"paragraphs": ["Bản sửa tay."]}).json()["origin"] == "manual"


def test_api_backlog_reports_quota_and_resumes(tmp_path):
    cfg, path = seed(tmp_path)
    now = [1800000000.0]
    runner = jobs.JobRunner(wall=lambda: now[0])
    waiting = threading.Event()
    original = runner._requeue_codex
    def requeue(job, exc):
        original(job, exc)
        waiting.set()
    runner._requeue_codex = requeue
    calls = []
    def process(cmd, **kw):
        calls.append(cmd)
        return (Codex(code=1, log="You've hit your usage limit") if len(calls) == 1 else Codex())(cmd, **kw)
    c, app = client_for(cfg, runner=process, jobs_runner=runner)
    with c:
        login(c)
        assert waiting.wait(5)  # lifecycle automatically admits existing backlog
        state = c.get("/api/posts/codex").json()
        assert state["enabled"] and state["remaining"] == 2
        assert state["current"]["episode_id"] == EID and state["current"]["clip_id"] == "k01"
        assert state["quota"]["waiting"] and state["quota"]["retry_at"] == now[0] + 1800
        clip_state = c.get(API + "/codex").json()
        assert clip_state["job"]["error"] is None and clip_state["errors"]["k01"] is None
        now[0] += 1800
        with runner._lock:
            runner._lock.notify_all()
        assert runner.wait_idle(5)
        app.state.post_codex_backlog.tick()
        assert runner.wait_idle(5)
        assert c.get("/api/posts/codex").json()["remaining"] == 0
        assert all(p["origin"] == "codex" for p in c.get(API).json()["posts"])
