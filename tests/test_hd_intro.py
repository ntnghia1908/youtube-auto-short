"""HDI1: generated media and memory-only store tests; no network or sockets."""
import hashlib
import json
import subprocess
from dataclasses import replace
from fractions import Fraction

import pytest

from auto_short.config import Config, ConfigError, HDIntroConfig, RenderConfig, StoreConfig, WorkspaceConfig, from_dict
from auto_short.enhance import state as enh
from auto_short.render import full, hd_intro as hd
from auto_short.render.stage import RenderError, _run, probe_media
from auto_short.store.borrow import borrow_hd, released_hd_sha
from auto_short.store.client import StoreMismatch
from auto_short.workspace import atomic_write_json

VID, PID = "abcDEF12_-3", "PLtest"


@pytest.fixture
def config(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                 store=StoreConfig(enabled=True), hd_intro=HDIntroConfig((PID,)))
    d = cfg.workspace.dir / VID
    atomic_write_json(d / "manifest.json", {"source": {"kind": "youtube"}})
    atomic_write_json(cfg.workspace.dir / "_playlists" / f"{PID}.json",
                      {"playlist_id": PID, "entries": [{"video_id": VID}]})
    return cfg


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "thumb.ppm"
    path.write_bytes(b"P6\n320 180\n255\n" + bytes([255, 0, 0]) * 320 * 180)
    return path


def media(path, codec, size):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size={size}:rate=30000/1001", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000", "-t", "4", "-c:v", "libx264", "-profile:v", "high",
                    "-pix_fmt", "yuv420p", "-threads", "2", "-c:a", "libopus" if codec == "opus" else "aac",
                    "-ac", "2", "-video_track_timescale", "30000", str(path)], check=True, timeout=30)
    return path


@pytest.mark.parametrize("codec,size", [("aac", "160x90"), ("aac", "160x120"),
                                        ("opus", "160x90"), ("opus", "160x120")])
