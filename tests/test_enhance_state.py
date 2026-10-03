"""CP13.1b: [enhance] config, worker tokens, the E1 decision (enhance.json), the khai thị mirror, the HD source the
render reads (E5, E6), the CLI token command and the auto clean-up rule (W9 S5, AC1, AC5, AC6)."""

import json
import os
from dataclasses import replace

import pytest

from auto_short import cli
from auto_short.config import ConfigError, EnhanceConfig, from_dict
from auto_short.enhance import state as st
from auto_short.enhance.tokens import TokenError, authenticate, parse_tokens
from auto_short.hashing import sha256_file
from auto_short.render import run_render
from auto_short.web.storage import auto_archive_plan, episode_sizes

from enhance_helpers import FRAMES, T1, T2, enhance_cfg, make_clip, make_yt_episode
from render_helpers import EID, make_render_episode, make_source

pytestmark = pytest.mark.usefixtures("_video_template")  # skips when ffmpeg is missing


# --- config + tokens ---------------------------------------------------------------------------------------

def test_config_defaults_and_validation():
    cfg = from_dict({})
    assert cfg.enhance == EnhanceConfig() and cfg.enhance.enabled is False and cfg.enhance.min_height == 720
    assert (cfg.enhance.model, cfg.enhance.denoise, cfg.enhance.pre_height, cfg.enhance.out_height) == \
        ("realesr-general-x4v3", 1.0, 360, 1080)
    assert (cfg.enhance.segment_seconds, cfg.enhance.lease_hours, cfg.enhance.max_segment_mb) == (60, 48, 200)
    got = from_dict({"enhance": {"enabled": True, "min_height": 480, "yield_workers": ["rtx3090"]}}).enhance
    assert got.enabled and got.min_height == 480 and got.yield_workers == ("rtx3090",)
    for bad in ({"enabled": "yes"}, {"min_height": 0}, {"segment_seconds": 0}, {"denoise": 2}, {"yield_workers": "x"},
                {"max_segment_mb": 0}):
        with pytest.raises(ConfigError):
            from_dict({"enhance": bad})


def test_tokens_parse_and_authenticate():
    tokens = parse_tokens(f"rtx3090={T1}, rtx3050 = {T2}")
    assert tokens == {"rtx3090": T1, "rtx3050": T2}
    assert parse_tokens(None) == {} and parse_tokens("") == {}
    assert authenticate(tokens, f"Bearer {T2}") == "rtx3050"
    assert authenticate(tokens, f"Bearer {T2}x") is None
    assert authenticate(tokens, T2) is None and authenticate(tokens, None) is None
    assert authenticate({}, f"Bearer {T1}") is None
    for bad in ("rtx3090=short", "noequals", f"a={T1},a={T2}", f"-bad={T1}"):
        with pytest.raises(TokenError):
            parse_tokens(bad)


def test_cli_makes_a_token(capsys):
    assert cli.main(["enhance-token", "--name", "rtx3090"]) == 0
    out, err = capsys.readouterr()
    token = out.strip()
    assert len(token) >= 64 and token.isalnum()
    assert "AUTO_SHORT_ENHANCE_TOKENS" in err and "rtx3090" in err and token not in err
    assert parse_tokens(f"rtx3090={token}")["rtx3090"] == token
    assert cli.main(["enhance-token"]) == 0 and capsys.readouterr().out.strip() != token


# --- E1: decision ------------------------------------------------------------------------------------------

def test_decide_by_height(tmp_path):
    cfg = enhance_cfg(tmp_path)
    low = make_yt_episode(cfg, "low00000001", height=240, with_enhance=False)
    doc = st.decide(cfg, "low00000001")
    assert doc["wanted"] is True and doc["override"] is False and doc["state"] == st.PENDING
    assert doc["height"] == 240 and doc["frames"] == FRAMES and doc["fps"] == "25"
    assert doc["segment_frames"] == 25 and st.total_segments(doc) == 4
    assert doc["source_sha256"] == json.loads((low.dir / "manifest.json").read_text())["source"]["sha256"]
    assert doc["config_hash"] and doc["params"]["pre_height"] == 0 and doc["wanted_at"]
    assert st.read(low.dir) == doc
    high = make_yt_episode(cfg, "hi000000001", height=720, with_enhance=False)
    doc = st.decide(cfg, "hi000000001")
    assert doc["wanted"] is False and "720" in doc["reason"] and doc["frames"] is None
    assert st.read(high.dir)["wanted"] is False


def test_decide_skips_when_off_or_not_youtube(tmp_path):
    off = enhance_cfg(tmp_path, enabled=False)
    ws = make_yt_episode(off, "off00000001", with_enhance=False)
    assert st.decide(off, "off00000001") is None and st.read(ws.dir) is None
    on = enhance_cfg(tmp_path)
    ws = make_yt_episode(on, "loc00000001", kind="local", with_enhance=False)
    assert st.decide(on, "loc00000001") is None and st.read(ws.dir) is None


