"""Selection stage: request (AC2), artifacts (AC3/AC4/AC6), retries/failures (AC5), resume (AC7), CLI, client."""

import hashlib
import json
import socket
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from auto_short import config as config_mod
from auto_short.analysis import run_analysis
from auto_short.cli import main
from auto_short.config import DEFAULT_START_BLOCKLIST, Config, WorkspaceConfig
from auto_short.hashing import canonical_json, config_hash, sha256_file
from auto_short.selection import SelectionError, run_selection
from auto_short.selection.client import ChatError, OllamaClient, resolve_host
from auto_short.selection.prompt import RESPONSE_SCHEMA, prompt_sha256, prompt_texts
from auto_short.selection.stage import used_config
from analysis_helpers import FakeAnalyzer
from selection_helpers import (
    SYN_ANALYSIS,
    FakeClient,
    http_error,
    make_selection_episode,
    proposal,
    response,
    synthetic_lecture,
)
from transcript_helpers import manifest_of

ARTIFACTS = ["clips.json", "selection_log.json"]
GOOD = {"w01": [response(proposal("u0002", "u0005", 9, topic="nhân quả", reason="trọn ý"),
                         proposal("u0001", "u0003", 8),                 # overlaps c00008 -> overlapped
                         proposal("u0003", "u0005", 9),                 # shot guard -> rejected
                         proposal("u0005", "u0006", 6))],               # score -> ineligible
        "w02": [response(proposal("u0008", "u0011", 7, start=False),   # ineligible
                         proposal("u0007", "u0010", 8, topic="tu tâm"))]}


@pytest.fixture
def scfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), analysis=SYN_ANALYSIS)


def _load(ws, name):
    return json.loads((ws.dir / name).read_text(encoding="utf-8"))


def _bytes(ws):
    return {n: (ws.dir / n).read_bytes() for n in ARTIFACTS}


def _sel(cfg, **kw):
    return replace(cfg, selection=replace(cfg.selection, **kw))


# --- AC2: request ---------------------------------------------------------------------------------------

def test_request_follows_b3(scfg):
    make_selection_episode(scfg.workspace.dir)
    fake = FakeClient(GOOD)
    run_selection("rbjfCfFq3Dk", scfg, client=fake)
    assert [c["window"] for c in fake.calls] == ["w01", "w02"]
    call = fake.calls[0]
    assert call["model"] == "qwen3:30b" and call["think"] is True
    assert call["options"] == {"temperature": 0, "seed": 42, "num_ctx": 32768}
    assert call["format"] == RESPONSE_SCHEMA
    system, user = call["messages"]
    assert system["role"] == "system" and "TRỌN MỘT Ý" in system["content"]
    assert user["role"] == "user" and user["content"].startswith("Video: (không rõ)\n")  # no title in metadata
    assert "u0001 | từ 0.0 | đến 19.6 | đầu nội dung | ý thứ 1" in user["content"]
    assert "u0002 | từ 20.0 | đến 39.6 | lặng 4.0 s | ý thứ 2" in user["content"]

    fake_v1 = FakeClient(GOOD)
    run_selection("rbjfCfFq3Dk", _sel(scfg, prompt_version="v1"), client=fake_v1)
    assert "u0001 | 19.0 | đầu nội dung | ý thứ 1" in fake_v1.calls[0]["messages"][1]["content"]
    assert fake_v1.calls[0]["messages"][0]["content"] == prompt_texts("v1")[0]

    cfg2 = _sel(scfg, model="qwen3:14b", think=False, seed=7, num_ctx=8192, temperature=0.2)
    fake2 = FakeClient(GOOD)
    run_selection("rbjfCfFq3Dk", cfg2, client=fake2)
    call = fake2.calls[0]
    assert (call["model"], call["think"]) == ("qwen3:14b", False)
    assert call["options"] == {"temperature": 0.2, "seed": 7, "num_ctx": 8192}


# --- AC3 / AC4 / AC6: artifacts ---------------------------------------------------------------------------