def test_stream_copy_timing_padding_and_offset_frames(tmp_path, image, codec, size):
    source = media(tmp_path / "source.mp4", codec, size)
    out = tmp_path / "stored.mp4"
    spec = hd.render(source, image, out)
    assert spec["frames"] == 90 and spec["offset"] == 3.003
    info = probe_media(out, _run)
    assert info["audio"]["codec_name"] == codec and info["video"]["profile"] == "High"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1",
                          "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    w, h = map(int, size.split("x"))
    center = raw[((h // 2) * w + w // 2) * 3:((h // 2) * w + w // 2) * 3 + 3]
    assert center[0] > 230 and max(center[1:]) < 15
    if h == 120:
        assert max(raw[:w * 3]) < 10
    src = enh.EffectiveSource(enh.SRC_HD, out, "a" * 64, offset=spec["offset"])
    # Full's input seek and CP7's copyts window both expose the original frame timeline.
    for start in (0, 0.7, 2.5):
        expected = hd.frame_hash(source, start, _run)
        cmd = ["ffmpeg", "-v", "error", *enh.hd_input_args(src, out, start=start), "-map", "0:v:0", "-frames:v", "1", "-f", "framemd5", "-"]
        assert _run(cmd).stdout.splitlines()[-1].split(",")[-1].strip() == expected
    base = ["ffmpeg", "-v", "error", "-ss", "0.5", "-t", "2", "-copyts", "-i", str(source),
            "-vf", "fps=30000/1001,select='between(n,30,44)',setpts=N/(30000/1001)/TB", "-an", "-f", "framemd5", "-"]
    adapted = [str(out) if x == str(source) else x for x in base]
    adapted = enh.hd_input_command(src, adapted, out)
    def hashes(command):
        proc = hd.checked(command, _run)
        return [x.split(",")[-1].strip() for x in proc.stdout.splitlines() if x and not x.startswith("#")]
    assert hashes(base) == hashes(adapted)


def test_invalid_inputs_and_failed_verification_remove_output(tmp_path, image):
    with pytest.raises(RenderError, match="thiếu HD"):
        hd.render(tmp_path / "missing", image, tmp_path / "out.mp4")
    with pytest.raises(RenderError, match="h264"):
        hd.intro_spec({"video": {"codec_name": "vp9"}, "audio": {"codec_name": "aac"}})
    with pytest.raises(RenderError, match="thời lượng"):
        hd.check_timing({"duration": 4}, {"duration": 9}, {"offset": 3, "fps": Fraction(30)}, {})
    with pytest.raises(RenderError, match="20 ms"):
        hd.check_timing({"duration": 4}, {"duration": 7}, {"offset": 3, "fps": Fraction(30)},
                        {"video": 3.021, "audio": 3})
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    out = tmp_path / "out.mp4"
    def runner(cmd):
        if cmd[0] == "ffprobe":
            info = {"streams": [{"codec_type": "video", "codec_name": "h264", "profile": "High", "width": 160,
                                 "height": 90, "pix_fmt": "yuv420p", "r_frame_rate": "30/1", "time_base": "1/30000"},
                                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2}],
                    "format": {"duration": 4}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(info), "")
        out.write_bytes(b"partial")
        return subprocess.CompletedProcess(cmd, 1, "", "synthetic failure")
    with pytest.raises(RenderError, match="synthetic failure"):
        hd.render(source, image, out, run=runner)
    assert not out.exists() and not list(tmp_path.glob(".hd-intro-*"))


class MemoryStore:
    def __init__(self, data, folder):
        self.data, self.folder, self.failure = data, folder, None
        self.replaced = 0

    def head(self, *args):
        return {"sha256": hashlib.sha256(self.data).hexdigest(), "size": len(self.data)}

    def index(self):
        return [{"video_id": VID, "kind": "hd", "series": PID, "file": "hd.mp4"}]

    def fetch(self, video_id, kind, dest, sha):
        assert sha == self.head()["sha256"]
        dest.write_bytes(self.data)
        return dest

    def replace(self, video_id, kind, series, name, path, sha, *, current_sha256):
        doc = hd.read(self.folder)
        assert doc["status"] == "pending" and doc["stored"]["sha256"] == sha
        assert current_sha256 == self.head()["sha256"]
        if self.failure == "before":
            raise StoreMismatch("upload failed")
        self.data = path.read_bytes()
        self.replaced += 1
        if self.failure == "after":
            raise StoreMismatch("response lost")


def seed(config, data=b"original"):
    d = config.workspace.dir / VID
    doc = enh.new_doc(VID)
    doc.update(state=enh.DONE, released=True, source_hd_sha256=hashlib.sha256(data).hexdigest(), source_hd_size=len(data))
    enh.write(d, doc)
    atomic_write_json(d / "backup.json", {"schema_version": 1, "released": {"hd": {"sha256": doc["source_hd_sha256"], "size": len(data)}}})
    return d, MemoryStore(data, d)


@pytest.mark.parametrize("failure", [None, "before", "after"])
def test_pending_recovery_identity_borrow_and_current(config, image, monkeypatch, failure):
    d, client = seed(config)
    original = client.head()
    monkeypatch.setattr(hd, "thumbnail", lambda *a, **k: image)
    def render(source, thumb, output, **kw):
        output.write_bytes(b"intro" + source.read_bytes())
        return {"frames": 90, "fps": Fraction(30000, 1001), "offset": 3.003}
    monkeypatch.setattr(hd, "render", render)
    client.failure = failure
    if failure:
        with pytest.raises(StoreMismatch):
            hd.run_intro(VID, config, client=client, keep_original=True)
        assert hd.read(d)["status"] == "pending"
        assert not (d / "source_hd.mp4").exists()
    client.failure = None
    doc = hd.run_intro(VID, config, client=client, keep_original=True)
    assert doc["status"] == "done" and doc["original"] == original and client.replaced == 1
    assert json.loads((d / "backup.json").read_text())["released"]["hd"] == doc["stored"]
    sample = config.render.output_dir / "_samples" / "hdi1-original" / f"{VID}.mp4"
    assert sample.read_bytes() == b"original"
    assert released_hd_sha(config, VID, d) == client.head()["sha256"]
    with borrow_hd(config, VID, client=client):
        src = enh.effective_source(config, VID)
        assert src.sha256 == original["sha256"] and src.stored_sha256 == client.head()["sha256"]
        assert src.offset == 3.003
    assert not (d / "source_hd.mp4").exists()
    vdir = full.vertical_dir(config, VID)
    vdir.mkdir(parents=True)
    full.vertical_path(config, VID).write_bytes(b"vertical")
    atomic_write_json(vdir / full.META_NAME, {"size": 8, "plan_version": full.FULL_PLAN_VERSION,
                                            "hd_sha256": original["sha256"]})
    assert full.current(config, VID)
    image.write_bytes(b"changed thumbnail")
    assert hd.view(config, VID)["stale"]


def test_config_and_zero_offset_preserve_commands(tmp_path):
    assert from_dict({}).hd_intro.playlists == ()
    assert from_dict({"hd_intro": {"playlists": [PID]}}).hd_intro.playlists == (PID,)
    with pytest.raises(ConfigError):
        from_dict({"hd_intro": {"playlists": "PLtest"}})
    source = enh.EffectiveSource(enh.SRC_HD, tmp_path, "a" * 64)
    assert source.stored_sha256 == source.sha256 and source.offset == 0
    assert enh.hd_input_args(source, tmp_path) == ["-i", str(tmp_path)]
    command = ["ffmpeg", "-ss", "2", "-i", str(tmp_path)]
    assert enh.hd_input_command(source, command, tmp_path) == command


@pytest.mark.parametrize("codec", ["aac", "opus"])
def test_real_job_rebuild_replaces_intro_without_stacking(config, image, tmp_path, monkeypatch, codec):
    source = media(tmp_path / "source.mp4", codec, "160x120")
    d, client = seed(config, source.read_bytes())
    monkeypatch.setattr(hd, "thumbnail", lambda *a, **kw: image)
    first = hd.run_intro(VID, config, client=client, keep_original=True)
    image.write_bytes(b"P6\n320 180\n255\n" + bytes([0, 0, 255]) * 320 * 180)
    second = hd.run_intro(VID, config, client=client)
    assert second["original"] == first["original"] and second["stored"] != first["stored"]
    assert client.replaced == 2 and second["offset_seconds"] == 3.003
    image.write_bytes(b"P6\n320 180\n255\n" + bytes([0, 255, 0]) * 320 * 180)
    third = hd.run_intro(VID, config, client=client)
    assert third["original"] == first["original"] and client.replaced == 3
    stored = tmp_path / "final.mp4"
    stored.write_bytes(client.data)
    assert probe_media(stored, _run)["duration"] == pytest.approx(7.007, abs=0.034)
    assert not (d / "source_hd.mp4").exists()


@pytest.mark.parametrize("kind", ["vertical", "pipeline", "render", "add"])
def test_route_gates_and_render_lane_without_sockets(config, image, monkeypatch, kind):
    from auto_short.web.app import create_app
    from auto_short.web.jobs import KIND_HD_INTRO, HDIntroTarget, RENDER
    from test_store_download import request

    d, _ = seed(config)
    monkeypatch.setattr(hd, "thumbnail", lambda *a, **kw: image)
    app = create_app(config, "pw", preflight=None, post_preflight=None)
    def post(eid=VID):
        return request(app, "POST", f"/api/episodes/{eid}/hd-intro", transport="direct")
    assert post("zyxWVUT9876").status_code == 404
    disabled = create_app(replace(config, hd_intro=HDIntroConfig()), "pw", preflight=None, post_preflight=None)
    assert request(disabled, "POST", f"/api/episodes/{VID}/hd-intro", transport="direct").status_code == 404
    (d / "source_hd.mp4").write_bytes(b"local")
    assert post().status_code == 409
    (d / "source_hd.mp4").unlink()
    job, _ = app.state.runner.submit(VID + ".kt", kind, lambda job: None)
    assert post().status_code == 409
    job.status = "done"
    result = post()
    assert result.status_code == 202 and result.json()["job"]["kind"] == KIND_HD_INTRO
    assert post().status_code == 200
    intro_job = next(j for j in app.state.runner.jobs() if j.kind == KIND_HD_INTRO)
    assert intro_job.steps[0].lane == RENDER and isinstance(intro_job.target, HDIntroTarget)


def test_owner_record_survives_short_workspace_deletion(config, image, monkeypatch):
    import shutil
    d, client = seed(config)
    kid = d.parent / (VID + ".kt")
    atomic_write_json(kid / "manifest.json", {"source": {"kind": "youtube"}})
    enh.mirror(config, VID)
    monkeypatch.setattr(hd, "thumbnail", lambda *a, **kw: image)
    def render(source, thumb, output, **kw):
        output.write_bytes(b"intro" + source.read_bytes())
        return {"frames": 90, "fps": Fraction(30000, 1001), "offset": 3.003}
    monkeypatch.setattr(hd, "render", render)
    doc = hd.run_intro(VID, config, client=client)
    assert hd.read(kid) == doc
    shutil.rmtree(d)
    assert enh.owner_for(config, VID) == VID + ".kt"
    with borrow_hd(config, VID + ".kt", client=client):
        src = enh.effective_source(config, VID + ".kt")
        assert src.offset == 3.003 and src.sha256 == doc["original"]["sha256"]
        assert src.stored_sha256 == doc["stored"]["sha256"]


def test_fetch_failure_cleans_private_partial(config, image, monkeypatch):
    from auto_short.render.stage import StoreWait
    from auto_short.store.client import StoreUnavailable
    d, client = seed(config)
    monkeypatch.setattr(hd, "thumbnail", lambda *a, **kw: image)
    paths = []
    def interrupted(video_id, kind, dest, sha):
        part = dest.with_name(dest.name + ".part")
        part.write_bytes(b"partial")
        paths.append(part)
        raise StoreUnavailable("interrupted")
    monkeypatch.setattr(client, "fetch", interrupted)
    with pytest.raises(StoreWait, match="interrupted"):
        hd.run_intro(VID, config, client=client)
    assert paths and not paths[0].parent.exists()
    assert not (d / "source_hd.mp4").exists() and hd.read(d) is None and client.replaced == 0
