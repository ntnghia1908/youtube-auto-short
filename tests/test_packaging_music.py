"""AUD1 acceptance checks on short synthetic media, with no external service."""
import json
import math
import shutil
import wave
from array import array
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short.hashing import config_hash, sha256_file
from auto_short.packaging import PackageError, assets, music, record, variant, visual
from auto_short.render.stage import RenderError, _run, probe_media
from auto_short.theme_render import audio
from auto_short.workspace import atomic_write_json

from test_packaging_visual import Media, SPEC as VISUAL


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    root = tmp_path_factory.mktemp("music-real")
    tc3, track = root / "abcdefgh-r1.mp4", root / "music.wav"
    commands = [
        ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=5:d=24.137", "-f", "lavfi", "-i",
         "aevalsrc=0.28*(0.55+0.3*sin(2*PI*0.73*t)+0.15*sin(2*PI*1.31*t))*sin(2*PI*630*t):s=48000:d=24.137",
         "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2", "-c:a", "aac", "-ac", "2",
         "-b:a", "192k", str(tc3)],
        ["-f", "lavfi", "-i", "aevalsrc=0.2*(0.5+0.45*sin(2*PI*2*t))*sin(2*PI*220*t):s=44100:d=8", "-c:a", "pcm_s16le", str(track)],
    ]
    for args in commands:
        proc = _run(["ffmpeg", "-v", "error", "-y", *args])
        assert proc.returncode == 0, proc.stderr
    return tc3, track


@pytest.fixture
def media(tmp_path, synthetic):
    tc3, track = synthetic
    asset_dir = tmp_path / "assets"
    entry = assets.add(asset_dir, track, kind="music", source="synthetic sine", license="CC0")
    assets.approve(asset_dir, entry["id"])
    meta = dict(sha256=sha256_file(tc3), plan_id="abcdefgh", revision=1, plan_fingerprint="f" * 64,
                chapters=[dict(start=0, title="Synthetic")], description="Synthetic TC3")
    spec = dict(visual=None, music=dict(asset_id=entry["id"], level_lu=-20, fade_in=0, fade_out=0, loop_crossfade=1))
    return SimpleNamespace(tc3=tc3, track=track, assets=asset_dir, folder=tmp_path / "pkg", meta=meta, spec=spec)


def build(s, **kwargs):
    return music.build(s.folder, s.tc3, s.meta, kwargs.pop("spec", s.spec), s.assets, **kwargs)


def test_voice_only_legacy_keys_music_controls_and_strict_spec(media):
    s = media
    legacy = variant.normalize(VISUAL)
    expected = config_hash(dict(spec=legacy, asset=legacy["visual"]["asset_id"],
                                tc3_sha256=s.meta["sha256"], **variant.encoding()))
    assert variant.normalize({**VISUAL, "music": None}) == legacy
    assert variant.key({**VISUAL, "music": None}, s.meta["sha256"]) == expected
    with pytest.raises(PackageError):
        variant.normalize(dict(visual=None, music=None))
    base = variant.key(s.spec, s.meta["sha256"])
    for changes in (dict(asset_id="a" * 64), dict(level_lu=-20.5), dict(fade_in=1), dict(fade_out=2), dict(loop_crossfade=2)):
        assert variant.key(dict(visual=None, music=s.spec["music"] | changes), s.meta["sha256"]) != base
    assert variant.key(s.spec | dict(visual=legacy["visual"]), s.meta["sha256"]) != base
    assert variant.key(s.spec, "b" * 64) != base
    assert variant.key(s.spec, s.meta["sha256"], settings=music.encoding("128k")) != base
    assert variant.key(s.spec, s.meta["sha256"], settings=dict(music_version=2, audio_bitrate="192k")) != base
    for invalid in (dict(level_lu=0), dict(level_lu=-20.1), dict(fade_in=True), dict(fade_out=float("nan")),
                    dict(loop_crossfade=0), dict(asset_id="../escape"), dict(extra=1)):
        with pytest.raises(PackageError):
            variant.normalize(dict(visual=None, music=s.spec["music"] | invalid))


