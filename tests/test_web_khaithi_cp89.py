"""CP8.9 khai thị on the web: POST /api/episodes with ``kinds`` (K7 + A1.1, AC7, AC11), GET fields (AC7), download
names / hashtags / "Tập lẻ" (K8, AC8), review actions on a khai thị episode (AC9), bộ kinh state with khai thị
(A1.2, A1.4, AC11, AC12). Fake pipeline / render (no real stage runs)."""

import io
import json
import shutil
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.playlists import combine_status, resume_kinds  # noqa: E402
from auto_short.workspace import Workspace  # noqa: E402

from render_helpers import EID, TITLES, make_render_episode, write_docs  # noqa: E402
from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
KT = EID + ".kt"
PL = "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp"


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"))


class FakeRender:
    def __init__(self):
        self.calls = []

    def __call__(self, episode_id, config):
        self.calls.append(episode_id)
        return SimpleNamespace(ran=True, rendered=2, clips=2, encoded=0, reused=2)


def client(cfg, *, calls=None, pipeline=None, render=None, preflight=lambda c: None, disk=None):
    app = app_mod.create_app(cfg, PW, preflight=preflight, render=render or FakeRender(),
                             pipeline=pipeline or fake_pipeline(calls if calls is not None else []),
                             disk_usage=disk or (lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9)))
    c = TestClient(app, follow_redirects=False)
    return c


def _login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def _source_uri(cfg, episode_id, video_id=EID):
    ws = Workspace(Path(cfg.workspace.dir), episode_id)
    m = ws.load_manifest()
    m["source"]["uri"] = f"https://youtu.be/{video_id}"
    ws.save_manifest(m)


def make_short(cfg, tmp_path):
    """Short episode EID: titles, render of k01 + k02 (fake mp4), 4 kB source.mp4, every stage done."""
    tmpl = tmp_path / "fake.mp4"
    tmpl.write_bytes(b"s" * 4096)
    ws = make_render_episode(Path(cfg.workspace.dir), tmpl)
    write_docs(ws)
    write_episode(cfg, EID, titles=TITLES)
    return ws


def make_kt(cfg, lo=4, hi=7, titles=None):
    """Khai thị episode EID.kt built like the Short (own docs, render manifest, source copy) + khaithi.json."""
    root = Path(cfg.workspace.dir)
    shutil.copytree(root / EID, root / KT)
    ws = Workspace(root, KT)
    for name in ("publish.json", "review.json"):  # user state of the Short, not of the khai thị episode
        (ws.dir / name).unlink(missing_ok=True)
    write_docs(ws)
    write_episode(cfg, KT, titles=titles or {"k01": "Khai thị một", "k02": "Khai thị hai"})
    _source_uri(cfg, KT)
    khaithi.write(ws.dir, KhaiThi(EID, lo, hi))
    return ws


# --- POST /api/episodes (AC7, AC11) -------------------------------------------------------------------------

def test_submit_default_makes_short_then_khaithi(tcfg):
    calls = []
    with client(tcfg, calls=calls) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}?si=x"})
        assert r.status_code == 202
        body = r.json()
        assert [(e["kind"], e["episode_id"], e["created"]) for e in body["episodes"]] == \
            [("short", EID, True), ("khaithi", KT, True)]
        assert (body["kind"], body["created"], body["episode_id"]) == ("video", True, EID)
        assert int(body["episodes"][0]["job"]["id"]) < int(body["episodes"][1]["job"]["id"])  # Short first
        assert khaithi.read(Path(tcfg.workspace.dir) / KT, 15) == KhaiThi(EID, 4, 7)  # A1 defaults
        assert c.app.state.runner.wait_idle(10)
        ingests = [(target, kw.get("episode_id")) for stage, target, kw in calls if stage == "ingest"]
        assert ingests == [(f"https://youtu.be/{EID}", None), (f"https://youtu.be/{EID}", KT)]


