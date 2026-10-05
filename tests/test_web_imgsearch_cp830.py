"""CP8.30 web routes: keyword image search job, candidate files, add to library, re-deal images (409 while a post job
runs). Fakes only: canned pages / images, no real network, no Ollama."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, PostConfig, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.post import imgsearch, store  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from post_helpers import EID, make_post_episode  # noqa: E402
from test_imgsearch_cp830 import SOURCES, FakeWeb, _public, png_pattern, site_routes, write_posts  # noqa: E402
from web_helpers import fake_pipeline  # noqa: E402

PW = "pw"


@pytest.fixture(params=["lanes", "serial"])
def tcfg(tmp_path, request) -> Config:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "01.png").write_bytes(png_pattern(700, 700, seed=3))
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(image_dir=tmp_path / "images"), web=WebConfig(queue_mode=request.param))


def fake_keyword_search(web):
    def run(keyword, config, progress):
        progress("fake")
        return imgsearch.run_search(keyword, config.post.image_dir, opener=web, resolver=_public, sources=SOURCES)
    return run


def make_client(cfg, **kw):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, render=lambda eid, c: SimpleNamespace(ran=False),
                             pipeline=fake_pipeline([]), **kw)
    c = TestClient(app, follow_redirects=False)
    return c, app


def login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def find_and_wait(c, app, keyword="Tây Phương Tam Thánh"):
    r = c.post("/api/post-images/find", json={"keyword": keyword})
    assert r.status_code == 202, r.text
    assert app.state.runner.wait_idle(30)
    return c.get(f"/api/post-images/find/{r.json()['job']['id']}").json()


def test_find_candidates_serve_thumbs_and_add(tcfg):
    c, app = make_client(tcfg, keyword_search=fake_keyword_search(FakeWeb(site_routes())))
    with c:
        assert c.post("/api/post-images/find", json={"keyword": "x"}).status_code in (302, 303, 401)  # needs login
        login(c)
        st = find_and_wait(c, app)
        assert st["status"] == "done" and len(st["candidates"]) == 3
        assert st["skipped"]["nhỏ hơn 600 px"] == 1 and "secret" not in str(st).lower()
        cand = st["candidates"][0]
        thumb = c.get(f"/files/post-image-candidates/{st['search_id']}/{cand['id']}?thumb=1")
        assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
        full = c.get(f"/files/post-image-candidates/{st['search_id']}/{cand['id']}")
        assert full.status_code == 200 and full.headers["content-type"] == "image/png"
        assert c.get(f"/files/post-image-candidates/{st['search_id']}/{'0' * 16}").status_code == 404
        assert c.get(f"/files/post-image-candidates/..%2Fx/{cand['id']}").status_code == 404
        before = c.get("/api/post-images").json()
        assert len(before["images"]) == 1 and before["search"] == {"google": {"enabled": False}}

        ids = [x["id"] for x in st["candidates"][:3]]
        r = c.post("/api/post-images/candidates/add", json={"search_id": st["search_id"], "ids": ids[:2]})
        assert r.status_code == 200 and r.json()["added"] == ["02.png", "03.png"]
        again = c.post("/api/post-images/candidates/add", json={"search_id": st["search_id"], "ids": ids[:2]}).json()
        assert again["added"] == [] and len(again["duplicate"]) == 2
        listing = c.get("/api/post-images").json()["images"]
        assert [i["name"] for i in listing] == ["01.png", "02.png", "03.png"]
        assert listing[1]["source"] == st["candidates"][0]["url"]
        assert c.post("/api/post-images/candidates/add", json={"search_id": st["search_id"], "ids": []}).status_code == 422
        assert c.post("/api/post-images/candidates/add", json={"search_id": "bad", "ids": ids}).status_code == 404


def test_find_rejects_empty_keyword_and_second_search_while_active(tcfg):
    gate = threading.Event()

    def slow(keyword, config, progress):
        gate.wait(10)
        return imgsearch.SearchOutcome("20260101000000-abcdef", keyword)

    c, app = make_client(tcfg, keyword_search=slow)
    with c:
        login(c)
        assert c.post("/api/post-images/find", json={"keyword": "  "}).status_code == 422
        assert c.post("/api/post-images/find", json={"keyword": "a di da"}).status_code == 202
        assert c.post("/api/post-images/find", json={"keyword": "a di da"}).status_code == 409
        gate.set()
        assert app.state.runner.wait_idle(10)
        assert c.get("/api/post-images/find/nope").status_code == 404


def test_redistribute_preview_confirm_and_backup(tcfg):
    work = tcfg.workspace.dir
    for n in (2, 3):
        (tcfg.post.image_dir / f"0{n}.png").write_bytes(png_pattern(700, 700, seed=n + 40))
    write_posts(work, "v1", [("k1", "01.png", True), ("k2", "01.png", False), ("k3", "01.png", False)])
    c, app = make_client(tcfg)
    with c:
        login(c)
        pv = c.post("/api/post-images/redistribute", json={}).json()
        assert pv["applied"] is False and pv["changes"] == 2 and pv["posted"] == 1 and pv["unposted"] == 2
        assert store.read_posts(work / "v1" / "posts.json", "v1")["posts"][1]["image"] == "01.png"  # preview: no write
        r = c.post("/api/post-images/redistribute", json={"confirm": True}).json()
        assert r["applied"] and r["changes"] == 2 and r["backup"]
        posts = store.read_posts(work / "v1" / "posts.json", "v1")["posts"]
        assert posts[0]["image"] == "01.png" and {p["image"] for p in posts[1:]} == {"02.png", "03.png"}
        assert (work / "_post-backups" / r["backup"] / "v1.json").is_file()
        assert c.post("/api/post-images/redistribute", json={"confirm": True}).json()["changes"] == 0


def test_redistribute_409_while_post_job_runs_and_422_empty_library(tcfg):
    make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir)
    gate = threading.Event()

    def blocking_compose(episode_id, config, clips, *, client=None, sleep=None, lock=None, before_ai=None):
        gate.wait(10)
        from auto_short.post import stage as post_stage
        return post_stage.ComposeSummary([], ai=0)

    c, app = make_client(tcfg, post_compose=blocking_compose, post_preflight=lambda cfg: None)
    with c:
        login(c)
        assert c.post(f"/api/episodes/{EID}/posts", json={"clips": ["k01"]}).status_code == 202
        r = c.post("/api/post-images/redistribute", json={"confirm": True})
        assert r.status_code == 409
        gate.set()
        assert app.state.runner.wait_idle(10)
        (tcfg.post.image_dir / "01.png").unlink()
        assert c.post("/api/post-images/redistribute", json={}).status_code == 422
