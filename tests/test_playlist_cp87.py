"""CP8.7: playlists (bộ kinh) on the web (L1–L5, fake yt-dlp), derived "Xong" (L4), download ticks "Đã đăng"
(bổ sung HUMAN LEAD 2026-09-27)."""

import io
import json
import threading
import time
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.review import episode_complete  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web.playlists import build_document, episode_number  # noqa: E402
from auto_short.web.urls import ASK, PLAYLIST, VIDEO, UrlError, classify_url  # noqa: E402

from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
PL = "PLOynZc0cJJfDVsh0G1RA3z-I3xSsuEvOp"
VIDS = ["aaaaaaaaaa1", "tHtxw6ykUmM", "ccccccccccc", "ddddddddddd"]


def _info(n=3, extra=()):
    entries = [{"id": VIDS[i], "title": f"Thập Thiện Nghiệp Đạo Kinh tập {i + 28}/149 - Pháp Sư Tịnh Không",
                "duration": 3500.0 + i} for i in range(n)]
    entries.insert(1, {"id": "eeeeeeeeeee", "title": "[Private video]", "duration": None})
    return {"id": PL, "title": "Thập Thiện Nghiệp Đạo Kinh [trọn bộ 149 tập]", "entries": entries + list(extra)}


class FakeLister:
    def __init__(self, info=None, error=None, delay=0.0):
        self.info, self.error, self.delay, self.calls = info or _info(), error, delay, []

    def __call__(self, url, config):
        self.calls.append(url)
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.info


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"))


def client(cfg, lister=None, pipeline=None, timeout=5.0):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, pipeline=pipeline or fake_pipeline([]),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9),
                             playlist_lister=lister or FakeLister(), playlist_timeout=timeout)
    c = TestClient(app, follow_redirects=False)
    return c


def _login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def _publish(cfg, eid):
    p = Path(cfg.workspace.dir) / eid / "publish.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


# --- L2 URLs -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url, kind, vid, pl", [
    (f"https://www.youtube.com/playlist?list={PL}", PLAYLIST, None, PL),
    (f"youtube.com/playlist?list={PL}&si=x", PLAYLIST, None, PL),
    (f"https://www.youtube.com/watch?v=tHtxw6ykUmM&list={PL}&index=29", ASK, "tHtxw6ykUmM", PL),
    ("https://www.youtube.com/watch?v=tHtxw6ykUmM&list=RDtHtxw6ykUmM", VIDEO, "tHtxw6ykUmM", None),
    ("https://youtu.be/tHtxw6ykUmM?si=x", VIDEO, "tHtxw6ykUmM", None),
])
def test_classify_url(url, kind, vid, pl):
    p = classify_url(url)
    assert (p.kind, p.video_id, p.playlist_id) == (kind, vid, pl)


@pytest.mark.parametrize("url", ["https://www.youtube.com/playlist?list=RDtHtxw6ykUmM",
                                 "https://www.youtube.com/playlist?list=WL", "https://www.youtube.com/playlist?list=LL",
                                 "https://www.youtube.com/playlist?list=PL1", "https://www.youtube.com/playlist",
                                 f"https://www.youtube.com/playlist?list={PL}&list=PLx0000000000"])
def test_classify_url_refused(url):
    with pytest.raises(UrlError):
        classify_url(url)


def test_build_document_and_episode_number(tcfg):
    doc = build_document(_info(), PL, tcfg, now="2026-09-27T12:00:00Z")
    assert doc["schema_version"] == 1 and doc["url"] == f"https://www.youtube.com/playlist?list={PL}"
    assert [(e["index"], e["video_id"], e["episode"], e["available"]) for e in doc["entries"]] == [
        (1, VIDS[0], "28", True), (2, "eeeeeeeeeee", None, False), (3, VIDS[1], "29", True), (4, VIDS[2], "30", True)]
    assert doc["entries"][0]["duration"] == 3500.0
    assert episode_number("Thập Thiện Nghiệp Đạo Kinh tập 1/149 - Pháp Sư Tịnh Không", tcfg) == "1"
    assert episode_number("không có số", tcfg) is None


# --- AC1 / AC4 import, refresh, delete ---------------------------------------------------------------------

