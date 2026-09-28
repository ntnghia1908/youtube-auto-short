"""CP8.9 khai thị (docs/decisions/CP8.9-khai-thi-contract.md): config K9 (AC10), khaithi.json K1 + minutes K2
(AC4), effective analysis / selection parameters and prompt kt1 (AC2, AC3), windows K4 (AC6), reuse of the base
episode K5 (AC5), CLI K6 and an end-to-end ``run --khai-thi`` without network (AC2, AC3, AC5)."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short import cli, khaithi, pipeline
from auto_short.analysis import AnalysisError, run_analysis
from auto_short.analysis.stage import used_config as analysis_used
from auto_short.config import Config, ConfigError, WorkspaceConfig, from_dict
from auto_short.hashing import config_hash
from auto_short.ingest import run_ingest
from auto_short.ingest.source import local_episode_id
from auto_short.khaithi import KhaiThi, KhaithiError
from auto_short.pipeline import StageDeps
from auto_short.selection import SelectionError, run_selection
from auto_short.selection.logic import build_windows
from auto_short.selection.prompt import prompt_sha256, system_prompt
from auto_short.selection.stage import used_config as selection_used
from auto_short.transcript import run_transcript
from auto_short.transcript.providers import LocalSubtitleProvider
from analysis_helpers import FakeAnalyzer, make_analysis_episode, seg
from selection_helpers import FakeClient, proposal, response
from test_ingest_youtube import URL, FakeDownloader
from test_pipeline_e2e import TitlingClient
from transcript_helpers import JSON3_HEAD, JSON3_HEAD_DURATION, FakeFetcher, FakeWhisper, make_episode, manifest_of

ROOT = Path(__file__).resolve().parents[1]
BASE = "rbjfCfFq3Dk"
KT = BASE + ".kt"


def _write_kt(root: Path, episode_id: str = KT, base: str = BASE, lo: int = 5, hi: int = 10) -> None:
    khaithi.write(root / episode_id, KhaiThi(base, lo, hi))


def _snapshot(d: Path) -> dict:
    """(bytes, mtime_ns) of every file under ``d``."""
    return {p.relative_to(d).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(d.rglob("*")) if p.is_file()}


# --- K9 config (AC10) --------------------------------------------------------------------------------

def test_config_defaults_and_example():
    kc = Config().khaithi
    assert (kc.default_min_minutes, kc.default_max_minutes, kc.max_minutes_limit, kc.prompt_version,
            kc.window_words_per_minute) == (4, 7, 15, "kt1", 400)
    data = tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))
    assert data["khaithi"] == {"default_min_minutes": 4, "default_max_minutes": 7, "max_minutes_limit": 15,
                               "prompt_version": "kt1", "window_words_per_minute": 400}
    assert from_dict(data).khaithi == kc


@pytest.mark.parametrize("section, msg", [
    ({"default_min_minutes": 10, "default_max_minutes": 10}, "default_min_minutes must be < "),
    ({"default_min_minutes": 0}, "khaithi.default_min_minutes"),
    ({"max_minutes_limit": 16}, "khaithi.max_minutes_limit"),
    ({"max_minutes_limit": 6}, "khaithi.default_max_minutes"),  # default max 7 > limit 6
    ({"window_words_per_minute": 0}, "khaithi.window_words_per_minute"),
    ({"default_max_minutes": 7.5}, "khaithi.default_max_minutes must be an integer"),
    ({"prompt_version": ""}, "khaithi.prompt_version"),
])
def test_config_invalid(section, msg):
    with pytest.raises(ConfigError, match=re.escape(msg)):
        from_dict({"khaithi": section})


def test_config_file_error_via_cli(tmp_path, capsys):
    p = tmp_path / "config.toml"
    p.write_text("[khaithi]\nmax_minutes_limit = 30\n", encoding="utf-8")
    assert cli.main(["status", "x", "--config", str(p)]) == 1
    assert "khaithi.max_minutes_limit must be an integer between 2 and 15" in capsys.readouterr().err


# --- K1/K2 khaithi.json (AC4) ------------------------------------------------------------------------

@pytest.mark.parametrize("lo, hi", [(5, 5), (6, 5), (0, 5), (5, 16), (5.5, 10), ("5", 10), (True, 10), (None, 5)])
def test_check_minutes_rejects(lo, hi):
    with pytest.raises(KhaithiError) as exc:
        khaithi.check_minutes(lo, hi, 15)
    assert exc.value.vi and exc.value.vi != str(exc.value)  # Vietnamese message for the web


def test_check_minutes_accepts():
    assert khaithi.check_minutes(1, 15, 15) == (1, 15)
    assert khaithi.check_minutes(5, 10, 15) == (5, 10)


def test_khaithi_json_write_read(tmp_path):
    d = tmp_path / KT
    assert khaithi.read(d, 15) is None
    assert khaithi.write(d, KhaiThi(BASE, 5, 10)) is True
    assert (d / "khaithi.json").read_text(encoding="utf-8") == (
        '{\n  "schema_version": 1,\n  "kind": "khaithi",\n  "base_episode_id": "rbjfCfFq3Dk",\n'
        '  "min_minutes": 5,\n  "max_minutes": 10\n}\n')
    mtime = (d / "khaithi.json").stat().st_mtime_ns
    assert khaithi.write(d, KhaiThi(BASE, 5, 10)) is False  # unchanged: not rewritten
    assert (d / "khaithi.json").stat().st_mtime_ns == mtime
    assert khaithi.read(d, 15) == KhaiThi(BASE, 5, 10)
    with pytest.raises(KhaithiError, match="max_minutes must be <= 8"):
        khaithi.read(d, 8)


@pytest.mark.parametrize("text", [
    "{not json", "[]", '{"schema_version": 2, "kind": "khaithi", "base_episode_id": "a", "min_minutes": 5, '
    '"max_minutes": 10}', '{"schema_version": 1, "kind": "short", "base_episode_id": "a", "min_minutes": 5, '
    '"max_minutes": 10}', '{"schema_version": 1, "kind": "khaithi", "base_episode_id": "../x", "min_minutes": 5, '
    '"max_minutes": 10}', '{"schema_version": 1, "kind": "khaithi", "base_episode_id": "a", "min_minutes": 10, '
    '"max_minutes": 5}', '{"schema_version": 1, "kind": "khaithi", "base_episode_id": "a", "min_minutes": 5.0, '
    '"max_minutes": 10}'])
def test_khaithi_json_broken(tmp_path, text):
    (tmp_path / "khaithi.json").write_text(text, encoding="utf-8")
    with pytest.raises(KhaithiError):
        khaithi.read(tmp_path, 15)
    assert khaithi.read_quiet(tmp_path, 15) is None


def test_prepare_refuses_archived(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path))
    (tmp_path / KT).mkdir()
    (tmp_path / KT / "archive.json").write_text("{}", encoding="utf-8")
    with pytest.raises(KhaithiError, match="archived"):
        khaithi.prepare(cfg, BASE, 5, 10)
    assert not (tmp_path / KT / "khaithi.json").exists()
    with pytest.raises(KhaithiError):
        khaithi.prepare(cfg, "x" * 126, 5, 10)  # <base>.kt longer than 128 chars


# --- K2-K4 effective parameters (AC1, AC3) ----------------------------------------------------------

def test_effective_config():
    c = Config()
    assert khaithi.effective_config(c, None) is c
    e = khaithi.effective_config(c, KhaiThi(BASE, 5, 10))
    assert (e.analysis.min_duration, e.analysis.max_duration, e.analysis.target_min, e.analysis.target_max) == \
        (300.0, 600.0, 300.0, 600.0)
    assert replace(e.analysis, min_duration=30.0, max_duration=180.0, target_min=60.0, target_max=90.0) == c.analysis
    assert (e.selection.prompt_version, e.selection.max_window_words, e.selection.duration_minutes) == \
        ("kt1", 4000, (5, 10))
    assert khaithi.effective_config(c, KhaiThi(BASE, 2, 5)).selection.max_window_words == 2500  # max(2500, 2000)
    used = selection_used(e)
    assert used["selection.duration_minutes"] == [5, 10] and used["selection.prompt_version"] == "kt1"
    assert used["selection.prompt_sha256"] == prompt_sha256("kt1")
    assert "selection.duration_minutes" not in selection_used(c)
    # K2: [analysis] durations of a Short do not reach a khai thị episode, and vice versa
    c2 = replace(c, analysis=replace(c.analysis, min_duration=20.0, max_duration=200.0))
    kt = KhaiThi(BASE, 5, 10)
    assert config_hash(analysis_used(khaithi.effective_config(c2, kt))) == \
        config_hash(analysis_used(khaithi.effective_config(c, kt)))
    assert config_hash(analysis_used(c2)) != config_hash(analysis_used(c))
    assert config_hash(analysis_used(khaithi.effective_config(c, KhaiThi(BASE, 5, 11)))) != \
        config_hash(analysis_used(khaithi.effective_config(c, kt)))


def test_prompt_kt1():
    words = Config().selection.head_cut_words
    text = system_prompt("kt1", words, (5, 10))
    assert "VIDEO KHAI THỊ NGẮN ĐỘC LẬP" in text
    assert "Thời lượng bắt buộc 5–10 phút (300–600 giây)" in text
    assert "Đoạn dưới 300 giây hoặc trên 600 giây bị loại bỏ" in text
    assert '"đến 490.2" → thời lượng 450.0 giây (7.5 phút)' in text
    assert '"cho nên", "vì vậy"' in text and "<<" not in text
    assert "30–180" not in text
    assert "1–2 phút (60–120 giây)" in system_prompt("kt1", words, (1, 2))
    with pytest.raises(ValueError, match="khai thi"):
        system_prompt("kt1", words)
    assert system_prompt("v3", words, (5, 10)) == system_prompt("v3", words)  # Short prompts unchanged
    sha = prompt_sha256("kt1")  # template hash: the minutes are in the config hash instead
    assert sha not in {prompt_sha256(v) for v in ("v1", "v2", "v3")}


# --- analysis on the real fixture (AC2, AC3, AC4) ---------------------------------------------------

# The real fixture has few long speech runs (one "unit" spans 413-1235 s), so 2-5 minutes is the range that yields
# candidates on it; the lecture-length ranges are exercised by the synthetic tests below and the real run.
def _kt_analysis(root: Path, lo=2, hi=5, episode_id=KT):
    ws = make_analysis_episode(root, episode_id=episode_id)
    _write_kt(root, episode_id, lo=lo, hi=hi)
    return ws


def test_analysis_khaithi_durations(tmp_path):
    root = tmp_path / "work"
    ws = _kt_analysis(root)
    cfg = Config(workspace=WorkspaceConfig(dir=root))
    res = run_analysis(KT, cfg, analyzer=FakeAnalyzer())
    doc = json.loads(res.path.read_text(encoding="utf-8"))
    assert res.ran and doc["candidates"]
    assert all(120.0 <= c["duration"] <= 300.0 and c["in_target"] for c in doc["candidates"])
    p = doc["params"]
    assert (p["min_duration"], p["max_duration"], p["target_min"], p["target_max"]) == (120.0, 300.0, 120.0, 300.0)
    assert manifest_of(ws)["stages"]["analysis"]["config_hash"] == \
        config_hash(analysis_used(khaithi.effective_config(cfg, KhaiThi(BASE, 2, 5))))


def test_analysis_stale_rules(tmp_path):
    root = tmp_path / "work"
    make_analysis_episode(root, episode_id=BASE)
    kt_ws = _kt_analysis(root)
    cfg = Config(workspace=WorkspaceConfig(dir=root))
    fa = FakeAnalyzer()
    assert run_analysis(BASE, cfg, analyzer=fa).ran and run_analysis(KT, cfg, analyzer=fa).ran
    assert not run_analysis(BASE, cfg, analyzer=fa).ran and not run_analysis(KT, cfg, analyzer=fa).ran
    # [analysis] Short durations changed -> Short re-runs, khai thị skips (K2)
    cfg2 = replace(cfg, analysis=replace(cfg.analysis, min_duration=40.0, max_duration=170.0))
    assert run_analysis(BASE, cfg2, analyzer=fa).ran
    assert not run_analysis(KT, cfg2, analyzer=fa).ran
    # minutes changed -> khai thị analysis re-runs and marks the later stages stale (CP2 D6)
    m = manifest_of(kt_ws)
    for s in ("selection", "titling", "render"):
        m["stages"][s] = {"status": "done", "artifacts": [], "inputs": [], "config_hash": "x"}
    kt_ws.save_manifest(m)
    _write_kt(root, lo=2, hi=6)
    assert run_analysis(KT, cfg2, analyzer=fa).ran
    stages = manifest_of(kt_ws)["stages"]
    assert [stages[s]["status"] for s in ("analysis", "selection", "titling", "render")] == \
        ["done", "stale", "stale", "stale"]


def test_broken_khaithi_json_stops_stages(tmp_path):
    root = tmp_path / "work"
    ws = _kt_analysis(root)
    (ws.dir / "khaithi.json").write_text('{"schema_version": 1, "kind": "khaithi"}', encoding="utf-8")
    cfg = Config(workspace=WorkspaceConfig(dir=root))
    before = ws.manifest_path.read_bytes()
    with pytest.raises(AnalysisError, match="invalid khai thi file"):
        run_analysis(KT, cfg, analyzer=FakeAnalyzer())
    with pytest.raises(SelectionError, match="invalid khai thi file"):
        run_selection(KT, cfg, client=FakeClient())
    with pytest.raises(pipeline.PipelineError, match="invalid khai thi file"):
        pipeline.run_pipeline(URL, cfg, episode_id=KT, preflight=None)
    assert ws.manifest_path.read_bytes() == before
    assert not (ws.dir / "candidates.json").exists()


# --- selection kt1 (AC2) ----------------------------------------------------------------------------

def test_selection_khaithi(tmp_path):
    root = tmp_path / "work"
    ws = _kt_analysis(root)
    cfg = Config(workspace=WorkspaceConfig(dir=root))
    run_analysis(KT, cfg, analyzer=FakeAnalyzer())
    cand = json.loads((ws.dir / "candidates.json").read_text(encoding="utf-8"))
    eff = khaithi.effective_config(cfg, KhaiThi(BASE, 2, 5))
    windows = build_windows(cand["units"], cand["candidates"], eff.selection.max_window_words)
    pick = max((c for c in cand["candidates"] if c["duration"] <= 280), key=lambda c: c["duration"])
    win = next(w for w in windows if pick in w.candidates)
    client = FakeClient({win.id: [response(proposal(*pick["unit_ids"], 9))]})
    res = run_selection(KT, cfg, client=client, sleep=lambda s: None)
    clips = json.loads(res.path.read_text(encoding="utf-8"))
    log_doc = json.loads((ws.dir / "selection_log.json").read_text(encoding="utf-8"))
    assert len(clips["clips"]) == 1 and all(120 <= c["duration"] <= 300 for c in clips["clips"])
    assert clips["prompt_version"] == log_doc["prompt_version"] == "kt1"
    assert clips["prompt_sha256"] == prompt_sha256("kt1")
    assert clips["params"]["max_window_words"] == 2500  # max(2500, 400 x 5)
    assert "Thời lượng bắt buộc 2–5 phút (120–300 giây)" in log_doc["system_prompt"]
    assert client.calls[0]["messages"][0]["content"] == log_doc["system_prompt"]
    assert manifest_of(ws)["stages"]["selection"]["config_hash"] == config_hash(selection_used(eff))
    assert not run_selection(KT, cfg, client=client).ran


def test_selection_prompt_kind_mismatch(tmp_path):
    root = tmp_path / "work"
    make_analysis_episode(root, episode_id=BASE)
    _kt_analysis(root)
    cfg = Config(workspace=WorkspaceConfig(dir=root))
    run_analysis(BASE, cfg, analyzer=FakeAnalyzer())
    run_analysis(KT, cfg, analyzer=FakeAnalyzer())
    with pytest.raises(SelectionError, match="selection.prompt_version: prompt 'kt1' is a khai thi prompt"):
        run_selection(BASE, replace(cfg, selection=replace(cfg.selection, prompt_version="kt1")), client=FakeClient())
    with pytest.raises(SelectionError, match="khaithi.prompt_version: prompt 'v3' is not a khai thi prompt"):
        run_selection(KT, replace(cfg, khaithi=replace(cfg.khaithi, prompt_version="v3")), client=FakeClient())


# --- K4 windows (AC6) -------------------------------------------------------------------------------

def _long_lecture(n_units: int, words_per_second: float) -> tuple[list[dict], list[tuple[float, float]], float]:
    """Continuous lecture (no hard break): units of 30 s speech, 3.5 s silences between them."""
    segments, silences, t = [], [], 5.0
    n_words = round(30 * words_per_second)
    for n in range(1, n_units + 1):
        segments.append(seg(n, t, t + 30.0, " ".join(["học"] * n_words)))
        silences.append((t + 30.0, t + 33.5))
        t += 33.5
    return segments, silences, round(t + 5.0, 3)


@pytest.mark.parametrize("wps", [2.5, 5.0])  # 150 and 300 words per minute
def test_windows_hold_the_longest_candidate(tmp_path, wps):
    root = tmp_path / "work"
    segments, silences, duration = _long_lecture(200, wps)
    make_analysis_episode(root, episode_id=KT, segments=segments, duration=duration)
    _write_kt(root, lo=14, hi=15)
    cfg = Config(workspace=WorkspaceConfig(dir=root))
    cfg = replace(cfg, analysis=replace(cfg.analysis, outro_window=5.0))
    res = run_analysis(KT, cfg, analyzer=FakeAnalyzer(changes=[], silences=silences))
    cand = json.loads(res.path.read_text(encoding="utf-8"))
    assert cand["candidates"] and max(c["duration"] for c in cand["candidates"]) > 870
    eff = khaithi.effective_config(cfg, khaithi.read(root / KT, 15))
    assert eff.selection.max_window_words == 6000
    windows = build_windows(cand["units"], cand["candidates"], eff.selection.max_window_words)
    assert len(windows) > 1  # the lecture had to be split into overlapping windows
    covered = {c["id"] for w in windows for c in w.candidates}
    assert covered == {c["id"] for c in cand["candidates"]}  # every candidate lies inside one window
    if wps == 5.0:  # [selection] max_window_words alone could not hold a 15-minute candidate
        with pytest.raises(SelectionError, match="more than max_window_words"):
            build_windows(cand["units"], cand["candidates"], cfg.selection.max_window_words)


# --- K5 reuse of the base episode (AC5) ---------------------------------------------------------------

class NoDownloader:
    def __init__(self):
        self.calls = []

    def __call__(self, url, dest_dir, config):
        self.calls.append(url)
        raise AssertionError("downloader must not be called")


def test_ingest_reuses_base_download(video, cfg):
    root = cfg.workspace.dir
    run_ingest(URL, cfg, downloader=FakeDownloader(video))
    base_dir = root / BASE
    before = _snapshot(base_dir)
    _write_kt(root)
    nd = NoDownloader()
    res = run_ingest(URL, cfg, episode_id=KT, downloader=nd)
    assert res.ran and nd.calls == []
    kt_src, base_src = root / KT / "source.mp4", base_dir / "source.mp4"
    assert os.stat(kt_src).st_ino == os.stat(base_src).st_ino  # hardlink
    base_meta = json.loads((base_dir / "metadata.json").read_text(encoding="utf-8"))
    kt_meta = json.loads((root / KT / "metadata.json").read_text(encoding="utf-8"))
    assert kt_meta["episode_id"] == KT and kt_meta["youtube"] == base_meta["youtube"]
    assert kt_meta["title"] == base_meta["title"] and kt_meta["source"]["sha256"] == base_meta["source"]["sha256"]
    m = manifest_of(SimpleNamespace(manifest_path=root / KT / "manifest.json"))
    assert m["stages"]["ingest"]["status"] == "done" and m["source"]["path"] == "source.mp4"
    assert m["stages"]["ingest"]["config_hash"] == \
        manifest_of(SimpleNamespace(manifest_path=base_dir / "manifest.json"))["stages"]["ingest"]["config_hash"]
    assert _snapshot(base_dir) == before  # nothing written in work/<base_id>/
    assert not run_ingest(URL, cfg, episode_id=KT, downloader=nd).ran


def test_ingest_copies_when_hardlink_fails(video, cfg, monkeypatch):
    root = cfg.workspace.dir
    run_ingest(URL, cfg, downloader=FakeDownloader(video))
    _write_kt(root)

    def no_link(a, b):
        raise OSError("cross-device link")

    monkeypatch.setattr(os, "link", no_link)
    assert run_ingest(URL, cfg, episode_id=KT, downloader=NoDownloader()).ran
    kt_src, base_src = root / KT / "source.mp4", root / BASE / "source.mp4"
    assert os.stat(kt_src).st_ino != os.stat(base_src).st_ino and kt_src.read_bytes() == base_src.read_bytes()


@pytest.mark.parametrize("case", ["no_base", "archived", "other_format", "sha_mismatch", "failed"])
def test_ingest_downloads_when_base_unusable(video, cfg, case):
    root = cfg.workspace.dir
    run_cfg = cfg
    if case != "no_base":
        run_ingest(URL, cfg, downloader=FakeDownloader(video))
        base = root / BASE
        m = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        if case == "archived":
            (base / "archive.json").write_text("{}", encoding="utf-8")
        elif case == "other_format":
            run_cfg = replace(cfg, ingest=replace(cfg.ingest, youtube_format="best"))
        elif case == "sha_mismatch":
            m["source"]["sha256"] = "0" * 64
        elif case == "failed":
            m["stages"]["ingest"]["status"] = "failed"
        (base / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    _write_kt(root)
    fd = FakeDownloader(video)
    assert run_ingest(URL, run_cfg, episode_id=KT, downloader=fd).ran
    assert len(fd.calls) == 1


class CountingFetcher(FakeFetcher):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.track_calls = 0

    def tracks(self, url):
        self.track_calls += 1
        return super().tracks(url)


def _yt_transcript_pair(root: Path):
    base, _ = make_episode(root, episode_id=BASE, kind="youtube", duration=JSON3_HEAD_DURATION)
    kt, _ = make_episode(root, episode_id=KT, kind="youtube", duration=JSON3_HEAD_DURATION)
    _write_kt(root)
    return base, kt


def test_transcript_reuses_base(tmp_path):
    root = tmp_path / "work"
    base, kt = _yt_transcript_pair(root)
    cfg = Config(workspace=WorkspaceConfig(dir=root))
    run_transcript(BASE, cfg, fetcher=FakeFetcher({("vi", True): JSON3_HEAD.read_bytes()}), backend=FakeWhisper())
    before = _snapshot(base.dir)
    fetcher, whisper = CountingFetcher(fail=True), FakeWhisper()
    res = run_transcript(KT, cfg, fetcher=fetcher, backend=whisper)
    assert res.ran and fetcher.track_calls == 0 and whisper.calls == []
    assert (kt.dir / "transcript.json").read_bytes() == (base.dir / "transcript.json").read_bytes()
    b, k = manifest_of(base)["stages"]["transcript"], manifest_of(kt)["stages"]["transcript"]
    assert k["status"] == "done" and k["config_hash"] == b["config_hash"] and k["artifacts"] == b["artifacts"]
    for rel in k["artifacts"]:
        assert (kt.dir / rel).read_bytes() == (base.dir / rel).read_bytes()
    assert (res.source, res.method) == ("youtube", "youtube_auto_caption")
    assert _snapshot(base.dir) == before
    assert not run_transcript(KT, cfg, fetcher=fetcher, backend=whisper).ran


def test_transcript_not_reused_with_other_config(tmp_path):
    root = tmp_path / "work"
    _yt_transcript_pair(root)
    cfg = Config(workspace=WorkspaceConfig(dir=root))
    run_transcript(BASE, cfg, fetcher=FakeFetcher({("vi", True): JSON3_HEAD.read_bytes()}), backend=FakeWhisper())
    cfg2 = replace(cfg, transcript=replace(cfg.transcript, min_coverage=0.4))
    fetcher = CountingFetcher({("vi", True): JSON3_HEAD.read_bytes()})
    assert run_transcript(KT, cfg2, fetcher=fetcher, backend=FakeWhisper()).ran
    assert fetcher.track_calls == 1


# --- K6 CLI (AC4) -----------------------------------------------------------------------------------

@pytest.mark.parametrize("args, msg", [
    (["--khai-thi", "--min-minutes", "10", "--max-minutes", "5"], "min_minutes must be < max_minutes"),
    (["--khai-thi", "--min-minutes", "0", "--max-minutes", "5"], "min_minutes must be >= 1"),
    (["--khai-thi", "--max-minutes", "16"], "max_minutes must be <= 15"),
    (["--min-minutes", "5"], "--min-minutes / --max-minutes need --khai-thi"),
])
def test_cli_run_khaithi_errors(config_file, tmp_path, capsys, args, msg):
    assert cli.main(["run", URL, "--no-preflight", "--config", str(config_file), *args]) == 1
    assert msg in capsys.readouterr().err
    assert not (tmp_path / "work").exists()


def test_cli_non_integer_minutes(config_file):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", URL, "--khai-thi", "--min-minutes", "5.5", "--config", str(config_file)])
    assert exc.value.code == 2


def test_cli_run_broken_khaithi_json(config_file, tmp_path, capsys):
    root = tmp_path / "work"
    ws = _kt_analysis(root)
    (ws.dir / "khaithi.json").write_text("{", encoding="utf-8")
    before = _snapshot(ws.dir)
    assert cli.main(["run", URL, "--episode-id", KT, "--no-preflight", "--config", str(config_file)]) == 1
    assert "cannot read" in capsys.readouterr().err
    assert _snapshot(ws.dir) == before
    assert cli.main(["analysis", KT, "--config", str(config_file)]) == 1
    assert _snapshot(ws.dir) == before


def test_cli_status_shows_kind(config_file, tmp_path, capsys):
    root = tmp_path / "work"
    _kt_analysis(root, lo=3, hi=8)
    make_analysis_episode(root, episode_id=BASE)
    assert cli.main(["status", KT, "--config", str(config_file)]) == 0
    assert "kind:      khai thi 3–8 minutes (base episode rbjfCfFq3Dk)" in capsys.readouterr().out
    assert cli.main(["status", BASE, "--config", str(config_file)]) == 0
    assert "kind:      short" in capsys.readouterr().out


# --- end to end: run --khai-thi on a local lecture (AC2, AC3, AC5) -------------------------------------

PERIOD, SPEECH, UNITS = 6.0, 4.5, 40
WORDS = "chúng ta hôm nay học về lòng biết ơn cha mẹ và thầy tổ".split()


def _ts(x: float) -> str:
    ms = round(x * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


@pytest.fixture
def long_lecture(tmp_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    video = tmp_path / "src" / "Bài Giảng Tập 9.mp4"
    video.parent.mkdir()
    dur = PERIOD * UNITS
    tone = f"if(lt(mod(t\\,{PERIOD})\\,{SPEECH})\\,0.3*sin(2*PI*440*t)\\,0)"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:size=320x240:rate=10:duration={dur}",
                    "-f", "lavfi", "-i", f"aevalsrc=exprs='{tone}':s=16000:d={dur}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(video)], check=True)
    srt = "".join(f"{n + 1}\n{_ts(n * PERIOD)} --> {_ts(n * PERIOD + SPEECH)}\n"
                  f"{' '.join(WORDS[(n + k) % len(WORDS)] for k in range(10))}\n\n" for n in range(UNITS))
    video.with_name(video.stem + ".vi.srt").write_text(srt, encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text(f'''[workspace]
dir = "{(tmp_path / 'work').as_posix()}"
[analysis]
min_boundary_silence = 1.0
hard_break_silence = 5.0
[selection]
retries = 0
[titling]
retries = 0
[render]
output_dir = "{(tmp_path / 'output').as_posix()}"
''', encoding="utf-8")
    return video, config


class KtSelectionClient:
    def __init__(self):
        self.calls = 0

    def chat(self, *, model, messages, format, options, think):
        from auto_short.selection.client import ChatResult
        self.calls += 1
        clips = [proposal(a, b, 9) for a, b in (("u0001", "u0012"), ("u0020", "u0033"))]
        return ChatResult(content=json.dumps({"clips": clips}, ensure_ascii=False))


def _fake_render(calls):
    def run(eid, config, **kw):
        calls.append(eid)
        out = Path(config.render.output_dir) / eid
        out.mkdir(parents=True, exist_ok=True)
        (out / "render_manifest.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(episode_id=eid, ran=True, path=out / "render_manifest.json", rendered=2, clips=2)
    return run


def test_run_khaithi_end_to_end(long_lecture, tmp_path, monkeypatch, capsys):
    video, config = long_lecture
    real = pipeline.run_pipeline
    holder = {}
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **kw: real(*a, deps=holder["deps"], **kw))

    # base episode: ingest + transcript only (the Short pipeline itself is not needed for K5)
    assert cli.main(["ingest", str(video), "--config", str(config)]) == 0
    base_id = capsys.readouterr().out.split("\t")[0]
    assert cli.main(["transcript", base_id, "--config", str(config)]) == 0
    capsys.readouterr()
    base_dir = tmp_path / "work" / base_id
    before = _snapshot(base_dir)
    assert base_id == local_episode_id(video, hashlib.sha256(video.read_bytes()).hexdigest())

    def no_subtitle(self, ctx):
        raise AssertionError("transcript provider must not run (K5)")

    monkeypatch.setattr(LocalSubtitleProvider, "fetch", no_subtitle)
    sel, ti, renders = KtSelectionClient(), TitlingClient(), []
    holder["deps"] = StageDeps(selection_client=sel, titling_client=ti, runners={"render": _fake_render(renders)})
    argv = ["run", str(video), "--khai-thi", "--min-minutes", "1", "--max-minutes", "2", "--no-preflight",
            "--series", "Bài giảng", "--episode", "9", "--config", str(config)]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    kt_id = base_id + ".kt"
    kt_dir = tmp_path / "work" / kt_id
    assert out.splitlines()[-1].startswith(f"{kt_id}\tdone")
    assert json.loads((kt_dir / "khaithi.json").read_text(encoding="utf-8")) == {
        "schema_version": 1, "kind": "khaithi", "base_episode_id": base_id, "min_minutes": 1, "max_minutes": 2}
    cand = json.loads((kt_dir / "candidates.json").read_text(encoding="utf-8"))
    clips = json.loads((kt_dir / "clips.json").read_text(encoding="utf-8"))
    slog = json.loads((kt_dir / "selection_log.json").read_text(encoding="utf-8"))
    assert cand["candidates"] and all(60 <= c["duration"] <= 120 for c in cand["candidates"])
    assert cand["params"]["min_duration"] == 60.0 and cand["params"]["max_duration"] == 120.0
    assert len(clips["clips"]) == 2 and all(60 <= c["duration"] <= 120 for c in clips["clips"])
    assert slog["prompt_version"] == "kt1" and "1–2 phút (60–120 giây)" in slog["system_prompt"]
    assert (kt_dir / "transcript.json").read_bytes() == (base_dir / "transcript.json").read_bytes()
    assert _snapshot(base_dir) == before
    assert (sel.calls, len(renders)) == (1, 1)

    # same command -> every stage skips
    assert cli.main(argv) == 0
    states = [line.split("\t")[1] for line in capsys.readouterr().out.splitlines()]
    assert states[:5] == ["skipped (up to date)"] * 5
    assert sel.calls == 1

    # other minutes -> analysis .. render re-run, ingest + transcript skip (AC3)
    argv[3:7] = ["--min-minutes", "1", "--max-minutes", "3"]
    assert cli.main(argv) == 0
    states = [line.split("\t")[1] for line in capsys.readouterr().out.splitlines()]
    assert states[:2] == ["skipped (up to date)"] * 2
    assert all(s != "skipped (up to date)" for s in states[2:5])
    assert (sel.calls, len(renders)) == (2, 3)  # the fake render runner never skips
    assert khaithi.read(kt_dir, 15) == KhaiThi(base_id, 1, 3)
    assert cli.main(["status", kt_id, "--config", str(config)]) == 0
    assert "kind:      khai thi 1–3 minutes" in capsys.readouterr().out
