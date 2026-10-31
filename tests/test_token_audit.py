"""Token audit uses temporary transcripts only; never reads the user's home."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("token_audit", Path(__file__).parents[1] / "scripts/token-audit.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


@pytest.fixture
def transcript(tmp_path):
    def write(chunks, path=None):
        path = path or tmp_path / "session.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        events = []
        for chunk in chunks:
            message = {"id": "msg-1", "model": "claude-opus-5-5", **chunk}
            events.append({"type": "assistant", "timestamp": "2026-10-25T12:00:00Z", "message": message})
        path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
        return path
    return write


@pytest.mark.parametrize("tools, expected", [
    ([], "reply"),
    ([("Agent", "")], "delegate"),
    ([("Bash", "cd repo && codex exec 'implement'")], "delegate"),
    ([("Bash", "python -m pytest -q")], "test"),
    ([("Bash", "node --check app.js")], "test"),
    ([("Bash", "node scripts/framework-check.mjs")], "test"),
    ([("Bash", "git status")], "git"),
    ([("Bash", "  gh pr view 1")], "git"),
    ([("Bash", "tmux list-sessions")], "ops"),
    ([("Bash", "curl localhost")], "ops"),
    ([("Bash", "auto-short run example")], "ops"),
    ([("Bash", "ffmpeg -version")], "ops"),
    ([("Bash", "python scripts/run.py")], "ops"),
    *[([(name, "")], "edit") for name in ("Edit", "Write", "NotebookEdit")],
    *[([(name, "")], "read") for name in ("Read", "Grep", "Glob", "ToolSearch")],
    ([("Unknown", "")], "other"),
    ([("Bash", "pytest"), ("Agent", "")], "delegate"),
    ([("Bash", "git status"), ("Bash", "pytest")], "test"),
    ([("Bash", "tmux ls"), ("Bash", "git status")], "git"),
    ([("Edit", ""), ("Bash", "ffmpeg -version")], "ops"),
    ([("Read", ""), ("Write", "")], "edit"),
    ([("Unknown", ""), ("Read", "")], "read"),
])
def test_classification_from_jsonl(transcript, tools, expected):
    content = [{"type": "tool_use", "name": name, "input": {"command": command}} for name, command in tools]
    path = transcript([{"usage": {"input_tokens": 100, "output_tokens": 5}, "content": content}])
    records = audit.turns(path)
    assert len(records) == 1
    assert records[0]["tools"] == tools
    assert audit.classify_turn(records[0]) == expected


def test_streaming_chunks_keep_tools_and_max_output(transcript):
    path = transcript([
        {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "secret"}}]},
        {"usage": {"input_tokens": 100, "output_tokens": 9}, "content": []},
        {"usage": {"output_tokens": 4}, "content": []},
        {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]},
        {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]},
    ])
    records = audit.turns(path)
    assert len(records) == 1
    assert records[0]["out"] == 9
    assert records[0]["usage"]["input_tokens"] == 100
    assert records[0]["tools"] == [("Read", ""), ("Bash", "pytest -q")]
    assert audit.classify_turn(records[0]) == "test"


@pytest.mark.parametrize("returncode, stdout, expected", [
    (0, "2026-10-19\n2026-10-20\n2026-10-25\n2026-10-31\n2026-11-01\n", 3),
    (0, "", 0),
    (128, "", None),
])
def test_merged_prs_uses_remote_ref(tmp_path, monkeypatch, capsys, returncode, stdout, expected):
    def run(command, **kwargs):
        assert command == ["git", "-C", str(tmp_path), "log", "--merges", "--first-parent",
                           "origin/main", "--format=%ad", "--date=short"]
        assert kwargs == {"capture_output": True, "text": True}
        return subprocess.CompletedProcess(command, returncode, stdout, "missing ref" if returncode else "")
    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.merged_prs(tmp_path, "2026-10-20", "2026-10-31") == expected
    warning = capsys.readouterr().err
    assert ("WARNING" in warning and "origin/main" in warning) if returncode else not warning


def test_main_work_cost_is_sorted_aggregated_and_private(tmp_path, transcript, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    project = tmp_path / ".claude/projects/youtube-test"
    transcript([
        {"id": "read", "usage": {"input_tokens": 100_000}, "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "PRIVATE_PATH"}}]},
        {"id": "ops", "usage": {"input_tokens": 300_000}, "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "echo PRIVATE_COMMAND"}},
            {"type": "text", "text": "PRIVATE_TEXT"}]},
    ], project / "main.jsonl")
    transcript([{"usage": {"input_tokens": 1_000_000}, "content": []}],
               project / "session/subagents/agent.jsonl")
    monkeypatch.setattr(audit, "merged_prs", lambda *args: None)
    monkeypatch.setattr(audit.sys, "argv", ["token-audit.py", "--since", "2026-10-20", "--until", "2026-10-31"])
    assert audit.main() == 0
    output = capsys.readouterr().out
    section = output.split("main session cost by work type (% of MAIN cost):\n")[1].split("main input above")[0]
    rows = [line.split() for line in section.splitlines()]
    assert rows == [["ops", "turns", "1", "$", "1.20", "75.0%"],
                    ["read", "turns", "1", "$", "0.40", "25.0%"]]
    assert "PRIVATE" not in output
    assert "merged PRs on origin/main: unavailable" in output
