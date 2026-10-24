"""VIS1: packet-preserving real media and transactional/cache failure coverage."""
import json
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short.hashing import sha256_file
from auto_short.packaging import PackageError, assets, record, variant, visual
from auto_short.render.stage import RenderError, _run, probe_media
from auto_short.workspace import atomic_write_json


SPEC = {"visual": {"asset_id": "generated:warm", "loop_seconds": 2, "crossfade": .5}}


class Media:
    """Small media runner for service and transaction tests; real codecs are tested below."""
    def __init__(self, *, fail=None, fail_at="loop", fallback=False):
        self.calls, self.fail, self.fallback, self.fail_at = [], fail, fallback, fail_at
        self.frames, self.duration = 60, 20

    def __call__(self, args):
        self.calls.append(args)
        path = Path(args[-1])
        if self.fail and args[0] == "ffmpeg" and ((self.fail_at == "loop" and "-frames:v" in args)
                or (self.fail_at == "mux" and "-t" in args)):
            path.write_bytes(b"partial")
            raise self.fail
        stdout, stderr = "", ""
        if args[0] == "ffprobe":
            loop = path.name.startswith("loop-")
            v = dict(codec_type="video", codec_name="h264", width=1920, height=1080,
                     sample_aspect_ratio="1:1", pix_fmt="yuv420p", avg_frame_rate="30/1",
                     nb_frames=str(self.frames), duration=str(self.frames / 30 if loop else self.duration))
            streams = [v] if loop else [v, dict(codec_type="audio", codec_name="aac", duration=str(self.duration))]
            stdout = json.dumps(dict(streams=streams, format={"duration": self.frames / 30 if loop else self.duration}))
        elif "streamhash" in args:
            digest = "a" * 64
            if self.fallback and "variant-" in args[args.index("-i") + 1]:
                self.fallback = False
                digest = "b" * 64
            stdout = "0,a,SHA256=" + digest + "\n"
        elif "-filter_complex" in args and "ssim[out]" in args[args.index("-filter_complex") + 1]:
            stderr = "SSIM Y:0.999 All:0.999 (30.0)"
        elif path.suffix == ".mp4":
            if "-frames:v" in args:
                self.frames = int(args[args.index("-frames:v") + 1])
            if "-t" in args:
                self.duration = float(args[args.index("-t") + 1])
            path.write_bytes(("encoded:" + " ".join(args[:-1])).encode())
        return subprocess.CompletedProcess(args, 0, stdout, stderr)


@pytest.fixture
def inputs(tmp_path):
    tc3 = tmp_path / "abcdefgh-r1.mp4"
    tc3.write_bytes(b"original TC3")
    meta = dict(sha256=sha256_file(tc3), plan_id="abcdefgh", revision=1, plan_fingerprint="f" * 64,
                chapters=[{"start": 0, "title": "Tu học"}], description="Mô tả")
    return SimpleNamespace(tc3=tc3, meta=meta, folder=tmp_path / "pkg", assets=tmp_path / "assets")


def build(s, **kwargs):
    return visual.build(s.folder, s.tc3, s.meta, kwargs.pop("spec", SPEC), s.assets, **kwargs)


def test_spec_keys_cache_stale_and_delete(inputs, monkeypatch):
    s, run = inputs, Media()
    doc = build(s, run=run)
    assert doc["checks"]["method"] == "copy"
    assert doc["chapters"] == s.meta["chapters"] and doc["description"] == s.meta["description"]
    assert build(s, run=lambda _: pytest.fail("cache invoked ffmpeg")) == doc
    with monkeypatch.context() as tuning:
        tuning.setattr(variant, "VISUAL_CRF", 24)
        assert variant.key(SPEC, s.meta["sha256"]) != doc["key"]
        assert variant.read(s.folder, doc["key"][:12]) == doc
    assert variant.key(SPEC) != variant.key(SPEC, s.meta["sha256"])
    assert variant.key({"visual": {"asset_id": "a" * 64, "motion": "none"}}) != variant.key(
        {"visual": {"asset_id": "a" * 64, "motion": "kenburns"}})
    for change in (dict(asset_id="generated:dawn"), dict(fit="blur"), dict(loop_seconds=4), dict(crossfade=1)):
        changed = {"visual": {**SPEC["visual"], **change}}
        assert variant.key(changed, s.meta["sha256"]) != doc["key"]
    assert variant.key({"visual": {}}) == variant.key(variant.normalize({"visual": {}}))
    assert variant.key({"visual": {"crossfade": 2.01}}) == variant.key({"visual": {"crossfade": 2}})
    plan = dict(plan_id="abcdefgh", revision=1)
    # fingerprint is separately covered at the adapter with real approved plans.
    monkeypatch.setattr(record, "fingerprint", lambda _: "f" * 64)
    assert variant.status(s.folder, doc, plan, s.meta) == "draft"
    changed = {**s.meta, "sha256": "c" * 64}
    assert variant.key(SPEC, changed["sha256"]) != doc["key"]
    assert variant.status(s.folder, doc, plan, changed) == "stale"
    s.tc3.write_bytes(b"new TC3 output")
    s.meta["sha256"] = sha256_file(s.tc3)
    rerun = Media()
    rebuilt = build(s, run=rerun)
    assert rebuilt["key"] != doc["key"] and not any("slow" in a for a in rerun.calls)
    variant.delete(s.folder, rebuilt)
    old = s.folder.parent / "abcdefgh-r1"
    s.folder.rename(old)
    assert variant.listing(old.parent / "abcdefgh-r2", {**plan, "revision": 2}, changed)[0][2] == "stale"
    variant.delete(old, doc)
    assert list(old.iterdir()) == []


