"""CP8.11 D7 (AC8): "Tên bộ kinh" store, API and playlist page."""

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
PL = "PLOynZc0cJJfA6C9mATbfggiF7ATJmwSJa"
TT = "Tập {n}/128: Giảng \"Thái Thượng Cảm Ứng Thiên\" | Tịnh Không Lão Pháp sư chủ giảng"


def _info(titles):
    return {"id": PL, "title": "Thái Thượng Cảm Ứng Thiên (128 tập) - Pháp Sư Tịnh Không",
            "entries": [{"id": f"vid{n:08d}", "title": t, "duration": 3500.0} for n, t in enumerate(titles, 1)]}


class FakeLister:
    def __init__(self, info):
        self.info, self.calls, self.during = info, [], None

    def __call__(self, url, config):
        self.calls.append(url)
        if self.during and len(self.calls) > 1:
            self.during()
        return self.info


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "out"))


def client(cfg, lister):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, pipeline=fake_pipeline([]),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9),
                             playlist_lister=lister, playlist_timeout=5.0)
    c = TestClient(app, follow_redirects=False)
    return c


def _import(c):
    assert c.post("/login", data={"password": PW}).status_code == 303
    assert c.post("/api/episodes", json={"url": f"https://www.youtube.com/playlist?list={PL}"}).status_code == 201


def _path(cfg) -> Path:
    return Path(cfg.workspace.dir) / "_playlists" / f"{PL}.json"


def test_series_view_suggestion_and_unrecognized(tcfg):
    titles = [TT.format(n=1), "Bài giảng lạ", "[Private video]", TT.format(n=4), "Khai thị đặc biệt"]
    with client(tcfg, FakeLister(_info(titles))) as c:
        _import(c)
        d = c.get(f"/api/playlists/{PL}").json()
        assert (d["series"], d["series_suggested"], d["unrecognized"]) == (None, "Thái Thượng Cảm Ứng Thiên", 2)
        assert [e["episode"] for e in d["entries"]] == ["1", None, None, "4", None]
    lister = FakeLister(_info(["Bài lạ"]))
    tcfg2 = Config(workspace=WorkspaceConfig(dir=Path(tcfg.workspace.dir).parent / "w2"))
    with client(tcfg2, lister) as c:
        _import(c)
        d = c.get(f"/api/playlists/{PL}").json()
        assert (d["series"], d["series_suggested"], d["unrecognized"]) == (None, None, 1)


def test_series_put_delete_validation_refresh(tcfg):
    lister = FakeLister(_info([TT.format(n=1), "Bài lạ"]))
    with client(tcfg, lister) as c:
        assert c.put(f"/api/playlists/{PL}/series", json={"series": "x"}).status_code == 401
        assert c.delete(f"/api/playlists/{PL}/series").status_code == 401
        _import(c)
        path = _path(tcfg)
        before = path.read_bytes()
        for bad in ({"series": ""}, {"series": "   "}, {"series": "a" * 101}, {"series": 5}, {"series": ["x"]},
                    {"series": None}, {}):
            assert c.put(f"/api/playlists/{PL}/series", json=bad).status_code == 422, bad
        assert path.read_bytes() == before  # nothing written
        assert c.put("/api/playlists/PLnope000000/series", json={"series": "x"}).status_code == 404
        assert c.delete("/api/playlists/PLnope000000/series").status_code == 404

        r = c.put(f"/api/playlists/{PL}/series", json={"series": "  Thái Thượng   Cảm Ứng Thiên "})
        assert r.status_code == 200
        assert r.json() == {"playlist_id": PL, "series": "Thái Thượng Cảm Ứng Thiên", "series_custom": True}
        assert json.loads(path.read_text())["series"] == "Thái Thượng Cảm Ứng Thiên"
        assert c.get(f"/api/playlists/{PL}").json()["series"] == "Thái Thượng Cảm Ứng Thiên"
        assert c.put(f"/api/playlists/{PL}/series", json={"series": "a" * 100}).status_code == 200
        c.put(f"/api/playlists/{PL}/series", json={"series": "Tên"})
        # hashtags + series: fixed key order, both kept by "Cập nhật danh sách"
        assert c.put(f"/api/playlists/{PL}/hashtags", json={"hashtags": ["Một"]}).status_code == 200
        c.put(f"/api/playlists/{PL}/series", json={"series": "Tên"})
        assert list(json.loads(path.read_text()))[-3:] == ["entries", "hashtags", "series"]
        assert c.post(f"/api/playlists/{PL}/refresh").status_code == 200
        doc = json.loads(path.read_text())
        assert (doc["hashtags"], doc["series"]) == (["Một"], "Tên")
        assert list(doc)[-2:] == ["hashtags", "series"]
        # reset
        r = c.delete(f"/api/playlists/{PL}/series")
        assert r.status_code == 200 and r.json() == {"playlist_id": PL, "series": None, "series_custom": False}
        doc = json.loads(path.read_text())
        assert "series" not in doc and doc["hashtags"] == ["Một"]
        assert c.delete(f"/api/playlists/{PL}/hashtags").status_code == 200
        c.put(f"/api/playlists/{PL}/series", json={"series": "Tên"})
        assert "hashtags" not in json.loads(path.read_text())
        # a hand-edited / broken field = not set
        for broken in (5, "", ["x"], "a" * 101):
            path.write_text(json.dumps({**doc, "series": broken}), encoding="utf-8")
            assert c.get(f"/api/playlists/{PL}").json()["series"] is None, broken
        # "Xóa bộ kinh" removes it with the file
        c.put(f"/api/playlists/{PL}/series", json={"series": "Tên"})
        assert c.delete(f"/api/playlists/{PL}").status_code == 200
        assert c.put(f"/api/playlists/{PL}/series", json={"series": "Tên"}).status_code == 404