def test_override_survives_a_new_decision_and_follows_the_source(tmp_path):
    cfg = enhance_cfg(tmp_path)
    ws = make_yt_episode(cfg, "vid00000001", height=240)
    doc = st.decide(cfg, "vid00000001", force=False)  # "Tắt enhance"
    assert doc["wanted"] is False and doc["override"] is True
    assert st.decide(cfg, "vid00000001")["wanted"] is False  # ingest runs again: the choice stays
    doc = st.decide(cfg, "vid00000001", force=True)
    assert doc["wanted"] is True and doc["override"] is True and st.decide(cfg, "vid00000001")["wanted"] is True
    # another download of the same video: the old HD source / segments do not apply any more
    st.hd_path(ws.dir).write_bytes(b"old")
    (ws.dir / st.ENHANCED_DIR / "x").mkdir(parents=True)
    manifest = json.loads((ws.dir / "manifest.json").read_text())
    manifest["source"]["sha256"] = "f" * 64
    (ws.dir / "manifest.json").write_text(json.dumps(manifest))
    doc = st.decide(cfg, "vid00000001")
    assert doc["wanted"] is True and doc["source_sha256"] == "f" * 64
    assert not st.hd_path(ws.dir).exists() and not (ws.dir / st.ENHANCED_DIR).exists()


def test_force_on_needs_a_source(tmp_path):
    cfg = enhance_cfg(tmp_path)
    ws = make_yt_episode(cfg, "vid00000001", height=720)
    (ws.dir / "source.mp4").unlink()
    with pytest.raises(st.EnhanceError, match="nguồn"):
        st.decide(cfg, "vid00000001", force=True)


def test_config_change_drops_old_segments(tmp_path):
    cfg = enhance_cfg(tmp_path)
    ws = make_yt_episode(cfg, "vid00000001")
    doc = st.read(ws.dir)
    seg_dir = st.segments_dir(ws.dir, doc["config_hash"])
    seg_dir.mkdir(parents=True)
    (seg_dir / "seg_00000.mp4").write_bytes(b"x")
    doc["segments"] = {"0": {"sha256": "1" * 64}}
    st.write(ws.dir, doc)
    new = replace(cfg, enhance=replace(cfg.enhance, denoise=0.5))
    doc2 = st.decide(new, "vid00000001")
    assert doc2["config_hash"] != doc["config_hash"] and doc2["segments"] == {} and not seg_dir.exists()


def test_khaithi_follows_the_video_and_links_the_hd_source(tmp_path):
    cfg = enhance_cfg(tmp_path)
    base = make_yt_episode(cfg, "vid00000001")
    kt = make_yt_episode(cfg, "vid00000001.kt", with_enhance=False)
    doc = st.decide(cfg, "vid00000001.kt")  # shares the video's single enhance
    assert doc["follows"] == "vid00000001" and doc["wanted"] is True and doc["state"] == st.PENDING
    assert doc["config_hash"] == st.read(base.dir)["config_hash"]
    # the HD source of the video appears -> mirrored into the khai thị workspace as a hard link
    hd = st.hd_path(base.dir)
    make_clip(hd, w=640, h=480, frames=FRAMES, audio=True)
    bdoc = st.read(base.dir)
    fp_sha = sha256_file(hd)
    bdoc.update(state=st.DONE, source_hd_sha256=fp_sha, source_hd_size=hd.stat().st_size,
                source_hd_mtime_ns=hd.stat().st_mtime_ns)
    st.write(base.dir, bdoc)
    kdoc = st.mirror(cfg, "vid00000001")
    assert kdoc["state"] == st.DONE and kdoc["follows"] == "vid00000001"
    assert os.path.samefile(st.hd_path(base.dir), st.hd_path(kt.dir))
    assert st.hd_fingerprint(kt.dir).sha256 == fp_sha
    # turning enhance off for the video also turns it off for the khai thị
    st.decide(cfg, "vid00000001", force=False)
    assert st.read(kt.dir)["wanted"] is False


def test_hd_fingerprint_validates_the_file(tmp_path):
    cfg = enhance_cfg(tmp_path)
    ws = make_yt_episode(cfg, "vid00000001")
    assert st.hd_fingerprint(ws.dir) is None  # nothing yet
    hd = st.hd_path(ws.dir)
    make_clip(hd, w=640, h=480, frames=FRAMES)
    doc = st.read(ws.dir)
    doc.update(state=st.DONE, source_hd_sha256=sha256_file(hd), source_hd_size=hd.stat().st_size,
               source_hd_mtime_ns=hd.stat().st_mtime_ns)
    st.write(ws.dir, doc)
    fp = st.hd_fingerprint(ws.dir)
    assert fp.sha256 == doc["source_hd_sha256"] and fp.path == hd.resolve()
    doc["source_hd_mtime_ns"] += 1  # record out of date -> hashed again, same bytes still match
    st.write(ws.dir, doc)
    assert st.hd_fingerprint(ws.dir).sha256 == doc["source_hd_sha256"]
    doc["source_hd_sha256"] = "0" * 64  # file differs from its record -> not used
    st.write(ws.dir, doc)
    assert st.hd_fingerprint(ws.dir) is None