@pytest.mark.parametrize("change", [{"motion": "bad"}, {"motion": "kenburns"}, {"fit": "pad"},
                                    {"loop_seconds": 3}, {"loop_seconds": True}, {"crossfade": float("nan")},
                                    {"crossfade": True}, {"asset_id": "../escape"}, {"unexpected": 1}])
def test_invalid_specs(change):
    with pytest.raises(PackageError):
        variant.normalize({"visual": change})


@pytest.mark.parametrize("failure", [RenderError("encode failed"), KeyboardInterrupt()])
@pytest.mark.parametrize("fail_at", ["loop", "mux"])
def test_failure_cleanup_and_tc3_unchanged(inputs, failure, fail_at):
    s = inputs
    before = sha256_file(s.tc3)
    with pytest.raises(type(failure)):
        build(s, run=Media(fail=failure, fail_at=fail_at))
    assert not list(s.folder.iterdir()) and sha256_file(s.tc3) == before
    good = build(s, run=Media())
    previous = {p.name: p.read_bytes() for p in s.folder.iterdir()}
    with pytest.raises(type(failure)):
        build(s, spec={"visual": {**SPEC["visual"], "asset_id": "generated:dawn"}}, run=Media(fail=failure, fail_at=fail_at))
    assert previous == {p.name: p.read_bytes() for p in s.folder.iterdir()}
    assert variant.reusable(s.folder, good)


@pytest.mark.parametrize("approved,license", [(False, "CC0"), (True, "")])
def test_asset_gate_precedes_media(inputs, approved, license):
    s = inputs
    s.assets.mkdir()
    image = s.assets / "source.png"
    image.write_bytes(b"image")
    ident = sha256_file(image)
    image.rename(s.assets / f"{ident}.png")
    atomic_write_json(s.assets / "library.json", dict(schema_version=1, assets=[dict(id=ident,
        file=f"{ident}.png", kind="image", approved=approved, license=license, source="manual", tags=[],
        width=50, height=50, duration=0)]))
    with pytest.raises(PackageError):
        build(s, spec={"visual": {"asset_id": ident}}, run=lambda _: pytest.fail("unapproved media ran"))


def test_fallback_disk_guard_and_preview(inputs, monkeypatch):
    s, run = inputs, Media(fallback=True)
    doc = build(s, run=run)
    assert doc["checks"]["method"] == "reencode"
    assert any("veryfast" in args for args in run.calls)
    preview = build(s, run=Media(), preview=True)
    assert (s.folder / f"preview-{preview['key'][:12]}.mp4").is_file()
    build(s, run=Media(), preview=True, spec={"visual": {"asset_id": "generated:dawn", "loop_seconds": 2}})
    assert len(list(s.folder.glob("preview-*.mp4"))) == 1
    assert len(list(s.folder.glob("variant-*.json"))) == 1
    monkeypatch.setattr(visual.shutil, "disk_usage", lambda _: SimpleNamespace(free=3 * 1024 ** 3 - 1))
    with pytest.raises(PackageError, match="3 GB"):
        build(s, spec={"visual": {"asset_id": "generated:soft"}}, run=lambda _: pytest.fail("disk guard too late"))


@pytest.fixture(scope="module")
def real_tc3(tmp_path_factory):
    root = tmp_path_factory.mktemp("ambient-real")
    tc3 = root / "abcdefgh-r1.mp4"
    proc = _run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=1:d=20.137",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=20.137", "-c:v", "libx264",
                 "-preset", "ultrafast", "-threads", "2", "-c:a", "aac", "-shortest", str(tc3)])
    assert proc.returncode == 0, proc.stderr
    return tc3