def test_clips_and_log_documents(scfg):
    ws = make_selection_episode(scfg.workspace.dir)
    result = run_selection("rbjfCfFq3Dk", scfg, client=FakeClient(GOOD))
    assert result.ran and result.clips == 2 and result.path == ws.dir / "clips.json"

    cands = _load(ws, "candidates.json")
    by_id = {c["id"]: c for c in cands["candidates"]}
    doc = _load(ws, "clips.json")
    assert list(doc) == ["schema_version", "episode_id", "candidates_sha256", "model", "prompt_version",
                         "prompt_sha256", "params", "stats", "clips"]
    assert doc["candidates_sha256"] == hashlib.sha256(canonical_json(cands).encode()).hexdigest()
    assert doc["model"] == {"provider": "ollama", "name": "qwen3:30b", "think": True,
                            "options": {"temperature": 0, "seed": 42, "num_ctx": 32768}}
    assert doc["prompt_version"] == "v2" and doc["prompt_sha256"] == prompt_sha256("v2")
    assert doc["params"] == {"max_clips": 25, "min_score": 7, "max_window_words": 2500, "retries": 2,
                             "start_blocklist": list(DEFAULT_START_BLOCKLIST)}
    assert doc["stats"] == {"windows": 2, "ai_calls": 2, "proposals": 6, "valid": 5, "filtered_start": 0,
                            "eligible": 3, "selected": 2,
                            "selected_seconds": round(by_id["c00008"]["duration"] + by_id["c00015"]["duration"], 3)}
    assert [(c["id"], c["candidate_id"], c["window"]) for c in doc["clips"]] == [("k01", "c00008", "w01"),
                                                                               ("k02", "c00015", "w02")]
    k1 = doc["clips"][0]
    assert (k1["score"], k1["topic"], k1["reason"]) == (9, "nhân quả", "trọn ý")
    for clip in doc["clips"]:
        for k in ("source_start", "source_end", "source_duration", "duration", "in_target", "unit_ids",
                  "segment_ids"):
            assert clip[k] == by_id[clip["candidate_id"]][k]

    lg = _load(ws, "selection_log.json")
    assert list(lg) == ["schema_version", "episode_id", "candidates_sha256", "model", "prompt_version",
                        "prompt_sha256", "system_prompt", "response_format", "stats", "unit_seconds", "windows"]
    assert lg["stats"] == doc["stats"] and lg["response_format"] == RESPONSE_SCHEMA
    w1 = lg["windows"][0]
    assert (w1["id"], w1["unit_ids"], w1["units"], w1["candidates"]) == ("w01", ["u0001", "u0006"], 6, 12)
    call = w1["ai_calls"][0]
    assert call["attempt"] == 1 and call["error"] is None
    assert call["request"]["messages"][0]["content"] == lg["system_prompt"]
    assert call["request"]["format"] == RESPONSE_SCHEMA and call["request"]["stream"] is False
    assert call["response"]["content"] == GOOD["w01"][0] and call["response"]["eval_count"] == 10
    statuses = [(p["first_unit"], p["status"], p["candidate_id"]) for p in w1["proposals"]]
    assert statuses == [("u0002", "selected", "c00008"), ("u0001", "overlapped", "c00002"),
                        ("u0003", "rejected", None), ("u0005", "ineligible", "c00012")]
    assert w1["proposals"][2]["reject_reason"].startswith("no candidate with unit_ids [u0003, u0005]")
    assert w1["proposals"][0]["clip_id"] == "k01"
    assert [p["status"] for p in lg["windows"][1]["proposals"]] == ["ineligible", "selected"]

    entry = manifest_of(ws)["stages"]["selection"]
    assert entry["status"] == "done" and entry["artifacts"] == ARTIFACTS
    assert entry["inputs"] == [{"path": "candidates.json", "sha256": sha256_file(ws.dir / "candidates.json")},
                               {"path": "metadata.json", "sha256": sha256_file(ws.dir / "metadata.json")}]
    assert entry["config_hash"] == config_hash(used_config(scfg))


def test_used_config_excludes_execution_keys(scfg):
    used = used_config(scfg)
    assert set(used) == {f"selection.{k}" for k in ("model", "think", "temperature", "seed", "num_ctx",
                                                     "prompt_version", "max_clips", "min_score", "max_window_words",
                                                     "retries", "start_blocklist", "prompt_sha256")}
    assert used_config(_sel(scfg, ollama_host="http://x:1", timeout=5)) == used


def test_no_clip_is_done_with_empty_list_and_warning(scfg, caplog):
    ws = make_selection_episode(scfg.workspace.dir)
    caplog.set_level("INFO", logger="auto_short")
    result = run_selection("rbjfCfFq3Dk", scfg, client=FakeClient({"w01": [response(proposal("u0001", "u0002", 5))]}))
    assert result.ran and result.clips == 0
    assert _load(ws, "clips.json")["clips"] == []
    assert manifest_of(ws)["stages"]["selection"]["status"] == "done"
    assert "no clip met the criteria" in caplog.text