# --- E6 / AC5: the render reads the HD source ---------------------------------------------------------------

def test_render_uses_the_hd_source_and_render_key_changes(tmp_path, _video_template):
    cfg = enhance_cfg(tmp_path)
    src = make_source(tmp_path / "src.mp4")
    ws = make_render_episode(cfg.workspace.dir, src)
    out = (cfg.render.output_dir / EID).resolve()
    run_render(EID, cfg)
    first = json.loads((out / "render_manifest.json").read_text(encoding="utf-8"))
    manifest = json.loads((ws.dir / "manifest.json").read_text(encoding="utf-8"))
    assert first["source_sha256"] == manifest["source"]["sha256"]
    keys = {s["clip_id"]: s["render_key"] for s in first["shorts"]}
    stage_hashes = {n: manifest["stages"][n]["config_hash"] for n in ("ingest", "titling")}
    # the same content in higher resolution = the HD source
    hd = st.hd_path(ws.dir)
    make_source(hd, size="1920x1080")
    doc = st.new_doc(EID)
    doc.update(wanted=True, state=st.DONE, source_hd_sha256=sha256_file(hd), source_hd_size=hd.stat().st_size,
               source_hd_mtime_ns=hd.stat().st_mtime_ns)
    st.write(ws.dir, doc)
    result = run_render(EID, cfg)
    assert result.ran and result.encoded == 2 and result.reused == 0
    second = json.loads((out / "render_manifest.json").read_text(encoding="utf-8"))
    assert second["source_sha256"] == doc["source_hd_sha256"] != first["source_sha256"]
    assert {s["clip_id"]: s["render_key"] for s in second["shorts"]}.keys() == keys.keys()
    assert all(s["render_key"] != keys[s["clip_id"]] for s in second["shorts"])
    after = json.loads((ws.dir / "manifest.json").read_text(encoding="utf-8"))
    assert after["stages"]["render"]["inputs"][-1]["path"] == "source_hd.mp4"
    assert {n: after["stages"][n]["config_hash"] for n in ("ingest", "titling")} == stage_hashes  # others unchanged
    assert all(after["stages"][n]["status"] == "done" for n in ("ingest", "transcript", "analysis", "selection", "titling"))
    assert not run_render(EID, cfg).ran  # up to date with the HD source
    hd.unlink()  # HD gone: back to the original source -> re-encoded from it
    third = run_render(EID, cfg)
    assert third.ran and json.loads((out / "render_manifest.json").read_text())["source_sha256"] == first["source_sha256"]


# --- AC6: W9 S5 / E5 ----------------------------------------------------------------------------------------

def _row(**kw):
    base = {"id": "v", "state": "done", "source_kind": "youtube", "source": 100, "complete": True,
            "complete_since": 1, "hd": 0, "enhance_pending": False, "links": {}, "source_links": {}}
    return {**base, **kw}


def test_auto_archive_skips_hd_and_pending_episodes():
    now = 10 ** 6
    assert [p["video_id"] for p in auto_archive_plan([_row()], now, 60)] == ["v"]
    assert auto_archive_plan([_row(hd=500)], now, 60) == []
    assert auto_archive_plan([_row(enhance_pending=True)], now, 60) == []
    # the khai thị part with an HD hard link is skipped, the Short part (no HD) is not
    rows = [_row(id="v", hd=0), _row(id="v.kt", hd=500)]
    assert [p["episodes"] for p in auto_archive_plan(rows, now, 60)] == [["v"]]


def test_storage_rows_report_hd_and_segment_sizes(tmp_path):
    cfg = enhance_cfg(tmp_path)
    ws = make_yt_episode(cfg, "vid00000001")
    rows = {r["id"]: r for r in episode_sizes(cfg)}
    assert rows["vid00000001"]["hd"] == 0 and rows["vid00000001"]["enhance_pending"] is True
    doc = st.read(ws.dir)
    seg_dir = st.segments_dir(ws.dir, doc["config_hash"])
    seg_dir.mkdir(parents=True)
    (seg_dir / "seg_00000.mp4").write_bytes(b"x" * 1000)
    make_clip(st.hd_path(ws.dir), w=320, h=240, frames=10)
    row = {r["id"]: r for r in episode_sizes(cfg)}["vid00000001"]
    assert row["enhance_tmp"] == 1000 and row["hd"] == st.hd_path(ws.dir).stat().st_size
