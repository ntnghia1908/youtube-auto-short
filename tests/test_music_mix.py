"""AUD2 AC1–7, short synthetic local media only; runners inject failures without sockets."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short.config import ConfigError, MusicConfig, from_dict
from auto_short.hashing import sha256_file
from auto_short.packaging import PackageError, assets, music
from auto_short.render.stage import RenderError, _run, probe_media
from auto_short.theme_render import audio
from auto_short.workspace import atomic_write_json


from render_helpers import ffmpeg


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp("music")
    source, track = root / "source.mp4", root / "track.wav"
    metadata = root / "chapters.txt"
    metadata.write_text(";FFMETADATA1\ntitle=Original title\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=8000\ntitle=Chapter one\n")
    # Video deliberately extends beyond audio: the music encode must retain every video packet.
    voice = "aevalsrc=0.16*sin(2*PI*330*t)*(0.55+0.4*sin(2*PI*1.7*t))*if(lt(t\\,1)\\,0\\,1):s=44100:d=8"
    ffmpeg("-nostdin", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x96:r=10:d=8.2", "-f", "lavfi", "-i", voice,
       "-i", metadata, "-map", "0:v", "-map", "1:a", "-map_metadata", "2", "-map_chapters", "2",
       "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-ar", "44100", "-ac", "2", source)
    ffmpeg("-nostdin", "-y", "-f", "lavfi", "-i", "aevalsrc=0.12*sin(2*PI*221*t)*if(between(t\\,0.2\\,5.7)\\,1\\,0):s=44100:d=6", track)
    return source, track


@pytest.fixture
def library(tmp_path, media):
    folder = tmp_path / "assets"
    entry = assets.add(folder, media[1], kind="music", source="Studio", license="verified license",
                       title="Test track", artist="Artist", attribution="Artist / License")
    assets.approve(folder, entry["id"])
    return folder, entry


def spec(entry, **kw):
    return dict(asset_id=entry["id"], fade_in=0, fade_out=0, loop_crossfade=.5, **kw)


def build(tmp_path, media, library, **kw):
    folder, entry = library
    return music.mix(media[0], 1, spec(entry), folder, folder=tmp_path / "music", **kw)


@pytest.mark.parametrize("level", [-18, -22, -26])
def test_mix_preserves_source_and_level(tmp_path, media, library, level):
    """AC1/2: real AAC resampling, source hash/video hash, speech, peaks, metadata, separate music LUFS."""
    source, track = media
    folder, entry = library
    original = sha256_file(source)
    outdir = tmp_path / "music"
    doc = music.mix(source, 1, spec(entry, level_lu=level), folder, folder=outdir)
    output = outdir / doc["file"]
    assert sha256_file(source) == original
    assert output != source
    info = probe_media(output, _run)
    assert (info["audio"]["codec_name"], info["audio"]["channels"], info["audio"]["sample_rate"]) == ("aac", 2, "48000")
    assert abs(float(info["audio"]["duration"]) - float(probe_media(source, _run)["audio"]["duration"])) <= music.AAC_FRAME
    assert music.video_hash(output, _run) == music.video_hash(source, _run)
    assert doc["speech"]["corr"] >= .9 and abs(doc["speech"]["lag"]) <= .04
    assert doc["true_peak"] <= doc["true_peak_limit"]
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_format", "-of", "json", str(output)], capture_output=True, text=True, check=True)
    tags = json.loads(probe.stdout)
    assert tags["format"]["tags"]["title"] == "Original title"
    assert tags["chapters"][0]["tags"]["title"] == "Chapter one"
    trimmed, unit, bed = tmp_path / "trim.wav", tmp_path / "unit.wav", tmp_path / "bed.m4a"
    music.trim_silence(track, trimmed, _run)
    music.loop_unit(trimmed, unit, .5, _run)
    ffmpeg("-nostdin", "-y", "-stream_loop", "-1", "-i", unit, "-af", music.music_filter(doc["spec"], doc["music"]["gain_db"], 8),
       "-t", "8", "-c:a", "aac", "-ar", "48000", "-ac", "2", bed)
    assert abs(music.measure(bed, _run)[0] - music.measure(source, _run, start=1)[0] - level) <= 1


def test_no_music_creates_nothing_and_cache_skips_runner(tmp_path, media, library):
    """AC1/5: default opt-out has no filesystem effect; exact spec reuses checked output."""
    source = media[0]
    digest = sha256_file(source)
    assert music.mix(source, 1, None, library[0], folder=tmp_path / "none") is None
    assert not (tmp_path / "none").exists() and sha256_file(source) == digest
    doc = build(tmp_path, media, library)
    def no_run(_):
        pytest.fail("cache must not run ffmpeg")
    assert build(tmp_path, media, library, run=no_run) == doc


def test_speech_and_peak_gates_reject_corrupt_runner(tmp_path, media, library):
    """AC2: runner replaces the requested gain with music at 0 LU; speech gate must reject it."""
    folder, entry = library
    voice = music.measure(media[0], _run, start=1)[0]
    trimmed = tmp_path / "trimmed.wav"
    music.trim_silence(media[1], trimmed, _run)
    loudness = music.measure(trimmed, _run)[0]
    def corrupt(cmd):
        cmd = list(cmd)
        if "-filter_complex" in cmd and "[music]" in cmd[cmd.index("-filter_complex") + 1]:
            i = cmd.index("-filter_complex") + 1
            # Music at +0 LU and unrelated amplitude variation overwhelms speech equivalence.
            cmd[i] = re.sub(r"volume=[-0-9.]+dB", f"volume={voice - loudness}dB,volume='if(lt(mod(t,1),0.5),0.05,2)':eval=frame", cmd[i])
        return _run(cmd)
    with pytest.raises(RenderError, match="phần lời"):
        music.mix(media[0], 1, spec(entry), folder, folder=tmp_path / "music", run=corrupt)
    assert not list((tmp_path / "music").glob("*.mp4"))
    def high_peak(cmd):
        if "ebur128=peak=true" in cmd and str(cmd[cmd.index("-i") + 1]).endswith("out.mp4"):
            return SimpleNamespace(returncode=0, stdout="", stderr="Summary:\nI: -20 LUFS\nPeak: 0 dBFS")
        return _run(cmd)
    # Direct gate checks the encoded result, never inserts a limiter or changes speech gain.
    output = tmp_path / "out.mp4"
    output.write_bytes(media[0].read_bytes())
    with pytest.raises(PackageError, match="true peak"):
        music.check_audio(output, 8, -1, lambda cmd: SimpleNamespace(returncode=0, stdout=json.dumps({"streams": [
            {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000", "duration": "8"}]}), stderr="") if cmd[0] == "ffprobe" else high_peak(cmd))


def test_trim_override_loop_and_all_seams(tmp_path, media):
    """AC3: boundary silence cut, explicit loop_end wins, all repeated seams keep 20 ms RMS continuous."""
    trimmed, override, unit, repeated = [tmp_path / n for n in ("trim.wav", "override.wav", "unit.wav", "repeat.wav")]
    cut = music.trim_silence(media[1], trimmed, _run)
    assert .19 < cut["start"] < .21 and 5.69 < cut["end"] < 5.72
    selected = music.trim_silence(media[1], override, _run, loop_end=5)
    assert selected["end"] == 5
    music.loop_unit(trimmed, unit, .5, _run)
    period = probe_media(unit, _run)["duration"]
    assert abs(period - (cut["duration"] - .5)) < .001
    ffmpeg("-nostdin", "-y", "-stream_loop", "-1", "-i", unit, "-t", str(period * 3), "-c:a", "pcm_s16le", repeated)
    envelopes, duration = audio.envelope(repeated, tmp_path / "rms.wav", _run)
    for seam in [period - .5, period, 2 * period - .5, 2 * period]:
        i = round(seam / .02)
        assert .7 < envelopes[i - 1] / envelopes[i + 1] < 1.4
        assert min(envelopes[i - 1:i + 2]) > 500
    assert abs(duration - period * 3) < .001
    with pytest.raises(PackageError, match="ít nhất"):
        music.loop_unit(trimmed, tmp_path / "short.wav", 4, _run)


def test_intro_default_fade_and_preview_phase(tmp_path, media, library):
    """AC4 + preview: voice measurement excludes intro; two previews have identical decoded phase/gain."""
    folder, entry = library
    settings = dict(asset_id=entry["id"], loop_crossfade=.5, fade_out=2)
    normalized = music.normalize(settings, 1, MusicConfig(fade_in=3))
    assert normalized["fade_in"] == 1
    assert music.normalize(settings, 0)["fade_in"] == 3
    graph = music.music_filter(dict(fade_in=3, fade_out=5), -10, 4)
    assert "d=1.500000000" in graph and "st=1.500000000:d=2.500000000" in graph
    doc = music.mix(media[0], 1, settings, folder, folder=tmp_path / "music")
    preview = music.preview(media[0], 1, settings, folder, folder=tmp_path / "music")
    assert len(preview["previews"]) == 2
    assert abs(doc["music"]["voice_lufs"] - music.measure(media[0], _run, start=1)[0]) < .01
    assert doc["music"] == preview["music"]
    for item in preview["previews"]:
        assert item["duration"] == 8 and item["start"] == 0
        a, b = tmp_path / "full.pcm", tmp_path / "preview.pcm"
        for path, out in ((tmp_path / "music" / doc["file"], a), (tmp_path / "music" / item["file"], b)):
            ffmpeg("-nostdin", "-y", "-i", path, "-map", "0:a:0", "-f", "s16le", out)
        assert a.read_bytes() == b.read_bytes()
    # Check fades on a separate music-only bed, including both endpoints and full intro level.
    unit, bed = tmp_path / "unit.wav", tmp_path / "fade.wav"
    music.loop_unit(media[1], unit, .5, _run)
    ffmpeg("-nostdin", "-y", "-stream_loop", "-1", "-i", unit, "-af", music.music_filter(normalized, 0, 8),
       "-t", "8", "-c:a", "pcm_s16le", bed)
    env, _ = audio.envelope(bed, tmp_path / "env.wav", _run)
    assert env[0] < env[50] * .05 and env[-1] < env[100] * .05


@pytest.mark.parametrize("change", [dict(level_lu=-18), dict(fade_in=2), dict(fade_out=1), dict(loop_crossfade=1), dict(asset_id="f" * 64)])
def test_effective_spec_changes_key(library, change):
    """AC5: every effective setting participates in identity."""
    original = music.normalize(dict(asset_id=library[1]["id"]), 1)
    modified = music.normalize({**original, **change}, 1)
    assert music.key(original, "source", "asset") != music.key(modified, "source", "asset")
    assert music.key(original, "source", "asset") != music.key(original, "changed", "asset")
    assert music.key(original, "source", "asset") != music.key(original, "source", "changed")
    assert music.key(original, "source", "asset", loop_end=5) != music.key(original, "source", "asset", loop_end=6)
    assert music.key(original, "source", "asset", "128k") != music.key(original, "source", "asset", "192k")


def test_stale_source_asset_approval_version(tmp_path, media, library, monkeypatch):
    folder, entry = library
    doc = build(tmp_path, media, library)
    valid = lambda sha=sha256_file(media[0]): music.current(tmp_path / "music", doc, sha, folder)
    assert valid() and not valid("changed")
    assets.unapprove(folder, entry["id"])
    assert not valid()
    assets.approve(folder, entry["id"])
    monkeypatch.setattr(music, "MUSIC_VERSION", 999)
    assert not valid()
    monkeypatch.setattr(music, "MUSIC_VERSION", doc["music_version"])
    (folder / entry["file"]).write_bytes(b"changed")
    assert not valid()


@pytest.mark.parametrize("failure", ["encode", "cancel", "replace", "recheck"])
def test_failed_replacement_preserves_current(tmp_path, media, library, monkeypatch, failure):
    """AC6: errors, cancellation and partial publish all roll back; old output and source survive."""
    doc = build(tmp_path, media, library)
    outdir = tmp_path / "music"
    before = {p.name: p.read_bytes() for p in outdir.iterdir()}
    source_sha = sha256_file(media[0])
    args = {}
    if failure in ("encode", "cancel"):
        def run(cmd):
            if "amix=inputs=2:weights='1 1'" in " ".join(cmd):
                if failure == "cancel":
                    raise KeyboardInterrupt
                return SimpleNamespace(returncode=1, stdout="", stderr="injected encode error")
            return _run(cmd)
        args["run"] = run
    elif failure == "replace":
        replace = music.os.replace
        def fail(src, dst):
            if str(dst).endswith(".json") and Path(dst).parent == outdir:
                raise OSError("injected publication error")
            return replace(src, dst)
        monkeypatch.setattr(music.os, "replace", fail)
    else:
        def changed():
            raise PackageError("source changed")
        args["before_publish"] = changed
    with pytest.raises((RenderError, PackageError, KeyboardInterrupt, OSError)):
        music.mix(media[0], 1, spec(library[1], level_lu=-18), library[0], folder=outdir, **args)
    assert {p.name: p.read_bytes() for p in outdir.iterdir()} == before
    assert sha256_file(media[0]) == source_sha
    assert (outdir / doc["file"]).is_file()


def test_success_replaces_only_after_publish_and_disk_gate(tmp_path, media, library, monkeypatch):
    old = build(tmp_path, media, library, stem="abcd1234-r1", family_stem="abcd1234")
    outdir = tmp_path / "music"
    def still_current():
        assert (outdir / old["file"]).is_file()
    new = music.mix(media[0], 1, spec(library[1], level_lu=-18), library[0], folder=outdir, before_publish=still_current,
                    stem="abcd1234-r2", family_stem="abcd1234")
    assert not (outdir / old["file"]).exists() and (outdir / new["file"]).exists()
    assert len(list(outdir.glob("*.mp4"))) == 1
    monkeypatch.setattr(music.shutil, "disk_usage", lambda p: SimpleNamespace(free=2 * 1024**3))
    with pytest.raises(PackageError, match="3 GB"):
        music.mix(media[0], 1, spec(library[1], level_lu=-26), library[0], folder=outdir)
    assert (outdir / new["file"]).exists()


def test_manifest_verified_metadata_and_pending_refusal(tmp_path, media):
    """AC7: verified-only import with explicit rejected pending entries, then separate approval."""
    source = media[1]
    entry = dict(id="BGM-06", filename=source.name, sha256=sha256_file(source), source="Studio", license="Library License",
                 license_status="verified", title="Falling Snow", artist="Artist", attribution="", loop_end=5)
    manifest = tmp_path / "manifest.json"
    atomic_write_json(manifest, dict(schema_version=1, tracks=[{**entry, "id": "pending", "license_status": "pending"}, entry]))
    result = assets.import_music(tmp_path / "assets", manifest, source.parent)
    assert [r["id"] for r in result["rejected"]] == ["pending"]
    imported = result["imported"][0]
    assert imported["title"] == "Falling Snow" and imported["loop_end"] == 5
    assert imported["artist"] == "Artist" and imported["attribution"] == "" and not imported["approved"]
    with pytest.raises(PackageError, match="approved"):
        assets.usable(tmp_path / "assets", imported["id"])
    assets.approve(tmp_path / "assets", imported["id"])
    assert assets.usable(tmp_path / "assets", imported["id"])[0]["approved"]
    for changed, message in [({"sha256": "0" * 64}, "sha256"), ({"filename": "missing.wav"}, "missing"),
                             ({"source": ""}, "source"), ({"license": ""}, "license"), ({"filename": "../x.wav"}, "filename")]:
        atomic_write_json(manifest, dict(schema_version=1, tracks=[{**entry, **changed}]))
        with pytest.raises(PackageError, match=message):
            assets.import_music(tmp_path / "bad", manifest, source.parent)
        assert not (tmp_path / "bad").exists()
    assert music.attributed_description("Description\n00:00 Chapter", "Artist") == "Description\n00:00 Chapter\n\nNhạc: Artist"
    assert music.attributed_description("Original", "") == "Original"
    # Legacy v1 entries do not need any of the new metadata fields.
    library = json.loads((tmp_path / "assets" / "library.json").read_text())
    for k in ("title", "artist", "attribution", "loop_end"):
        library["assets"][0].pop(k)
    atomic_write_json(tmp_path / "assets" / "library.json", library)
    assert assets.usable(tmp_path / "assets", imported["id"])[0]["approved"]


@pytest.mark.parametrize("field,value", [("default_level_lu", -31), ("default_level_lu", -21.3), ("fade_in", -1),
                                        ("fade_in", 11), ("fade_out", 16), ("loop_crossfade", .4),
                                        ("loop_crossfade", 9), ("fade_in", float("nan")), ("fade_out", True)])
def test_music_config_validates_ranges(field, value):
    with pytest.raises(ConfigError):
        from_dict({"music": {field: value}})


def test_silent_asset_and_invalid_specs(tmp_path, media, library):
    silent = tmp_path / "silent.wav"
    ffmpeg("-nostdin", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", silent)
    entry = assets.add(library[0], silent, kind="music", source="Studio", license="License")
    assets.approve(library[0], entry["id"])
    with pytest.raises(PackageError, match="im lặng"):
        music.mix(media[0], 1, spec(entry), library[0], folder=tmp_path / "silent-output")
    for changed in (dict(level_lu=0), dict(fade_in=float("nan")), dict(intro_mode="silent"), dict(unknown=1)):
        with pytest.raises(PackageError):
            music.normalize({"asset_id": entry["id"], **changed})
    assert from_dict({}).music == MusicConfig()


def test_preview_positions_and_timeline_filters():
    # AC4/preview: first crossfade is centred, short-video fallback is centred in content.
    assert music.preview_positions(100, 40, 36, 4) == [0, 19]
    assert music.preview_positions(38, 40, 36, 4) == [0, 4]
    assert music.preview_positions(8, 40, 36, 4) == [0, 0]
    graph = music.music_filter(dict(fade_in=3, fade_out=5), -22, 100, start=19, seconds=30)
    assert graph.index("afade=t=in:st=0") < graph.index("atrim=start=19")
    assert "afade=t=out:st=95.000000000" in graph


@pytest.mark.slow
def test_long_preview_matches_full_at_nonzero_position(tmp_path, library):
    """Real 2 x 30 s previews around a seam; light coverage: test_intro_default_fade_and_preview_phase."""
    folder, entry = library
    source = tmp_path / "long.mp4"
    ffmpeg("-nostdin", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x96:r=10:d=70", "-f", "lavfi", "-i",
       "aevalsrc=0.16*sin(2*PI*330*t)*(0.55+0.4*sin(2*PI*1.7*t)):s=48000:d=70",
       "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-ac", "2", source)
    track = tmp_path / "long.wav"
    ffmpeg("-nostdin", "-y", "-f", "lavfi", "-i", "sine=frequency=221:sample_rate=44100:duration=40", track)
    entry = assets.add(folder, track, kind="music", source="Studio", license="License")
    assets.approve(folder, entry["id"])
    settings = dict(asset_id=entry["id"], fade_in=3, fade_out=5, loop_crossfade=4)
    target = tmp_path / "music"
    full = music.mix(source, 0, settings, folder, folder=target)
    previews = music.preview(source, 0, settings, folder, folder=target)["previews"]
    assert len(previews) == 2 and all(p["duration"] == 30 for p in previews)
    assert 18.9 < previews[1]["start"] < 19.1
    for i, p in enumerate(previews):
        reference = tmp_path / f"ref-{i}.wav"
        ffmpeg("-nostdin", "-y", "-ss", p["start"], "-i", target / full["file"], "-t", "30", "-c:a", "pcm_s16le", reference)
        facts = audio.compare(target / p["file"], reference, tmp_path, _run)
        assert facts["corr"] > .99 and abs(facts["lag"]) <= .02


def test_true_peak_limit_is_not_lowered_by_float_noise():
    assert -.4 + .5 < .1  # the case found on a real clip: peak 0.1 dBTP was refused against "0.1"
    assert not .1 > music.true_peak_limit(-.4)
    assert music.true_peak_limit(-3) == -1