def test_series_saved_during_refresh_survives(tcfg):
    lister = FakeLister(_info([TT.format(n=1)]))
    with client(tcfg, lister) as c:
        _import(c)
        lister.during = lambda: c.app.state.playlists.set_series(PL, "Lưu giữa chừng")
        assert c.post(f"/api/playlists/{PL}/refresh").status_code == 200
        assert json.loads(_path(tcfg).read_text())["series"] == "Lưu giữa chừng"


def test_series_does_not_touch_episodes_and_is_read_by_titling_lookup(tcfg):
    from auto_short.titling.playlist import playlist_header
    lister = FakeLister(_info(["Bài lạ", TT.format(n=2)]))
    write_episode(tcfg, "vid00000001", titles={"k01": "Tiêu đề"})
    with client(tcfg, lister) as c:
        _import(c)
        before = {p: p.read_bytes() for p in Path(tcfg.workspace.dir, "vid00000001").rglob("*") if p.is_file()}
        assert playlist_header(tcfg.workspace.dir, "vid00000001") is None
        c.put(f"/api/playlists/{PL}/series", json={"series": "Kinh Riêng"})
        assert playlist_header(tcfg.workspace.dir, "vid00000001") == ("Kinh Riêng", "1")  # index fallback
        assert playlist_header(tcfg.workspace.dir, "vid00000002") == ("Kinh Riêng", "2")  # entry.episode
        after = {p: p.read_bytes() for p in Path(tcfg.workspace.dir, "vid00000001").rglob("*") if p.is_file()}
        assert after == before


def test_playlist_page_series_box(tcfg):
    with client(tcfg, FakeLister(_info([TT.format(n=1)]))) as c:
        _import(c)
        html = c.get(f"/playlists/{PL}").text
        for needle in ('id="sr-box"', "Tên bộ kinh", 'id="sr-input"', 'maxlength="100"', 'id="sr-save"',
                       'id="sr-reset"', "Bỏ tên", 'id="sr-unrecognized"',
                       "Chỉ dùng cho tập mà tiêu đề video không nhận ra tên bộ kinh / số tập",
                       "Đổi tên sau khi tập đã xử lý → lần chạy sau tạo lại tiêu đề AI của tập đó."):
            assert needle in html, needle
        js = c.get("/static/app.js").text
        for needle in ("/series`", "series_suggested", "unrecognized", "srEditing", "initSeries()", "srLoad(d)",
                       'method: "DELETE"', "confirm(\"Bỏ tên bộ kinh?"):
            assert needle in js, needle
        css = c.get("/static/style.css").text
        mobile = css[css.index("@media (max-width: 640px)"):]
        assert "#sr-box .edit-actions .btn { width: 100%; }" in mobile[:mobile.index("}\n@media")]
