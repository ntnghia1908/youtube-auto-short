"""CP8.35: "Xử lý" with the ``vertical`` flag queues the vertical full-episode job by itself once the Shorts are
rendered and the best HD source is ready (enhance on: after the HD is assembled)."""

import hashlib
import json
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from auto_short.config import Config, EnhanceConfig, RenderConfig, WorkspaceConfig  # noqa: E402
from auto_short.enhance import state as st  # noqa: E402
from auto_short.pipeline import PIPELINE_STAGES, StageDeps, run_pipeline  # noqa: E402
from auto_short.render import full  # noqa: E402
from auto_short.web import app as app_mod  # noqa: E402
from auto_short.web import auto_vertical as av_mod  # noqa: E402

from test_web_vertical_cp832 import ffmpeg_clip, fake_vertical, make_ep, write_hd  # noqa: E402
from web_helpers import login, web_client, write_episode  # noqa: E402

VID = "aaaaaaaaaa1"
KT = VID + ".kt"
WS = "x"


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output", preset="ultrafast", threads=2),
                  enhance=EnhanceConfig(enabled=False, min_height=720))


def pipeline_of(height: int):
    """Fake pipeline: the render stage leaves a finished episode whose original is ``height`` p (the khai thị id only
    gets Shorts)."""
    def runner(stage):
        def run(target_or_id, config, **kw):
            if stage == "ingest":
                eid = kw.get("episode_id") or target_or_id.rsplit("/", 1)[-1]
                return SimpleNamespace(episode_id=eid, ran=True, workspace=Path(config.workspace.dir) / eid)
            if stage == "render":
                if target_or_id.endswith(".kt"):
                    write_episode(config, target_or_id)
                else:
                    keep = st.read(Path(config.workspace.dir) / target_or_id)
                    make_ep(config, target_or_id, height=height)
                    if keep is not None:
                        st.write(Path(config.workspace.dir) / target_or_id, keep)
                path = Path(config.render.output_dir) / target_or_id / "render_manifest.json"
                return SimpleNamespace(episode_id=target_or_id, ran=True, path=path, rendered=1, clips=1,
                                       encoded=1, reused=0)
            return SimpleNamespace(episode_id=target_or_id, ran=stage != "analysis", path=None)
        return run
    return partial(run_pipeline, deps=StageDeps(runners={s: runner(s) for s in PIPELINE_STAGES}))


def make_client(cfg, calls, *, height=1080, **kw):
    c = web_client(cfg, pipeline=pipeline_of(height), vertical=fake_vertical(calls), **kw)
    c.__enter__()
    login(c)
    return c


def submit(c, **body):
    return c.post("/api/episodes", json={"url": f"https://youtu.be/{VID}", "mode": "video", **body})


def idle(c):
    assert c.app.state.runner.wait_idle(15)


def vertical_jobs(c):
    return [j for j in c.app.state.runner.jobs() if j.kind == "vertical"]


def write_pending(cfg, eid=VID):
    """The video is known (manifest from an earlier ingest) and its HD is wanted but not there yet."""
    d = make_ep(cfg, eid, height=480)  # low resolution: enhance wants an HD source
    ffmpeg_clip(d / "source.mp4", seconds=1, w=854, h=480)  # a real file: the pipeline's enhance check probes it
    data = (d / "source.mp4").read_bytes()
    m = json.loads((d / "manifest.json").read_text())
    m["source"].update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    (d / "manifest.json").write_text(json.dumps(m))
    doc = st.new_doc(eid)
    doc.update(wanted=True, state=st.PENDING)
    st.write(d, doc)


def test_ac1_ui_boxes_and_defaults():
    root = Path(app_mod.__file__).parent / "static"
    assert 'id="pl-vertical-box" type="checkbox" checked' in (root / "playlist.html").read_text(encoding="utf-8")
    assert 'id="idx-vertical" type="checkbox" checked' in (root / "index.html").read_text(encoding="utf-8")
    js = (root / "app.js").read_text(encoding="utf-8")
    assert "saved.vertical !== false" in js  # a choice saved before CP8.35 = ticked
    assert 'store("autoShort.idxVertical") !== "0"' in js
    assert "body.vertical = true" in js


def test_ac2_original_queues_one_vertical_after_render(tcfg):
    calls = []
    c = make_client(tcfg, calls)
    assert submit(c, vertical=True).status_code == 202
    idle(c)
    jobs = vertical_jobs(c)
    assert len(jobs) == 1 and jobs[0].status == "done" and jobs[0].episode_id == VID
    assert calls == [VID] and full.current(tcfg, VID)
    assert not c.app.state.auto_vertical.wanted(VID)  # the wish is dropped once the job is queued
    c.__exit__(None, None, None)


def test_ac3_enhance_pending_waits_for_the_hd(tcfg):
    cfg = replace(tcfg, enhance=EnhanceConfig(enabled=True, min_height=720))
    write_pending(cfg)
    calls = []
    c = make_client(cfg, calls, height=480)
    assert submit(c, vertical=True).status_code == 202
    idle(c)
    assert vertical_jobs(c) == [] and c.app.state.auto_vertical.wanted(VID)
    d = Path(cfg.workspace.dir) / VID
    write_hd(cfg, VID)  # the HD is assembled
    c.app.state.hd_ready(VID)
    idle(c)
    jobs = vertical_jobs(c)
    assert len(jobs) == 1 and jobs[0].status == "done"
    assert full.read_meta(cfg, VID)["source"] == "hd" and (d / "source_hd.mp4").is_file()
    assert not c.app.state.auto_vertical.wanted(VID)
    c.app.state.hd_ready(VID)  # a second HD event: nothing more
    idle(c)
    assert len(vertical_jobs(c)) == 1
    c.__exit__(None, None, None)


