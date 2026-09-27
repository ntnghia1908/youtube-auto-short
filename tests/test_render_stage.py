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
                             "display_lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo", "Kinh (tập 9)"],
                             "font_size": 67}
    assert doc["layout"]["title_panel"]["h"] == 292
    assert doc["stats"] == {"clips": 2, "rendered": 2, "skipped": 0, "seconds": 5.1}
    k01, k02 = doc["shorts"]
    assert list(k01) == ["clip_id", "candidate_id", "status", "skip_reason", "file", "sha256", "title",
                         "title_display_lines", "title_font_size", "layout", "source_start", "source_end",
                         "segments", "duration"]
    assert k01["segments"] == SEGMENTS["k01"] and k02["segments"] == SEGMENTS["k02"]
    assert len(k01["title_display_lines"]) == 3 and k01["title_font_size"] == 88
    assert k01["layout"]["title_panel"]["h"] > 292  # 3 lines: panel grew (P3)
    assert k02["layout"]["title_panel"]["h"] == 292 and len(k02["title_display_lines"]) == 2
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
    assert {"font_file", "title_font_size", "min_frame_margin", "crf", "preset", "title_source"} <= set(HASH_KEYS)
    a = used_config(RenderConfig(), "f" * 64)
    assert a["render.font_sha256"] == "f" * 64
    assert config_hash(a) != config_hash(used_config(RenderConfig(), "0" * 64))


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


def test_titling_not_done(ws, rcfg):
    run_render(EID, rcfg)  # earlier outputs are removed on failure
    manifest = json.loads(ws.manifest_path.read_text(encoding="utf-8"))
    manifest["stages"]["titling"]["status"] = "failed"
    ws.save_manifest(manifest)
    with pytest.raises(RenderError, match="titling is not done"):
        run_render(EID, rcfg)
    _assert_failed(ws, rcfg, "titling is not done")


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


def test_ffmpeg_failure_cleans_everything(ws, rcfg):
    run_render(EID, rcfg)
    rec = Recorder(fail_ffmpeg_at=2)  # k01 succeeds, k02 fails
    with pytest.raises(RenderError, match=r"clip k02: ffmpeg failed: \[fake\] Conversion failed!"):
        run_render(EID, rcfg, force=True, run=rec)
    _assert_failed(ws, rcfg, "clip k02: ffmpeg failed")
    assert rec.ffmpeg_calls == 2


# --- CLI ------------------------------------------------------------------------------------------------------

def test_cli_render_and_status(ws, rcfg, tmp_path, capsys):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(f'[workspace]\ndir = "{rcfg.workspace.dir.as_posix()}"\n'
                        f'[render]\noutput_dir = "{rcfg.render.output_dir.as_posix()}"\npreset = "ultrafast"\n',
                        encoding="utf-8")
    assert main(["render", EID, "--config", str(cfg_file)]) == 0
    out = capsys.readouterr()
    assert out.out == f"{EID}\trendered (2/2 clips)\t{_out(rcfg) / 'render_manifest.json'}\n"
    assert "render: header HT.Tịnh Không / Thập Thiện Nghiệp Đạo / Kinh (tập 9) (67 px)" in out.err
    assert "render: clip k01: " in out.err and "render: font Be Vietnam Pro" in out.err
    assert main(["render", EID, "--config", str(cfg_file)]) == 0
    assert "skipped (up to date)" in capsys.readouterr().out
    assert main(["status", EID, "--config", str(cfg_file)]) == 0
    assert "render      done" in capsys.readouterr().out

    write_docs(ws, titles={"k01": "Tâm 心", "k02": "x y"})
    assert main(["render", EID, "--config", str(cfg_file)]) == 1
    assert "error: render failed: clip k01: font" in capsys.readouterr().err
