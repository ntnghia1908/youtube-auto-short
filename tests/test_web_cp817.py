"""CP8.17: (D3 reversed by CP8.31 D1: a zip ticks "Đã đăng"), zip names with the bộ kinh (D4), "Tải cả hai" ``all.zip`` (D5)."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.review.names import MAX_SERIES_BYTES, zip_name  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
VID = "aaaaaaaaaa1"
KT = VID + ".kt"
SERIES = "Thập Thiện Nghiệp Đạo Kinh"


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


def set_header(cfg, episode_id, series, episode="29"):
    fields = {}
    if series is not None:
        fields["series"] = series
    if episode is not None:
        fields["episode"] = episode
    (Path(cfg.workspace.dir) / episode_id / "titles.json").write_text(
        json.dumps({"header": {"fields": fields}}, ensure_ascii=False), encoding="utf-8")


def make_pair(cfg, *, series=SERIES, kt_series="inherit", with_kt=True):
    files = {VID: write_episode(cfg, VID, clips=("k01", "k02", "k03"), titles={"k01": "Một", "k02": "Hai", "k03": "Ba"})}
    set_header(cfg, VID, series)
    if with_kt:
        files[KT] = write_episode(cfg, KT, clips=("k01", "k02"), titles={"k01": "Khai một", "k02": "Khai hai"})
        khaithi.write(Path(cfg.workspace.dir) / KT, KhaiThi(VID, 4, 7))
        set_header(cfg, KT, series if kt_series == "inherit" else kt_series)
    return files


def publish(cfg, episode_id):
    p = Path(cfg.workspace.dir) / episode_id / "publish.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# --- pure names (D4, D5) --------------------------------------------------------------------------------

def test_zip_name_series_and_both():
    assert zip_name("29") == "Tập29_Shorts.zip"
    assert zip_name("29", series=SERIES) == f"{SERIES}_Tập29_Shorts.zip"
    assert zip_name("29", khaithi=True, series=SERIES) == f"{SERIES}_Tập29_KhaiThị.zip"
    assert zip_name("29", series=SERIES, both=True) == f"{SERIES}_Tập29_Shorts+KhaiThị.zip"
    assert zip_name("29", both=True) == "Tập29_Shorts+KhaiThị.zip"
    assert zip_name("29", series="  ") == zip_name("29", series=None) == "Tập29_Shorts.zip"
    assert zip_name("29", series='a/b:c*"d') == "abcd_Tập29_Shorts.zip"  # forbidden characters dropped


def test_zip_name_series_truncated():
    long = " ".join(["Thập Thiện Nghiệp"] * 10)
    name = zip_name("29", series=long)
    head = name[:-len("_Tập29_Shorts.zip")]
    assert len(head.encode("utf-8")) <= MAX_SERIES_BYTES and long.startswith(head) and long[len(head)] == " "


# --- CP8.31 D1 (reverses CP8.17 D3): a zip ticks every Short it contains -------------------------------------

def ticked(cfg, episode_id):
    doc = publish(cfg, episode_id)
    return [e["clip_id"] for e in doc["published"]] if doc else []


def test_zip_ticks_published_per_kind(tcfg):
    make_pair(tcfg)
    with client(tcfg) as c:
        login(c)
        assert c.get(f"/files/{KT}/shorts.zip").status_code == 200
        assert ticked(tcfg, KT) == ["k01", "k02"] and publish(tcfg, VID) is None  # khai thị zip -> only the khai thị
        assert c.get(f"/files/{VID}/shorts.zip").status_code == 200
        assert ticked(tcfg, VID) == ["k01", "k02", "k03"]


def test_all_zip_ticks_both_episodes(tcfg):
    make_pair(tcfg)
    with client(tcfg) as c:
        login(c)
        assert c.get(f"/files/{KT}/all.zip").status_code == 200  # either id gives the same result
        assert ticked(tcfg, VID) == ["k01", "k02", "k03"] and ticked(tcfg, KT) == ["k01", "k02"]
        d = c.get(f"/api/episodes/{VID}").json()
        assert d["published"] == 3 and d["complete"] is True


def test_zip_skips_deleted_short_and_stale_becomes_current(tcfg):
    make_pair(tcfg)
    rm_path = Path(tcfg.render.output_dir) / VID / "render_manifest.json"
    rm = json.loads(rm_path.read_text(encoding="utf-8"))
    rm["shorts"][1].update(status="skipped", skip_reason="rejected")  # the last render skipped the deleted Short
    rm_path.write_text(json.dumps(rm), encoding="utf-8")
    with client(tcfg) as c:
        login(c)
        c.get(f"/files/{VID}/shorts.zip")
        assert ticked(tcfg, VID) == ["k01", "k03"]  # the deleted Short is not in the zip, so not ticked
    # a Short re-rendered after its tick ("đã đăng bản cũ") is ticked for the current file by a zip
    rm["shorts"][0]["sha256"] = "f" * 64
    rm_path.write_text(json.dumps(rm), encoding="utf-8")
    with client(tcfg) as c:
        login(c)
        assert c.get(f"/api/episodes/{VID}").json()["shorts"][0]["published_stale"] is True
        c.get(f"/files/{VID}/shorts.zip")
        assert c.get(f"/api/episodes/{VID}").json()["shorts"][0]["published_stale"] is False


def test_zip_still_served_when_publish_json_unwritable(tcfg, monkeypatch):
    make_pair(tcfg)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(app_mod, "mark_downloaded", boom)
    with client(tcfg) as c:
        login(c)
        r = c.get(f"/files/{VID}/shorts.zip")
        assert r.status_code == 200 and zipfile.ZipFile(io.BytesIO(r.content)).testzip() is None
        assert c.get(f"/files/{VID}/all.zip").status_code == 200


# --- D4: zip names -----------------------------------------------------------------------------------------

def test_zip_names_with_series(tcfg):
    files = make_pair(tcfg)
    with client(tcfg) as c:
        login(c)
        s, k = c.get(f"/api/episodes/{VID}").json(), c.get(f"/api/episodes/{KT}").json()
        assert s["zip_name"] == f"{SERIES}_Tập29_Shorts.zip"
        assert k["zip_name"] == f"{SERIES}_Tập29_KhaiThị.zip"
        r = c.get(s["zip_url"])
        assert "filename*=UTF-8''Th%E1%BA%ADp%20Thi%E1%BB%87n" in r.headers["content-disposition"]
        assert 'filename="Thap Thien Nghiep Dao Kinh_Tap29_Shorts.zip"' in r.headers["content-disposition"]
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assert names == ["T29_S01_Một.mp4", "T29_S02_Hai.mp4", "T29_S03_Ba.mp4"]  # entries unchanged
        assert files[VID]  # keep the helper's return used


def test_zip_name_without_series_and_khaithi_fallback(tcfg):
    make_pair(tcfg, series=None, kt_series=None)
    with client(tcfg) as c:
        login(c)
        assert c.get(f"/api/episodes/{VID}").json()["zip_name"] == "Tập29_Shorts.zip"
        assert c.get(f"/api/episodes/{KT}").json()["zip_name"] == "Tập29_KhaiThị.zip"
    # khai thị titles.json without series -> the base Short episode's
    set_header(tcfg, VID, SERIES)
    set_header(tcfg, KT, None)
    with client(tcfg) as c:
        login(c)
        assert c.get(f"/api/episodes/{KT}").json()["zip_name"] == f"{SERIES}_Tập29_KhaiThị.zip"
    # the khai thị's own series wins
    set_header(tcfg, KT, "Kinh Khác")
    with client(tcfg) as c:
        login(c)
        assert c.get(f"/api/episodes/{KT}").json()["zip_name"] == "Kinh Khác_Tập29_KhaiThị.zip"


# --- D5: all.zip --------------------------------------------------------------------------------------------

def test_all_zip_both_ids(tcfg):
    files = make_pair(tcfg)
    with client(tcfg) as c:
        login(c)
        s, k = c.get(f"/api/episodes/{VID}").json(), c.get(f"/api/episodes/{KT}").json()
        assert s["zip_all_url"] == f"/files/{VID}/all.zip" and k["zip_all_url"] == f"/files/{KT}/all.zip"
        assert s["zip_all_name"] == k["zip_all_name"] == f"{SERIES}_Tập29_Shorts+KhaiThị.zip"
        bodies = []
        for url in (s["zip_all_url"], k["zip_all_url"]):
            r = c.get(url)
            assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
            assert "Shorts%2BKhaiTh%E1%BB%8B.zip" in r.headers["content-disposition"] \
                or "Shorts+KhaiTh%E1%BB%8B.zip" in r.headers["content-disposition"]
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                assert zf.testzip() is None
                assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())
                assert all(i.flag_bits & 0x800 for i in zf.infolist() if not i.filename.isascii())  # CP8.21: ASCII names need no flag
                assert zf.namelist() == [
                    "Shorts/T29_S01_Một.mp4", "Shorts/T29_S02_Hai.mp4", "Shorts/T29_S03_Ba.mp4",
                    "KhaiThị/T29_KT01_Khai một.mp4", "KhaiThị/T29_KT02_Khai hai.mp4"]
                got = {n: hashlib.sha256(zf.read(n)).hexdigest() for n in zf.namelist()}
            bodies.append(got)
        assert bodies[0] == bodies[1]
        want = [files[VID]["k01"], files[VID]["k02"], files[VID]["k03"], files[KT]["k01"], files[KT]["k02"]]
        assert list(bodies[0].values()) == [hashlib.sha256(b).hexdigest() for b in want]


def test_all_zip_skips_deleted_short_and_404_when_missing(tcfg):
    make_pair(tcfg, with_kt=False)
    with client(tcfg) as c:
        login(c)
        d = c.get(f"/api/episodes/{VID}").json()
        assert d["zip_all_url"] is None and d["zip_all_name"] is None and d["zip_url"]
        assert c.get(f"/files/{VID}/all.zip").status_code == 404
        assert c.get(f"/files/{KT}/all.zip").status_code == 404
    make_pair(tcfg)
    with client(tcfg) as c:
        login(c)
        rm = Path(tcfg.render.output_dir) / VID / "render_manifest.json"
        doc = json.loads(rm.read_text(encoding="utf-8"))
        doc["shorts"][1].update(status="skipped", skip_reason="rejected")
        rm.write_text(json.dumps(doc), encoding="utf-8")
        (Path(tcfg.render.output_dir) / VID / "shorts" / "k02.mp4").unlink()
        names = zipfile.ZipFile(io.BytesIO(c.get(f"/files/{VID}/all.zip").content)).namelist()
        assert [n for n in names if n.startswith("Shorts/")] == ["Shorts/T29_S01_Một.mp4", "Shorts/T29_S03_Ba.mp4"]
    # no rendered Short left in the khai thị -> 404 + null
    kt_rm = Path(tcfg.render.output_dir) / KT / "render_manifest.json"
    doc = json.loads(kt_rm.read_text(encoding="utf-8"))
    for sh in doc["shorts"]:
        sh.update(status="skipped", skip_reason="rejected")
    kt_rm.write_text(json.dumps(doc), encoding="utf-8")
    with client(tcfg) as c:
        login(c)
        assert c.get(f"/files/{VID}/all.zip").status_code == 404
        assert c.get(f"/api/episodes/{VID}").json()["zip_all_url"] is None


def test_all_zip_requires_login_and_valid_id(tcfg):
    make_pair(tcfg)
    with client(tcfg) as c:
        assert c.get(f"/files/{VID}/all.zip").status_code in (401, 303)
        login(c)
        assert c.get("/files/..%2Fx/all.zip").status_code == 404
        assert c.get("/files/nonexistent1/all.zip").status_code == 404


def test_static_ui_labels_and_refresh_after_zip(tcfg):
    make_pair(tcfg)
    with client(tcfg) as c:
        login(c)
        js = c.get("/static/app.js").text
        html = c.get(f"/episodes/{VID}").text
        assert "Tải tất cả Short (.zip)" in js and "Tải tất cả khai thị (.zip)" in js
        assert 'id="zip-all"' in html and "Tải cả hai (.zip)" in html
        assert "autoShort.postMarks" in js and "markPostStep" in js  # D1