@pytest.mark.parametrize("kind", ["generated", pytest.param("image", marks=pytest.mark.slow),
                                  pytest.param("loop", marks=pytest.mark.slow)])
def test_real_media_audio_seam_and_preview(tmp_path, real_tc3, kind):
    asset_dir, folder = tmp_path / "assets", tmp_path / "pkg"
    spec = deepcopy(SPEC)
    if kind == "generated":
        spec["visual"]["crossfade"] = 2
    if kind != "generated":
        asset = tmp_path / ("image.png" if kind == "image" else "loop.mp4")
        args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                "testsrc2=s=480x640:r=30:d=4"]
        args += ["-frames:v", "1", "-threads", "1"] if kind == "image" else ["-c:v", "libx264", "-threads", "2"]
        proc = _run([*args, str(asset)])
        assert proc.returncode == 0, proc.stderr
        entry = assets.add(asset_dir, asset, kind=kind, source="synthetic fixture", license="CC0")
        assets.approve(asset_dir, entry["id"])
        spec["visual"].update(asset_id=entry["id"], fit="blur", motion="kenburns" if kind == "image" else "none")
    meta = dict(sha256=sha256_file(real_tc3), plan_id="abcdefgh", revision=1, plan_fingerprint="f" * 64,
                chapters=[], description="Synthetic TC3")
    timings = []
    def run(args):
        start = time.monotonic()
        result = _run(args)
        if "slow" in args:
            timings.append(time.monotonic() - start)
        return result
    doc = visual.build(folder, real_tc3, meta, spec, asset_dir, run=run)
    output = folder / f"variant-{doc['key'][:12]}.mp4"
    assert visual.audio_hash(output, _run) == visual.audio_hash(real_tc3, _run)
    assert doc["checks"]["black"] is False and doc["checks"]["seam_ssim"] >= .97
    assert doc["checks"]["method"] == "copy"
    assert sha256_file(real_tc3) == meta["sha256"]
    info = probe_media(output, _run)
    assert (info["video"]["width"], info["video"]["height"], info["video"]["sample_aspect_ratio"]) == (1920, 1080, "1:1")
    assert info["video"]["codec_name"] == "h264" and info["audio"]["codec_name"] == "aac"
    preview = visual.build(folder, real_tc3, meta, spec, asset_dir, preview=True)
    assert abs(probe_media(folder / f"preview-{preview['key'][:12]}.mp4", _run)["duration"] - 20) < 2.04
    assert len(list(folder.glob("variant-*.json"))) == 1
    print(f"{kind}: CRF={visual.VISUAL_CRF}, loop_encode={timings[0]:.3f}s, build={doc['build_seconds']}s, "
          f"loop_bytes={(folder / ('loop-' + doc['loop_key'][:12] + '.mp4')).stat().st_size}")


def test_publication_interrupt_restores_previous_files(inputs, monkeypatch):
    s = inputs
    build(s, run=Media())
    build(s, run=Media(), preview=True)
    previous = {p.name: p.read_bytes() for p in s.folder.iterdir()}
    replace, interrupted = visual.os.replace, False
    def cancel_after_replace(source, dest):
        nonlocal interrupted
        replace(source, dest)
        if Path(dest).parent == s.folder and Path(dest).name.startswith("preview-") and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
    monkeypatch.setattr(visual.os, "replace", cancel_after_replace)
    with pytest.raises(KeyboardInterrupt):
        build(s, run=Media(), preview=True)
    assert previous == {p.name: p.read_bytes() for p in s.folder.iterdir()}
    assert sha256_file(s.tc3) == s.meta["sha256"]


@pytest.mark.parametrize("check", ["black", "seam", "audio"])
def test_failed_checks_never_publish(inputs, check):
    s, media = inputs, Media()
    def run(args):
        proc = media(args)
        if check == "black" and "blackdetect=d=0.1" in args:
            proc.stderr = "black_start:0 black_end:1 black_duration:1"
        if check == "seam" and "-filter_complex" in args and "ssim[out]" in args[args.index("-filter_complex") + 1]:
            proc.stderr = "SSIM All:0.9"
        if check == "audio" and "streamhash" in args and "variant-" in args[args.index("-i") + 1]:
            proc.stdout = "0,a,SHA256=" + "b" * 64
        return proc
    with pytest.raises(RenderError):
        build(s, run=run)
    assert not list(s.folder.iterdir())
    assert sha256_file(s.tc3) == s.meta["sha256"]
    if check == "audio":
        assert any("veryfast" in args for args in media.calls)
