"""CP8.15 P9 web routes: compose (job, lane ai), edit fields, "Đã đăng bài", image library (P5/P5a/P5b), 409/422/503/404.
Render/AI/search are fakes; no real Ollama, no real network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, PostConfig, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.pipeline import PreflightError  # noqa: E402
from auto_short.post import fetch as post_fetch  # noqa: E402
from auto_short.post import stage as post_stage  # noqa: E402
from auto_short.post import store as post_store  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from image_fixtures import make_png  # noqa: E402
from post_helpers import EID, make_post_episode  # noqa: E402
from web_helpers import fake_pipeline  # noqa: E402

PW = "pw"
API = f"/api/episodes/{EID}"


@pytest.fixture(params=["lanes", "serial"])
def tcfg(tmp_path, request) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(image_dir=tmp_path / "images"), web=WebConfig(queue_mode=request.param))


@pytest.fixture
def ws(tcfg):
    return make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir)


class FakeComposeAI:
    """Stand-in for :func:`post_stage.compose_posts`: composes trivially (append a period), always ``ai``."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, episode_id, config, clips, *, client=None, sleep=None, lock=None, before_ai=None):
        self.calls.append((episode_id, clips))
        from auto_short.post import source as post_source

        order = [cid for cid, _ in post_stage.rendered_clip_ids(config, episode_id)]
        if not order:
            raise post_stage.PostComposeError(f"tập {episode_id} chưa có Short nào dựng xong")
        ep = post_source.load(episode_id, config)
        tokens = [clips] if isinstance(clips, str) else list(clips)
        if any(t in ("all", "auto") for t in tokens):  # CP8.16 R4 / R3 (merged request)
            try:
                cur = post_store.read_posts(config.workspace.dir / episode_id / post_store.POSTS_NAME, episode_id)
            except post_store.PostsError:
                cur = post_store.empty_posts(episode_id)
            todo = post_stage.resolve_todo(ep, cur, order, tokens)
        else:
            todo = list(tokens)
        if todo and before_ai is not None:  # FIX-post-doc-no-gpu F1: the lazy Ollama preflight
            before_ai()
        for cid in todo:
            text = post_source.source_text(ep, cid)
            paragraphs = [text[0].upper() + text[1:] + "."]
            posts_path = config.workspace.dir / episode_id / post_store.POSTS_NAME
            with lock if lock is not None else post_stage._NullLock():
                doc = post_store.read_posts(posts_path, episode_id)
                doc = post_store.with_compose(doc, order, clip_id=cid,
                                              candidate_id=dict(post_stage.rendered_clip_ids(config, episode_id))[cid],
                                              source_sha256=post_source.source_sha256(text), paragraphs=paragraphs,
                                              origin=post_store.AI, image=None, now="2026-09-29T10:00:00Z")
                post_store.write(posts_path, doc)
        return post_stage.ComposeSummary(list(todo), ai=len(todo))


def make_client(cfg, *, compose=None, post_preflight=lambda c: None, search=None):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, render=lambda eid, c: SimpleNamespace(ran=False),
                             pipeline=fake_pipeline([]), post_compose=compose or FakeComposeAI(),
                             post_preflight=post_preflight, post_search=search)
    c = TestClient(app, follow_redirects=False)
    return c, app


def _login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def _wait(app):
    assert app.state.runner.wait_idle(10)


# --- compose (P1) ----------------------------------------------------------------------------------------------


def test_compose_one_clip_then_get(tcfg, ws):
    c, app = make_client(tcfg)
    with c:
        _login(c)
        r = c.get(f"{API}/posts")
        assert r.status_code == 200 and r.json() == {"posts": [], "post_error": None}

        r = c.post(f"{API}/posts", json={"clips": ["k01"]})
        assert r.status_code == 202
        _wait(app)

        r = c.get(f"{API}/posts")
        assert r.status_code == 200
        posts = r.json()["posts"]
        assert len(posts) == 1
        p = posts[0]
        assert p["clip_id"] == "k01" and p["origin"] == "ai" and p["stale"] is False
        assert p["image"] is None and p["image_missing"] is False and p["link"] is None and p["posted"] is False
        assert p["text"].startswith("TIÊU ĐỀ K01\n\n")  # P4: title first
        assert "— HT. Tịnh Không, Kinh Test tập 9" in p["text"]  # CP8.16 R5
        assert p["chars"] == len(p["text"])