def test_real_mix_loudness_voice_video_and_cache(media, monkeypatch):
    s, calls = media, []
    def run(args):
        calls.append(args)
        return _run(args)
    doc = build(s, run=run)
    path = s.folder / f"variant-{doc['key'][:12]}.mp4"
    assert variant.validate(doc) == doc and "loop_key" not in doc
    assert doc["chapters"] == s.meta["chapters"] and doc["description"] == s.meta["description"]
    info = probe_media(path, _run)
    assert (info["audio"]["channels"], info["audio"]["sample_rate"], info["audio"]["codec_name"]) == (2, "48000", "aac")
    assert abs(float(info["audio"]["duration"]) - float(probe_media(s.tc3, _run)["audio"]["duration"])) <= music.AAC_FRAME
    assert music.video_hash(path, _run) == music.video_hash(s.tc3, _run)
    assert doc["music"]["true_peak"] <= max(-1, doc["music"]["true_peak_tc3"] + .5)
    assert doc["music"]["corr"] >= audio.MIN_CORRELATION and abs(doc["music"]["lag"]) <= audio.MAX_LAG
    assert len([c for c in calls if "aac" in c and "-c:a" in c]) == 1
    assert build(s, run=lambda _: pytest.fail("cache ran ffmpeg")) == doc
    # Measure the music contribution independently, through the exact production loop/gain filters.
    unit, bed = s.folder / "test-unit.wav", s.folder / "test-bed.wav"
    music.loop_unit(s.track, unit, 1, _run)
    duration = float(probe_media(s.tc3, _run)["audio"]["duration"])
    proc = _run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", str(unit), "-af",
                 music.music_filter(doc["spec"]["music"], doc["music"]["gain_db"], duration), "-c:a", "pcm_f32le", str(bed)])
    assert proc.returncode == 0, proc.stderr
    measured, _ = music.measure(bed, _run)
    assert abs(measured - (doc["music"]["voice_lufs"] - 20)) <= 1
    assert sha256_file(s.tc3) == s.meta["sha256"]
    plan = dict(plan_id="abcdefgh", revision=1)
    monkeypatch.setattr(record, "fingerprint", lambda _: "f" * 64)
    assert variant.status(s.folder, doc, plan, s.meta, asset_dir=s.assets) == "draft"
    assert variant.status(s.folder, doc, plan, s.meta | dict(sha256="b" * 64), asset_dir=s.assets) == "stale"
    library = json.loads((s.assets / "library.json").read_text())
    library["assets"][0]["approved"] = False
    atomic_write_json(s.assets / "library.json", library)
    assert variant.status(s.folder, doc, plan, s.meta, asset_dir=s.assets) == "stale"
    for mutate in (lambda d: d["music"].update(corr=.2), lambda d: d["music"].update(true_peak=10),
                   lambda d: d["checks"].update(duration_diff=.1), lambda d: d["video_source"].update(key="a" * 64)):
        damaged = deepcopy(doc)
        mutate(damaged)
        with pytest.raises(PackageError):
            variant.validate(damaged)


def test_loop_seams_have_continuous_twenty_ms_rms(media):
    s = media
    unit, repeated = s.folder / "unit.wav", s.folder / "repeat.wav"
    s.folder.mkdir()
    sine = s.folder / "sine.wav"
    proc = _run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                 "sine=frequency=220:sample_rate=44100:duration=8", str(sine)])
    assert proc.returncode == 0, proc.stderr
    music.loop_unit(sine, unit, 1, _run)
    proc = _run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "2", "-i", str(unit),
                 "-c:a", "pcm_s16le", str(repeated)])
    assert proc.returncode == 0, proc.stderr
    assert abs(probe_media(unit, _run)["duration"] - 7) < 1 / 48000
    with wave.open(str(repeated), "rb") as pcm:
        for seam in (6, 7, 13, 14):  # start of crossfade and wrap, twice
            pcm.setpos(round((seam - .02) * 48000))
            left = array("h", pcm.readframes(960))
            right = array("h", pcm.readframes(960))
            rms = lambda samples: math.sqrt(sum(x * x for x in samples) / len(samples))
            assert .8 <= rms(left) / rms(right) <= 1.25


