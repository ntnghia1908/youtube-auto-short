"""CP8.27: HD video download route (H1/H3), view fields (H2) and the vertical full-episode version (H4)."""

import hashlib
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auto_short import khaithi  # noqa: E402
from auto_short.config import Config, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.enhance import state as st  # noqa: E402
from auto_short.khaithi import KhaiThi  # noqa: E402
from auto_short.render import full  # noqa: E402
from auto_short.render.stage import RenderError  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402

from web_helpers import fake_pipeline, write_episode  # noqa: E402

PW = "pw"
VID = "aaaaaaaaaa1"
KT = VID + ".kt"
SERIES = "Địa Tạng Bồ Tát Bổn Nguyện Kinh"
HD_BYTES = bytes(range(256)) * 40


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output", preset="ultrafast", threads=2))


def client(cfg, **kw):
    app = app_mod.create_app(cfg, PW, preflight=lambda c: None, pipeline=fake_pipeline([]),
                             disk_usage=lambda p: (100 * 10**9, 50 * 10**9, 50 * 10**9), **kw)
    return TestClient(app, follow_redirects=False)


def login(c):
    assert c.post("/login", data={"password": PW}).status_code == 303


def set_titles(cfg, eid, *, series=SERIES, episode="1", lines=("HT. Tịnh Không", "Địa Tạng (tập 1)")):
    fields = {k: v for k, v in (("speaker", lines[0]), ("series", series), ("episode", episode)) if v is not None}
    (Path(cfg.workspace.dir) / eid / "titles.json").write_text(
        json.dumps({"header": {"fields": fields, "lines": list(lines)}}, ensure_ascii=False), encoding="utf-8")


def write_hd(cfg, eid, data=HD_BYTES, *, done=True, claim_sha=None):
    d = Path(cfg.workspace.dir) / eid
    d.mkdir(parents=True, exist_ok=True)
    (d / "source_hd.mp4").write_bytes(data)
    stt = (d / "source_hd.mp4").stat()
    doc = st.new_doc(eid)
    doc.update(wanted=True, state=st.DONE if done else st.ASSEMBLING,
               source_hd_sha256=claim_sha or hashlib.sha256(data).hexdigest(), source_hd_size=stt.st_size,
               source_hd_mtime_ns=stt.st_mtime_ns)
    st.write(d, doc)


def make_ep(cfg, *, with_kt=False, episode="1"):
    write_episode(cfg, VID, clips=("k01",))
    set_titles(cfg, VID, episode=episode)
    if with_kt:
        write_episode(cfg, KT, clips=("k01",))
        khaithi.write(Path(cfg.workspace.dir) / KT, KhaiThi(VID, 4, 7))
        set_titles(cfg, KT, episode=episode)


def test_unauthenticated_blocked(tcfg):
    make_ep(tcfg)
    write_hd(tcfg, VID)
    c = client(tcfg)
    for method, path in (("get", f"/api/episodes/{VID}/source-hd"), ("get", f"/api/episodes/{VID}/vertical"),
                         ("post", f"/api/episodes/{VID}/vertical")):
        assert getattr(c, method)(path).status_code in (303, 401)


