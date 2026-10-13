"""Render stage with a synthetic lavfi source: artifacts (AC1-AC3, AC9), resume (AC7), determinism (AC8),
failures (AC10), CLI."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from auto_short.cli import main
from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.hashing import config_hash, sha256_file
from auto_short.render import RenderError, run_render
from auto_short.render.stage import HASH_KEYS, font_path, used_config
from auto_short.workspace import run_stage
from render_helpers import CLIPS, EID, SEGMENTS, make_render_episode, make_source, write_docs

pytestmark = pytest.mark.usefixtures("_ffmpeg")


@pytest.fixture(scope="session")
def _ffmpeg(_video_template):  # skips when ffmpeg is missing (conftest)
    return None


@pytest.fixture(scope="session")
def source_template(tmp_path_factory, _ffmpeg) -> Path:
    return make_source(tmp_path_factory.mktemp("render") / "src.mp4")


@pytest.fixture
def rcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=replace(RenderConfig(), output_dir=tmp_path / "output", preset="ultrafast"))


@pytest.fixture
def ws(rcfg, source_template):
    return make_render_episode(rcfg.workspace.dir, source_template)


class Recorder:
    """Runner double that records calls and delegates to subprocess (optionally failing ffmpeg)."""

    def __init__(self, fail_ffmpeg_at: int | None = None):
        self.calls: list[list[str]] = []
        self.fail_at = fail_ffmpeg_at

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "ffmpeg" and self.fail_at is not None and self.ffmpeg_calls == self.fail_at:
            return subprocess.CompletedProcess(cmd, 1, "", "frame=1\n[fake] Conversion failed!\n")
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)

    @property
    def ffmpeg_calls(self):
        return sum(c[0] == "ffmpeg" for c in self.calls)


def _out(rcfg):
    return (rcfg.render.output_dir / EID).resolve()


def _rm(rcfg):
    return json.loads((_out(rcfg) / "render_manifest.json").read_text(encoding="utf-8"))


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


def _stage(ws, name="render"):
    return json.loads(ws.manifest_path.read_text(encoding="utf-8"))["stages"].get(name, {})


def _files(rcfg):
    root = rcfg.render.output_dir
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []


# --- AC1-AC3, AC9 ---------------------------------------------------------------------------------------------

def test_render_writes_shorts_and_manifest(ws, rcfg):
    result = run_render(EID, rcfg)
    assert result.ran and (result.rendered, result.clips) == (2, 2)
    out = _out(rcfg)
    assert result.path == out / "render_manifest.json"
    doc = _rm(rcfg)
    assert list(doc) == ["schema_version", "episode_id", "source_sha256", "clips_sha256", "titles_sha256",
                         "candidates_sha256", "render_config_hash", "title_source", "font", "layout", "encode",
                         "header", "stats", "shorts"]
    assert doc["title_source"] == "titles"
    assert doc["font"] == {"family": "Be Vietnam Pro", "file": "fonts/BeVietnamPro-Regular.ttf",
                           "sha256": sha256_file(font_path(RenderConfig()))}
    assert doc["encode"]["fps"] == "30000/1001" and doc["encode"]["preset"] == "ultrafast"
    assert doc["header"] == {"lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"],
                             "display_lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"],
                             "font_size": 48}  # CP8.14: 184 px header, 49 px shrinks to 48 px on 2 lines
    assert doc["layout"]["header_panel"] == {"x": 81, "y": 22, "w": 918, "h": 184, "radius": 59}
    assert doc["layout"]["title_panel"] == {"x": 135, "y": 1373, "w": 810, "h": 227, "radius": 59}
    assert doc["stats"] == {"clips": 2, "rendered": 2, "skipped": 0, "seconds": 5.1}
    k01, k02 = doc["shorts"]
    assert list(k01) == ["clip_id", "candidate_id", "status", "skip_reason", "file", "sha256", "title",
                         "title_display_lines", "title_font_size", "layout", "source_start", "source_end",
                         "segments", "duration", "dissolves", "title_origin", "render_key", "origin", "cut"]
    assert (k01["origin"], k01["cut"]) == ("ai", None)  # CP9 C5: not added, no manual cut
    assert (k01["title_origin"], k02["title_origin"]) == ("ai", "ai")  # CP8.2 T4: no review.json
    assert len(k01["render_key"]) == 64 and k01["render_key"] != k02["render_key"]
    assert doc["encode"]["dissolve"] == 0.15 and list(doc["encode"])[-1] == "dissolve"
    # one junction each, trimmed gaps of 15 / 18 frames -> full 4-frame dissolve (CP8.1 V2, V4)
    assert k01["dissolves"] == [{"at": 0.901, "frames": 4}] and k02["dissolves"] == [{"at": 0.5, "frames": 4}]
    assert k01["segments"] == SEGMENTS["k01"] and k02["segments"] == SEGMENTS["k02"]
    # CP8.14: both titles are 2 lines at 70 px (3-line titles: test_title_panel_is_drawn_over_the_video)
    for s in (k01, k02):
        assert len(s["title_display_lines"]) == 2 and s["title_font_size"] == 70
        assert s["layout"] == {k: doc["layout"][k] for k in ("header_panel", "video", "title_panel")}
    for s, clip in zip(doc["shorts"], CLIPS):
        path = out / s["file"]
        assert s["file"] == f"shorts/{clip['id']}.mp4" and sha256_file(path) == s["sha256"]
        st = _probe(path)
        v, a = st["video"], st["audio"]
        assert (v["codec_name"], v["width"], v["height"], v["pix_fmt"], v["r_frame_rate"]) == \
            ("h264", 1080, 1920, "yuv420p", "30000/1001")
        assert (a["codec_name"], a["sample_rate"], a["channels"]) == ("aac", "48000", 2)
        assert abs(float(v["duration"]) - clip["duration"]) <= 0.1
        assert abs(float(a["duration"]) - clip["duration"]) <= 0.1
        assert int(v["nb_frames"]) == round(clip["duration"] * 30000 / 1001)  # V5
    entry = _stage(ws)
    assert entry["status"] == "done"
    assert entry["artifacts"] == [str(out / "render_manifest.json"), str(out / "shorts/k01.mp4"),
                                  str(out / "shorts/k02.mp4")]
    assert [i["path"] for i in entry["inputs"]] == ["clips.json", "titles.json", "candidates.json",
                                                    "metadata.json", "source.mp4"]
    assert not list(out.glob("shorts/.*"))  # no temp files


def test_untitled_clip_is_skipped(ws, rcfg, caplog):
    write_docs(ws, titles={"k01": None, "k02": "Mỗi suy nghĩ đều là tội lỗi?"})
    run_render(EID, rcfg)
    doc = _rm(rcfg)
    k01 = doc["shorts"][0]
    assert (k01["status"], k01["skip_reason"], k01["file"], k01["sha256"]) == ("skipped", "untitled", None, None)
    assert k01["dissolves"] is None
    assert k01["segments"] == SEGMENTS["k01"]
    assert doc["stats"] == {"clips": 2, "rendered": 1, "skipped": 1, "seconds": 2.7}
    assert _files(rcfg) == [f"{EID}/render_manifest.json", f"{EID}/shorts/k02.mp4"]
    assert "clip k01 skipped: untitled" in caplog.text


@pytest.mark.parametrize("docs", [{"titles": {}}, {"clips": []}])
def test_nothing_to_render_is_done_without_mp4(ws, rcfg, docs, caplog):
    write_docs(ws, **docs)
    result = run_render(EID, rcfg)
    assert result.ran and result.rendered == 0
    assert _files(rcfg) == [f"{EID}/render_manifest.json"]
    assert _stage(ws)["status"] == "done"
    assert "no titled clip" in caplog.text


# --- AC7, AC8 -------------------------------------------------------------------------------------------------

def test_resume_skip_config_and_stale(ws, rcfg):
    run_render(EID, rcfg)
    rm = _out(rcfg) / "render_manifest.json"
    before = rm.read_bytes()
    rec = Recorder()
    assert not run_render(EID, rcfg, run=rec).ran
    assert rec.calls == [] and rm.read_bytes() == before

    exec_only = replace(rcfg, render=replace(rcfg.render, threads=2, output_dir=rcfg.render.output_dir / "x"))
    assert not run_render(EID, exec_only, run=rec).ran and rec.calls == []

    changed = replace(rcfg, render=replace(rcfg.render, crf=30))
    assert run_render(EID, changed, run=rec).ran and rec.ffmpeg_calls == 2
    assert _rm(rcfg)["encode"]["crf"] == 30

    # titling re-run -> render stale -> re-runs
    manifest = json.loads(ws.manifest_path.read_text(encoding="utf-8"))
    run_stage(ws, manifest, "titling", inputs=[], cfg_hash="y", force=True, action=lambda: ["titles.json"])
    assert _stage(ws)["status"] == "stale"
    assert run_render(EID, changed).ran


def test_config_hash_keys():
    assert "output_dir" not in HASH_KEYS and "threads" not in HASH_KEYS
    assert {"font_file", "title_font_size", "min_frame_margin", "crf", "preset", "title_source",
            "dissolve", "title_bottom"} <= set(HASH_KEYS)
    assert "gap_video_title" not in HASH_KEYS  # CP8.14 L2
    assert config_hash(used_config(replace(RenderConfig(), title_bottom=1.4), "f" * 64)) != \
        config_hash(used_config(RenderConfig(), "f" * 64))
    assert config_hash(used_config(replace(RenderConfig(), dissolve=0), "f" * 64)) != \
        config_hash(used_config(RenderConfig(), "f" * 64))
    a = used_config(RenderConfig(), "f" * 64)
    assert a["render.font_sha256"] == "f" * 64
    assert config_hash(a) != config_hash(used_config(RenderConfig(), "0" * 64))


@pytest.mark.slow
def test_force_rerender_is_byte_identical(ws, rcfg):
    run_render(EID, rcfg)
    out = _out(rcfg)
    before = {p.name: p.read_bytes() for p in [out / "render_manifest.json", *out.glob("shorts/*.mp4")]}
    assert run_render(EID, rcfg, force=True).ran
    after = {p.name: p.read_bytes() for p in [out / "render_manifest.json", *out.glob("shorts/*.mp4")]}
    assert after == before


# --- AC10 -----------------------------------------------------------------------------------------------------

def _assert_failed(ws, rcfg, match):
    entry = _stage(ws)
    assert entry["status"] == "failed" and match in entry["error"]
    assert _files(rcfg) == []


def _snapshot(rcfg):
    root = rcfg.render.output_dir
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_titling_not_done(ws, rcfg):
    run_render(EID, rcfg)
    before = _snapshot(rcfg)
    manifest = json.loads(ws.manifest_path.read_text(encoding="utf-8"))
    manifest["stages"]["titling"]["status"] = "failed"
    ws.save_manifest(manifest)
    with pytest.raises(RenderError, match="titling is not done"):
        run_render(EID, rcfg)
    entry = _stage(ws)
    assert entry["status"] == "failed" and "titling is not done" in entry["error"]
    # CP8.2 T5: a failure only deletes files written by that run; the previous render stays intact.
    assert _snapshot(rcfg) == before


def test_sha_mismatch(ws, rcfg):
    doc = json.loads((ws.dir / "titles.json").read_text(encoding="utf-8"))
    doc["clips_sha256"] = "0" * 64
    (ws.dir / "titles.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RenderError, match="titles.json does not match"):
        run_render(EID, rcfg)
    _assert_failed(ws, rcfg, "titles.json does not match")

    write_docs(ws)
    doc = json.loads((ws.dir / "clips.json").read_text(encoding="utf-8"))
    doc["candidates_sha256"] = "0" * 64
    (ws.dir / "clips.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RenderError, match="clips.json does not match candidates.json"):
        run_render(EID, rcfg)


def test_segment_sum_mismatch(ws, rcfg):
    clips = [dict(CLIPS[0], duration=2.5), CLIPS[1]]
    write_docs(ws, clips=clips)
    with pytest.raises(RenderError, match="k01: kept segments total 2.400 s but clips.json duration is 2.500 s"):
        run_render(EID, rcfg)
    _assert_failed(ws, rcfg, "kept segments total")


def test_missing_glyph_and_fit_failures(ws, rcfg):
    write_docs(ws, titles={"k01": "Tâm thiện 心 thì", "k02": "Mỗi suy nghĩ"})
    with pytest.raises(RenderError, match="k01: font BeVietnamPro-Regular.ttf has no glyph for '心'"):
        run_render(EID, rcfg)
    _assert_failed(ws, rcfg, "no glyph")

    write_docs(ws, titles={"k01": "Tâm", "k02": " ".join(["Phật pháp"] * 20)})
    with pytest.raises(RenderError, match="k02: title .* does not fit"):
        run_render(EID, rcfg)
    _assert_failed(ws, rcfg, "does not fit")


@pytest.mark.slow
def test_ffmpeg_failure_keeps_previous_render(ws, rcfg):
    run_render(EID, rcfg)
    before = _snapshot(rcfg)
    rec = Recorder(fail_ffmpeg_at=2)  # k01 succeeds, k02 fails
    with pytest.raises(RenderError, match=r"clip k02: ffmpeg failed: \[fake\] Conversion failed!"):
        run_render(EID, rcfg, force=True, run=rec)
    entry = _stage(ws)
    assert entry["status"] == "failed" and "clip k02: ffmpeg failed" in entry["error"]
    assert rec.ffmpeg_calls == 2
    # CP8.2 T5: the k01 encoded by the failed run is deleted (never committed); the previous render is intact.
    assert _snapshot(rcfg) == before

    # Without a previous render, the failed run leaves nothing.
    _remove_all(rcfg)
    with pytest.raises(RenderError, match="clip k02: ffmpeg failed"):
        run_render(EID, rcfg, force=True, run=Recorder(fail_ffmpeg_at=2))
    _assert_failed(ws, rcfg, "clip k02: ffmpeg failed")


def _remove_all(rcfg):
    import shutil
    shutil.rmtree(rcfg.render.output_dir)


# --- CLI ------------------------------------------------------------------------------------------------------

def test_cli_render_and_status(ws, rcfg, tmp_path, capsys):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(f'[workspace]\ndir = "{rcfg.workspace.dir.as_posix()}"\n'
                        f'[render]\noutput_dir = "{rcfg.render.output_dir.as_posix()}"\npreset = "ultrafast"\n',
                        encoding="utf-8")
    assert main(["render", EID, "--config", str(cfg_file)]) == 0
    out = capsys.readouterr()
    assert out.out == f"{EID}\trendered (2/2 clips)\t{_out(rcfg) / 'render_manifest.json'}\n"
    assert "render: header HT.Tịnh Không / Thập Thiện Nghiệp Đạo Kinh (tập 9) (48 px)" in out.err
    assert "render: clip k01: " in out.err and "render: font Be Vietnam Pro" in out.err
    assert main(["render", EID, "--config", str(cfg_file)]) == 0
    assert "skipped (up to date)" in capsys.readouterr().out
    assert main(["status", EID, "--config", str(cfg_file)]) == 0
    assert "render      done" in capsys.readouterr().out

    write_docs(ws, titles={"k01": "Tâm 心", "k02": "x y"})
    assert main(["render", EID, "--config", str(cfg_file)]) == 1
    assert "error: render failed: clip k01: font" in capsys.readouterr().err


# --- CP8.14: layout V16 ------------------------------------------------------------------------------------------

THREE_LINES = "Chân tướng sự thật của vũ trụ nhân sinh không thể nói ra"  # 3 lines at 70 px
SHRINKS = "Thường Trụ Chân Tâm Thanh Tịnh Quang Minh Không Sinh Diệt"  # 3 lines only at 68 px


def _frame_rgb(path: Path) -> bytes:
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                           "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout


def _px(frame: bytes, x: int, y: int) -> tuple[int, int, int]:
    i = (y * 1080 + x) * 3
    return frame[i], frame[i + 1], frame[i + 2]


def test_title_panel_is_drawn_over_the_video(ws, rcfg):
    """AC1/AC2: 3-line titles keep 70 px in a 297 px panel (or shrink in it); the panel bottom is at 1600 and
    it covers the bottom of the video (overlap pixels are panel yellow). AC5: the title preview gives the same
    lines / size / panel height as the render."""
    from auto_short.review import preview_title
    write_docs(ws, titles={"k01": THREE_LINES, "k02": SHRINKS})
    run_render(EID, rcfg)
    doc = _rm(rcfg)
    k01, k02 = doc["shorts"]
    assert (len(k01["title_display_lines"]), k01["title_font_size"]) == (3, 70)
    assert (len(k02["title_display_lines"]), k02["title_font_size"]) == (3, 68)
    for s in (k01, k02):
        video, title = s["layout"]["video"], s["layout"]["title_panel"]
        assert video == doc["layout"]["video"] == {"x": 0, "y": 211, "w": 1080, "h": 1254,
                                                    "crop": {"w": 930, "h": 1080, "x": 255, "y": 0}}
        assert title == {"x": 135, "y": 1303, "w": 810, "h": 297, "radius": 59}
        assert title["y"] + title["h"] == 1600 < 1625
        p = preview_title(EID, rcfg, s["clip_id"], s["title"])
        assert (p.display_lines, p.font_size, p.panel_height) == \
            (s["title_display_lines"], s["title_font_size"], title["h"])
    frame = _frame_rgb(_out(rcfg) / k01["file"])
    yellow = (254, 219, 0)
    # inside the panel where it overlaps the video (y 1303-1465): top padding row, left padding column
    for x, y in ((540, 1312), (150, 1400), (930, 1440), (540, 1460)):
        assert all(abs(a - b) <= 12 for a, b in zip(_px(frame, x, y), yellow)), (x, y, _px(frame, x, y))
    # video right above the panel and beside it; black below the video beside the panel
    assert any(max(_px(frame, x, 1290)) > 40 for x in range(135, 945, 10))
    assert any(max(_px(frame, x, 1400)) > 40 for x in range(0, 120, 5))
    assert all(max(_px(frame, x, y)) <= 20 for x in (20, 100, 1000, 1060) for y in (1480, 1700, 1900))
    assert all(max(_px(frame, x, 1620)) <= 20 for x in range(0, 1080, 20))  # nothing below the title


# --- CP8.1: video dissolve (V2-V5) ----------------------------------------------------------------------------

# Candidate over the whole source with three trims: segments [0, 1] [1.5, 3] [3.07, 5] [6, 7.9] (6.33 s);
# gaps 15, 2 and 30 grid frames -> dissolves of 4, 2 and 4 frames.
MULTI_CAND = {"id": "c00009", "source_start": 0.0, "source_end": 7.9, "source_duration": 7.9, "duration": 6.33,
              "trims": [[1.0, 1.5], [3.0, 3.07], [5.0, 6.0]]}
MULTI_CLIP = {"id": "k01", "candidate_id": "c00009", "source_start": 0.0, "source_end": 7.9, "source_duration": 7.9,
              "duration": 6.33, "head_cut": None}


def _framemd5(graph: str, source: Path, segments, tmp: Path, tag: str) -> tuple[list[str], list[str]]:
    from auto_short.render import plan
    script = tmp / f"{tag}.filter"
    script.write_text(graph, encoding="utf-8")
    seek, length = plan.input_window(segments, plan.Fraction(30000, 1001))
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(seek), "-t", str(length), "-copyts", "-i", str(source),
                          "-filter_complex_script", str(script), "-map", "[vout]", "-map", "[aout]",
                          "-f", "framemd5", "-"], capture_output=True, text=True, check=True).stdout
    rows = [ln.split(",") for ln in out.splitlines() if ln and not ln.startswith("#")]
    return [r[-1].strip() for r in rows if r[0].strip() == "0"], [r[-1].strip() for r in rows if r[0].strip() == "1"]


def test_dissolve_render_multi_segment(ws, rcfg, tmp_path):
    from fractions import Fraction

    from auto_short.render import plan
    write_docs(ws, clips=[MULTI_CLIP], candidates=[MULTI_CAND], titles={"k01": "Mỗi suy nghĩ đều là tội lỗi?"})
    run_render(EID, rcfg)
    doc = _rm(rcfg)
    k01 = doc["shorts"][0]
    assert k01["segments"] == [[0.0, 1.0], [1.5, 3.0], [3.07, 5.0], [6.0, 7.9]]
    assert [d["frames"] for d in k01["dissolves"]] == [4, 2, 4]
    fps = Fraction(30000, 1001)
    segs = plan.kept_segments(0.0, 7.9, MULTI_CAND["trims"])
    planned = plan.planned_frames(segs, fps)
    assert planned == round(Fraction(633, 100) * fps) == 190
    path = _out(rcfg) / k01["file"]
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames,duration", "-of", "json", str(path)],
                           capture_output=True, text=True, check=True).stdout
    v = json.loads(probe)["streams"][0]
    assert int(v["nb_read_frames"]) == planned  # V5: same frame count as the hard-cut plan
    assert abs(float(v["duration"]) - 6.33) <= 0.1

    # Composed (pre-encode) frames: dissolve 0.15 vs 0 differ only inside the dissolve windows; audio identical.
    g = plan.geometry(RenderConfig())
    lay = plan.layout(g, g.title_h, 1440, 1080)
    (tmp_path / "l.txt").write_text("x", encoding="utf-8")
    lines = [plan.TextLine(tmp_path / "l.txt", 100)]
    kw = dict(segments=segs, fps=fps, lay=lay, font_file=font_path(RenderConfig()), header_lines=lines,
              header_size=67, title_lines=lines, title_size=88)
    src = ws.dir / "source.mp4"
    v0, a0 = _framemd5(plan.filter_graph(**kw, dissolve=0), src, segs, tmp_path, "cut")
    v1, a1 = _framemd5(plan.filter_graph(**kw, dissolve=0.15), src, segs, tmp_path, "dissolve")
    assert len(v0) == len(v1) == planned and a0 == a1
    # Window of D frames centred on the junction; xfade's first blended frame is still 100 % the outgoing
    # segment (progress 1 at the offset), so the frames that differ are the last D - 1 of each window.
    blended = []
    for d in k01["dissolves"]:
        c = round(Fraction(str(d["at"])) * fps)
        blended += range(c - d["frames"] // 2 + 1, c + d["frames"] // 2)
    assert blended == [29, 30, 31, 75, 132, 133, 134]
    assert [i for i in range(planned) if v0[i] != v1[i]] == blended


def test_verify_output_checks_frame_count(tmp_path):
    from fractions import Fraction

    from auto_short.render.stage import verify_output

    def fake(nb):
        doc = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920,
                            "pix_fmt": "yuv420p", "r_frame_rate": "30000/1001", "duration": "1.001",
                            "nb_frames": str(nb)},
                           {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2,
                            "duration": "1.0"}], "format": {"duration": "1.001"}}
        return lambda cmd: subprocess.CompletedProcess(cmd, 0, json.dumps(doc), "")

    verify_output(tmp_path / "x.mp4", Fraction(30000, 1001), 30, fake(30))
    with pytest.raises(RenderError, match="video frames 29 != 30"):
        verify_output(tmp_path / "x.mp4", Fraction(30000, 1001), 30, fake(29))


# --- FIX-render-video-tail ---------------------------------------------------------------------------------

def _short_video_source(path: Path, video_s: float, audio_s: float = 8.0) -> Path:
    """lavfi source whose video stream ends before its audio (like a real file with a short video tail)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=1440x1080:rate=30000/1001:duration={video_s}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={audio_s}:sample_rate=48000",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2",
                    str(path)], check=True)
    return path


