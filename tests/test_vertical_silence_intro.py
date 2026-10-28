"""VERT2: streaming silence cuts, PKG2 intro and store revisions; no sockets."""
import array
import hashlib
import json
import subprocess
from fractions import Fraction

import pytest

from auto_short.packaging import PackageError, episode
from auto_short.render import full, plan
from auto_short.render.stage import RenderError, probe_media
from auto_short.review import backup
from auto_short.review.cuts import kept_segments_ms
from auto_short.store import offload
from auto_short.workspace import atomic_write_json
from auto_short.web.app import create_app

from test_store_download import request as call_route
from test_store_offload import MemoryStore, ocfg, seed  # noqa: F401
from test_store_server import DATA, PLAYLIST, VIDEO, archive, request, store  # noqa: F401
from test_store_shorts_edit import memory_store  # noqa: F401
from test_web_vertical_cp832 import VID, make_ep, seed_playlist_for, tcfg, write_hd  # noqa: F401
from test_vertical_header_fallback import media_runner  # noqa: F401


@pytest.mark.parametrize("fps", [Fraction(25), Fraction(30000, 1001)])
def test_segments_share_rounded_boundaries_and_stream(fps, tcfg, tmp_path):
    silences = [(0, 1.23), (2, 2.2), (3.01, 5.22), (8.07, 10)]
    expected = plan.frame_plan(kept_segments_ms(0, 10, silences, 0.5), fps)
    frames = full.content_frames(10, silences, 0.5, fps)
    assert frames == expected
    graph = full.filter_graph(frames=frames, fps=fps,
                              lay=full.full_layout(plan.geometry(tcfg.render), 320, 180),
                              font_file=tmp_path / "font.ttf", top_lines=[], top_size=32,
                              bottom_lines=[], bottom_size=32, intro=True)
    selection = "+".join(f"between(n,{a},{a + n - 1})" for a, n in expected)
    assert graph.count(f"select='{selection}'") == 2
    assert "asetnsamples=" in graph and "asetpts=N/SR/TB" in graph
    assert "split" not in graph and graph.count("concat=") == 1 and "concat=n=2" in graph
    # Hundreds of cuts still use a constant number of stream branches.
    many = full.content_frames(3600, [(i, i + 2) for i in range(1, 3598, 5)], 0.5, fps)
    assert len(many) > 600 and sum(n for _, n in many) > 0


@pytest.mark.parametrize("fps,broken", [("25", False), ("30000/1001", False), ("25", True)])
def test_real_render_intro_silence_sync_and_fallback(tcfg, monkeypatch, caplog, fps, broken):
    d = make_ep(tcfg, height=480, duration=4)
    source = d / "source_hd.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc=size=320x180:rate={fps}:duration=4", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=4", "-af",
                    "volume=enable='between(t,0.8,2.8)':volume=0", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", str(source)], check=True, timeout=30)
    write_hd(tcfg, VID, source.read_bytes())
    silences = {"silences": [{"start": 0.8, "end": 2.8}]}
    atomic_write_json(d / "silences.json", silences)
    atomic_write_json(d / "candidates.json", {"params": {"max_pause": 0.4},
                                             "silences_sha256": full._sha(silences)})
    seed_playlist_for(tcfg, VID)
    if broken:
        def fail(*args, **kwargs):
            raise PackageError("synthetic thumbnail failure")
        monkeypatch.setattr(episode, "build_episode", fail)
    result = full.run_vertical(VID, tcfg)
    meta = full.read_meta(tcfg, VID)
    source_info = probe_media(source, full._run)
    duration = float(source_info["video"]["duration"])
    rate = Fraction(fps)
    content = float(Fraction(sum(n for _, n in full.content_frames(duration, [(0.8, 2.8)], 0.4, rate))) / rate)
    expected = content + (0 if broken else 3)
    info = probe_media(result.path, full._run)
    vd, ad = (float(info[k]["duration"]) for k in ("video", "audio"))
    assert abs(vd - expected) <= 1 / float(rate)
    assert abs(ad - vd) <= 1 / float(rate)
    assert meta["plan_version"] == full.FULL_PLAN_VERSION
    assert meta["trimmed_seconds"] == pytest.approx(duration - content)
    if broken:
        assert meta["intro"] is None and "tiếp tục không intro" in caplog.text
    else:
        image = full.intro_image(tcfg, VID)
        assert meta["intro"] == {"sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "seconds": 3}
        pixels = []
        for path, seek in ((image, None), (result.path, "0"), (result.path, "2.8")):
            pixels.append(subprocess.run(["ffmpeg", "-v", "error", *(["-ss", seek] if seek else []), "-i", str(path),
                                          "-frames:v", "1", "-vf", "scale=16:16", "-pix_fmt", "rgb24",
                                          "-f", "rawvideo", "pipe:1"], capture_output=True, check=True,
                                         timeout=20).stdout)
        assert len(pixels[0]) == 16 * 16 * 3
        for got in pixels[1:]:
            assert len(got) == len(pixels[0])
            assert sum(abs(a - b) for a, b in zip(pixels[0], got)) / len(got) < 8
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(result.path), "-t", "2.98",
                              "-f", "f32le", "-ac", "1", "pipe:1"], capture_output=True, check=True,
                             timeout=20).stdout
        samples = array.array("f", pcm)
        assert max(abs(x) for x in samples) < 0.001
    assert not full.run_vertical(VID, tcfg).ran


