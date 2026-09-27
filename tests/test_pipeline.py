"""Pipeline orchestration with fake stages, Ollama preflight and the ``run`` CLI (CP8, E1-E8)."""

import functools
import http.server
import io
import json
import socket
import threading
import urllib.error
from types import SimpleNamespace

import pytest

from auto_short import cli, pipeline
from auto_short.config import Config, SelectionConfig, TitlingConfig, WorkspaceConfig
from auto_short.pipeline import (PIPELINE_STAGES, PipelineError, PipelineInterrupted, PreflightError, StageDeps,
                                 ollama_preflight, run_pipeline)
from auto_short.selection import SelectionError


class FakeStages:
    """Stand-ins for the six run_<stage> functions with CP2 D6-like semantics: a stage runs when forced,
    not done yet, or an earlier stage ran in this pipeline run (stale); otherwise it skips."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.done: set[str] = set()
        self.fail: dict[str, Exception] = {}
        self.calls: list[tuple[str, bool, dict]] = []
        self._upstream_ran = False

    def runners(self) -> dict:
        return {s: functools.partial(self._run, s) for s in PIPELINE_STAGES}

    def _run(self, stage, first, config, *, force=False, **kw):
        if stage == "ingest":
            self._upstream_ran = False
        self.calls.append((stage, force, dict(kw, first=first)))
        if stage in self.fail:
            self.done.discard(stage)
            raise self.fail[stage]
        ran = force or stage not in self.done or self._upstream_ran
        self._upstream_ran |= ran
        self.done.add(stage)
        out = self.tmp_path / "out"
        extra = {"rendered": 2 if ran else None, "clips": 2 if ran else None} if stage == "render" else {"clips": 2}
        if stage == "render" and ran:
            out.mkdir(exist_ok=True)
            (out / "render_manifest.json").write_text(json.dumps({"stats": {"rendered": 2, "clips": 2}}))
        return SimpleNamespace(episode_id="ep1", ran=ran, workspace=self.tmp_path / "work" / "ep1",
                               path=out / "render_manifest.json" if stage == "render" else self.tmp_path / stage,
                               source="local_subtitle", method="subtitle_srt", candidates=5, titled=2, **extra)

    def ran(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture
def fake(tmp_path):
    return FakeStages(tmp_path)


def _run(fake, **kw):
    return run_pipeline("video.mp4", Config(), preflight=None, deps=StageDeps(runners=fake.runners()), **kw)


def test_order_args_and_resume(fake):
    result = _run(fake, episode_id="ep1", subtitle="x.srt", speaker="S", series="Se", episode="9")
    assert result.ok and result.episode_id == "ep1"
    assert fake.ran() == list(PIPELINE_STAGES)
    assert [r.stage for r in result.stages] == list(PIPELINE_STAGES)
    assert all(r.ran for r in result.stages) and all(r.seconds >= 0 for r in result.stages)
    kw = {c[0]: c[2] for c in fake.calls}
    assert kw["ingest"] == {"episode_id": "ep1", "first": "video.mp4"}
    assert kw["transcript"]["subtitle"] == "x.srt" and kw["transcript"]["first"] == "ep1"
    assert (kw["titling"]["speaker"], kw["titling"]["series"], kw["titling"]["episode"]) == ("S", "Se", "9")
    assert not any(c[1] for c in fake.calls)  # no force without --force-from
    assert (result.rendered, result.clips) == (2, 2)

    fake.calls.clear()
    again = _run(fake)
    assert [r.ran for r in again.stages] == [False] * 6
    # render skipped: counts come from render_manifest.json
    assert (again.rendered, again.clips, again.output_dir) == (2, 2, fake.tmp_path / "out")


def test_stop_on_error_then_resume(fake):
    fake.fail["selection"] = SelectionError("selection failed: boom")
    result = _run(fake)
    assert not result.ok and result.failed_stage == "selection" and str(result.error) == "selection failed: boom"
    assert fake.ran() == ["ingest", "transcript", "analysis", "selection"]
    assert [r.stage for r in result.stages] == ["ingest", "transcript", "analysis"]

    del fake.fail["selection"]
    fake.calls.clear()
    result = _run(fake)
    assert result.ok
    assert [(r.stage, r.ran) for r in result.stages] == [
        ("ingest", False), ("transcript", False), ("analysis", False),
        ("selection", True), ("titling", True), ("render", True)]


def test_force_from_only_forces_that_stage(fake):
    _run(fake)
    fake.calls.clear()
    result = _run(fake, force_from="titling")
    assert [(c[0], c[1]) for c in fake.calls] == [
        ("ingest", False), ("transcript", False), ("analysis", False), ("selection", False),
        ("titling", True), ("render", False)]
    assert [r.ran for r in result.stages] == [False, False, False, False, True, True]

    with pytest.raises(PipelineError, match="unknown stage 'review'"):
        _run(fake, force_from="review")


def test_interrupt_names_running_stage(fake):
    fake.fail["analysis"] = KeyboardInterrupt()
    with pytest.raises(PipelineInterrupted) as info:
        _run(fake)
    assert info.value.stage == "analysis"
    assert isinstance(info.value, KeyboardInterrupt)
    assert [r.stage for r in info.value.result.stages] == ["ingest", "transcript"]


def test_preflight_runs_first_and_blocks_every_stage(fake):
    def failing(config):
        raise PreflightError("cannot reach Ollama")

    with pytest.raises(PreflightError):
        run_pipeline("video.mp4", Config(), preflight=failing, deps=StageDeps(runners=fake.runners()))
    assert fake.calls == []

    seen = []
    run_pipeline("video.mp4", Config(), preflight=seen.append, deps=StageDeps(runners=fake.runners()))
    assert len(seen) == 1 and fake.ran() == list(PIPELINE_STAGES)


# --- E8 preflight -----------------------------------------------------------------------------

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, reply):
        self.reply = reply
        self.urls: list[str] = []

    def __call__(self, req, timeout):
        self.urls.append(req.full_url)
        assert timeout == 10.0 and req.get_method() == "GET"
        if isinstance(self.reply, Exception):
            raise self.reply
        return FakeResponse(self.reply if isinstance(self.reply, bytes) else json.dumps(self.reply).encode())


def _tags(*names):
    return {"models": [{"name": n, "model": n} for n in names]}


def _cfg(sel_host="http://127.0.0.1:11437", ti_host="http://127.0.0.1:11437", sel="qwen3:30b", ti="qwen3:14b"):
    return Config(selection=SelectionConfig(model=sel, ollama_host=sel_host),
                  titling=TitlingConfig(model=ti, ollama_host=ti_host))


@pytest.fixture(autouse=True)
def _no_ollama_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)


def test_preflight_ok_one_call_per_host():
    opener = FakeOpener(_tags("qwen3:30b", "qwen3:14b", "other:1b"))
    ollama_preflight(_cfg(), opener=opener)
    assert opener.urls == ["http://127.0.0.1:11437/api/tags"]

    opener = FakeOpener(_tags("qwen3:30b", "qwen3:14b"))
    ollama_preflight(_cfg(ti_host="127.0.0.1:9"), opener=opener)
    assert opener.urls == ["http://127.0.0.1:11437/api/tags", "http://127.0.0.1:9/api/tags"]


def test_preflight_env_override_and_latest_tag(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "10.0.0.5:1234")
    opener = FakeOpener(_tags("llama3:latest", "qwen3:14b"))
    ollama_preflight(_cfg(sel="llama3"), opener=opener)
    assert opener.urls == ["http://10.0.0.5:1234/api/tags"]


@pytest.mark.parametrize("reply, match", [
    (_tags("qwen3:14b"), r"model 'qwen3:30b' \(\[selection\] model\) is not available at http://127.0.0.1:11437"),
    (_tags("qwen3:30b"), r"model 'qwen3:14b' \(\[titling\] model\)"),
    (urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
     "cannot reach Ollama at http://127.0.0.1:11437"),
    (urllib.error.HTTPError("u", 500, "err", {}, io.BytesIO(b"")), "HTTP 500 from http://127.0.0.1:11437/api/tags"),
    (TimeoutError(), r"timeout after 10 s"),
    (b"<html>", "invalid response"),
    ({"nope": 1}, "invalid response"),
])
def test_preflight_errors(reply, match):
    with pytest.raises(PreflightError, match=match):
        ollama_preflight(_cfg(), opener=FakeOpener(reply))


# --- CLI `run` ----------------------------------------------------------------------------------

@pytest.fixture
def cli_fake(monkeypatch, fake):
    """cli.run_pipeline with the fake stages injected (preflight argument kept as the CLI passes it)."""
    real = pipeline.run_pipeline

    def wrapper(*args, **kw):
        return real(*args, deps=StageDeps(runners=fake.runners()), **kw)

    monkeypatch.setattr(cli, "run_pipeline", wrapper)
    return fake


def test_cli_run_output(cli_fake, config_file, capsys):
    assert cli.main(["run", "video.mp4", "--no-preflight", "--config", str(config_file)]) == 0
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert len(lines) == 7
    work, tmp = cli_fake.tmp_path / "work" / "ep1", cli_fake.tmp_path
    assert lines[:6] == [f"ep1\tingested\t{work}",
                         f"ep1\ttranscribed (local_subtitle/subtitle_srt)\t{tmp / 'transcript'}",
                         f"ep1\tanalyzed (5 candidates)\t{tmp / 'analysis'}",
                         f"ep1\tselected (2 clips)\t{tmp / 'selection'}",
                         f"ep1\ttitled (2/2 clips)\t{tmp / 'titling'}",
                         f"ep1\trendered (2/2 clips)\t{tmp / 'out' / 'render_manifest.json'}"]
    assert lines[6] == f"ep1\tdone (2/2 Shorts)\t{tmp / 'out'}"
    assert "AI titles are auto-approved" in out.err
    assert "run: summary [ep1]" in out.err
    assert "  render      ran " in out.err and "  total " in out.err

    assert cli.main(["run", "video.mp4", "--no-preflight", "--config", str(config_file)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [ln.split("\t")[1] for ln in lines[:6]] == ["skipped (up to date)"] * 6
    assert lines[6] == f"ep1\tdone (2/2 Shorts)\t{tmp / 'out'}"


def test_cli_run_error_exit_1(cli_fake, config_file, capsys):
    cli_fake.fail["titling"] = cli.TitlingError("titling failed: no model")
    assert cli.main(["run", "video.mp4", "--no-preflight", "--config", str(config_file)]) == 1
    out = capsys.readouterr()
    assert len(out.out.splitlines()) == 4
    assert "auto-short: error: titling failed: no model" in out.err
    assert "re-run the same command to resume" in out.err
    assert "  titling     error" in out.err
    assert cli_fake.ran()[-1] == "titling"


def test_cli_run_interrupt_exit_130(cli_fake, config_file, capsys):
    cli_fake.fail["render"] = KeyboardInterrupt()
    assert cli.main(["run", "video.mp4", "--no-preflight", "--config", str(config_file)]) == 130
    err = capsys.readouterr().err
    assert "auto-short: interrupted during render; re-run the same command to resume" in err
    assert "  render      interrupted" in err
    assert "Traceback" not in err


def test_cli_run_force_from(cli_fake, config_file, capsys):
    assert cli.main(["run", "v.mp4", "--no-preflight", "--config", str(config_file)]) == 0
    cli_fake.calls.clear()
    assert cli.main(["run", "v.mp4", "--no-preflight", "--force-from", "titling", "--config", str(config_file)]) == 0
    assert [c[0] for c in cli_fake.calls if c[1]] == ["titling"]
    capsys.readouterr()
    with pytest.raises(SystemExit) as info:
        cli.main(["run", "v.mp4", "--force-from", "review", "--config", str(config_file)])
    assert info.value.code == 2
    assert "invalid choice: 'review'" in capsys.readouterr().err


class _TagsHandler(http.server.BaseHTTPRequestHandler):
    models: list[str] = []

    def do_GET(self):
        body = json.dumps(_tags(*self.models)).encode()
        self.send_response(200 if self.path == "/api/tags" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def ollama_server():
    """A local HTTP server answering GET /api/tags with ``_TagsHandler.models``."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _TagsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _config(tmp_path, host: str):
    p = tmp_path / "run.toml"
    p.write_text(f'[workspace]\ndir = "{(tmp_path / "work").as_posix()}"\n'
                 f'[selection]\nollama_host = "{host}"\n[titling]\nollama_host = "{host}"\n'
                 '[transcript.providers]\nwhisper = false\n', encoding="utf-8")
    return p