def test_start_blocklist_filter_in_stage(scfg):
    ws = make_selection_episode(scfg.workspace.dir)
    run_selection("rbjfCfFq3Dk", _sel(scfg, start_blocklist=("ý thứ 2", "ý thứ 7")), client=FakeClient(GOOD))
    doc = _load(ws, "clips.json")
    # c00008 (u0002..) and c00015 (u0007..) filtered; c00002 (u0001..u0003) no longer overlapped
    assert [c["candidate_id"] for c in doc["clips"]] == ["c00002"]
    assert doc["params"]["start_blocklist"] == ["ý thứ 2", "ý thứ 7"]
    assert doc["stats"]["filtered_start"] == 2 and doc["stats"]["valid"] == 5 and doc["stats"]["eligible"] == 1
    props = [p for w in _load(ws, "selection_log.json")["windows"] for p in w["proposals"]]
    assert [(p["candidate_id"], p["reject_reason"]) for p in props if p["status"] == "ineligible"
            and p["reject_reason"].startswith("start connector")] == [("c00008", "start connector: ý thứ 2"),
                                                            ("c00015", "start connector: ý thứ 7")]


def test_max_clips_limit(scfg):
    ws = make_selection_episode(scfg.workspace.dir)
    run_selection("rbjfCfFq3Dk", _sel(scfg, max_clips=1), client=FakeClient(GOOD))
    doc = _load(ws, "clips.json")
    assert [c["candidate_id"] for c in doc["clips"]] == ["c00008"]
    assert _load(ws, "selection_log.json")["windows"][1]["proposals"][1]["status"] == "over_limit"


def test_duplicate_proposals_are_deduped(scfg):
    ws = make_selection_episode(scfg.workspace.dir)
    run_selection("rbjfCfFq3Dk", scfg, client=FakeClient(
        {"w01": [response(proposal("u0002", "u0005", 7), proposal("u0002", "u0005", 9))]}))
    props = _load(ws, "selection_log.json")["windows"][0]["proposals"]
    assert [p["status"] for p in props] == ["rejected", "selected"]
    assert props[0]["reject_reason"] == "duplicate of proposal in w01"
    assert _load(ws, "clips.json")["clips"][0]["score"] == 9


# --- AC5: retries / failures ------------------------------------------------------------------------------

def _assert_failed(ws, needle):
    entry = manifest_of(ws)["stages"]["selection"]
    assert entry["status"] == "failed" and needle in entry["error"] and entry["artifacts"] == []
    assert not any((ws.dir / n).exists() for n in ARTIFACTS)


def test_retry_then_success(scfg):
    ws = make_selection_episode(scfg.workspace.dir)
    fake = FakeClient({"w01": [http_error(), "not json", GOOD["w01"][0]]})
    assert run_selection("rbjfCfFq3Dk", scfg, client=fake).ran
    assert [c["window"] for c in fake.calls] == ["w01", "w01", "w01", "w02"]
    calls = _load(ws, "selection_log.json")["windows"][0]["ai_calls"]
    assert [c["attempt"] for c in calls] == [1, 2, 3]
    assert "HTTP 500" in calls[0]["error"] and calls[0]["response"] is None
    assert "not valid JSON" in calls[1]["error"] and calls[1]["response"]["content"] == "not json"
    assert calls[2]["error"] is None
    assert _load(ws, "clips.json")["stats"]["ai_calls"] == 4


@pytest.mark.parametrize("reply,needle", [(http_error(), "HTTP 500"), ('{"clips": [{"x": 1}]}', "missing"),
                                          ("{", "not valid JSON")])
def test_retries_exhausted_fails_without_artifacts(scfg, reply, needle):
    ws = make_selection_episode(scfg.workspace.dir)
    assert run_selection("rbjfCfFq3Dk", scfg, client=FakeClient(GOOD)).ran
    fake = FakeClient({"w02": [reply]})
    with pytest.raises(SelectionError, match="window w02: .*after 2 attempts"):
        run_selection("rbjfCfFq3Dk", _sel(scfg, retries=1), client=fake)
    assert [c["window"] for c in fake.calls] == ["w01", "w02", "w02"]
    _assert_failed(ws, needle)