def test_import_playlist_lists_without_downloading(tcfg):
    lister = FakeLister()
    with client(tcfg, lister=lister) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        assert r.status_code == 201 and r.json() == {"kind": "playlist", "created": True, "playlist_id": PL,
                                                     "title": _info()["title"], "count": 4}
        assert lister.calls == [f"https://www.youtube.com/playlist?list={PL}"]
        assert sorted(p.name for p in Path(tcfg.workspace.dir).iterdir()) == [".web_secret", "_playlists"]
        doc = json.loads((Path(tcfg.workspace.dir) / "_playlists" / f"{PL}.json").read_text())
        assert list(doc) == ["schema_version", "playlist_id", "title", "url", "fetched_at", "entries"]
        d = c.get(f"/api/playlists/{PL}").json()
        assert [e["video_id"] for e in d["entries"]] == [VIDS[0], "eeeeeeeeeee", VIDS[1], VIDS[2]]
        assert [e["state"] for e in d["entries"]] == ["new", "unavailable", "new", "new"]
        assert d["counts"] == {"all": 4, "todo": 3, "running": 0, "failed": 0, "doing": 0, "done": 0}  # CP8.13 G1
        assert c.get("/api/playlists").json()["playlists"] == [
            {"id": PL, "title": _info()["title"], "count": 4, "fetched_at": doc["fetched_at"], "processed": 0,
             "complete": 0, "running": 0, "failed": 0, "doing": 0, "deleted": 0}]  # CP8.13 G3
        # the same playlist again: stored one, no new listing
        r = c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        assert r.status_code == 200 and r.json()["created"] is False and len(lister.calls) == 1
        assert c.get(f"/playlists/{PL}").status_code == 200
        assert c.get("/playlists/..%2Fx").status_code == 404
        assert c.get("/api/playlists/PLnope000000").status_code == 404


def test_watch_with_list_asks(tcfg):
    calls = []
    with client(tcfg, pipeline=fake_pipeline(calls)) as c:
        _login(c)
        url = f"https://www.youtube.com/watch?v={VIDS[1]}&list={PL}&index=29"
        r = c.post("/api/episodes", json={"url": url})
        assert r.status_code == 200 and r.json() == {"kind": "ask", "video_id": VIDS[1], "playlist_id": PL}
        assert c.app.state.runner.jobs() == [] and not (Path(tcfg.workspace.dir) / "_playlists").exists()
        r = c.post("/api/episodes", json={"url": url, "mode": "playlist"})
        assert r.status_code == 201 and r.json()["kind"] == "playlist"
        r = c.post("/api/episodes", json={"url": url, "mode": "video"})
        assert r.status_code == 202 and r.json()["kind"] == "video" and r.json()["episode_id"] == VIDS[1]
        assert c.app.state.runner.wait_idle(5)
        r = c.post("/api/episodes", json={"url": f"https://youtu.be/{VIDS[1]}", "mode": "playlist"})
        assert r.status_code == 422
        assert c.post("/api/episodes", json={"url": url, "mode": "x"}).status_code == 422
        for bad in ("https://www.youtube.com/playlist?list=RDabc123456789", "https://www.youtube.com/playlist?list=WL"):
            r = c.post("/api/episodes", json={"url": bad})
            assert r.status_code == 422 and r.json()["detail"]


def test_list_errors_and_timeout(tcfg):
    with client(tcfg, lister=FakeLister(error=RuntimeError("HTTP Error 403"))) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        assert r.status_code == 502 and "HTTP Error 403" in r.json()["detail"]
    with client(tcfg, lister=FakeLister(delay=1.0), timeout=0.2) as c:
        _login(c)
        r = c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        assert r.status_code == 502 and "không trả lời trong" in r.json()["detail"]
        assert not (Path(tcfg.workspace.dir) / "_playlists" / f"{PL}.json").exists()


def test_refresh_adds_new_keeps_order_and_delete_keeps_episodes(tcfg):
    lister = FakeLister()
    write_episode(tcfg, VIDS[1])  # an episode of the playlist already processed
    with client(tcfg, lister=lister) as c:
        _login(c)
        c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        assert [e["in_playlist"] for e in c.get("/api/episodes").json()["episodes"]] == [True]
        lister.info = _info(4)
        r = c.post(f"/api/playlists/{PL}/refresh")
        assert r.status_code == 200 and r.json() == {"playlist_id": PL, "count": 5, "added": [VIDS[3]]}
        d = c.get(f"/api/playlists/{PL}").json()
        assert [e["video_id"] for e in d["entries"]] == [VIDS[0], "eeeeeeeeeee", VIDS[1], VIDS[2], VIDS[3]]
        assert [e["index"] for e in d["entries"]] == [1, 2, 3, 4, 5]
        assert c.post("/api/playlists/PLnope000000/refresh").status_code == 404
        assert c.delete(f"/api/playlists/{PL}").status_code == 200
        assert c.delete(f"/api/playlists/{PL}").status_code == 404
        assert c.get("/api/playlists").json()["playlists"] == []
        assert (Path(tcfg.workspace.dir) / VIDS[1] / "manifest.json").is_file()
        assert (Path(tcfg.render.output_dir) / VIDS[1] / "render_manifest.json").is_file()
        assert [e["in_playlist"] for e in c.get("/api/episodes").json()["episodes"]] == [False]