def test_cli_preflight_real_http(video, tmp_path, capsys, ollama_server, monkeypatch):
    """E8 with real HTTP: a failing preflight leaves the workspace untouched; --no-preflight skips it."""
    assert cli.main(["ingest", str(video), "--config", str(_config(tmp_path, ollama_server))]) == 0
    eid = capsys.readouterr().out.split("\t")[0]
    manifest = tmp_path / "work" / eid / "manifest.json"
    before = manifest.read_bytes()

    monkeypatch.setattr(_TagsHandler, "models", ["qwen3:14b"])
    cfg = _config(tmp_path, ollama_server)
    assert cli.main(["run", str(video), "--config", str(cfg)]) == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.strip().splitlines()[-1] == (
        f"auto-short: error: ollama preflight: model 'qwen3:30b' ([selection] model) is not available at "
        f"{ollama_server} (ollama pull qwen3:30b)")
    assert manifest.read_bytes() == before

    dead = f"http://127.0.0.1:{_closed_port()}"
    assert cli.main(["run", str(video), "--config", str(_config(tmp_path, dead))]) == 1
    err = capsys.readouterr().err
    assert f"auto-short: error: ollama preflight: cannot reach Ollama at {dead}" in err
    assert manifest.read_bytes() == before

    monkeypatch.setenv("OLLAMA_HOST", dead)  # env overrides config, like the stages
    assert cli.main(["run", str(video), "--config", str(cfg)]) == 1
    assert "cannot reach Ollama at " + dead in capsys.readouterr().err

    # --no-preflight: the stages run (real stages; without a subtitle and with Whisper off transcript fails)
    monkeypatch.delenv("OLLAMA_HOST")
    assert cli.main(["run", str(video), "--no-preflight", "--config", str(_config(tmp_path, dead))]) == 1
    out = capsys.readouterr()
    assert out.out.startswith(f"{eid}\tskipped (up to date)\t")
    assert "ollama preflight" not in out.err
    assert "auto-short: error: transcript failed" in out.err