def test_compose_all_composes_every_rendered_short(tcfg, ws):
    c, app = make_client(tcfg)
    with c:
        _login(c)
        r = c.post(f"{API}/posts", json={"clips": "all"})
        assert r.status_code == 202
        _wait(app)
        posts = c.get(f"{API}/posts").json()["posts"]
        assert {p["clip_id"] for p in posts} == {"k01", "k02"}


def test_compose_invalid_clips_body(tcfg, ws):
    c, _app = make_client(tcfg)
    with c:
        _login(c)
        assert c.post(f"{API}/posts", json={"clips": []}).status_code == 422
        assert c.post(f"{API}/posts", json={"clips": "nope"}).status_code == 422
        assert c.post(f"{API}/posts", json={"clips": ["not a valid clip id!"]}).status_code == 422


def test_compose_no_rendered_short_fails_job_cleanly(tcfg):
    """The episode id format is valid but nothing was ever rendered: the job (not the route) reports the error,
    like a pipeline job on an episode that does not exist yet."""
    c, app = make_client(tcfg)
    with c:
        _login(c)
        r = c.post("/api/episodes/nosuchepisode1/posts", json={"clips": "all"})
        assert r.status_code == 202
        _wait(app)
        job = app.state.runner.job(r.json()["job"]["id"])
        assert job.status == "failed" and "chưa có Short" in job.error


def test_compose_preflight_failure_queues_job(tcfg, ws):
    # FIX-ollama-wait O4 (was: 503): 202 + job; the ai lane reports a missing model as a failed job
    def bad_preflight(_cfg):
        raise PreflightError("model missing")

    c, app = make_client(tcfg, post_preflight=bad_preflight)
    with c:
        _login(c)
        r = c.post(f"{API}/posts", json={"clips": ["k01"]})
        assert r.status_code == 202
        assert app.state.runner.wait_idle(10)
        job = app.state.runner.job(r.json()["job"]["id"])
        assert job.status == "failed" and job.error == "ollama preflight: model missing"


def test_compose_returns_waiting_job_while_job_active(tcfg, ws):  # CP8.16 R3 (was 409, CP8.15 P1)
    gate = None
    import threading

    gate = threading.Event()

    class SlowCompose(FakeComposeAI):
        def __call__(self, *a, **kw):
            gate.wait(5)
            return super().__call__(*a, **kw)

    c, app = make_client(tcfg, compose=SlowCompose())
    with c:
        _login(c)
        r1 = c.post(f"{API}/posts", json={"clips": ["k01"]})
        assert r1.status_code == 202
        r2 = c.post(f"{API}/posts", json={"clips": ["k02"]})
        assert r2.status_code == 202 and r2.json()["job"]["id"] == r1.json()["job"]["id"]  # one job per episode
        gate.set()
        _wait(app)


# --- edit (P9 PUT) ----------------------------------------------------------------------------------------------


def test_put_requires_existing_post(tcfg, ws):
    c, _app = make_client(tcfg)
    with c:
        _login(c)
        r = c.put(f"{API}/posts/k01", json={"paragraphs": ["X."]})
        assert r.status_code == 422


def test_put_paragraphs_sets_manual_origin(tcfg, ws):
    c, app = make_client(tcfg)
    with c:
        _login(c)
        c.post(f"{API}/posts", json={"clips": ["k01"]})
        _wait(app)
        r = c.put(f"{API}/posts/k01", json={"paragraphs": ["Đoạn sửa tay."]})
        assert r.status_code == 200
        assert r.json()["origin"] == "manual"
        posts = c.get(f"{API}/posts").json()["posts"]
        assert posts[0]["origin"] == "manual" and posts[0]["stale"] is False  # source text unchanged