# --- AC2 process an entry ---------------------------------------------------------------------------------

def test_process_entry_queues_pipeline_and_status(tcfg):
    gate = threading.Event()
    calls = []
    write_episode(tcfg, VIDS[1])  # already processed: rendered, nothing ticked
    with client(tcfg, pipeline=fake_pipeline(calls, gate=gate)) as c:
        _login(c)
        c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        st = {e["video_id"]: e for e in c.get(f"/api/playlists/{PL}").json()["entries"]}
        assert (st[VIDS[1]]["state"], st[VIDS[1]]["shorts"], st[VIDS[1]]["published"]) == ("rendered", 2, 0)
        assert st[VIDS[1]]["group"] == "doing"
        # "Xử lý" = the single-video submit; two entries queue one after the other (W5)
        for vid in (VIDS[0], VIDS[2]):
            r = c.post("/api/episodes", json={"url": f"https://youtu.be/{vid}", "mode": "video"})
            assert r.status_code == 202
        st = {e["video_id"]: e for e in c.get(f"/api/playlists/{PL}").json()["entries"]}
        assert st[VIDS[0]]["state"] == "processing" and st[VIDS[2]]["state"] == "queued"
        gate.set()
        assert c.app.state.runner.wait_idle(10)
        c.app.state.playlists.invalidate()
        d = c.get(f"/api/playlists/{PL}").json()
        st = {e["video_id"]: e for e in d["entries"]}
        assert st[VIDS[0]]["state"] == "rendered" and st[VIDS[2]]["state"] == "rendered"
        assert d["counts"] == {"all": 4, "todo": 0, "running": 0, "failed": 0, "doing": 3, "done": 0}


def test_failed_job_error_readable(tcfg):
    with client(tcfg, pipeline=fake_pipeline([], fail_stage="transcript")) as c:
        _login(c)
        c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        c.post("/api/episodes", json={"url": f"https://youtu.be/{VIDS[0]}"})
        assert c.app.state.runner.wait_idle(5)
        e = c.get(f"/api/playlists/{PL}").json()["entries"][0]
        assert e["state"] == "failed" and "transcript boom" in e["error"]


# --- AC3 derived Xong (L4) ----------------------------------------------------------------------------------

def test_episode_complete_predicate():
    shorts = [{"clip_id": "k01", "candidate_id": "c1", "status": "rendered", "sha256": "a" * 64},
              {"clip_id": "k02", "candidate_id": "c2", "status": "skipped", "skip_reason": "rejected", "sha256": None}]
    tick = {"clip_id": "k01", "candidate_id": "c1", "sha256": "a" * 64, "at": "2026-09-27T00:00:00Z"}
    assert episode_complete("done", shorts, {"published": [tick]})
    assert not episode_complete("stale", shorts, {"published": [tick]})
    assert not episode_complete("done", shorts, {"published": []})
    assert not episode_complete("done", shorts, {"published": [{**tick, "sha256": "b" * 64}]})  # bản cũ
    assert not episode_complete("done", shorts, {"published": [{**tick, "candidate_id": "c9"}]})
    assert episode_complete("done", shorts[1:], {"published": []})  # every Short deleted


def test_xong_follows_ticks_restart_title_change_and_storage(tcfg):
    eid = VIDS[1]
    write_episode(tcfg, eid)
    with client(tcfg) as c:
        _login(c)
        c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        base = f"/api/episodes/{eid}/shorts"
        c.post(f"{base}/k01/published", json={"value": True})
        assert c.get(f"/api/episodes/{eid}").json()["complete"] is False
        c.post(f"{base}/k02/published", json={"value": True})
        assert c.get(f"/api/episodes/{eid}").json()["complete"] is True
        e = next(x for x in c.get(f"/api/playlists/{PL}").json()["entries"] if x["video_id"] == eid)
        assert (e["state"], e["group"]) == ("complete", "done")
        recs = c.get("/api/storage").json()["recommendations"]
        assert [(r["episode_id"], r["rule"]) for r in recs] == [(eid, "all_published")]
        assert c.get("/api/episodes").json()["episodes"][0]["publish_group"] == "done"
    with client(tcfg) as c:  # restart
        _login(c)
        assert c.get(f"/api/episodes/{eid}").json()["complete"] is True
        c.post(f"/api/episodes/{eid}/shorts/k02/published", json={"value": False})
        assert c.get(f"/api/episodes/{eid}").json()["complete"] is False
        c.post(f"/api/episodes/{eid}/shorts/k02/published", json={"value": True})
    # a re-render of k02 (e.g. new title): its tick is "đã đăng bản cũ" -> not Xong
    rm_path = Path(tcfg.render.output_dir) / eid / "render_manifest.json"
    rm = json.loads(rm_path.read_text(encoding="utf-8"))
    rm["shorts"][1]["sha256"] = "f" * 64
    rm_path.write_text(json.dumps(rm), encoding="utf-8")
    with client(tcfg) as c:
        _login(c)
        d = c.get(f"/api/episodes/{eid}").json()
        assert d["complete"] is False and d["shorts"][1]["published_stale"] is True
        c.app.state.playlists.invalidate()
        e = next(x for x in c.get(f"/api/playlists/{PL}").json()["entries"] if x["video_id"] == eid)
        assert e["state"] == "rendered"
        assert c.get("/api/storage").json()["recommendations"] == []