def test_submit_single_kind(tcfg):
    calls = []
    with client(tcfg, calls=calls) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["khaithi"],
                                          "min_minutes": 5, "max_minutes": 10})
        assert r.status_code == 202 and r.json()["episode_id"] == KT
        assert [e["kind"] for e in r.json()["episodes"]] == ["khaithi"]
        assert c.app.state.runner.wait_idle(10)
        assert khaithi.read(Path(tcfg.workspace.dir) / KT, 15) == KhaiThi(EID, 5, 10)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["short"]})
        assert r.status_code == 202 and [e["episode_id"] for e in r.json()["episodes"]] == [EID]
        assert c.app.state.runner.wait_idle(10)
        assert len(c.app.state.runner.jobs()) == 2


@pytest.mark.parametrize("extra, msg", [
    ({"kinds": []}, "kinds"), ({"kinds": ["short", "short"]}, "trùng"), ({"kinds": ["x"]}, "kinds"),
    ({"kinds": "short"}, "kinds"), ({"kinds": ["short"], "min_minutes": 4}, "Số phút chỉ dùng"),
    ({"min_minutes": 7, "max_minutes": 5}, "nhỏ hơn"), ({"min_minutes": 5.5}, "số nguyên"),
    ({"max_minutes": 16}, "quá 15"), ({"min_minutes": 0}, "từ 1"), ({"min_minutes": "5"}, "số nguyên"),
])
def test_submit_invalid(tcfg, extra, msg):
    with client(tcfg) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", **extra})
        assert r.status_code == 422 and msg in r.json()["detail"]
        assert c.app.state.runner.jobs() == []
        assert not (Path(tcfg.workspace.dir) / KT).exists()


def test_submit_unauthenticated(tcfg):
    with client(tcfg) as c:
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["khaithi"]})
        assert r.status_code == 401


def test_submit_duplicate_and_archived(tcfg):
    gate = threading.Event()
    with client(tcfg, pipeline=fake_pipeline([], gate=gate)) as c:
        _login(c)
        first = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}"}).json()
        again = c.post("/api/episodes", json={"url": f"https://www.youtube.com/watch?v={EID}"})
        assert again.status_code == 200
        assert [(e["created"], e["job"]["id"]) for e in again.json()["episodes"]] == \
            [(False, e["job"]["id"]) for e in first["episodes"]]
        gate.set()
        assert c.app.state.runner.wait_idle(10)
    root = Path(tcfg.workspace.dir)
    (root / KT / "archive.json").write_text("{}", encoding="utf-8")
    with client(tcfg) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}"})
        assert r.status_code == 202  # the Short still runs
        short, kt = r.json()["episodes"]
        assert short["created"] is True and kt["status"] == 409 and "đã dọn video nguồn" in kt["error"]
        assert c.app.state.runner.wait_idle(10)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["khaithi"]})
        assert r.status_code == 409 and "đã dọn video nguồn" in r.json()["detail"]


def test_submit_preflight_and_disk(tcfg):
    from auto_short.pipeline import PreflightError

    def down(cfg):
        raise PreflightError("cannot reach Ollama")

    with client(tcfg, preflight=down) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}"})
        assert r.status_code == 503 and [e["status"] for e in r.json()["episodes"]] == [503, 503]
        assert not (Path(tcfg.workspace.dir) / KT / "khaithi.json").exists()
    with client(tcfg, disk=lambda p: (100 * 10**9, 99 * 10**9, 10**9)) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["khaithi"]})
        assert r.status_code == 507


def test_minutes_change_rewrites_khaithi_json(tcfg):
    with client(tcfg) as c:
        _login(c)
        c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["khaithi"]})
        assert c.app.state.runner.wait_idle(10)
        c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "kinds": ["khaithi"], "min_minutes": 3,
                                      "max_minutes": 6})
        assert c.app.state.runner.wait_idle(10)
        assert khaithi.read(Path(tcfg.workspace.dir) / KT, 15) == KhaiThi(EID, 3, 6)


# --- GET fields, names, hashtags, Tập lẻ (AC7, AC8) ---------------------------------------------------------

