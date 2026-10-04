"""CP13.4: face restoration parameters (G1), worker capability gating (G2, AC2), finished videos keep their HD source and
"Enhance lại" (G3, AC3). Real ffmpeg, tiny videos; no worker, no GPU."""

import logging
from dataclasses import replace

import pytest

pytest.importorskip("fastapi")

from auto_short import hashing  # noqa: E402
from auto_short.config import ConfigError, EnhanceConfig, from_dict  # noqa: E402
from auto_short.enhance import state as st  # noqa: E402
from auto_short.hashing import sha256_file  # noqa: E402

from enhance_helpers import FRAMES, T1, T2, enhance_cfg, make_clip, make_segment, make_yt_episode  # noqa: E402
from test_enhance_api import E1, H1, H2, Ctx, sha, wait_for  # noqa: E402

pytestmark = pytest.mark.usefixtures("_video_template")
FACE = "gfpgan_v1.4"
CAP = [f"face:{FACE}"]


def lease(ctx, headers=H1, caps=None):
    body = {"worker": "w", "gpu": "RTX 3090"}
    if caps is not None:
        body["capabilities"] = caps
    return ctx.client.post("/api/enhance/lease", json=body, headers=headers)


def fake_done_hd(ws, cfg_hash_made=None):
    """Mark the episode as enhanced earlier (a HD source on disk, state done)."""
    hd = st.hd_path(ws.dir)
    make_clip(hd, w=640, h=480, frames=FRAMES, audio=True)
    doc = st.read(ws.dir)
    doc.update(state=st.DONE, source_hd_sha256=sha256_file(hd), source_hd_size=hd.stat().st_size,
               source_hd_mtime_ns=hd.stat().st_mtime_ns)
    st.write(ws.dir, doc)
    return doc


# --- G1: parameters + hash ----------------------------------------------------------------------------------

def test_config_face_defaults_and_validation():
    d = EnhanceConfig()
    assert (d.face, d.face_weight, d.face_detect_every) == ("none", 1.0, 5)
    got = from_dict({"enhance": {"face": FACE, "face_weight": 0.5, "face_detect_every": 5}}).enhance
    assert (got.face, got.face_weight, got.face_detect_every) == (FACE, 0.5, 5)
    for bad in ({"face": "codeformer"}, {"face_weight": 1.5}, {"face_detect_every": 0}, {"face_detect_every": 31}):
        with pytest.raises(ConfigError):
            from_dict({"enhance": bad})


def test_face_none_keeps_params_and_hash_byte_identical():
    cfg = EnhanceConfig()
    params = st.params_of(cfg)
    assert params == {"model": "realesr-general-x4v3", "denoise": 1.0, "pre_height": 360, "out_height": 1080}
    old = hashing.config_hash({"plan": 1, "params": params, "segment_frames": 1800, "source_sha256": "s"})
    assert st.config_hash_of(params, 1800, "s") == old
    with_face = st.params_of(replace(cfg, face=FACE))
    assert with_face["face"] == FACE and with_face["face_weight"] == 1.0 and with_face["face_detect_every"] == 5
    assert st.config_hash_of(with_face, 1800, "s") != old
    assert st.config_hash_of(st.params_of(replace(cfg, face=FACE, face_detect_every=3)), 1800, "s") \
        != st.config_hash_of(with_face, 1800, "s")
    assert st.has_face(with_face) and not st.has_face(params)


# --- G2 / AC2: capability gating --------------------------------------------------------------------------

def test_face_lease_goes_only_to_a_capable_worker(tmp_path, caplog):
    ctx = Ctx(tmp_path, face=FACE)
    with ctx.client:
        make_yt_episode(ctx.cfg, E1)
        with caplog.at_level(logging.WARNING, logger="auto_short"):
            assert lease(ctx, H2).status_code == 204                      # old worker: no capabilities
            assert lease(ctx, H2, caps="face").status_code == 204         # junk is ignored
            assert lease(ctx, H2, caps=["face:other"]).status_code == 204
        assert "cần cập nhật worker" in caplog.text and caplog.text.count("cần cập nhật worker") == 1
        r = lease(ctx, H1, caps=CAP)
        assert r.status_code == 200
        body = r.json()
        assert body["params"]["face"] == FACE and body["params"]["face_weight"] == 1.0
        assert body["params"]["face_detect_every"] == 5
        # the worker panel flags the one that cannot do it
        status = ctx.client.get("/api/enhance/status", cookies=ctx.web_login()).json()
        flags = {w["name"]: w["outdated"] for w in status["workers"]}
        assert flags == {"w3090": False, "w3050": True}


def test_face_none_is_given_to_any_worker(tmp_path):
    ctx = Ctx(tmp_path)
    with ctx.client:
        make_yt_episode(ctx.cfg, E1)
        r = lease(ctx, H2)
        assert r.status_code == 200 and "face" not in r.json()["params"]


# --- G3 / AC3 ---------------------------------------------------------------------------------------------

