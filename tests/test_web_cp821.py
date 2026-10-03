"""CP8.21: names with the episode code (D3), "Đã xem" (D4), hidden advanced buttons (D5), icon buttons (D6),
"Xem Khai thị" (D2)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, RenderConfig, WebConfig, WorkspaceConfig, from_dict  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.review.names import copy_prefix, copy_text, download_name  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
VID = "aaaaaaaaaa1"
KT = VID + ".kt"
SERIES = "Thập Thiện Nghiệp Đạo Kinh"
TAGS = ("TịnhKhông", "LờiPhậtDạy")


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output"))


def client(cfg):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, pipeline=fake_pipeline([]),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9))
    return TestClient(app, follow_redirects=False)


def login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def make_pair(cfg):
    files = {VID: write_episode(cfg, VID, clips=("k01", "k02"), titles={"k01": "Một", "k02": "Hai"}),
             KT: write_episode(cfg, KT, clips=("k01", "k02"), titles={"k01": "Khai một", "k02": "Khai hai"})}
    khaithi.write(Path(cfg.workspace.dir) / KT, KhaiThi(VID, 4, 7))
    for eid in (VID, KT):
        (Path(cfg.workspace.dir) / eid / "titles.json").write_text(
            json.dumps({"header": {"fields": {"series": SERIES, "episode": "29"}}}, ensure_ascii=False),
            encoding="utf-8")
    return files


# --- D3 pure ------------------------------------------------------------------------------------------------

def test_download_name_format():
    assert download_name("29", 1, 20, "Tâm thiện?") == "T29_S01_Tâm thiện.mp4"
    assert download_name("29", 1, 20, "Tâm thiện", khaithi=True) == "T29_TK01_Tâm thiện.mp4"
    assert download_name("29", 7, 100, None) == "T29_S007.mp4"
    assert download_name("29", 3, 5, "???", khaithi=True) == "T29_TK03.mp4"


def test_copy_text_prefix():
    assert copy_prefix("29", 1, 20) == "T29_S01_"
    assert copy_prefix("29", 1, 20, khaithi=True) == "Khai Thị: T29_TK01_"
    text, kept = copy_text("Tâm thiện", SERIES, TAGS, prefix=copy_prefix("29", 1, 20))
    assert text == "T29_S01_Tâm thiện #ThậpThiệnNghiệpĐạoKinh #TịnhKhông #LờiPhậtDạy" and len(kept) == 3
    text, _ = copy_text("Tâm thiện", None, TAGS, prefix=copy_prefix("29", 2, 20, khaithi=True))
    assert text == "Khai Thị: T29_TK02_Tâm thiện #TịnhKhông #LờiPhậtDạy"


def test_copy_text_prefix_counts_towards_100_and_title_not_cut():
    prefix = copy_prefix("29", 1, 20, khaithi=True)  # 19 chars
    title = "x" * 50
    text, kept = copy_text(title, SERIES, TAGS, prefix=prefix)
    assert len(text) <= 100 and text.startswith(prefix + title) and kept == ["#ThậpThiệnNghiệpĐạoKinh"]
    long = "y" * 99
    assert copy_text(long, SERIES, TAGS, prefix="T29_S01_") == ("T29_S01_" + long, [])  # title never cut


# --- D3 / D2 web ---------------------------------------------------------------------------------------------

def test_view_names_and_copy_text(tcfg):
    make_pair(tcfg)
    with client(tcfg) as c:
        login(c)
        s, k = c.get(f"/api/episodes/{VID}").json(), c.get(f"/api/episodes/{KT}").json()
        assert s["shorts"][0]["download_name"] == "T29_S01_Một.mp4"
        assert k["shorts"][1]["download_name"] == "T29_TK02_Khai hai.mp4"
        assert s["shorts"][0]["copy_text"].startswith("T29_S01_Một #")
        assert k["shorts"][0]["copy_text"].startswith("Khai Thị: T29_TK01_Khai một #")
        assert s["zip_name"] == f"{SERIES}_Tập29_Shorts.zip"  # zip name unchanged
        assert k["zip_name"] == f"{SERIES}_Tập29_KhaiThị.zip"
        assert s["shorts"][0]["title"]["text"] == "Một"  # the title in the video / titles.json is unchanged


# --- D4 ------------------------------------------------------------------------------------------------------

def read(cfg, eid):
    p = Path(cfg.workspace.dir) / eid / "watched.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_watched_tick_untick_idempotent_and_independent(tcfg):
    files = make_pair(tcfg)
    ws = Path(tcfg.workspace.dir) / VID
    before = {p: p.read_bytes() for p in ws.rglob("*") if p.is_file()}
    with client(tcfg) as c:
        login(c)
        v = c.get(f"/api/episodes/{VID}").json()
        assert [(s["watched"], s["watched_stale"], s["watched_at"]) for s in v["shorts"]] == [(False, False, None)] * 2
        r = c.post(f"/api/episodes/{VID}/shorts/k01/watched", json={"value": True})
        assert r.status_code == 200 and r.json()["watched"] is True and r.json()["stale"] is False
        doc = read(tcfg, VID)
        assert [e["clip_id"] for e in doc["watched"]] == ["k01"]
        at = doc["watched"][0]["at"]
        c.post(f"/api/episodes/{VID}/shorts/k01/watched", json={"value": True})
        assert read(tcfg, VID)["watched"][0]["at"] == at  # idempotent
        v = c.get(f"/api/episodes/{VID}").json()
        assert v["shorts"][0]["watched"] is True and v["shorts"][1]["watched"] is False
        assert v["shorts"][0]["published"] is False  # independent of "Đã đăng"
        assert not (ws / "publish.json").exists()
        assert c.get(f"/api/episodes/{KT}").json()["shorts"][0]["watched"] is False
        r = c.post(f"/api/episodes/{VID}/shorts/k01/watched", json={"value": False})
        assert r.json()["watched"] is False and read(tcfg, VID)["watched"] == []
        assert c.post(f"/api/episodes/{VID}/shorts/k01/watched", json={"value": "yes"}).status_code == 422
        assert c.post(f"/api/episodes/{VID}/shorts/nope/watched", json={"value": True}).status_code in (404, 422)
    after = {p: p.read_bytes() for p in ws.rglob("*") if p.is_file() and p.name != "watched.json"}
    assert after == before  # no stage / review / manifest file touched (render not stale), no job
    assert files  # silence unused


def test_watched_requires_login(tcfg):
    make_pair(tcfg)
    with client(tcfg) as c:
        assert c.post(f"/api/episodes/{VID}/shorts/k01/watched", json={"value": True}).status_code == 401


def test_watched_stale_after_rerender_and_old_files(tcfg):
    make_pair(tcfg)
    out = Path(tcfg.render.output_dir) / VID
    with client(tcfg) as c:
        login(c)
        c.post(f"/api/episodes/{VID}/shorts/k01/watched", json={"value": True})
        rm = json.loads((out / "render_manifest.json").read_text(encoding="utf-8"))
        rm["shorts"][0]["sha256"] = "f" * 64  # a re-render produced another file
        (out / "render_manifest.json").write_text(json.dumps(rm), encoding="utf-8")
        s = c.get(f"/api/episodes/{VID}").json()["shorts"][0]
        assert s["watched"] is True and s["watched_stale"] is True
        r = c.post(f"/api/episodes/{VID}/shorts/k01/watched", json={"value": True})
        assert r.json()["stale"] is False  # "đánh dấu bản này"
        # an episode with only the old files (no watched.json) and a broken watched.json read as "not watched"
        (Path(tcfg.workspace.dir) / VID / "watched.json").write_text("{broken", encoding="utf-8")
        s = c.get(f"/api/episodes/{VID}").json()["shorts"][0]
        assert s["watched"] is False and s["published"] is False
        (Path(tcfg.workspace.dir) / VID / "watched.json").unlink()
        assert c.get(f"/api/episodes/{VID}").json()["shorts"][0]["watched"] is False


def test_publish_json_schema_unchanged(tcfg):
    make_pair(tcfg)
    with client(tcfg) as c:
        login(c)
        c.post(f"/api/episodes/{VID}/shorts/k01/published", json={"value": True})
        c.post(f"/api/episodes/{VID}/shorts/k01/watched", json={"value": True})
    doc = json.loads((Path(tcfg.workspace.dir) / VID / "publish.json").read_text(encoding="utf-8"))
    assert list(doc) == ["schema_version", "episode_id", "published"]


# --- D5 ------------------------------------------------------------------------------------------------------

def test_show_advanced_flag_default_hidden(tcfg):
    assert from_dict({}).web.show_advanced is False
    assert from_dict({"web": {"show_advanced": True}}).web.show_advanced is True
    with pytest.raises(Exception):
        from_dict({"web": {"show_advanced": "yes"}})
    with client(tcfg) as c:
        assert c.get("/api/ui").status_code == 401
        login(c)
        assert c.get("/api/ui").json() == {"advanced": False}
    with client(replace(tcfg, web=WebConfig(show_advanced=True))) as c:
        login(c)
        assert c.get("/api/ui").json() == {"advanced": True}


def test_script_gates_advanced_buttons_and_uses_icons(tcfg):
    with client(tcfg) as c:
        login(c)
        js = c.get("/static/app.js").text
        css = c.get("/static/style.css").text
    assert "uiFlags.advanced ? cutEditor(s) : null" in js
    assert '$("#corr-open").hidden = !uiFlags.advanced' in js
    assert 'g.view.kind === "khaithi" ? "Xem Khai thị" : "Xem Short"' in js
    for label in ("Tải về", "Lặp lại"):
        assert f'title: "{label}"' in js and f'"aria-label": "{label}"' in js
    assert '"aria-label": `Xóa ${noun()}`' in js and "icon(\"trash\")" in js
    assert ".icon-btn" in css and "min-width: 2.75rem" in css and "min-height: 2.75rem" in css
    assert "/watched" in js and 'video.addEventListener("ended", finished)' in js