@pytest.mark.parametrize("bad", ["candidates", "silences", "sha", "max_pause"])
def test_analysis_inputs_required(tcfg, monkeypatch, bad):
    d = make_ep(tcfg, height=480)
    write_hd(tcfg, VID)
    monkeypatch.setattr(full, "probe_media", lambda *a: {
        "duration": 4, "video": {"duration": 4, "width": 320, "height": 180,
                                 "avg_frame_rate": "25/1", "r_frame_rate": "25/1"}, "audio": {}})
    if bad in ("candidates", "silences"):
        (d / f"{bad}.json").unlink()
    else:
        doc = json.loads((d / "candidates.json").read_text())
        doc["silences_sha256"] = "bad" if bad == "sha" else doc["silences_sha256"]
        if bad == "max_pause":
            doc["params"] = {}
        atomic_write_json(d / "candidates.json", doc)
    with pytest.raises(RenderError, match="candidates.json|silences.json|max_pause"):
        full.run_vertical(VID, tcfg)


def test_key_tracks_silences_pause_intro_bytes_and_length(tcfg, monkeypatch, tmp_path, media_runner):
    d = make_ep(tcfg, height=480)
    write_hd(tcfg, VID)
    run, encodes = media_runner
    image = tmp_path / "intro.jpg"
    image.write_bytes(b"first-image")
    monkeypatch.setattr(full, "intro_image", lambda *a: image)
    # The runner writes fake media; real verification is exercised by the ffmpeg test above.
    monkeypatch.setattr(full, "verify", lambda path, fps, seconds, run: {"duration": seconds, "frames": 125})
    keys = []
    for change in ("initial", "max_pause", "silences", "image", "seconds"):
        doc = json.loads((d / "candidates.json").read_text())
        if change == "max_pause":
            doc["params"]["max_pause"] = 0.5
        elif change == "silences":
            silences = {"silences": [{"start": 10, "end": 11}]}
            atomic_write_json(d / "silences.json", silences)
            doc["silences_sha256"] = full._sha(silences)
        elif change == "image":
            image.write_bytes(b"second-image")
        elif change == "seconds":
            monkeypatch.setattr(full, "INTRO_SECONDS", 4)
        atomic_write_json(d / "candidates.json", doc)
        assert full.run_vertical(VID, tcfg, run=run).ran
        keys.append(full.read_meta(tcfg, VID)["key"])
        assert not full.run_vertical(VID, tcfg, run=run).ran
    assert len(set(keys)) == len(encodes) == 5


@pytest.mark.parametrize("released", [False, True])
def test_old_plan_skipped_by_offload_and_requeued(ocfg, monkeypatch, released):
    d, path = seed(ocfg)
    client = MemoryStore()
    if released:
        offload.push_vertical(ocfg, d.name, client=client)
        assert not path.exists()
        app = create_app(ocfg, "pw", preflight=None, post_preflight=None)
        response = call_route(app, "POST", f"/api/episodes/{d.name}/vertical", transport="direct")
        assert response.status_code == 200 and response.json()["job"] is None
    meta = full.read_meta(ocfg, d.name)
    meta.pop("plan_version")
    atomic_write_json(path.parent / full.META_NAME, meta)
    assert not full.current(ocfg, d.name)
    assert offload.candidates(ocfg, errors={}) == []
    assert not offload.push_vertical(ocfg, d.name, client=client)["pushed"]
    assert path.exists() is (not released)
    assert not client.uploads or released
    monkeypatch.setattr(full, "_run_vertical", lambda *a, **kw: pytest.fail("route must only queue"))
    app = create_app(ocfg, "pw", preflight=None, post_preflight=None)
    response = call_route(app, "POST", f"/api/episodes/{d.name}/vertical", transport="direct")
    assert response.status_code == 202 and response.json()["job"]["kind"] == "vertical"


@pytest.mark.parametrize("kind", ["vertical", "hd"])
def test_store_revision_roundtrip(memory_store, tmp_path, kind):
    service, client = memory_store.service, memory_store.client
    name = f"[{kind}] Tập 1.mp4"
    path = tmp_path / "upload.mp4"
    path.write_bytes(DATA)
    first_sha = hashlib.sha256(DATA).hexdigest()
    client.put(VIDEO, kind, PLAYLIST, name, path, first_sha)
    path.write_bytes(b"new-version")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if kind == "hd":
        from auto_short.store.client import StoreMismatch
        with pytest.raises(StoreMismatch):
            client.put(VIDEO, kind, PLAYLIST, name, path, sha)
        from urllib.parse import urlencode
        assert request(service, "PUT", f"/files/{VIDEO}/hd?" + urlencode(dict(series=PLAYLIST, name=name)),
                       {"Content-Length": str(path.stat().st_size), "X-Sha256": sha}, path.read_bytes())[0] == 409
        return
    client.put(VIDEO, kind, PLAYLIST, name, path, sha)
    row, stored = service.lookup(VIDEO, kind)
    assert row["file"] == name[:-4] + " (r2).mp4"
    assert stored.read_bytes() == path.read_bytes() and (stored.parent / name).read_bytes() == DATA
    assert client.head(VIDEO, kind) == {"sha256": sha, "size": path.stat().st_size}
    sums = (stored.parent / "SHA256SUMS.txt").read_text(encoding="utf-8-sig")
    assert f"{first_sha}  {name}" in sums and f"{sha}  {stored.name}" in sums
    assert ("PUT", f"/files/{VIDEO}/vertical") in memory_store.calls
    client.put(VIDEO, kind, PLAYLIST, name, path, sha)
    assert len(list(stored.parent.glob("*.mp4"))) == 2
    restarted = store.Store(service.config)
    assert restarted.lookup(VIDEO, kind)[0]["file"] == row["file"]