# --- download ticks "Đã đăng" (bổ sung HUMAN LEAD 2026-09-27) -----------------------------------------------

def test_download_ticks_published(tcfg):
    eid = VIDS[1]
    files = write_episode(tcfg, eid, clips=("k01", "k02", "k03"))
    with client(tcfg) as c:
        _login(c)
        assert c.get(f"/files/{eid}/k01.mp4").content == files["k01"]  # playback: no tick
        assert c.get(f"/files/{eid}/k01.mp4", headers={"Range": "bytes=0-9"}).status_code == 206
        assert _publish(tcfg, eid) is None
        r = c.get(f"/files/{eid}/k01.mp4?download=1")
        assert r.status_code == 200 and r.content == files["k01"]
        pub = _publish(tcfg, eid)
        assert [(e["clip_id"], e["sha256"]) for e in pub["published"]] == [("k01", f"{0:064x}")]
        at = pub["published"][0]["at"]
        # a Range continuation of the same download: idempotent (same entry, same time)
        r = c.get(f"/files/{eid}/k01.mp4?download=1", headers={"Range": "bytes=100-"})
        assert r.status_code == 206 and _publish(tcfg, eid)["published"][0]["at"] == at
        # untick stays unticked until downloaded again
        c.post(f"/api/episodes/{eid}/shorts/k01/published", json={"value": False})
        c.get(f"/files/{eid}/k01.mp4")
        assert _publish(tcfg, eid)["published"] == []
        # CP8.31 D1 (reverses CP8.17 D3): the zip ticks every Short it contains
        with zipfile.ZipFile(io.BytesIO(c.get(f"/files/{eid}/shorts.zip").content)) as zf:
            assert len(zf.namelist()) == 3
        assert [e["clip_id"] for e in _publish(tcfg, eid)["published"]] == ["k01", "k02", "k03"]
        assert c.get(f"/api/episodes/{eid}").json()["complete"] is True
    # re-render k02 -> stale; downloading again re-ticks with the new sha256
    rm_path = Path(tcfg.render.output_dir) / eid / "render_manifest.json"
    rm = json.loads(rm_path.read_text(encoding="utf-8"))
    rm["shorts"][1]["sha256"] = "f" * 64
    rm_path.write_text(json.dumps(rm), encoding="utf-8")
    with client(tcfg) as c:
        _login(c)
        assert c.get(f"/api/episodes/{eid}").json()["shorts"][1]["published_stale"] is True
        c.get(f"/files/{eid}/k02.mp4?download=1")
        k02 = next(e for e in _publish(tcfg, eid)["published"] if e["clip_id"] == "k02")
        assert k02["sha256"] == "f" * 64
        d = c.get(f"/api/episodes/{eid}").json()
        assert d["shorts"][1]["published_stale"] is False and d["complete"] is True


def test_download_ticks_archived_episode(tcfg, tmp_path):
    eid = VIDS[1]
    write_episode(tcfg, eid)
    (Path(tcfg.workspace.dir) / eid / "source.mp4").write_bytes(b"s" * 100)
    with client(tcfg) as c:
        _login(c)
        assert c.post(f"/api/episodes/{eid}/archive").status_code == 200
        assert c.get(f"/files/{eid}/k02.mp4?download=1").status_code == 200
        assert [e["clip_id"] for e in _publish(tcfg, eid)["published"]] == ["k02"]


def test_models_dir_shown_absolute(tcfg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "models" / "m").mkdir(parents=True)
    (tmp_path / "models" / "m" / "x.bin").write_bytes(b"x" * 10)
    with client(tcfg) as c:
        _login(c)
        cache = c.get("/api/storage").json()["caches"][0]
        assert cache == {"name": "Model Whisper", "path": str(tmp_path / "models"), "bytes": 10, "exists": True}