def test_ac3_playlist_entry_says_will_make_when_hd_comes(tcfg):
    cfg = replace(tcfg, enhance=EnhanceConfig(enabled=True, min_height=720))
    write_pending(cfg)
    c = make_client(cfg, [], height=480)
    pl = "PLtest0000000000000000000000000000"
    path = Path(cfg.workspace.dir) / "_playlists" / f"{pl}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "playlist_id": pl, "title": "T", "url": "u",
                                "fetched_at": "2026-10-18T00:00:00Z",
                                "entries": [{"index": 1, "video_id": VID, "title": "Tập 1", "duration": 3000.0,
                                             "episode": "1", "available": True}]}), encoding="utf-8")
    v = c.get(f"/api/playlists/{pl}").json()["entries"][0]["vertical"]
    assert v["auto_waiting"] is False
    c.app.state.auto_vertical.set(VID, True)
    v = c.get(f"/api/playlists/{pl}").json()["entries"][0]["vertical"]
    assert v["auto_waiting"] is True and v["reason"] == "sẽ tạo khi có HD"
    c.__exit__(None, None, None)


def test_ac4_low_resolution_drops_the_wish(tcfg):
    calls = []
    c = make_client(tcfg, calls, height=480)
    assert submit(c, vertical=True).status_code == 202
    idle(c)
    assert vertical_jobs(c) == [] and calls == []
    assert not c.app.state.auto_vertical.wanted(VID)
    c.__exit__(None, None, None)


@pytest.mark.parametrize("body", [{}, {"vertical": False}])
def test_ac5_absent_or_false_is_the_old_behaviour(tcfg, body):
    calls = []
    c = make_client(tcfg, calls)
    assert submit(c, **body).status_code == 202
    idle(c)
    assert vertical_jobs(c) == [] and calls == []
    c.__exit__(None, None, None)


def test_ac5_false_after_true_clears_the_wish(tcfg):
    cfg = replace(tcfg, enhance=EnhanceConfig(enabled=True, min_height=720))
    write_pending(cfg)
    c = make_client(cfg, [], height=480)
    submit(c, vertical=True)
    idle(c)
    assert c.app.state.auto_vertical.wanted(VID)
    submit(c, vertical=False)
    assert not c.app.state.auto_vertical.wanted(VID)
    idle(c)  # never stop the server under a running job (JobRunner.stop interrupts it asynchronously)
    c.__exit__(None, None, None)


def test_ac5_wish_survives_a_restart(tcfg):
    cfg = replace(tcfg, enhance=EnhanceConfig(enabled=True, min_height=720))
    write_pending(cfg)
    c = make_client(cfg, [], height=480)
    submit(c, vertical=True)
    idle(c)
    assert (Path(cfg.workspace.dir) / av_mod.WISH_FILE).is_file()
    c.__exit__(None, None, None)
    calls = []
    c2 = make_client(cfg, calls, height=480)  # a new server over the same workspace
    assert c2.app.state.auto_vertical.wanted(VID) and vertical_jobs(c2) == []
    write_hd(cfg, VID)
    c2.app.state.hd_ready(VID)
    idle(c2)
    assert len(vertical_jobs(c2)) == 1 and calls == [VID]
    c2.__exit__(None, None, None)


def test_ac6_short_and_khaithi_make_one_vertical(tcfg):
    calls = []
    c = make_client(tcfg, calls)
    kc = tcfg.khaithi
    r = submit(c, vertical=True, kinds=["short", "khaithi"], min_minutes=kc.default_min_minutes,
               max_minutes=kc.default_max_minutes)
    assert r.status_code == 202
    idle(c)
    assert len(vertical_jobs(c)) == 1 and calls == [VID]
    c.__exit__(None, None, None)


def test_ac6_khaithi_only_triggers_and_current_vertical_is_not_queued_again(tcfg):
    calls = []
    c = make_client(tcfg, calls)
    kc = tcfg.khaithi
    make_ep(tcfg, VID)  # the video's Short episode with its original (the khai thị reuses it)
    r = submit(c, vertical=True, kinds=["khaithi"], min_minutes=kc.default_min_minutes, max_minutes=kc.default_max_minutes)
    assert r.status_code == 202
    idle(c)
    assert len(vertical_jobs(c)) == 1 and calls == [VID]
    # the vertical file is current: a second "Xử lý" with the flag queues nothing
    c.app.state.auto_vertical.set(VID, True)
    c.app.state.hd_ready(VID)
    idle(c)
    assert len(vertical_jobs(c)) == 1 and calls == [VID]
    assert not c.app.state.auto_vertical.wanted(VID)
    c.__exit__(None, None, None)


def test_wish_file_unreadable_is_ignored(tmp_path):
    p = tmp_path / av_mod.WISH_FILE
    p.write_text("{not json", encoding="utf-8")
    assert av_mod.AutoVertical(p).videos() == []
    p.write_text(json.dumps({"version": 1, "videos": [VID, 3]}), encoding="utf-8")
    a = av_mod.AutoVertical(p)
    assert a.wanted(KT) and a.videos() == [VID]  # a khai thị id shares the wish of its video
