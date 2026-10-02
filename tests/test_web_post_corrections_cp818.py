"""CP8.18 web routes: D5 (rules CRUD, 422 / 404 / auth), D4 (approve applies to unposted ai/raw posts of every episode),
D2/D6 via ``PUT …/posts/{clip}`` (``proposed``, edit log, never failing the save). Nothing outside tmp_path."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, PostConfig, RenderConfig, WebConfig, WorkspaceConfig  # noqa: E402
from auto_short.post import corrections as C  # noqa: E402
from auto_short.post import store as post_store  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from post_helpers import EID, make_post_episode  # noqa: E402
from web_helpers import fake_pipeline  # noqa: E402

PW = "pw"
EID2 = "post8TestEp2"
NOW = "2026-10-02T08:00:00Z"
RULES = "/api/post-corrections"


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(image_dir=tmp_path / "images", corrections_path=tmp_path / "data" / "corr.json"),
                 web=WebConfig(queue_mode="serial"))


@pytest.fixture
def eps(tcfg):
    make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir)
    make_post_episode(tcfg.workspace.dir, tcfg.render.output_dir, episode_id=EID2)


def seed(cfg, eid, clip, paragraphs, *, origin="ai", posted=False):
    path = cfg.workspace.dir / eid / post_store.POSTS_NAME
    doc = post_store.read_posts(path, eid)
    doc = post_store.with_compose(doc, ["k01", "k02"], clip_id=clip, candidate_id="c00001" if clip == "k01" else "c00002",
                                  source_sha256="a" * 64, paragraphs=paragraphs, origin=origin, image=None, now=NOW)
    if posted:
        doc = post_store.with_posted(doc, ["k01", "k02"], clip, True, now=NOW)
    post_store.write(path, doc)


def paragraphs_of(cfg, eid, clip):
    return post_store.find(post_store.read_posts(cfg.workspace.dir / eid / post_store.POSTS_NAME, eid), clip)


def make_client(cfg):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, render=lambda eid, c: SimpleNamespace(ran=False),
                             pipeline=fake_pipeline([]), post_preflight=lambda c: None)
    c = TestClient(app, follow_redirects=False)
    return c


def login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def test_auth_required(tcfg, eps):
    with make_client(tcfg) as c:
        assert c.get(RULES).status_code == 401
        assert c.post(RULES, json={"from": "a", "to": "b"}).status_code == 401
        assert c.put(f"{RULES}/r0001", json={"status": "approved"}).status_code == 401
        assert c.delete(f"{RULES}/r0001").status_code == 401


def test_get_empty_when_no_file(tcfg, eps):  # AC9
    with make_client(tcfg) as c:
        login(c)
        d = c.get(RULES).json()
        assert d == {"rules": [], "stats": {"saves": 0, "avg_changed_pct": None}, "error": None}


def test_get_corrupt_returns_error_and_keeps_file(tcfg, eps):  # AC9
    tcfg.post.corrections_path.parent.mkdir(parents=True)
    tcfg.post.corrections_path.write_text("{oops", encoding="utf-8")
    with make_client(tcfg) as c:
        login(c)
        d = c.get(RULES).json()
        assert d["rules"] == [] and d["error"]
        assert c.post(RULES, json={"from": "a", "to": "b"}).status_code == 422
    assert tcfg.post.corrections_path.read_text(encoding="utf-8") == "{oops"


def test_add_rule_applies_to_unposted_ai_raw_only(tcfg, eps):  # AC6, AC7
    seed(tcfg, EID, "k01", ["Hết thầy tất cả, đều vậy.", "Hết thầy tất cả."])
    seed(tcfg, EID, "k02", ["Hết thầy tất cả."], posted=True)
    seed(tcfg, EID2, "k01", ["Ông nói “hết thầy tất cả”."], origin="raw")
    seed(tcfg, EID2, "k02", ["Hết thầy tất cả."], origin="manual")
    with make_client(tcfg) as c:
        login(c)
        r = c.post(RULES, json={"from": "Hết thầy tất cả", "to": "hết thảy tất cả"})
        assert r.status_code == 200
        body = r.json()
        assert body["rule"]["status"] == "approved" and body["rule"]["from"] == "hết thầy tất cả"
        assert body["applied"] == {"posts": 2, "places": 3}
    a = paragraphs_of(tcfg, EID, "k01")
    assert a["paragraphs"] == ["Hết thảy tất cả, đều vậy.", "Hết thảy tất cả."]
    assert a["origin"] == "ai" and a["updated_at"] != NOW
    assert paragraphs_of(tcfg, EID, "k02")["paragraphs"] == ["Hết thầy tất cả."]  # posted
    assert paragraphs_of(tcfg, EID2, "k01")["paragraphs"] == ["Ông nói “hết thảy tất cả”."]
    m = paragraphs_of(tcfg, EID2, "k02")
    assert m["paragraphs"] == ["Hết thầy tất cả."] and m["updated_at"] == NOW  # manual


def test_validation_422_and_404(tcfg, eps):  # AC7
    with make_client(tcfg) as c:
        login(c)
        for body in [{"from": "", "to": "b"}, {"from": "a b c d e f g h i", "to": "b"}, {"from": "a", "to": "A."},
                     {"from": "a", "to": ""}]:
            assert c.post(RULES, json=body).status_code == 422, body
        assert c.post(RULES, json={"from": "a b", "to": "c d"}).status_code == 200
        r = c.post(RULES, json={"from": "A b", "to": "x y"})  # same approved `from`
        assert r.status_code == 422
        assert c.put(f"{RULES}/r9999", json={"status": "approved"}).status_code == 404
        assert c.delete(f"{RULES}/r9999").status_code == 404
        assert c.put(f"{RULES}/r0001", json={}).status_code == 422
        assert c.put(f"{RULES}/r0001", json={"status": "bogus"}).status_code == 422


def test_put_status_flow_and_dup_approved(tcfg, eps):  # AC6, AC7
    seed(tcfg, EID, "k01", ["Câu suốt thế gian này."])
    doc = C.record(C.empty_doc(), [("suốt thế", "xuất thế"), ("suốt thế", "xuất gia")], "e", "k", NOW)
    C.save(tcfg.post.corrections_path, doc)
    with make_client(tcfg) as c:
        login(c)
        r = c.put(f"{RULES}/r0001", json={"status": "approved", "from": "suốt thế", "to": "xuất thế gian"})
        assert r.status_code == 200
        assert r.json()["applied"] == {"posts": 1, "places": 1}
        assert paragraphs_of(tcfg, EID, "k01")["paragraphs"] == ["Câu xuất thế gian gian này."]
        assert c.put(f"{RULES}/r0002", json={"status": "approved"}).status_code == 422  # same `from`
        r = c.put(f"{RULES}/r0002", json={"status": "rejected"})
        assert r.status_code == 200 and "applied" not in r.json() and r.json()["rule"]["status"] == "rejected"
        r = c.put(f"{RULES}/r0001", json={"status": "proposed"})  # un-approve: posts are not reverted
        assert r.status_code == 200 and "applied" not in r.json()
        assert paragraphs_of(tcfg, EID, "k01")["paragraphs"] == ["Câu xuất thế gian gian này."]
        assert c.delete(f"{RULES}/r0002").status_code == 200
        rules = c.get(RULES).json()["rules"]
        assert [x["id"] for x in rules] == ["r0001"]


def test_put_post_records_proposal_and_edit_log(tcfg, eps):  # AC1, AC2, AC8
    seed(tcfg, EID, "k01", ["Pháp và suốt thế gian Pháp."])
    seed(tcfg, EID2, "k01", ["Pháp và suốt thế gian Pháp."])
    with make_client(tcfg) as c:
        login(c)
        r = c.put(f"/api/episodes/{EID}/posts/k01", json={"paragraphs": ["Pháp và xuất thế gian Pháp."]})
        assert r.status_code == 200 and r.json()["proposed"] == 1 and r.json()["origin"] == "manual"
        rules = c.get(RULES).json()["rules"]
        assert len(rules) == 1
        assert (rules[0]["from"], rules[0]["to"], rules[0]["status"], rules[0]["count"]) == \
            ("và suốt thế", "và xuất thế", "proposed", 1)
        r = c.put(f"/api/episodes/{EID2}/posts/k01", json={"paragraphs": ["Pháp và xuất thế gian Pháp."]})
        assert r.json()["proposed"] == 1
        rules = c.get(RULES).json()["rules"]
        assert len(rules) == 1 and rules[0]["count"] == 2
        # punctuation / case only, and a rewrite > 3 tokens: no proposal, still saved as manual
        r = c.put(f"/api/episodes/{EID}/posts/k01", json={"paragraphs": ["pháp, và xuất thế gian pháp"]})
        assert r.json()["proposed"] == 0
        r = c.put(f"/api/episodes/{EID}/posts/k01", json={"paragraphs": ["Một hai ba bốn năm sáu bảy."]})
        assert r.json()["proposed"] == 0 and r.json()["origin"] == "manual"
        assert len(c.get(RULES).json()["rules"]) == 1
        # link-only edit has no `proposed`
        r = c.put(f"/api/episodes/{EID}/posts/k01", json={"link": "https://youtu.be/abcdefghijk"})
        assert "proposed" not in r.json()
        st = c.get(RULES).json()["stats"]
    assert st["saves"] == 4
    lines = [json.loads(x) for x in (tcfg.post.corrections_path.parent / "post-edit-log.jsonl").read_text().splitlines()]
    assert [(x["words"], x["changed_words"]) for x in lines[:2]] == [(6, 1), (6, 1)]
    assert lines[0]["episode_id"] == EID and lines[0]["clip_id"] == "k01"


def test_rejected_rule_not_reproposed(tcfg, eps):  # AC3
    seed(tcfg, EID, "k01", ["Pháp và suốt thế gian Pháp."])
    with make_client(tcfg) as c:
        login(c)
        c.put(f"/api/episodes/{EID}/posts/k01", json={"paragraphs": ["Pháp và xuất thế gian Pháp."]})
        assert c.put(f"{RULES}/r0001", json={"status": "rejected"}).status_code == 200
        seed(tcfg, EID, "k01", ["Pháp và suốt thế gian Pháp."])
        c.put(f"/api/episodes/{EID}/posts/k01", json={"paragraphs": ["Pháp và xuất thế gian Pháp."]})
        rules = c.get(RULES).json()["rules"]
        assert len(rules) == 1 and rules[0]["status"] == "rejected" and rules[0]["count"] == 2


def test_put_post_survives_dictionary_failure(tcfg, eps):  # AC3
    seed(tcfg, EID, "k01", ["Pháp và suốt thế gian Pháp."])
    tcfg.post.corrections_path.parent.mkdir(parents=True)
    tcfg.post.corrections_path.write_text("{oops", encoding="utf-8")
    with make_client(tcfg) as c:
        login(c)
        r = c.put(f"/api/episodes/{EID}/posts/k01", json={"paragraphs": ["Pháp và xuất thế gian Pháp."]})
        assert r.status_code == 200 and r.json()["proposed"] is None and r.json()["origin"] == "manual"
    assert tcfg.post.corrections_path.read_text(encoding="utf-8") == "{oops"
    assert paragraphs_of(tcfg, EID, "k01")["paragraphs"] == ["Pháp và xuất thế gian Pháp."]


def test_put_post_survives_unwritable_dictionary(tcfg, eps, tmp_path):  # AC3
    seed(tcfg, EID, "k01", ["Pháp và suốt thế gian Pháp."])
    blocker = tmp_path / "data"
    blocker.write_text("a file, not a directory", encoding="utf-8")  # corrections_path's parent cannot be created
    with make_client(tcfg) as c:
        login(c)
        r = c.put(f"/api/episodes/{EID}/posts/k01", json={"paragraphs": ["Pháp và xuất thế gian Pháp."]})
        assert r.status_code == 200 and r.json()["proposed"] is None


def test_stats_use_last_20_saves(tcfg, eps):  # AC8
    for n in range(25):
        C.append_edit_log(tcfg.post.corrections_path, at=NOW, episode_id=EID, clip_id="k01", words=10,
                          changed_words=10 if n < 5 else 1)
    with make_client(tcfg) as c:
        login(c)
        assert c.get(RULES).json()["stats"] == {"saves": 25, "avg_changed_pct": 10.0}