def test_copy_title_button_served(tcfg):
    """Bổ sung HUMAN LEAD 2026-09-27: "Copy" next to each Short's title (clipboard API only in a secure context,
    else textarea + execCommand("copy"), else a selected box). Real phones: manual gate."""
    with client(tcfg) as c:
        _login(c)
        js = c.get("/static/app.js").text
        assert "copyTitleButton(s.copy_text)" in js and 'text: "Copy"' in js and "Đã copy" in js
        assert "window.isSecureContext && navigator.clipboard" in js
        assert 'document.execCommand("copy")' in js and "setSelectionRange(0, text.length)" in js
        assert "copy-fallback" in js and "Giữ vào ô để copy" in js
        assert ".copy-fallback" in c.get("/static/style.css").text


# --- bổ sung HUMAN LEAD 2026-09-27: tombstones (A), copy text with hashtags (B) ------------------------------

from auto_short.review.names import copy_text, hashtag, hashtags  # noqa: E402


@pytest.mark.parametrize("text, tag", [("Thập Thiện Nghiệp Đạo Kinh", "#ThậpThiệnNghiệpĐạoKinh"),
                                       ("#TịnhKhông", "#TịnhKhông"), ("Lời Phật dạy!", "#LờiPhậtdạy"),
                                       ("  ", None), (None, None), ("A-B_C 1", "#ABC1")])
def test_hashtag(text, tag):
    assert hashtag(text) == tag


def test_copy_text_dedup_and_100_chars():
    tags = ("TịnhKhông", "LờiPhậtDạy", "TịnhĐộ")
    assert hashtags("Tịnh Độ", tags) == ["#TịnhĐộ", "#TịnhKhông", "#LờiPhậtDạy"]  # series first, dedup casefold
    assert hashtags(None, ("a", "A", "", "b")) == ["#a", "#b"]
    text, kept = copy_text("Đánh mắng trẻ là có tội không?", "Thập Thiện Nghiệp Đạo Kinh", tags)
    assert text == "Đánh mắng trẻ là có tội không? #ThậpThiệnNghiệpĐạoKinh #TịnhKhông #LờiPhậtDạy #TịnhĐộ"
    assert len(text) <= 100 and len(kept) == 4
    title = "x" * 60
    text, kept = copy_text(title, "Thập Thiện Nghiệp Đạo Kinh", tags)
    assert len(text) <= 100 and text.startswith(title + " ") and kept == ["#ThậpThiệnNghiệpĐạoKinh", "#TịnhKhông"]
    long = "y" * 99
    assert copy_text(long, "S", tags) == (long, [])  # the title is never cut
    assert copy_text("z" * 120, None, tags) == ("z" * 120, [])


def test_copy_text_in_short_view_and_config(tcfg):
    from dataclasses import replace
    from auto_short.config import WebConfig, from_dict
    assert from_dict({"web": {"hashtags": ["A", "B"]}}).web.hashtags == ("A", "B")
    assert from_dict({}).web.hashtags == ("TịnhKhông", "LờiPhậtDạy", "TịnhĐộ", "NiệmPhật")
    text, kept = copy_text("Đánh mắng trẻ là có tội không?", "Thập Thiện Nghiệp Đạo Kinh", from_dict({}).web.hashtags)
    assert kept == ["#ThậpThiệnNghiệpĐạoKinh", "#TịnhKhông", "#LờiPhậtDạy", "#TịnhĐộ", "#NiệmPhật"] and len(text) == 95
    with pytest.raises(Exception):
        from_dict({"web": {"hashtags": "A"}})
    eid = VIDS[1]
    write_episode(tcfg, eid, titles={"k01": "Đánh mắng trẻ là có tội không?", "k02": "Tiêu đề"})
    (Path(tcfg.workspace.dir) / eid / "titles.json").write_text(json.dumps(
        {"header": {"fields": {"series": "Thập Thiện Nghiệp Đạo Kinh", "episode": "29"}}}), encoding="utf-8")
    cfg = replace(tcfg, web=WebConfig(hashtags=("TịnhKhông", "thậpthiệnnghiệpđạokinh")))
    with client(cfg) as c:
        _login(c)
        k01 = c.get(f"/api/episodes/{eid}").json()["shorts"][0]
        assert k01["copy_text"] == "T29_S01_Đánh mắng trẻ là có tội không? #ThậpThiệnNghiệpĐạoKinh #TịnhKhông"
        assert k01["hashtags"] == ["#ThậpThiệnNghiệpĐạoKinh", "#TịnhKhông"]
        js = c.get("/static/app.js").text
        assert "copyTitleButton(s.copy_text)" in js and 's.hashtags.join(" ")' in js


