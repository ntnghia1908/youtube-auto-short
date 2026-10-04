"""CP8.19 web: ``PUT /api/playlists/{id}/doc`` (D1: validation, field kept across refresh / other edits, ``check``),
D7 (recompose of unposted ``ai`` / ``raw`` posts of Short + khai thị episodes, ``queued``), D8 (``origin: doc`` in the
posts view, no "ít dấu câu"), static UI hooks. AI / network are fakes; nothing outside tmp_path."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, PostConfig, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.post import doc as post_doc  # noqa: E402
from auto_short.post import store as post_store  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.app import STATIC_DIR  # noqa: E402
from doc_helpers import BASE_URL, write_playlist  # noqa: E402
from post_helpers import EID, make_post_episode  # noqa: E402
from test_web_post_cp815 import FakeComposeAI  # noqa: E402
from web_helpers import fake_pipeline  # noqa: E402

PW = "pw"
PL = "PLdocTest0123456789"
EID2 = "post8TestEp2"
KT = EID + ".kt"
NOW = "2026-10-02T08:00:00Z"
URL = "https://ph.tinhtong.vn/Home/KinhThu?d=KinhThu_001.html"


@pytest.fixture(params=["lanes", "serial"])
def tcfg(tmp_path, request) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(image_dir=tmp_path / "images"), web=WebConfig(queue_mode=request.param))


class FakePrepare:
    """Stand-in for ``doc.prepare`` (the ``check``): records calls, returns a DocText with ``match`` or raises."""

    def __init__(self, match: float | None = 0.88, error: Exception | None = None):
        self.match, self.error, self.calls = match, error, []

    def __call__(self, episode_id, workspace_dir, segments):
        self.calls.append((episode_id, len(segments)))
        if self.error:
            raise self.error
        return post_doc.build_text(BASE_URL, ["Một."], self.match)


def make_client(cfg, *, compose=None, prepare=None):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, render=lambda eid, c: SimpleNamespace(ran=False),
                             pipeline=fake_pipeline([]), post_compose=compose or FakeComposeAI(),
                             post_preflight=lambda c: None, doc_prepare=prepare or FakePrepare(),
                             playlist_lister=lambda url, c: {"id": PL, "title": "KT", "entries": [
                                 {"id": EID, "title": "Kinh Thử tập 1", "duration": 1.0}]})
    return TestClient(app, follow_redirects=False), app


def login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def seed(cfg, eid, clip, *, origin="ai", posted=False, paragraphs=("Một đoạn.",)):
    path = cfg.workspace.dir / eid / post_store.POSTS_NAME
    doc = post_store.read_posts(path, eid)
    doc = post_store.with_compose(doc, ["k01", "k02"], clip_id=clip,
                                  candidate_id="c00001" if clip == "k01" else "c00002", source_sha256="a" * 64,
                                  paragraphs=list(paragraphs), origin=origin, image=None, now=NOW)
    if posted:
        doc = post_store.with_posted(doc, ["k01", "k02"], clip, True, now=NOW)
    post_store.write(path, doc)


def playlist_file(cfg):
    return cfg.workspace.dir / "_playlists" / f"{PL}.json"


@pytest.fixture
def pl(tcfg):
    write_playlist(tcfg.workspace.dir, PL, [(EID, "1"), (EID2, "2")], doc_url=None)


def put(c, body):
    return c.put(f"/api/playlists/{PL}/doc", json=body)


def test_auth_required(tcfg, pl):
    c, _ = make_client(tcfg)
    with c:
        assert put(c, {"url": URL}).status_code == 401


def test_validation_404_422(tcfg, pl):  # AC1
    c, _ = make_client(tcfg)
    with c:
        login(c)
        assert c.put("/api/playlists/PLnope0123456789/doc", json={"url": URL}).status_code == 404
        for bad in ({"url": "http://ph.tinhtong.vn/Home/A?d=A_001.html"}, {"url": "https://evil.example/Home/A?d=A_1.html"},
                    {"url": "https://ph.tinhtong.vn/Home/A?d=B_001.html"}, {"url": 5}, {"url": ""}, {}):
            assert put(c, bad).status_code == 422, bad
        assert "doc_url" not in json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))


def test_put_saves_get_returns_null_clears_and_survives_refresh_and_other_edits(tcfg, pl):  # AC1
    c, _ = make_client(tcfg)
    with c:
        login(c)
        assert c.get(f"/api/playlists/{PL}").json()["doc_url"] is None
        r = put(c, {"url": f"  {URL} "})
        assert r.status_code == 200
        body = r.json()
        assert body["doc_url"] == URL and body["playlist_id"] == PL
        assert c.get(f"/api/playlists/{PL}").json()["doc_url"] == URL
        assert json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))["doc_url"] == URL
        # "Làm mới", hashtags and series keep the link (and are kept by it)
        assert c.post(f"/api/playlists/{PL}/refresh").status_code == 200
        assert c.get(f"/api/playlists/{PL}").json()["doc_url"] == URL
        assert c.put(f"/api/playlists/{PL}/hashtags", json={"hashtags": ["Một"]}).status_code == 200
        assert c.put(f"/api/playlists/{PL}/series", json={"series": "Kinh Thử"}).status_code == 200
        assert c.delete(f"/api/playlists/{PL}/hashtags").status_code == 200
        stored = json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))
        assert stored["doc_url"] == URL and stored["series"] == "Kinh Thử"
        r = put(c, {"url": None})
        assert r.status_code == 200 and r.json() == {"playlist_id": PL, "doc_url": None, "check": None, "queued": 0,
                                                    "doc_videos_per_page": 1}
        assert "doc_url" not in json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))
        assert c.get(f"/api/playlists/{PL}").json()["doc_url"] is None


def test_check_uses_first_episode_with_transcript(tcfg, pl):  # AC1 (check)
    prepare = FakePrepare(match=0.88)
    c, _ = make_client(tcfg, prepare=prepare)
    with c:
        login(c)
        assert put(c, {"url": URL}).json()["check"] is None  # no episode has a transcript yet
        assert prepare.calls == []
        make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir, episode_id=EID2)  # tập 2 has one
        r = put(c, {"url": URL}).json()
        assert r["check"] == {"episode_id": EID2, "episode": "2", "match": 0.88, "ok": True}
        assert prepare.calls[0][0] == EID2 and prepare.calls[0][1] > 0
        prepare.match = 0.02
        assert put(c, {"url": URL}).json()["check"] == {"episode_id": EID2, "episode": "2", "match": 0.02, "ok": False}
        prepare.error = post_doc.DocError("HTTP 404 khi tải")
        chk = put(c, {"url": URL}).json()["check"]
        assert chk["ok"] is False and chk["match"] is None and "404" in chk["error"]
        assert json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))["doc_url"] == URL  # still saved


def test_put_queues_recompose_of_unposted_ai_raw_posts_of_short_and_khaithi(tcfg, pl):  # AC7, AC8
    for eid in (EID, EID2, KT):
        make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir, episode_id=eid)
    seed(tcfg, EID, "k01", origin="ai")
    seed(tcfg, EID, "k02", origin="manual")
    seed(tcfg, EID2, "k01", origin="raw", posted=True)
    seed(tcfg, EID2, "k02", origin="raw")
    seed(tcfg, KT, "k01", origin="ai")
    seed(tcfg, KT, "k02", origin="doc")  # an older doc post is not recomposed by this rule (ai / raw only)
    compose = FakeComposeAI()
    c, app = make_client(tcfg, compose=compose)
    with c:
        login(c)
        r = put(c, {"url": URL})
        assert r.status_code == 200 and r.json()["queued"] == 3
        assert app.state.runner.wait_idle(10)
    assert sorted((e, tuple(clips)) for e, clips in compose.calls) == sorted(
        [(EID, ("k01",)), (EID2, ("k02",)), (KT, ("k01",))])


def test_put_queues_nothing_without_posts_and_null_does_not_queue(tcfg, pl):  # AC7
    make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir)  # EID: rendered but no posts.json
    compose = FakeComposeAI()
    c, app = make_client(tcfg, compose=compose)
    with c:
        login(c)
        assert put(c, {"url": URL}).json()["queued"] == 0
        seed(tcfg, EID, "k01")
        assert put(c, {"url": None}).json()["queued"] == 0
        assert app.state.runner.wait_idle(10)
    assert compose.calls == []


def test_posts_view_reports_doc_origin_without_low_punctuation_label(tcfg, pl):  # D8
    make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir)
    seed(tcfg, EID, "k01", origin="doc", paragraphs=["Chữ không dấu câu nào cả vậy đó"])
    seed(tcfg, EID, "k02", origin="ai", paragraphs=["Chữ không dấu câu nào cả vậy đó"])
    c, _ = make_client(tcfg)
    with c:
        login(c)
        posts = {p["clip_id"]: p for p in c.get(f"/api/episodes/{EID}/posts").json()["posts"]}
    assert posts["k01"]["origin"] == "doc" and posts["k01"]["low_punctuation"] is False
    assert posts["k02"]["low_punctuation"] is True


def test_static_ui_has_doc_field_and_origin_label():  # D1 UI, D8
    html = (STATIC_DIR / "playlist.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'id="dc-input"' in html and "Văn bản gốc" in html and 'id="dc-save"' in html and 'id="dc-reset"' in html
    assert "/doc`" in js and 'p.origin === "doc"' in js and "Văn bản gốc" in js


# --- CP8.24: videos per text page -------------------------------------------------------------------------------------

def test_cp824_videos_per_page_validation_save_and_view(tcfg, pl):  # AC3
    c, _ = make_client(tcfg)
    with c:
        login(c)
        for bad in (0, -1, 11, "2", "abc", 1.5, True):
            r = put(c, {"url": URL, "videos_per_page": bad})
            assert r.status_code == 422 and "số video mỗi trang" in r.json()["detail"], bad
        assert "doc_url" not in json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))
        assert c.get(f"/api/playlists/{PL}").json()["doc_videos_per_page"] == 1
        r = put(c, {"url": URL, "videos_per_page": 2})
        assert r.status_code == 200 and r.json()["doc_videos_per_page"] == 2
        assert c.get(f"/api/playlists/{PL}").json()["doc_videos_per_page"] == 2
        stored = json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))
        assert stored["doc_videos_per_page"] == 2
        # absent keeps; refresh / series edit keep; 1 removes the field; null url removes both
        assert put(c, {"url": URL}).json()["doc_videos_per_page"] == 2
        assert c.post(f"/api/playlists/{PL}/refresh").status_code == 200
        assert c.put(f"/api/playlists/{PL}/series", json={"series": "Kinh Thử"}).status_code == 200
        assert json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))["doc_videos_per_page"] == 2
        assert put(c, {"url": URL, "videos_per_page": 1}).json()["doc_videos_per_page"] == 1
        assert "doc_videos_per_page" not in json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))
        put(c, {"url": URL, "videos_per_page": 3})
        put(c, {"url": None})
        assert "doc_videos_per_page" not in json.loads(playlist_file(tcfg).read_text(encoding="utf-8"))


def test_cp824_ui_hooks():
    html = (STATIC_DIR / "playlist.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'id="dc-vpp"' in html and "Số video mỗi trang" in html
    assert "videos_per_page" in js and "doc_videos_per_page" in js