def test_get_fields_names_and_zip(tcfg, tmp_path):
    make_short(tcfg, tmp_path)
    make_kt(tcfg, 5, 10)
    with client(tcfg) as c:
        _login(c)
        s = c.get(f"/api/episodes/{EID}").json()
        k = c.get(f"/api/episodes/{KT}").json()
        assert (s["kind"], s["min_minutes"], s["base_episode_id"], s["khaithi_episode_id"]) == \
            ("short", None, None, KT)
        assert (k["kind"], k["min_minutes"], k["max_minutes"], k["base_episode_id"], k["khaithi_episode_id"]) == \
            ("khaithi", 5, 10, EID, None)
        items = {i["id"]: i for i in c.get("/api/episodes").json()["episodes"]}
        assert items[KT]["kind"] == "khaithi" and items[KT]["base_episode_id"] == EID
        assert items[EID]["khaithi_episode_id"] == KT
        # K8 names: <episode> = base id (write_episode's titles.json has no header fields)
        assert k["shorts"][0]["download_name"] == f"Tập{EID}_KT01_Khai thị một.mp4"
        assert k["zip_name"] == f"Tập{EID}_KhaiThị.zip"
        assert s["shorts"][0]["download_name"].startswith(f"Tập{EID}_S01_")
        r = c.get(f"/files/{KT}/shorts.zip")
        assert r.status_code == 200 and "filename*=UTF-8''T%E1%BA%ADp" in r.headers["content-disposition"]
        assert "KhaiTh%E1%BB%8B.zip" in r.headers["content-disposition"]
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assert names[0].startswith(f"Tập{EID}_KT01_")
        r = c.get(f"/files/{KT}/k02.mp4?download=1")
        assert "_KT02_" in r.headers["content-disposition"] or "KT02" in r.headers["content-disposition"]


def test_header_episode_label_and_playlist_hashtags(tcfg, tmp_path):
    make_short(tcfg, tmp_path)
    kt = make_kt(tcfg)
    titles = json.loads((kt.dir / "titles.json").read_text(encoding="utf-8"))
    titles["header"] = {"lines": ["HT.Tịnh Không", "Kinh A (tập 29)"],
                        "fields": {"speaker": "HT.Tịnh Không", "series": "Kinh A", "episode": "29"}}
    (kt.dir / "titles.json").write_text(json.dumps(titles, ensure_ascii=False), encoding="utf-8")
    pl_dir = Path(tcfg.workspace.dir) / "_playlists"
    pl_dir.mkdir()
    (pl_dir / f"{PL}.json").write_text(json.dumps({
        "schema_version": 1, "playlist_id": PL, "title": "Bộ kinh", "url": "u", "fetched_at": "t",
        "entries": [{"index": 1, "video_id": EID, "title": "t", "duration": 1.0, "episode": "29",
                     "available": True}], "hashtags": ["BộKinhA", "TịnhĐộ"]}, ensure_ascii=False), encoding="utf-8")
    with client(tcfg) as c:
        _login(c)
        k = c.get(f"/api/episodes/{KT}").json()
        assert k["shorts"][0]["download_name"] == "Tập29_KT01_Khai thị một.mp4"
        assert k["zip_name"] == "Tập29_KhaiThị.zip"
        assert k["shorts"][0]["hashtags"] == ["#BộKinhA", "#TịnhĐộ"]  # CP8.8 H4 via the base video
        items = {i["id"]: i for i in c.get("/api/episodes").json()["episodes"]}
        assert items[KT]["in_playlist"] is True and items[EID]["in_playlist"] is True  # not in "Tập lẻ"


# --- review actions on a khai thị episode (AC9) -----------------------------------------------------------------

