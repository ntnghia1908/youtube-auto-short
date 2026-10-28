"""FIX-hd-owner-kt: a video whose Short workspace is gone and only ``work/<id>.kt/`` is left keeps its HD / vertical."""

import hashlib
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.enhance import state as st  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.render import full  # noqa: E402

from test_hd_backup import HD, HD_SHA, V_SHA, VERT, VID, KT  # noqa: E402
from web_helpers import login, web_client as client, write_episode  # noqa: E402

PL = "PLtestplaylist01"


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output", preset="ultrafast", threads=2))


def kt_only(cfg, *, vertical=False):
    write_episode(cfg, KT, clips=("k01",))
    d = Path(cfg.workspace.dir) / KT
    khaithi.write(d, KhaiThi(VID, 4, 7))
    (d / "source_hd.mp4").write_bytes(HD)
    stt = (d / "source_hd.mp4").stat()
    doc = st.new_doc(KT)
    doc.update(wanted=True, state=st.DONE, source_hd_sha256=HD_SHA, source_hd_size=stt.st_size,
               source_hd_mtime_ns=stt.st_mtime_ns)
    st.write(d, doc)
    (d / "titles.json").write_text('{"header": {}}', encoding="utf-8")
    if vertical:
        vd = Path(cfg.render.output_dir) / KT / "full"
        vd.mkdir(parents=True, exist_ok=True)
        (vd / "vertical.mp4").write_bytes(VERT)
        (vd / "vertical.json").write_text(json.dumps({"plan_version": full.FULL_PLAN_VERSION, "hd_sha256": HD_SHA, "size": len(VERT), "key": "k"}),
                                          encoding="utf-8")


def logged(cfg, **kw):
    c = client(cfg, **kw)
    login(c)
    return c


def test_owner_for(tcfg):
    assert st.owner_for(tcfg, VID) == VID and st.owner_for(tcfg, KT) == VID  # nothing on disk
    kt_only(tcfg)
    assert st.owner_for(tcfg, VID) == KT and st.owner_for(tcfg, KT) == KT
    write_episode(tcfg, VID, clips=("k01",))
    assert st.owner_for(tcfg, VID) == VID and st.owner_for(tcfg, KT) == VID  # AC3: work/<id>/ wins


def test_ac1_playlist_source_hd_vertical(tcfg):
    kt_only(tcfg, vertical=True)
    root = Path(tcfg.workspace.dir) / "_playlists"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{PL}.json").write_text(json.dumps({
        "schema_version": 1, "playlist_id": PL, "title": "Thử", "url": "u", "fetched_at": "2026-10-01T00:00:00Z",
        "entries": [{"index": 1, "video_id": VID, "title": "Tập 1", "duration": 3000.0, "episode": "1",
                     "available": True}]}), encoding="utf-8")
    c = logged(tcfg)
    e = c.get(f"/api/playlists/{PL}").json()["entries"][0]
    assert e["hd_url"] == f"/api/episodes/{VID}/source-hd"
    assert e["vertical"]["ready"] and e["vertical"]["url"]
    for eid in (VID, KT):
        r = c.get(f"/api/episodes/{eid}/source-hd")
        assert r.status_code == 200 and r.content == HD
        r = c.get(f"/api/episodes/{eid}/vertical")
        assert r.status_code == 200 and r.content == VERT
    assert full.vertical_path(tcfg, VID) == (Path(tcfg.render.output_dir) / KT / "full" / "vertical.mp4").resolve()
    assert not (Path(tcfg.render.output_dir) / VID).exists()


def test_ac1_vertical_job_writes_under_kt(tcfg):
    kt_only(tcfg)

    def fake_vertical(eid, cfg):
        d = full.vertical_dir(cfg, eid)
        d.mkdir(parents=True, exist_ok=True)
        (d / full.VIDEO_NAME).write_bytes(VERT)
        (d / full.META_NAME).write_text(json.dumps({"plan_version": full.FULL_PLAN_VERSION, "hd_sha256": HD_SHA, "size": len(VERT), "key": "k"}),
                                        encoding="utf-8")
        return full.FullResult(eid, d / full.VIDEO_NAME, True, 0.1, len(VERT))

    c = client(tcfg, vertical=fake_vertical)
    c.__enter__()
    login(c)
    assert c.post(f"/api/episodes/{VID}/vertical").status_code == 202
    for _ in range(100):
        if c.get(f"/api/episodes/{VID}/vertical").status_code == 200:
            break
        time.sleep(0.1)
    assert (Path(tcfg.render.output_dir) / KT / "full" / "vertical.mp4").read_bytes() == VERT
    assert not (Path(tcfg.render.output_dir) / VID).exists()
    assert c.get(f"/api/episodes/{KT}/vertical").content == VERT
    c.__exit__(None, None, None)


@pytest.mark.parametrize("eid", [VID, KT])
def test_ac2_backup_and_release_touch_only_kt(tcfg, eid):
    kt_only(tcfg, vertical=True)
    c = logged(tcfg)
    assert c.post(f"/api/episodes/{eid}/backup", json={"kind": "hd", "sha256": HD_SHA}).status_code == 200
    assert c.post(f"/api/episodes/{eid}/backup", json={"kind": "vertical", "sha256": V_SHA}).status_code == 200
    ws = Path(tcfg.workspace.dir)
    assert (ws / KT / "backup.json").is_file() and not (ws / VID).exists()
    r = c.post(f"/api/episodes/{eid}/release", json={})
    assert r.status_code == 200, r.text
    assert r.json()["released"] == VID and r.json()["freed"] == len(HD) + len(VERT)  # response keeps the video id
    assert len(r.json()["removed"]) == 2 and all(f"/{KT}/" in p for p in r.json()["removed"])
    assert not (ws / KT / "source_hd.mp4").exists()
    assert not (Path(tcfg.render.output_dir) / KT / "full" / "vertical.mp4").exists()
    assert st.read(ws / KT)["released"] is True
    assert not (ws / VID).exists() and not (ws / (KT + ".kt")).exists()
    again = c.post(f"/api/episodes/{eid}/release", json={})
    assert again.status_code == 200 and again.json()["changed"] is False


def test_ac3_normal_video_unchanged(tcfg):
    write_episode(tcfg, VID, clips=("k01",))
    d = Path(tcfg.workspace.dir) / VID
    (d / "source_hd.mp4").write_bytes(HD)
    stt = (d / "source_hd.mp4").stat()
    doc = st.new_doc(VID)
    doc.update(wanted=True, state=st.DONE, source_hd_sha256=hashlib.sha256(HD).hexdigest(),
               source_hd_size=stt.st_size, source_hd_mtime_ns=stt.st_mtime_ns)
    st.write(d, doc)
    assert st.owner_for(tcfg, KT) == VID
    assert full.vertical_path(tcfg, KT) == (Path(tcfg.render.output_dir) / VID / "full" / "vertical.mp4").resolve()
    c = logged(tcfg)
    assert c.get(f"/api/episodes/{KT}/source-hd").content == HD