def test_unreachable_ollama_fails(scfg):
    ws = make_selection_episode(scfg.workspace.dir)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # closed after the block -> connection refused
    with pytest.raises(SelectionError, match="cannot reach Ollama"):
        run_selection("rbjfCfFq3Dk", _sel(scfg, ollama_host=f"http://127.0.0.1:{port}", retries=0))
    _assert_failed(ws, "cannot reach Ollama")


def test_analysis_not_done_is_refused(scfg):
    ws = make_selection_episode(scfg.workspace.dir, analysis_status="failed")
    fake = FakeClient(GOOD)
    with pytest.raises(SelectionError, match="analysis is not done"):
        run_selection("rbjfCfFq3Dk", scfg, client=fake)
    _assert_failed(ws, "analysis is not done")
    assert fake.calls == []


def test_unknown_prompt_version_and_missing_manifest(scfg):
    with pytest.raises(SelectionError, match="unknown prompt_version"):
        run_selection("rbjfCfFq3Dk", _sel(scfg, prompt_version="v9"), client=FakeClient())
    with pytest.raises(SelectionError, match="no manifest"):
        run_selection("nope", scfg, client=FakeClient())


# --- AC7: resume / stale / force ---------------------------------------------------------------------------

def test_rerun_skip_and_rerun_conditions(scfg, caplog):
    ws = make_selection_episode(scfg.workspace.dir)
    fake = FakeClient(GOOD)
    assert run_selection("rbjfCfFq3Dk", scfg, client=fake).ran
    first, n_calls = _bytes(ws), len(fake.calls)

    caplog.set_level("INFO", logger="auto_short")
    assert not run_selection("rbjfCfFq3Dk", scfg, client=fake).ran
    assert "selection: skip (up to date)" in caplog.text
    assert len(fake.calls) == n_calls and _bytes(ws)["clips.json"] == first["clips.json"]

    # execution-only keys and other stages' config do not rerun
    assert not run_selection("rbjfCfFq3Dk", _sel(scfg, ollama_host="http://other:1", timeout=5), client=fake).ran
    assert not run_selection("rbjfCfFq3Dk", replace(scfg, analysis=replace(scfg.analysis, max_pause=0.7)),
                             client=fake).ran
    assert len(fake.calls) == n_calls

    # any hashed [selection] key reruns
    for kw in ({"prompt_version": "v1"}, {"model": "qwen3:14b"}, {"think": False}, {"start_blocklist": ()},
               {"start_blocklist": ("cho nên",)}, {"min_score": 8}, {"max_clips": 3}, {"seed": 1},
               {"num_ctx": 8192}, {"temperature": 0.1}, {"max_window_words": 3000}, {"retries": 1}):
        assert run_selection("rbjfCfFq3Dk", _sel(scfg, **kw), client=fake).ran, kw
    assert run_selection("rbjfCfFq3Dk", scfg, client=fake).ran
    assert _bytes(ws)["clips.json"] == first["clips.json"]

    # --force always reruns; same fake answers -> identical clips.json
    before = len(fake.calls)
    assert run_selection("rbjfCfFq3Dk", scfg, force=True, client=fake).ran
    assert len(fake.calls) == before + 2 and _bytes(ws)["clips.json"] == first["clips.json"]


def test_analysis_rerun_makes_selection_stale_then_rerun(scfg):
    ws = make_selection_episode(scfg.workspace.dir)
    assert run_selection("rbjfCfFq3Dk", scfg, client=FakeClient(GOOD)).ran
    segments, silences, changes, _ = synthetic_lecture()
    run_analysis("rbjfCfFq3Dk", scfg, force=True, analyzer=FakeAnalyzer(changes=changes, silences=silences))
    assert manifest_of(ws)["stages"]["selection"]["status"] == "stale"
    assert run_selection("rbjfCfFq3Dk", scfg, client=FakeClient(GOOD)).ran

    # selection rerun marks downstream stale
    manifest = manifest_of(ws)
    manifest["stages"]["titling"] = dict(manifest["stages"]["selection"], artifacts=[])
    ws.save_manifest(manifest)
    assert run_selection("rbjfCfFq3Dk", scfg, force=True, client=FakeClient(GOOD)).ran
    assert manifest_of(ws)["stages"]["titling"]["status"] == "stale"