def test_pending_video_switches_to_the_new_config(tmp_path):
    old = Ctx(tmp_path)
    ws = make_yt_episode(old.cfg, E1)
    d0 = st.read(ws.dir)
    seg_dir = st.segments_dir(ws.dir, d0["config_hash"])
    seg_dir.mkdir(parents=True)
    (seg_dir / "seg_00000.mp4").write_bytes(b"x")
    d0["segments"] = {"0": {"sha256": "1" * 64}}
    st.write(ws.dir, d0)
    new = Ctx(tmp_path, face=FACE)
    with new.client:
        body = lease(new, H1, CAP).json()
    assert body["config_hash"] != d0["config_hash"] and body["done_segments"] == [] and not seg_dir.exists()


def test_done_video_keeps_hd_is_labelled_old_and_redo_queues_it(tmp_path):
    old = Ctx(tmp_path)
    ws = make_yt_episode(old.cfg, E1)
    d0 = fake_done_hd(ws)
    hd_sha = d0["source_hd_sha256"]
    new = Ctx(tmp_path, face=FACE)
    with new.client:
        cookie = new.web_login()
        view = new.client.get(f"/api/episodes/{E1}", cookies=cookie).json()["enhance"]
        assert view["state"] == "done" and view["hd_old_config"] is True and view["can_redo"] is True
        assert lease(new, H1, CAP).status_code == 204                      # not redone by itself
        doc = st.read(ws.dir)
        assert doc["state"] == st.DONE and st.hd_fingerprint(ws.dir).sha256 == hd_sha
        # redo: queued with the new config, the old HD stays in use meanwhile
        r = new.client.post(f"/api/episodes/{E1}/enhance/redo", cookies=cookie)
        assert r.status_code == 200
        doc = st.read(ws.dir)
        assert doc["state"] == st.PENDING and doc["redo"] is True and doc["hd_config_hash"] == d0["config_hash"]
        assert st.hd_fingerprint(ws.dir).sha256 == hd_sha and not new.svc.hold(E1)
        v = new.client.get(f"/api/episodes/{E1}", cookies=cookie).json()["enhance"]
        assert v["state"] == "queued" and v["redo"] is True and v["hd_ready"] is True
        assert new.client.post(f"/api/episodes/{E1}/enhance/redo", cookies=cookie).status_code == 409
        # a capable worker does it; old workers never get it
        assert lease(new, H2).status_code == 204
        got = lease(new, H1, CAP).json()
        assert got["config_hash"] != d0["config_hash"] and got["params"]["face"] == FACE
        for n in range(4):
            data = make_segment(tmp_path / f"s{n}.mp4", n)
            r = new.client.put(f"/api/enhance/{got['lease_id']}/seg/{n}", content=data,
                               headers={**H1, "X-Sha256": sha(data)})
            assert r.status_code == 200
        wait_for(lambda: st.read(ws.dir)["state"] == st.DONE)
        doc = st.read(ws.dir)
        assert doc["redo"] is False and doc["hd_config_hash"] == doc["config_hash"] == got["config_hash"]
        assert doc["source_hd_sha256"] != hd_sha and st.hd_fingerprint(ws.dir) is not None
        v = new.client.get(f"/api/episodes/{E1}", cookies=cookie).json()["enhance"]
        assert v["hd_old_config"] is False and v["can_redo"] is False
        assert new.client.post(f"/api/episodes/{E1}/enhance/redo", cookies=cookie).status_code == 409


def test_redo_is_refused_when_the_hd_already_matches(tmp_path):
    ctx = Ctx(tmp_path)
    with ctx.client:
        ws = make_yt_episode(ctx.cfg, E1)
        fake_done_hd(ws)
        assert ctx.client.post(f"/api/episodes/{E1}/enhance/redo", cookies=ctx.web_login()).status_code == 409
        assert st.read(ws.dir)["state"] == st.DONE


def test_khaithi_keeps_the_old_hd_while_the_video_redoes(tmp_path):
    old = Ctx(tmp_path)
    ws = make_yt_episode(old.cfg, E1)
    kt = make_yt_episode(old.cfg, E1 + ".kt", with_enhance=False)
    st.decide(old.cfg, E1 + ".kt")
    fake_done_hd(ws)
    st.mirror(old.cfg, E1)
    new = Ctx(tmp_path, face=FACE)
    with new.client:
        assert new.client.post(f"/api/episodes/{E1}/enhance/redo", cookies=new.web_login()).status_code == 200
    kdoc = st.read(kt.dir)
    assert kdoc["state"] == st.PENDING and kdoc["redo"] is True and st.hd_path(kt.dir).is_file()
    assert st.hd_fingerprint(kt.dir) is not None


def test_playlist_redo_queues_every_old_hd(tmp_path):
    from doc_helpers import write_playlist
    old = Ctx(tmp_path)
    other = "vid00000002"
    for eid in (E1, other):
        fake_done_hd(make_yt_episode(old.cfg, eid))
    write_playlist(old.cfg.workspace.dir, "PLenhRedo0123456789", [(E1, "1"), (other, "2")], doc_url=None)
    new = Ctx(tmp_path, face=FACE)
    with new.client:
        r = new.client.post("/api/playlists/PLenhRedo0123456789/enhance-redo", cookies=new.web_login())
        assert r.status_code == 200 and r.json()["queued"] == 2 and r.json()["errors"] == []
        again = new.client.post("/api/playlists/PLenhRedo0123456789/enhance-redo", cookies=new.web_login())
        assert again.json()["queued"] == 0
    assert all(st.read(new.cfg.workspace.dir / e)["redo"] for e in (E1, other))
