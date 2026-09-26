import json
import subprocess
import sys

from auto_short.cli import main


def test_cli_ingest_then_status(video, config_file, tmp_path, capsys):
    assert main(["ingest", str(video), "--config", str(config_file)]) == 0
    out = capsys.readouterr()
    episode_id = out.out.split("\t")[0]
    assert "ingested" in out.out

    assert main(["ingest", str(video), "--config", str(config_file)]) == 0
    out = capsys.readouterr()
    assert "skipped (up to date)" in out.out
    assert "ingest: skip (up to date)" in out.err

    assert main(["status", episode_id, "--config", str(config_file)]) == 0
    out = capsys.readouterr().out
    assert f"episode:   {episode_id}" in out
    assert "ingest      done" in out
    assert "transcript  pending" in out
    assert "render      pending" in out


def test_cli_errors_exit_nonzero(tmp_path, config_file, capsys):
    assert main(["ingest", str(tmp_path / "missing.mp4"), "--config", str(config_file)]) == 1
    assert "error: source file not found" in capsys.readouterr().err

    assert main(["status", "nope", "--config", str(config_file)]) == 1
    assert "no manifest" in capsys.readouterr().err

    assert main(["ingest", "x.mp4", "--config", str(tmp_path / "missing.toml")]) == 1
    assert "config file not found" in capsys.readouterr().err


def test_cli_status_shows_failure(tmp_path, config_file, capsys):
    bogus = tmp_path / "bad.mp4"
    bogus.write_text("nope")
    assert main(["ingest", str(bogus), "--episode-id", "bad", "--config", str(config_file)]) == 1
    capsys.readouterr()
    assert main(["status", "bad", "--config", str(config_file)]) == 0
    assert "ingest      failed" in capsys.readouterr().out


def test_python_dash_m(video, config_file, tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "auto_short", "ingest", str(video), "--config", str(config_file)],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    episode_id = proc.stdout.split("\t")[0]
    manifest = json.loads((tmp_path / "work" / episode_id / "manifest.json").read_text())
    assert manifest["stages"]["ingest"]["status"] == "done"