def _playlist_with(c, vids):
    c.app.state.playlists.root.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "playlist_id": PL, "title": "Bộ kinh", "url": "u", "fetched_at": "2026-09-27T00:00:00Z",
           "entries": [{"index": n, "video_id": v, "title": f"tập {n}", "duration": 1.0, "episode": str(n),
                        "available": True} for n, v in enumerate(vids, 1)]}
    (c.app.state.playlists.root / f"{PL}.json").write_text(json.dumps(doc), encoding="utf-8")


def test_tombstone_on_delete_playlist_stats_and_reprocess(tcfg):
    done_id, todo_id = VIDS[0], VIDS[1]
    write_episode(tcfg, done_id, title="Tập xong")
    write_episode(tcfg, todo_id, title="Tập chưa xong")
    (Path(tcfg.workspace.dir) / done_id / "titles.json").write_text(json.dumps(
        {"header": {"fields": {"series": "Thập Thiện", "episode": "28"}}}), encoding="utf-8")
    with client(tcfg) as c:
        _login(c)
        _playlist_with(c, [done_id, todo_id, VIDS[2]])
        for clip in ("k01", "k02"):  # single download = published -> Xong (CP8.17 D3: a zip no longer ticks)
            c.get(f"/files/{done_id}/{clip}.mp4?download=1")
        c.post(f"/api/episodes/{todo_id}/shorts/k01/published", json={"value": True})
        # delete via the storage "Làm" path (recommendation for the Xong episode) and via the episode page
        recs = c.get("/api/storage").json()["recommendations"]
        assert [r["episode_id"] for r in recs] == [done_id]
        assert c.delete(f"/api/episodes/{done_id}").status_code == 200
        assert c.delete(f"/api/episodes/{todo_id}").status_code == 200
        tomb = json.loads((Path(tcfg.workspace.dir) / "_deleted" / f"{done_id}.json").read_text())
        assert list(tomb) == ["schema_version", "episode_id", "title", "source_url", "deleted_at", "shorts",
                              "published", "complete", "header"]
        assert (tomb["title"], tomb["source_url"], tomb["shorts"], tomb["published"], tomb["complete"]) == \
            ("Tập xong", f"https://youtu.be/{done_id}", 2, 2, True)
        assert tomb["header"] == {"series": "Thập Thiện", "episode": "28"}
        t2 = json.loads((Path(tcfg.workspace.dir) / "_deleted" / f"{todo_id}.json").read_text())
        assert (t2["published"], t2["complete"], t2["header"]) == (1, False, {"series": None, "episode": None})
        d = c.get(f"/api/playlists/{PL}").json()
        e = {x["video_id"]: x for x in d["entries"]}
        assert (e[done_id]["state"], e[done_id]["group"], e[done_id]["action"], e[done_id]["shorts"],
                e[done_id]["published"]) == ("deleted", "done", "reprocess", 2, 2)
        assert (e[todo_id]["state"], e[todo_id]["group"], e[todo_id]["complete"]) == ("deleted", "todo", False)
        assert e[VIDS[2]]["action"] == "process"
        assert d["counts"] == {"all": 3, "todo": 2, "running": 0, "failed": 0, "doing": 0, "done": 1}
        s = c.get("/api/playlists").json()["playlists"][0]
        assert (s["processed"], s["complete"], s["deleted"]) == (2, 1, 2)
        # in a playlist -> not in the home "Đã xóa" list
        assert c.get("/api/deleted").json()["episodes"] == []
        js = c.get("/static/app.js").text
        assert 'e.action === "reprocess" && !confirm(' in js and "Xử lý lại" in js
        # processing again: the new workspace wins, the tombstone is ignored (kept on disk)
        write_episode(tcfg, done_id)
        c.app.state.playlists.invalidate()
        e = {x["video_id"]: x for x in c.get(f"/api/playlists/{PL}").json()["entries"]}
        assert e[done_id]["state"] == "rendered"
        assert (Path(tcfg.workspace.dir) / "_deleted" / f"{done_id}.json").is_file()


def test_deleted_single_episodes_on_home(tcfg):
    write_episode(tcfg, VIDS[3], title="Tập lẻ đã xóa")
    with client(tcfg) as c:
        _login(c)
        assert c.delete(f"/api/episodes/{VIDS[3]}").status_code == 200
        items = c.get("/api/deleted").json()["episodes"]
        assert [(t["episode_id"], t["title"], t["complete"]) for t in items] == [(VIDS[3], "Tập lẻ đã xóa", False)]
        assert 'id="deleted-box"' in c.get("/").text
        assert c.get("/api/episodes").json()["episodes"] == []
        assert c.delete("/api/deleted/..%2Fx").status_code == 404
        assert c.delete(f"/api/deleted/{VIDS[3]}").status_code == 200
        assert c.get("/api/deleted").json()["episodes"] == []
        assert c.delete(f"/api/deleted/{VIDS[3]}").status_code == 404