def _tail_episode(tmp_path, rcfg, video_s: float, dissolve: float):
    src = _short_video_source(tmp_path / "short.mp4", video_s)
    ws = make_render_episode(rcfg.workspace.dir, src, candidates=[
        {"id": "c00002", "source_start": 4.5, "source_end": 8.0, "source_duration": 3.5, "duration": 2.9,
         "trims": [[5.0, 5.6]]}],
        clips=[{"id": "k02", "candidate_id": "c00002", "source_start": 4.5, "source_end": 8.0,
                "source_duration": 3.5, "duration": 2.9, "head_cut": None}], titles={"k02": "Tiêu đề thử"})
    return ws, replace(rcfg, render=replace(rcfg.render, dissolve=dissolve))


@pytest.mark.parametrize("dissolve", [0.15, 0.0])
def test_clip_past_the_video_end_is_padded_with_the_last_frame(tmp_path, rcfg, dissolve):
    ws, cfg = _tail_episode(tmp_path, rcfg, 7.9, dissolve)  # video 237 frames (7.908 s), clip planned to 8.0 s
    run = Recorder()
    run_render(EID, cfg, run=run)
    cmd = next(c for c in run.calls if c[0] == "ffmpeg")
    script = cmd[cmd.index("-filter_complex_script") + 1]
    short = _out(cfg) / "shorts/k02.mp4"
    v = _probe(short)["video"]
    assert int(v["nb_frames"]) == round(2.9 * 30000 / 1001) == 87
    assert not list((_out(cfg) / "shorts").glob(".*"))
    assert _rm(cfg)["shorts"][0]["status"] == "rendered"
    assert script  # the graph file lives in a temp dir; its content is covered by the plan tests


def test_clip_far_past_the_video_end_fails_without_encode(tmp_path, rcfg):
    ws, cfg = _tail_episode(tmp_path, rcfg, 7.5, 0.15)  # about 15 frames missing
    run = Recorder()
    with pytest.raises(RenderError, match=r"clip k02: video stream ends at 7\.5\d\d s, before the clip end 8\.000 s"):
        run_render(EID, cfg, run=run)
    assert run.ffmpeg_calls == 0
    assert not list((_out(cfg) / "shorts").glob(".*")) if (_out(cfg) / "shorts").exists() else True
    assert _stage(ws)["status"] == "failed"