def test_put_empty_paragraphs_rejected(tcfg, ws):
    c, app = make_client(tcfg)
    with c:
        _login(c)
        c.post(f"{API}/posts", json={"clips": ["k01"]})
        _wait(app)
        assert c.put(f"{API}/posts/k01", json={"paragraphs": []}).status_code == 422
        assert c.put(f"{API}/posts/k01", json={"paragraphs": ["  "]}).status_code == 422


def test_put_image_valid_and_unknown(tcfg, ws):
    c, app = make_client(tcfg)
    with c:
        _login(c)
        (tcfg.post.image_dir).mkdir(parents=True)
        name = "a.png"
        (tcfg.post.image_dir / name).write_bytes(make_png(700, 900))
        c.post(f"{API}/posts", json={"clips": ["k01"]})
        _wait(app)
        r = c.put(f"{API}/posts/k01", json={"image": name})
        assert r.status_code == 200 and r.json()["image"] == name
        r = c.put(f"{API}/posts/k01", json={"image": "missing.png"})
        assert r.status_code == 404


def test_put_link_valid_and_invalid(tcfg, ws):
    c, app = make_client(tcfg)
    with c:
        _login(c)
        c.post(f"{API}/posts", json={"clips": ["k01"]})
        _wait(app)
        r = c.put(f"{API}/posts/k01", json={"link": "https://youtu.be/AbCdEfGhIjK"})
        assert r.status_code == 200
        assert r.json()["link"] == "https://youtube.com/shorts/AbCdEfGhIjK"
        r = c.put(f"{API}/posts/k01", json={"link": "https://example.com/x"})
        assert r.status_code == 422
        r = c.put(f"{API}/posts/k01", json={"link": ""})  # empty clears
        assert r.status_code == 200 and r.json()["link"] is None


def test_put_edit_allowed_while_job_running(tcfg, ws):
    """P7: manual edits are not blocked by a running job (unlike title/cut edits)."""
    import threading

    gate = threading.Event()

    class SlowCompose(FakeComposeAI):
        def __call__(self, *a, **kw):
            r = super().__call__(*a, **kw)
            gate.wait(5)
            return r

    c, app = make_client(tcfg, compose=SlowCompose())
    with c:
        _login(c)
        c.post(f"{API}/posts", json={"clips": ["k01"]})
        import time as _time
        _time.sleep(0.2)
        r = c.put(f"{API}/posts/k01", json={"link": "https://youtu.be/AbCdEfGhIjK"})
        gate.set()
        _wait(app)
        assert r.status_code == 200


# --- posted (P8) -----------------------------------------------------------------------------------------------


def test_posted_toggle_does_not_touch_publish_or_complete(tcfg, ws):
    c, app = make_client(tcfg)
    with c:
        _login(c)
        c.post(f"{API}/posts", json={"clips": ["k01"]})
        _wait(app)
        before = c.get(API).json()
        r = c.post(f"{API}/posts/k01/posted", json={"value": True})
        assert r.status_code == 200 and r.json()["posted"] is True
        after = c.get(API).json()
        assert before["published"] == after["published"] and before["complete"] == after["complete"]
        r = c.post(f"{API}/posts/k01/posted", json={"value": False})
        assert r.json()["posted"] is False and r.json()["posted_at"] is None


def test_posted_requires_existing_post(tcfg, ws):
    c, _app = make_client(tcfg)
    with c:
        _login(c)
        assert c.post(f"{API}/posts/k01/posted", json={"value": True}).status_code == 422


# --- image library (P5, P5a) ------------------------------------------------------------------------------------