def test_storage_page_responsive_markup(tcfg):
    with client(tcfg) as c:
        _login(c)
        assert 'id="ep-cards"' in c.get("/storage").text
        css = c.get("/static/style.css").text
        assert "@media (max-width: 640px)" in css and "min-height: 40px" in css and ".ep-card" in css


# --- per-bộ kinh hashtags (bổ sung HUMAN LEAD 2026-09-27) --------------------------------------------------

def test_playlist_hashtags_store_reset_refresh_and_effect(tcfg):
    eid = VIDS[1]
    write_episode(tcfg, eid, titles={"k01": "Đánh mắng trẻ là có tội không?", "k02": "x" * 60})
    (Path(tcfg.workspace.dir) / eid / "titles.json").write_text(json.dumps(
        {"header": {"fields": {"series": "Thập Thiện Nghiệp Đạo Kinh"}}}), encoding="utf-8")
    lister = FakeLister()
    with client(tcfg, lister=lister) as c:
        _login(c)
        c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        d = c.get(f"/api/playlists/{PL}").json()
        assert d["hashtags_custom"] is False
        assert d["hashtags"] == ["#ThậpThiệnNghiệpĐạoKinh", "#TịnhKhông", "#LờiPhậtDạy", "#TịnhĐộ", "#NiệmPhật"]
        # invalid -> 422, nothing stored
        for bad in (["  "], ["A", "a"], ["t" + str(i) for i in range(16)], "x"):
            r = c.put(f"/api/playlists/{PL}/hashtags", json={"hashtags": bad})
            assert r.status_code == 422, bad
        path = Path(tcfg.workspace.dir) / "_playlists" / f"{PL}.json"
        assert "hashtags" not in json.loads(path.read_text())
        r = c.put(f"/api/playlists/{PL}/hashtags", json={"hashtags": ["Thập Thiện", "#Tịnh Độ Tông!", "PhápSư"]})
        assert r.status_code == 200 and r.json() == {"playlist_id": PL, "hashtags": ["#ThậpThiện", "#TịnhĐộTông",
                                                                                      "#PhápSư"],
                                                     "hashtags_custom": True}
        assert json.loads(path.read_text())["hashtags"] == ["ThậpThiện", "TịnhĐộTông", "PhápSư"]
        k01, k02 = c.get(f"/api/episodes/{eid}").json()["shorts"]
        assert k01["copy_text"] == f"T{VIDS[1]}_S01_Đánh mắng trẻ là có tội không? #ThậpThiện #TịnhĐộTông #PhápSư"
        # CP8.21 D3: the "T<tập>_S<NN>_" prefix counts towards the 100 characters, so k02 loses its last hashtag
        assert k02["hashtags"] == ["#ThậpThiện", "#TịnhĐộTông"] and len(k02["copy_text"]) <= 100
        assert k02["copy_text"].startswith(f"T{eid}_S02_")
        p = c.post(f"/api/playlists/{PL}/hashtags/preview", json={"hashtags": ["A" * 20, "B" * 20]}).json()
        assert p["title"] == "x" * 60 and p["title_is_real"] is True
        assert p["copy_text"] == "x" * 60 + " #" + "A" * 20 and p["dropped"] == ["#" + "B" * 20]
        assert c.post(f"/api/playlists/{PL}/hashtags/preview", json={"hashtags": ["a", "A"]}).status_code == 422
        # "Cập nhật danh sách" keeps the list
        c.post(f"/api/playlists/{PL}/refresh")
        assert json.loads(path.read_text())["hashtags"] == ["ThậpThiện", "TịnhĐộTông", "PhápSư"]
        # single episodes keep the default
        write_episode(tcfg, "singleEp001", titles={"k01": "Tiêu đề"})
        assert c.get("/api/episodes/singleEp001").json()["shorts"][0]["hashtags"] == \
            ["#TịnhKhông", "#LờiPhậtDạy", "#TịnhĐộ", "#NiệmPhật"]
        # reset
        r = c.delete(f"/api/playlists/{PL}/hashtags")
        assert r.status_code == 200 and r.json()["hashtags_custom"] is False
        assert "hashtags" not in json.loads(path.read_text())
        assert c.get(f"/api/episodes/{eid}").json()["shorts"][0]["hashtags"][0] == "#ThậpThiệnNghiệpĐạoKinh"
        assert c.put("/api/playlists/PLnope000000/hashtags", json={"hashtags": []}).status_code == 404
        # empty custom list = no hashtags at all
        c.put(f"/api/playlists/{PL}/hashtags", json={"hashtags": []})
        assert c.get(f"/api/episodes/{eid}").json()["shorts"][0]["copy_text"] == f"T{eid}_S01_Đánh mắng trẻ là có tội không?"