def test_review_actions_on_khaithi(tcfg, tmp_path):
    make_short(tcfg, tmp_path)
    kt = make_kt(tcfg)
    render = FakeRender()
    with client(tcfg, render=render) as c:
        _login(c)
        base = f"/api/episodes/{KT}/shorts"
        assert c.post(f"{base}/k01/published", json={"value": True}).json()["published"] is True
        r = c.post(f"{base}/k02/title", json={"set": "Tiêu đề khai thị mới"})
        assert r.status_code == 202 and r.json()["job"]["episode_id"] == KT
        assert c.app.state.runner.wait_idle(5)
        assert c.post(f"{base}/k02/delete").status_code == 202
        assert c.app.state.runner.wait_idle(5)
        assert c.post(f"{base}/k02/restore").status_code == 202
        assert c.app.state.runner.wait_idle(5) and render.calls == [KT, KT, KT]
        assert json.loads((kt.dir / "review.json").read_text(encoding="utf-8"))["episode_id"] == KT
        short_before = sorted(p.name for p in (Path(tcfg.workspace.dir) / EID).iterdir())
        # archive + delete the khai thị episode: the Short is untouched
        assert c.post(f"/api/episodes/{KT}/archive").status_code == 200
        assert not (kt.dir / "source.mp4").exists() and (Path(tcfg.workspace.dir) / EID / "source.mp4").exists()
        assert c.delete(f"/api/episodes/{KT}").status_code == 200
        assert not kt.dir.exists() and not (Path(tcfg.render.output_dir) / KT).exists()
        assert sorted(p.name for p in (Path(tcfg.workspace.dir) / EID).iterdir()) == short_before
        assert c.get(f"/api/episodes/{EID}").json()["khaithi_episode_id"] is None


def test_deleting_short_keeps_khaithi(tcfg, tmp_path):
    make_short(tcfg, tmp_path)
    kt = make_kt(tcfg)
    before = sorted(p.name for p in kt.dir.iterdir())
    with client(tcfg) as c:
        _login(c)
        assert c.post(f"/api/episodes/{EID}/archive").status_code == 200
        assert (kt.dir / "source.mp4").exists()
        assert c.delete(f"/api/episodes/{EID}").status_code == 200
        assert sorted(p.name for p in kt.dir.iterdir()) == before
        k = c.get(f"/api/episodes/{KT}").json()
        assert k["kind"] == "khaithi" and k["rendered"] == 2


# --- bộ kinh with khai thị (A1.2, A1.4; AC11, AC12) ---------------------------------------------------------------

def _st(state, shorts=0, published=0, complete=False, error=None, stage=None):
    return {"state": state, "stage": stage, "error": error, "shorts": shorts, "published": published,
            "archived": False, "complete": complete, "deleted_at": None}


def test_combine_status_rules():
    assert combine_status(_st("complete", 3, 3, True), None)["state"] == "complete"  # no khai thị: unchanged
    c = combine_status(_st("complete", 3, 3, True), _st("rendered", 2, 1))
    assert (c["state"], c["complete"], c["shorts"], c["khaithi_videos"], c["khaithi_published"]) == \
        ("rendered", False, 3, 2, 1)
    c = combine_status(_st("complete", 3, 3, True), _st("complete", 2, 2, True))
    assert (c["state"], c["complete"]) == ("complete", True)
    assert combine_status(_st("rendered", 3), _st("processing", stage="selection"))["state"] == "processing"
    assert combine_status(_st("queued"), _st("new"))["state"] == "queued"
    c = combine_status(_st("complete", 3, 3, True), _st("failed", error="selection: boom"))
    assert c["state"] == "failed" and c["error"] == "khai thị: selection: boom"
    assert combine_status(_st("new"), _st("incomplete"))["state"] == "new"
    assert combine_status(_st("complete", 3, 3, True), _st("incomplete"))["state"] == "incomplete"
    # A1.2 "Chạy tiếp"
    assert resume_kinds(combine_status(_st("failed"), None)) == ["short"]
    assert resume_kinds(combine_status(_st("complete", 3, 3, True), _st("incomplete"))) == ["khaithi"]
    assert resume_kinds(combine_status(_st("failed"), _st("failed"))) == ["short", "khaithi"]
    assert resume_kinds(combine_status(_st("failed"), _st("rendered", 2))) == ["short"]


def _playlist(cfg):
    pl_dir = Path(cfg.workspace.dir) / "_playlists"
    pl_dir.mkdir(exist_ok=True)
    (pl_dir / f"{PL}.json").write_text(json.dumps({
        "schema_version": 1, "playlist_id": PL, "title": "Bộ kinh", "url": "u", "fetched_at": "t",
        "entries": [{"index": 1, "video_id": EID, "title": "t", "duration": 1.0, "episode": "9",
                     "available": True}]}), encoding="utf-8")