def test_download_name_range_and_no_tick(tcfg):
    make_ep(tcfg)
    write_hd(tcfg, VID)
    c = client(tcfg)
    login(c)
    r = c.get(f"/api/episodes/{VID}/source-hd")
    assert r.status_code == 200 and r.content == HD_BYTES
    name = f"{SERIES}_Tập1_HD.mp4"
    assert f"filename*=UTF-8''{quote(name, safe='')}" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].startswith("attachment")
    part = c.get(f"/api/episodes/{VID}/source-hd", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == HD_BYTES[10:20]
    ws = Path(tcfg.workspace.dir) / VID  # H3: a download ticks nothing
    assert not (ws / "published.json").exists() and not (ws / "watched.json").exists()
    view = c.get(f"/api/episodes/{VID}").json()["hd_video"]
    assert view["url"] == f"/api/episodes/{VID}/source-hd" and view["name"] == name
    assert view["size"] == len(HD_BYTES) and view["vertical"]["ready"] is False


@pytest.mark.parametrize("case", ["none", "assembling", "bad_sha", "bad_size"])
def test_no_valid_hd_is_404_and_hidden(tcfg, case):
    make_ep(tcfg)
    if case == "assembling":
        write_hd(tcfg, VID, done=False)
    elif case == "bad_sha":
        write_hd(tcfg, VID, claim_sha="0" * 64)
        d = Path(tcfg.workspace.dir) / VID
        doc = st.read(d)
        doc["source_hd_size"] = 1  # size / mtime disagree -> sha256 is checked and does not match
        st.write(d, doc)
    elif case == "bad_size":
        write_hd(tcfg, VID)
        (Path(tcfg.workspace.dir) / VID / "source_hd.mp4").write_bytes(b"truncated")
    c = client(tcfg)
    login(c)
    r = c.get(f"/api/episodes/{VID}/source-hd")
    assert r.status_code == 404 and "HD" in r.json()["detail"]
    assert c.get(f"/api/episodes/{VID}/vertical").status_code == 404
    assert c.post(f"/api/episodes/{VID}/vertical").status_code == 404
    assert c.get(f"/api/episodes/{VID}").json()["hd_video"] is None


def test_khaithi_uses_video_hd_and_bad_ids(tcfg):
    make_ep(tcfg, with_kt=True)
    write_hd(tcfg, VID)
    c = client(tcfg)
    login(c)
    r = c.get(f"/api/episodes/{KT}/source-hd")
    assert r.status_code == 200 and r.content == HD_BYTES
    assert "Tập1_HD.mp4" in quote(r.headers["content-disposition"], safe="%") or "T%E1%BA%ADp1_HD.mp4" in r.headers["content-disposition"]
    for bad in ("..", "x", "a/b", "%2e%2e%2fwork"):
        assert c.get(f"/api/episodes/{bad}/source-hd").status_code in (404, 422)


def test_no_episode_number_uses_video_id(tcfg):
    make_ep(tcfg, episode=None)
    write_hd(tcfg, VID)
    c = client(tcfg)
    login(c)
    assert c.get(f"/api/episodes/{VID}").json()["hd_video"]["name"] == f"{VID}_HD.mp4"
    assert f"filename=\"{VID}_HD.mp4\"" in c.get(f"/api/episodes/{VID}/source-hd").headers["content-disposition"]


def test_vertical_job_runs_in_render_lane_and_is_reused(tcfg):
    make_ep(tcfg)
    write_hd(tcfg, VID)
    calls = []

    def fake_vertical(eid, cfg):
        calls.append(eid)
        d = full.vertical_dir(cfg, eid)
        d.mkdir(parents=True, exist_ok=True)
        (d / full.VIDEO_NAME).write_bytes(b"v" * 123)
        sha = st.read(Path(cfg.workspace.dir) / eid)["source_hd_sha256"]
        (d / full.META_NAME).write_text(json.dumps({"hd_sha256": sha, "size": 123, "key": "k"}), encoding="utf-8")
        return full.FullResult(eid, d / full.VIDEO_NAME, True, 0.1, 123)

    c = client(tcfg, vertical=fake_vertical)
    c.__enter__()  # lifespan starts the job runner
    login(c)
    assert c.get(f"/api/episodes/{VID}/vertical").status_code == 404
    r = c.post(f"/api/episodes/{VID}/vertical")
    assert r.status_code == 202 and r.json()["job"]["kind"] == "vertical"
    for _ in range(100):
        v = c.get(f"/api/episodes/{VID}").json()["hd_video"]["vertical"]
        if v["ready"]:
            break
        time.sleep(0.1)
    assert v["ready"] and v["size"] == 123 and v["name"] == f"{SERIES}_Tập1_Doc.mp4"
    assert calls == [VID]
    got = c.get(f"/api/episodes/{VID}/vertical")
    assert got.status_code == 200 and got.content == b"v" * 123
    assert "Doc.mp4" in got.headers["content-disposition"]
    assert c.get("/api/monitor/queue").status_code == 200
    c.__exit__(None, None, None)


def test_vertical_failure_is_reported(tcfg):
    make_ep(tcfg)
    write_hd(tcfg, VID)

    def broken(eid, cfg):
        raise RenderError("boom")

    c = client(tcfg, vertical=broken)
    c.__enter__()
    login(c)
    c.post(f"/api/episodes/{VID}/vertical")
    for _ in range(100):
        job = c.get(f"/api/episodes/{VID}").json()["hd_video"]["vertical"]["job"]
        if job["status"] == "failed":
            break
        time.sleep(0.1)
    assert job["status"] == "failed" and "boom" in job["error"]
    c.__exit__(None, None, None)


def test_playlist_entry_gets_hd_url_only_when_done(tcfg):
    make_ep(tcfg)
    write_hd(tcfg, VID)
    from auto_short.web.playlists import hd_progress
    assert hd_progress(tcfg, VID)["state"] == "done"


# --- real ffmpeg: the vertical file ------------------------------------------------------------------------------

def _ffmpeg_clip(path: Path, seconds=3, w=640, h=480, fps=25):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps}",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2",
                    str(path)], check=True)