def test_episode_in_two_playlists_uses_first_by_id(tcfg):
    eid = VIDS[1]
    write_episode(tcfg, eid, titles={"k01": "Tiêu đề"})
    with client(tcfg) as c:
        _login(c)
        root = c.app.state.playlists.root
        root.mkdir(parents=True)
        for pid, tags in (("PLbbbbbbbbbbbb", ["Hai"]), ("PLaaaaaaaaaaaa", ["Một"]), ("PLcccccccccccc", None)):
            doc = {"schema_version": 1, "playlist_id": pid, "title": pid, "url": "u", "fetched_at": "x",
                   "entries": [{"index": 1, "video_id": eid, "title": "t", "duration": 1.0, "episode": "1",
                                "available": True}]}
            if tags is not None:
                doc["hashtags"] = tags
            (root / f"{pid}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        assert c.get(f"/api/episodes/{eid}").json()["shorts"][0]["hashtags"] == ["#Một"]
        js = c.get("/static/app.js").text
        assert "hashtags/preview" in js and "Khôi phục mặc định" in c.get(f"/playlists/{PL}").text


def test_playlist_hashtags_saved_during_refresh_survive(tcfg):
    """H5: a list saved while "Cập nhật danh sách" is listing is re-read under the lock, not overwritten."""
    holder = {}

    class SavingLister(FakeLister):
        def __call__(self, url, config):
            if len(self.calls) == 1:  # the refresh listing: the user saves meanwhile
                holder["store"].set_hashtags(PL, ["Mới"])
            return super().__call__(url, config)

    with client(tcfg, lister=SavingLister()) as c:
        _login(c)
        holder["store"] = c.app.state.playlists
        c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        assert c.post(f"/api/playlists/{PL}/refresh").status_code == 200
        path = Path(tcfg.workspace.dir) / "_playlists" / f"{PL}.json"
        assert json.loads(path.read_text())["hashtags"] == ["Mới"]


def test_playlist_hashtags_delete_playlist_auth_body_and_files(tcfg):
    eid = VIDS[1]
    write_episode(tcfg, eid, titles={"k01": "Tiêu đề"})
    with client(tcfg) as c:
        assert c.put(f"/api/playlists/{PL}/hashtags", json={"hashtags": []}).status_code == 401
        assert c.post(f"/api/playlists/{PL}/hashtags/preview", json={"hashtags": []}).status_code == 401
        _login(c)
        c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"})
        for bad in ({"hashtags": [1]}, {"hashtags": None}, {}, {"hashtags": ["a"] * 101}):
            assert c.put(f"/api/playlists/{PL}/hashtags", json=bad).status_code == 422, bad
        before = {p: p.read_bytes() for p in Path(tcfg.workspace.dir, eid).rglob("*") if p.is_file()}
        assert c.put(f"/api/playlists/{PL}/hashtags", json={"hashtags": ["Riêng"]}).status_code == 200
        assert c.get(f"/api/episodes/{eid}").json()["shorts"][0]["copy_text"] == f"T{eid}_S01_Tiêu đề #Riêng"
        after = {p: p.read_bytes() for p in Path(tcfg.workspace.dir, eid).rglob("*") if p.is_file()}
        assert after == before  # AC8: nothing in the episode workspace changes
        # a hand-edited list of the wrong type -> default
        path = Path(tcfg.workspace.dir) / "_playlists" / f"{PL}.json"
        doc = json.loads(path.read_text())
        path.write_text(json.dumps({**doc, "hashtags": [1, 2]}), encoding="utf-8")
        assert c.get(f"/api/episodes/{eid}").json()["shorts"][0]["hashtags"] == \
            ["#TịnhKhông", "#LờiPhậtDạy", "#TịnhĐộ", "#NiệmPhật"]
        assert c.get(f"/api/playlists/{PL}").json()["hashtags_custom"] is False
        path.write_text(json.dumps(doc | {"hashtags": ["Riêng"]}), encoding="utf-8")
        # "Xóa bộ kinh" removes the list with the file -> default again
        assert c.delete(f"/api/playlists/{PL}").status_code == 200
        assert c.get(f"/api/episodes/{eid}").json()["shorts"][0]["copy_text"] == \
            f"T{eid}_S01_Tiêu đề #TịnhKhông #LờiPhậtDạy #TịnhĐộ #NiệmPhật"
        assert c.delete(f"/api/playlists/{PL}/hashtags").status_code == 404