def test_silences_mismatch_fails(scfg):
    ws = make_selection_episode(scfg.workspace.dir)
    sil = _load(ws, "silences.json")
    sil["silences"] = sil["silences"][1:]
    (ws.dir / "silences.json").write_text(json.dumps(sil), encoding="utf-8")
    with pytest.raises(SelectionError, match="silences.json does not match"):
        run_selection("rbjfCfFq3Dk", scfg, client=FakeClient(GOOD))
    _assert_failed(ws, "silences.json does not match")


# --- Ollama client + CLI (fake Ollama HTTP server) ----------------------------------------------------------

class _FakeOllama(BaseHTTPRequestHandler):
    requests: list = []
    replies: dict = {}

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append((self.path, body))
        wid = body["messages"][-1]["content"].split("Đoạn ", 1)[1].split(":", 1)[0]
        content = type(self).replies.get(wid, response())
        if content == "500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":"boom"}')
            return
        data = json.dumps({"model": body["model"], "message": {"role": "assistant", "content": content},
                           "done": True, "done_reason": "stop", "eval_count": 5, "prompt_eval_count": 50,
                           "total_duration": 1000}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def ollama():
    _FakeOllama.requests, _FakeOllama.replies = [], {}
    server = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", _FakeOllama
    server.shutdown()


def test_ollama_client_request_and_errors(ollama):
    host, handler = ollama
    client = OllamaClient(host, timeout=5)
    msgs = [{"role": "user", "content": "Đoạn w01: x"}]
    handler.replies = {"w01": '{"clips": []}'}
    res = client.chat(model="m", messages=msgs, format=RESPONSE_SCHEMA, options={"seed": 1}, think=False)
    assert res.content == '{"clips": []}' and res.eval_count == 5 and res.extra == {"done_reason": "stop"}
    path, body = handler.requests[0]
    assert path == "/api/chat"
    assert body == {"model": "m", "messages": msgs, "format": RESPONSE_SCHEMA, "options": {"seed": 1},
                    "think": False, "stream": False}
    handler.replies = {"w01": "500"}
    with pytest.raises(ChatError, match="HTTP 500"):
        client.chat(model="m", messages=msgs, format=RESPONSE_SCHEMA, options={}, think=False)


def test_resolve_host_env_overrides_config(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert resolve_host("http://127.0.0.1:11435/") == "http://127.0.0.1:11435"
    monkeypatch.setenv("OLLAMA_HOST", "gpu-box:11434")
    assert resolve_host("http://127.0.0.1:11435") == "http://gpu-box:11434"


def test_cli_selection_end_to_end(tmp_path, ollama, monkeypatch, capsys):
    host, handler = ollama
    handler.replies = {"w01": GOOD["w01"][0], "w02": GOOD["w02"][0]}
    monkeypatch.setenv("OLLAMA_HOST", host)
    root = tmp_path / "work"
    ws = make_selection_episode(root)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(f'[workspace]\ndir = "{root.as_posix()}"\n[analysis]\noutro_window = 5.0\n'
                        '[selection]\nollama_host = "http://127.0.0.1:1"\n', encoding="utf-8")
    assert config_mod.load(cfg_file).analysis == SYN_ANALYSIS

    assert main(["selection", "rbjfCfFq3Dk", "--config", str(cfg_file)]) == 0
    out = capsys.readouterr()
    ep, state, path = out.out.rstrip("\n").split("\t")
    assert (ep, state) == ("rbjfCfFq3Dk", "selected (2 clips)") and path.endswith("rbjfCfFq3Dk/clips.json")
    assert "selection: window w01: 6 units" in out.err and "selected=2" in out.err
    assert len(handler.requests) == 2

    assert main(["selection", "rbjfCfFq3Dk", "--config", str(cfg_file)]) == 0
    out = capsys.readouterr()
    assert out.out.split("\t")[1] == "skipped (up to date)" and len(handler.requests) == 2
    assert main(["selection", "rbjfCfFq3Dk", "--force", "--config", str(cfg_file)]) == 0
    assert "selected (2 clips)" in capsys.readouterr().out

    assert main(["status", "rbjfCfFq3Dk", "--config", str(cfg_file)]) == 0
    assert "selection   done" in capsys.readouterr().out

    handler.replies = {"w01": "500"}
    assert main(["selection", "rbjfCfFq3Dk", "--force", "--config", str(cfg_file)]) == 1
    assert "window w01" in capsys.readouterr().err
    assert not (ws.dir / "clips.json").exists()