def test_image_upload_list_delete(tcfg):
    c, _app = make_client(tcfg)
    with c:
        _login(c)
        png = make_png(700, 900)
        r = c.post("/api/post-images?name=Ảnh test.png", content=png)
        assert r.status_code == 200
        body = r.json()
        assert body["duplicate"] is False
        name = body["image"]

        r = c.get("/api/post-images")
        assert r.status_code == 200
        images = r.json()["images"]
        assert len(images) == 1 and images[0]["name"] == name and images[0]["used"] == 0

        r = c.get(f"/files/post-images/{name}")
        assert r.status_code == 200 and r.content == png

        r = c.delete(f"/api/post-images/{name}")
        assert r.status_code == 200 and r.json() == {"used": 0}
        assert c.get("/api/post-images").json()["images"] == []


def test_image_upload_rejects_invalid(tcfg):
    c, _app = make_client(tcfg)
    with c:
        _login(c)
        r = c.post("/api/post-images?name=a.png", content=b"not an image")
        assert r.status_code == 422


def test_image_file_404_for_traversal_and_unknown(tcfg):
    c, _app = make_client(tcfg)
    with c:
        _login(c)
        assert c.get("/files/post-images/..%2Fsecret.png").status_code == 404
        assert c.get("/files/post-images/missing.png").status_code == 404
        assert c.delete("/api/post-images/..%2Fsecret.png").status_code == 404


def test_image_delete_reports_usage_count(tcfg, ws):
    c, app = make_client(tcfg)
    with c:
        _login(c)
        (tcfg.post.image_dir).mkdir(parents=True)
        name = "a.png"
        (tcfg.post.image_dir / name).write_bytes(make_png(700, 900))
        c.post(f"{API}/posts", json={"clips": ["k01"]})
        _wait(app)
        c.put(f"{API}/posts/k01", json={"image": name})
        r = c.delete(f"/api/post-images/{name}")
        assert r.json() == {"used": 1}
        posts = c.get(f"{API}/posts").json()["posts"]
        assert posts[0]["image"] == name and posts[0]["image_missing"] is True  # tick/text kept, image now missing


# --- image search from link (P5b) -------------------------------------------------------------------------------


def test_image_search_job_and_status(tcfg):
    def fake_search(url, image_dir, sources_path):
        image_dir.mkdir(parents=True, exist_ok=True)
        (image_dir / "found.png").write_bytes(make_png(700, 900))
        return post_fetch.SearchResult(added=["found.png"], duplicate=[], skipped={})

    c, app = make_client(tcfg, search=fake_search)
    with c:
        _login(c)
        r = c.post("/api/post-images/search", json={"url": "https://example.com/page"})
        assert r.status_code == 202
        job_id = r.json()["job"]["id"]
        _wait(app)
        r = c.get(f"/api/post-images/search/{job_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "done" and body["added"] == ["found.png"] and body["found"] == 1


def test_image_search_409_while_running(tcfg):
    import threading
    gate = threading.Event()

    def slow_search(url, image_dir, sources_path):
        gate.wait(5)
        return post_fetch.SearchResult()

    c, app = make_client(tcfg, search=slow_search)
    with c:
        _login(c)
        r1 = c.post("/api/post-images/search", json={"url": "https://example.com/a"})
        assert r1.status_code == 202
        r2 = c.post("/api/post-images/search", json={"url": "https://example.com/b"})
        assert r2.status_code == 409
        gate.set()
        _wait(app)


def test_image_search_unknown_job_404(tcfg):
    c, _app = make_client(tcfg)
    with c:
        _login(c)
        assert c.get("/api/post-images/search/999999").status_code == 404


# --- auth ---------------------------------------------------------------------------------------------------------


def test_routes_require_login(tcfg, ws):
    c, _app = make_client(tcfg)
    with c:
        assert c.get(f"{API}/posts").status_code == 401
        assert c.post(f"{API}/posts", json={"clips": "all"}).status_code == 401
        assert c.get("/api/post-images").status_code == 401