def _probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


def test_run_vertical_real_encode_and_reuse(tcfg):
    make_ep(tcfg)
    d = Path(tcfg.workspace.dir) / VID
    _ffmpeg_clip(d / "source_hd.mp4")
    data = (d / "source_hd.mp4").read_bytes()
    write_hd(tcfg, VID, data)  # records the fingerprint of the real file
    r1 = full.run_vertical(VID, tcfg)
    assert r1.ran and r1.path == full.vertical_path(tcfg, VID) and r1.size > 0
    s = _probe(r1.path)
    assert (s["video"]["width"], s["video"]["height"], s["video"]["pix_fmt"]) == (1080, 1920, "yuv420p")
    assert s["video"]["nb_frames"] == "75" and abs(float(s["audio"]["duration"]) - 3.0) < 0.1
    assert full.current(tcfg, VID)
    r2 = full.run_vertical(VID, tcfg)  # nothing changed -> no encode
    assert not r2.ran and r2.path == r1.path
    set_titles(tcfg, VID, lines=("HT. Tịnh Không", "Địa Tạng (tập 2)"))  # header changed -> encode again
    assert full.run_vertical(KT, tcfg).ran  # a khai thị id means its video
    assert full.read_meta(tcfg, VID)["speaker"] == ["HT. Tịnh Không"]
    assert not any(p.name.endswith(".part") for p in r1.path.parent.iterdir())


def test_run_vertical_without_hd_or_header(tcfg):
    make_ep(tcfg)
    with pytest.raises(RenderError, match="HD"):
        full.run_vertical(VID, tcfg)
    d = Path(tcfg.workspace.dir) / VID
    _ffmpeg_clip(d / "source_hd.mp4", seconds=1)
    write_hd(tcfg, VID, (d / "source_hd.mp4").read_bytes())
    (d / "titles.json").unlink()
    with pytest.raises(RenderError, match="titles"):
        full.run_vertical(VID, tcfg)


def test_split_header_and_dot_space():
    assert full.split_header(["HT.Tịnh Không", "Kinh X (tập 1)"], "HT.Tịnh Không") == (["Kinh X (tập 1)"], "HT. Tịnh Không")
    assert full.split_header(["HT. Tịnh Không", "Kinh X", "(tập 1)"], None) == (["Kinh X", "(tập 1)"], "HT. Tịnh Không")
    assert full.split_header(["Chỉ một dòng"], "Khác")[0] == ["Chỉ một dòng"]


def test_full_layout_video_as_v1_panels_fill_black(tcfg):
    from auto_short.render import plan
    geo = plan.geometry(tcfg.render)
    lay = full_layout_of(geo)
    s = geo.min_frame_margin
    v1 = plan.layout(geo, geo.title_h, 1440, 1080)  # the first CP8.27 version = the Short V16 video box + crop
    assert lay.video.w == v1.video.w and lay.video.h == v1.video.h and lay.crop == v1.crop
    assert lay.top.y == s and lay.video.y == s + lay.top.h + s
    assert lay.bottom.y == lay.video.y + lay.video.h + s
    assert lay.bottom.y + lay.bottom.h + s == plan.HEIGHT           # nothing black but the margins
    assert 4 * s <= 0.05 * plan.HEIGHT and lay.bottom.h > lay.top.h > geo.header_h


def full_layout_of(geo):
    return full.full_layout(geo, 1440, 1080)


def test_layout_change_changes_reuse_key(tcfg, monkeypatch):
    make_ep(tcfg)
    d = Path(tcfg.workspace.dir) / VID
    _ffmpeg_clip(d / "source_hd.mp4", seconds=1)
    write_hd(tcfg, VID, (d / "source_hd.mp4").read_bytes())
    assert full.run_vertical(VID, tcfg).ran
    assert not full.run_vertical(VID, tcfg).ran
    monkeypatch.setattr(full, "SPEAKER_SCALE", 2.0)
    assert full.run_vertical(VID, tcfg).ran