@pytest.mark.parametrize("damage", ["loud_music", "reversed_voice", "wrong_video", "duration", "peak"])
def test_bad_mix_rejected(media, damage):
    s = media
    def run(args):
        if "-filter_complex" in args and "[voice][music]amix=" in args[args.index("-filter_complex") + 1]:
            args = list(args)
            pos = args.index("-filter_complex") + 1
            if damage == "loud_music":
                # Bypass the public -30..-12 gate to exercise the post-mix validator at +0 LU.
                args[pos] = args[pos].replace("[1:a]volume=", "[1:a]volume=10,volume=")
            if damage == "reversed_voice":
                args[pos] = args[pos].replace("[0:a]aformat", "[0:a]areverse,aformat")
        proc = _run(args)
        if damage == "wrong_video" and "streamhash" in args and "variant-" in args[args.index("-i") + 1]:
            proc.stdout = "0,v,SHA256=" + "a" * 64
        if damage == "duration" and args[0] == "ffprobe" and "variant-" in args[-1]:
            data = json.loads(proc.stdout)
            next(a for a in data["streams"] if a["codec_type"] == "audio")["duration"] = "25"
            proc.stdout = json.dumps(data)
        if damage == "peak" and "ebur128=peak=true" in args and "variant-" in args[args.index("-i") + 1]:
            proc.stderr = "Summary:\n I: -15 LUFS\n Peak: 2 dBFS"
        return proc
    error = RenderError if damage in ("loud_music", "reversed_voice") else (PackageError, RenderError)
    match = "không xác minh được phần lời" if damage in ("loud_music", "reversed_voice") else None
    with pytest.raises(error, match=match):
        build(s, run=run)
    assert not list(s.folder.iterdir()) and sha256_file(s.tc3) == s.meta["sha256"]


@pytest.mark.parametrize("long_source", [False, True])
def test_preview_three_positions_fades_and_replacement(media, long_source):
    s = media
    s.spec["music"].update(fade_in=3, fade_out=5)
    if long_source:
        longer = s.folder.parent / s.tc3.name
        proc = _run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "2", "-i", str(s.tc3),
                     "-t", "64.137", "-c", "copy", str(longer)])
        assert proc.returncode == 0, proc.stderr
        s.tc3 = longer
        s.meta["sha256"] = sha256_file(longer)
    doc = build(s, preview=True)
    assert len(doc["previews"]) == 3 and not list(s.folder.glob("variant-*"))
    duration = float(probe_media(s.tc3, _run)["audio"]["duration"])
    seconds = min(30, duration)
    assert [p["start"] for p in doc["previews"]] == [0, (duration - seconds) / 2, duration - seconds]
    for p in doc["previews"]:
        path = s.folder / p["file"]
        assert path.suffix == ".m4a" and abs(float(probe_media(path, _run)["audio"]["duration"]) - min(30, duration)) <= music.AAC_FRAME
    # Positions and fades for a long source use the same absolute time music graph.
    assert "atrim=start=45.000000000:end=75.000000000" in music.music_filter(s.spec["music"], -10, 120, start=45, seconds=30)
    assert "afade=t=out:st=115.000000000:d=5" in music.music_filter(s.spec["music"], -10, 120)
    s.spec["music"]["level_lu"] = -22
    new = build(s, preview=True)
    assert {p.name for p in s.folder.iterdir()} == {p["file"] for p in new["previews"]}


@pytest.mark.parametrize("failure", [RenderError("failed"), KeyboardInterrupt()])
@pytest.mark.parametrize("stage", ["loop", "mix", "publish"])
def test_failure_and_interrupt_cleanup_preserve_sources(media, failure, stage, monkeypatch):
    s = media
    ambient = visual.build(s.folder, s.tc3, s.meta, VISUAL, s.assets, run=Media())
    if stage == "publish":
        build(s, preview=True)
    before = {p.name: sha256_file(p) for p in s.folder.iterdir()}
    original = music.os.replace
    fired = False
    def replace(src, dest):
        nonlocal fired
        original(src, dest)
        if stage == "publish" and Path(dest).parent == s.folder and not fired:
            fired = True
            raise failure
    monkeypatch.setattr(music.os, "replace", replace)
    def run(args):
        if (stage == "loop" and args[-1].endswith("unit.wav")) or (stage == "mix" and "-c:a" in args and "aac" in args):
            Path(args[-1]).write_bytes(b"partial")
            raise failure
        return _run(args)
    with pytest.raises(type(failure)):
        build(s, run=run, preview=stage == "publish")
    assert before == {p.name: sha256_file(p) for p in s.folder.iterdir()}
    assert sha256_file(s.tc3) == s.meta["sha256"] and variant.reusable(s.folder, ambient)


