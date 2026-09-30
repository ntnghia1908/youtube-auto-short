"""CP8.16 web: tab "Bài đăng" page + static, ``clips: "auto"``, ``post_job``, the ``post`` job under its own runner
key (R3), the automatic compose after an episode job (R2a). Render / AI are fakes; no Ollama, no network."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, PostConfig, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.post import stage as post_stage  # noqa: E402
from auto_short.post import store as post_store  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web import jobs as jobs_mod  # noqa: E402
from post_helpers import EID, make_post_episode  # noqa: E402
from test_web_post_cp815 import FakeComposeAI  # noqa: E402
from web_helpers import fake_pipeline  # noqa: E402

PW = "pw"
API = f"/api/episodes/{EID}"
EID2 = "post8TestEp2"


@pytest.fixture(params=["lanes", "serial"])
def tcfg(tmp_path, request) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(image_dir=tmp_path / "images"), web=WebConfig(queue_mode=request.param))


@pytest.fixture
def ws(tcfg):
    return make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir)


class GatedCompose(FakeComposeAI):
    """Compose that blocks on ``gate`` for the episodes in ``block`` (None = every episode)."""

    def __init__(self, gate: threading.Event, block: set[str] | None = None):
        super().__init__()
        self.gate, self.block = gate, block
        self.started = threading.Event()

    def __call__(self, episode_id, config, clips, **kw):
        if self.block is None or episode_id in self.block:
            self.started.set()
            assert self.gate.wait(10)
        return super().__call__(episode_id, config, clips, **kw)


def make_client(cfg, *, compose=None, render=None):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None,
                             render=render or (lambda eid, c: SimpleNamespace(ran=False)),
                             pipeline=fake_pipeline([]), post_compose=compose or FakeComposeAI(),
                             post_preflight=lambda c: None)
    c = TestClient(app, follow_redirects=False)
    return c, app


def _login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def _wait(app):
    assert app.state.runner.wait_idle(10)


def _episode_job(app, kind, *, fail=False, gate=None, eid=EID):
    def target(job):
        if gate is not None:
            assert gate.wait(10)
        if fail:
            raise jobs_mod.JobFailed("boom")
    return app.state.runner.submit(eid, kind, target)


# --- R1: page + static ---------------------------------------------------------------------------------------------


def test_posts_page_routes(tcfg, ws):  # AC5
    c, _app = make_client(tcfg)
    with c:
        r = c.get(f"/episodes/{EID}/posts")
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")  # no cookie
        _login(c)
        for eid in (EID, EID + ".kt", "neverprocessed"):  # the page is the same HTML; the JS handles missing tập
            r = c.get(f"/episodes/{eid}/posts")
            assert r.status_code == 200 and 'id="post-groups"' in r.text
            nav = r.text[r.text.index('<nav id="kind-bar"'):]
            nav = nav[:nav.index("</nav>")]
            assert ">Shorts<" in nav and ">Khai thị<" in nav and ">Bài đăng<" in nav
            assert 'id="image-dialog"' in r.text and "AutoShort.initPosts()" in r.text
        assert c.get("/episodes/bad!id/posts").status_code == 404


def test_short_view_has_three_buttons_and_no_post_area(tcfg, ws):  # AC5
    c, _app = make_client(tcfg)
    with c:
        _login(c)
        html = c.get(f"/episodes/{EID}").text
        js = c.get("/static/app.js").text
    nav = html[html.index('<nav id="kind-bar"'):]
    nav = nav[:nav.index("</nav>")]
    assert ">Shorts<" in nav and ">Khai thị<" in nav and ">Bài đăng<" in nav
    for gone in ('id="posts-head"', 'id="posts-compose-all"', 'id="image-dialog"', 'id="posts-msg"'):
        assert gone not in html, gone
    for gone in ("function postPanel(", "refreshPostsHead", "Bài đăng cộng đồng đã đăng:", "posts-compose-all"):
        assert gone not in js, gone
    for needle in ("function initPosts()", '"/episodes/" + encodeURIComponent(id) + "/posts"', 'clips: "auto"',
                   "postsPage.autoTried", "Sao chép bài"):
        assert needle in js, needle
    assert "initPosts" in js[js.index("return { initIndex"):]


# --- R3: API ---------------------------------------------------------------------------------------------------------


def test_episode_api_has_post_job(tcfg, ws):  # AC3
    c, app = make_client(tcfg)
    with c:
        _login(c)
        assert c.get(API).json()["post_job"] is None
        r = c.post(f"{API}/posts", json={"clips": "auto"})
        assert r.status_code == 202
        _wait(app)
        d = c.get(API).json()
        assert d["post_job"]["kind"] == "post" and d["post_job"]["status"] == "done" and d["job"] is None
        assert d["post_job"]["episode_id"] == EID
        assert c.get(f"{API}/posts").json()["post_error"] is None
        assert {p["clip_id"] for p in c.get(f"{API}/posts").json()["posts"]} == {"k01", "k02"}


def test_compose_auto_invalid_still_422(tcfg, ws):
    c, _app = make_client(tcfg)
    with c:
        _login(c)
        assert c.post(f"{API}/posts", json={"clips": "everything"}).status_code == 422


def test_sources_edit_not_blocked_by_post_job(tcfg, ws):  # AC3
    gate = threading.Event()
    comp = GatedCompose(gate)
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        assert c.post(f"{API}/posts", json={"clips": "auto"}).status_code == 202
        assert comp.started.wait(10) or tcfg.web.queue_mode == "serial"
        assert app.state.runner.latest_post(EID).active
        r = c.post(f"{API}/shorts/k01/title", json={"set": "Tiêu đề mới cho Short"})
        assert r.status_code == 202, r.text  # CP8.15 would answer 409 here
        if tcfg.web.queue_mode == "lanes":  # serial: the one worker is busy composing, the render job waits behind it
            for _ in range(200):
                if not app.state.runner.latest(EID).active:
                    break
                threading.Event().wait(0.05)
            assert c.post(f"{API}/shorts/k02/delete").status_code == 202
            for _ in range(200):
                if not app.state.runner.latest(EID).active:
                    break
                threading.Event().wait(0.05)
            assert c.post(f"{API}/shorts/k02/restore").status_code == 202
        gate.set()
        _wait(app)


def test_manual_compose_409_while_pipeline_job_active(tcfg, ws):  # AC3
    gate = threading.Event()
    c, app = make_client(tcfg)
    with c:
        _login(c)
        job, _ = _episode_job(app, jobs_mod.KIND_PIPELINE, gate=gate)
        r = c.post(f"{API}/posts", json={"clips": ["k01"]})
        assert r.status_code == 409 and r.json()["job"]["id"] == job.id
        gate.set()
        _wait(app)
        assert c.post(f"{API}/posts", json={"clips": ["k01"]}).status_code == 202
        _wait(app)


def test_compose_allowed_while_render_job_active(tcfg, ws):  # AC3 (only a pipeline job blocks a manual compose)
    gate = threading.Event()
    c, app = make_client(tcfg)
    with c:
        _login(c)
        _episode_job(app, jobs_mod.KIND_RENDER, gate=gate)
        assert c.post(f"{API}/posts", json={"clips": ["k01"]}).status_code == 202
        gate.set()
        _wait(app)


def test_two_submits_while_waiting_give_one_job(tcfg, ws):  # AC3
    make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir, episode_id=EID2)
    gate = threading.Event()
    comp = GatedCompose(gate, block={EID2})
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        assert c.post(f"/api/episodes/{EID2}/posts", json={"clips": "auto"}).status_code == 202
        assert comp.started.wait(10)  # the ai lane (or the one serial worker) is now busy
        r1 = c.post(f"{API}/posts", json={"clips": "auto"})
        r2 = c.post(f"{API}/posts", json={"clips": ["k01"]})
        assert r1.status_code == r2.status_code == 202
        assert r1.json()["job"]["id"] == r2.json()["job"]["id"]
        assert r1.json()["job"]["status"] == "queued"
        assert c.get(API).json()["post_job"]["status"] == "queued"
        gate.set()
        _wait(app)
        assert len([j for j in app.state.runner.jobs() if j.episode_id == EID]) == 1


def test_trigger_while_running_adds_exactly_one_pass(tcfg, ws):  # AC3
    if tcfg.web.queue_mode == "serial":
        pytest.skip("serial: the trigger's render job waits for the one worker, so it never overlaps the compose job")
    gate = threading.Event()
    comp = GatedCompose(gate, block={EID})
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        assert c.post(f"{API}/posts", json={"clips": "auto"}).status_code == 202
        assert comp.started.wait(10)
        _episode_job(app, jobs_mod.KIND_RENDER)  # R2a trigger while the compose job runs (posts not written yet)
        for _ in range(200):  # the hook asked for one more pass: ``again`` is set on the running job
            if app.state.runner.latest_post(EID).again:
                break
            threading.Event().wait(0.05)
        assert app.state.runner.latest_post(EID).again
        gate.set()
        _wait(app)
        posts = [j for j in app.state.runner.jobs() if j.kind == "post"]
        assert len(posts) == 2 and all(j.status == "done" for j in posts)
        assert [call[1] for call in comp.calls] == ["auto", "auto"]  # exactly one extra pass, no third
    # no trigger while running → no extra pass
    assert len(comp.calls) == 2


def test_no_extra_pass_without_trigger(tcfg, ws):
    comp = FakeComposeAI()
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        c.post(f"{API}/posts", json={"clips": "auto"})
        _wait(app)
    assert len(comp.calls) == 1


def test_delete_episode_409_while_post_job_active_and_forgets_it(tcfg, ws):  # AC3
    gate = threading.Event()
    comp = GatedCompose(gate)
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        assert c.post(f"{API}/posts", json={"clips": "auto"}).status_code == 202
        r = c.delete(API)
        assert r.status_code == 409 and r.json()["job"]["kind"] == "post"
        gate.set()
        _wait(app)
        assert c.delete(API).status_code == 200
        assert app.state.runner.latest_post(EID) is None and app.state.runner.latest(EID) is None


# --- R2a ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [jobs_mod.KIND_PIPELINE, jobs_mod.KIND_RENDER, jobs_mod.KIND_ADD])
def test_auto_compose_queued_after_episode_job(tcfg, ws, kind):  # AC2
    comp = FakeComposeAI()
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        _episode_job(app, kind)
        _wait(app)
        job = app.state.runner.latest_post(EID)
        assert job is not None and job.kind == "post" and job.status == "done"
        assert comp.calls == [(EID, "auto")]
        assert {p["clip_id"] for p in c.get(f"{API}/posts").json()["posts"]} == {"k01", "k02"}


def test_auto_compose_runs_in_ai_lane(tmp_path):  # AC2 (lane)
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(image_dir=tmp_path / "images"), web=WebConfig(queue_mode="lanes"))
    make_post_episode(cfg.workspace.dir, cfg.render.output_dir)
    gate = threading.Event()
    comp = GatedCompose(gate)
    c, app = make_client(cfg, compose=comp)
    with c:
        _login(c)
        _episode_job(app, jobs_mod.KIND_RENDER)
        assert comp.started.wait(10)
        assert app.state.runner.latest_post(EID).lane == "ai"
        gate.set()
        _wait(app)


def test_no_job_when_nothing_to_compose(tcfg, ws):  # AC2: title edit → nothing stale → no job
    comp = FakeComposeAI()
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        c.post(f"{API}/posts", json={"clips": "all"})
        _wait(app)
        comp.calls.clear()
        r = c.post(f"{API}/shorts/k01/title", json={"set": "Tiêu đề khác hẳn"})
        assert r.status_code == 202
        _wait(app)
        assert comp.calls == []
        assert len([j for j in app.state.runner.jobs() if j.kind == "post"]) == 1  # only the first one


def test_stale_post_recomposed_after_cut_render(tcfg, ws):  # AC2: an edited cut makes the post stale → recompose
    comp = FakeComposeAI()
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        c.post(f"{API}/posts", json={"clips": "all"})
        _wait(app)
        path = tcfg.workspace.dir / EID / post_store.POSTS_NAME
        doc = post_store.read_posts(path, EID)
        post_store.find(doc, "k01")["source_sha256"] = "0" * 64  # what a cut edit does to the source text
        post_store.write(path, doc)
        assert c.get(f"{API}/posts").json()["posts"][0]["stale"] is True
        comp.calls.clear()
        _episode_job(app, jobs_mod.KIND_RENDER)
        _wait(app)
        assert comp.calls == [(EID, "auto")]
        assert c.get(f"{API}/posts").json()["posts"][0]["stale"] is False


def test_failed_episode_job_still_triggers(tcfg, ws):  # AC2
    comp = FakeComposeAI()
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        job, _ = _episode_job(app, jobs_mod.KIND_PIPELINE, fail=True)
        _wait(app)
        assert job.status == "failed"
        assert comp.calls == [(EID, "auto")]


def test_no_job_without_rendered_shorts_or_source(tcfg):  # AC2: empty set → no job
    comp = FakeComposeAI()
    c, app = make_client(tcfg, compose=comp)
    with c:
        _login(c)
        _episode_job(app, jobs_mod.KIND_PIPELINE, eid="nothingthere")
        _wait(app)
        assert app.state.runner.latest_post("nothingthere") is None and comp.calls == []


def test_compose_error_ends_post_job_failed_not_retried(tcfg, ws):  # R2: no automatic retry
    def boom(episode_id, config, clips, **kw):
        raise post_stage.PostComposeError("Ollama lỗi")

    c, app = make_client(tcfg, compose=boom)
    with c:
        _login(c)
        _episode_job(app, jobs_mod.KIND_RENDER)
        _wait(app)
        d = c.get(API).json()
        assert d["post_job"]["status"] == "failed" and "Ollama" in d["post_job"]["error"]
        assert len([j for j in app.state.runner.jobs() if j.kind == "post"]) == 1