def test_playlist_xong_needs_both(tcfg, tmp_path):
    make_short(tcfg, tmp_path)
    _playlist(tcfg)
    with client(tcfg) as c:
        _login(c)
        for clip in ("k01", "k02"):
            c.post(f"/api/episodes/{EID}/shorts/{clip}/published", json={"value": True})
        e = c.get(f"/api/playlists/{PL}").json()["entries"][0]
        assert (e["state"], e["complete"], e["khaithi_episode_id"], e["khaithi_state"]) == \
            ("complete", True, None, None)  # before CP8.9: unchanged
        make_kt(tcfg)
        c.app.state.playlists.invalidate()
        v = c.get(f"/api/playlists/{PL}").json()
        e = v["entries"][0]
        assert (e["state"], e["complete"], e["khaithi_episode_id"], e["khaithi_videos"], e["khaithi_published"]) == \
            ("rendered", False, KT, 2, 0)
        assert v["counts"]["done"] == 0 and v["counts"]["doing"] == 1
        for clip in ("k01", "k02"):
            c.post(f"/api/episodes/{KT}/shorts/{clip}/published", json={"value": True})
        v = c.get(f"/api/playlists/{PL}").json()
        e = v["entries"][0]
        assert (e["state"], e["complete"], e["khaithi_published"]) == ("complete", True, 2)
        assert c.get("/api/playlists").json()["playlists"][0]["complete"] == 1


def test_playlist_resume_sends_unfinished_kinds(tcfg, tmp_path):
    make_short(tcfg, tmp_path)
    kt = make_kt(tcfg)
    m = kt.load_manifest()
    m["stages"]["selection"]["status"] = "failed"
    m["stages"]["selection"]["error"] = "boom"
    kt.save_manifest(m)
    _playlist(tcfg)
    calls = []
    with client(tcfg, calls=calls) as c:
        _login(c)
        e = c.get(f"/api/playlists/{PL}").json()["entries"][0]
        assert (e["state"], e["action"], e["resume_kinds"]) == ("failed", "resume", ["khaithi"])
        assert e["error"] == "khai thị: boom"
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "mode": "video",
                                          "kinds": e["resume_kinds"]})
        assert r.status_code == 202 and [x["episode_id"] for x in r.json()["episodes"]] == [KT]
        assert c.app.state.runner.wait_idle(10)


# --- A2 bộ kinh page (AC14) ---------------------------------------------------------------------------------------

def test_playlist_kind_bar_defaults_and_page(tcfg, tmp_path):
    from dataclasses import replace
    make_short(tcfg, tmp_path)
    _playlist(tcfg)
    cfg = replace(tcfg, khaithi=replace(tcfg.khaithi, default_min_minutes=3, default_max_minutes=9))
    with client(cfg) as c:
        _login(c)
        v = c.get(f"/api/playlists/{PL}").json()
        assert v["khaithi_defaults"] == {"min_minutes": 3, "max_minutes": 9, "max_minutes_limit": 15}
        page = c.get(f"/playlists/{PL}").text
        assert 'id="pl-kinds"' in page and 'value="short" checked' in page and 'value="khaithi" checked' in page
        js = c.get("/static/app.js").text
        assert 'let plFilter = "doing"' in js and "autoShort.plFilter" in js and "autoShort.plKinds" in js
        # "Xử lý" with the kind bar = Short only -> one job, no khai thị episode
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{EID}", "mode": "video", "kinds": ["short"]})
        assert [e["kind"] for e in r.json()["episodes"]] == ["short"]
        assert c.app.state.runner.wait_idle(10)
        assert not (Path(cfg.workspace.dir) / KT).exists()


def test_khaithi_labels_in_ui_script(tcfg):
    with client(tcfg) as c:
        _login(c)
        js = c.get("/static/app.js").text
        assert "`Xóa ${noun()}`" in js and "Hiện ${noun()} đã xóa" in js and '"Dựng video khai thị"' in js
        assert '"Xóa Short"' not in js