def test_ambient_dependency_disk_and_asset_gates(media, monkeypatch):
    s = media
    spec = s.spec | dict(visual=variant.normalize(VISUAL)["visual"])
    with pytest.raises(PackageError, match="hãy dựng hình ambient trước"):
        build(s, spec=spec, run=lambda _: pytest.fail("missing ambient encoded"))
    monkeypatch.setattr(music.shutil, "disk_usage", lambda _: SimpleNamespace(free=3 * 1024 ** 3 - 1))
    with pytest.raises(PackageError, match="3 GB"):
        build(s, run=lambda _: pytest.fail("disk guard too late"))
    monkeypatch.undo()
    for change, message in ((dict(approved=False), "approved"), (dict(duration=2), "Nhạc cần dài")):
        library = json.loads((s.assets / "library.json").read_text())
        library["assets"][0].update(change)
        atomic_write_json(s.assets / "library.json", library)
        with pytest.raises(PackageError, match=message):
            build(s, run=lambda _: pytest.fail("asset gate too late"))
        library["assets"][0].update(approved=True, duration=8)
        atomic_write_json(s.assets / "library.json", library)


def test_ambient_video_copy_stale_delete_isolation(media, monkeypatch):
    s = media
    ambient = visual.build(s.folder, s.tc3, s.meta, VISUAL, s.assets, run=Media())
    # Use actual video packets as the ambient artifact; no dependency on expensive VIS1 rendering here.
    origin = s.folder / f"variant-{ambient['key'][:12]}.mp4"
    shutil.copyfile(s.tc3, origin)
    ambient.update(sha256=sha256_file(origin), size=origin.stat().st_size)
    variant.write(s.folder, ambient)
    spec = s.spec | dict(visual=ambient["spec"]["visual"])
    doc = build(s, spec=spec)
    assert doc["video_source"] == dict(key=ambient["key"], sha256=ambient["sha256"])
    output = s.folder / f"variant-{doc['key'][:12]}.mp4"
    assert music.video_hash(output, _run) == music.video_hash(origin, _run)
    monkeypatch.setattr(record, "fingerprint", lambda _: "f" * 64)
    plan = dict(plan_id="abcdefgh", revision=1)
    assert variant.status(s.folder, doc, plan, s.meta, asset_dir=s.assets) == "draft"
    assert build(s, spec=spec, run=lambda _: pytest.fail("ambient cache ran encode")) == doc
    origin.write_bytes(b"changed source")
    assert variant.status(s.folder, doc, plan, s.meta, asset_dir=s.assets) == "stale"
    origin.unlink()
    assert variant.status(s.folder, doc, plan, s.meta, asset_dir=s.assets) == "stale"
    before = {p.name: p.read_bytes() for p in s.folder.iterdir() if not p.name.startswith("variant-" + doc["key"][:12])}
    variant.delete(s.folder, doc)
    assert before == {p.name: p.read_bytes() for p in s.folder.iterdir()}


def test_compressed_music_padding_and_silence_gate(media):
    s = media
    compressed, unit = s.folder.parent / "music.mp3", s.folder.parent / "unit.wav"
    proc = _run(["ffmpeg", "-v", "error", "-y", "-i", str(s.track), "-c:a", "libmp3lame", str(compressed)])
    assert proc.returncode == 0, proc.stderr
    music.loop_unit(compressed, unit, 1, _run)
    assert abs(probe_media(unit, _run)["duration"] - 7) < 1 / 48000
    quiet = s.folder.parent / "quiet.wav"
    proc = _run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                 "-t", "8", str(quiet)])
    assert proc.returncode == 0, proc.stderr
    entry = assets.add(s.assets, quiet, kind="music", source="synthetic silence", license="CC0")
    assets.approve(s.assets, entry["id"])
    spec = deepcopy(s.spec)
    spec["music"]["asset_id"] = entry["id"]
    with pytest.raises(PackageError, match="im lặng|không đo được"):
        build(s, spec=spec)
    assert not list(s.folder.iterdir())


def test_true_peak_margin_for_hot_tc3(media):
    s = media
    hot = s.folder.parent / s.tc3.name
    proc = _run(["ffmpeg", "-v", "error", "-y", "-i", str(s.tc3), "-map", "0:v:0", "-map", "0:a:0",
                 "-c:v", "copy", "-af", "volume=4.8", "-c:a", "aac", "-b:a", "192k", str(hot)])
    assert proc.returncode == 0, proc.stderr
    s.tc3 = hot
    s.meta["sha256"] = sha256_file(hot)
    s.spec["music"]["level_lu"] = -30
    _, peak = music.measure(hot, _run)
    assert peak > -1, "fixture must exercise TC3's relative peak margin"
    doc = build(s)
    assert doc["music"]["true_peak_tc3"] == peak
    assert doc["music"]["true_peak_limit"] == peak + .5
    assert doc["music"]["true_peak"] <= peak + .5
    assert sha256_file(hot) == s.meta["sha256"]
