"""Titling stage: request (AC3), artifacts (AC2/AC4/AC6), retries/failures (AC5), resume (AC7), CLI."""

import hashlib
import json
from dataclasses import replace

import pytest

from auto_short import config as config_mod
from auto_short.cli import main
from auto_short.config import Config, WorkspaceConfig
from auto_short.hashing import canonical_json, config_hash, sha256_file
from auto_short.selection import run_selection
from auto_short.titling import TitlingError, run_titling
from auto_short.titling.prompt import RESPONSE_SCHEMA, prompt_sha256, system_prompt
from auto_short.titling.stage import used_config
from selection_helpers import SYN_ANALYSIS, FakeClient as SelectionClient, proposal, response
from titling_helpers import SELECTION, FakeClient, good_reply, http_error, make_titling_episode, option, reply
from transcript_helpers import manifest_of

ARTIFACTS = ["titles.json", "titling_log.json"]
HEADER = ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"]
EID = "rbjfCfFq3Dk"


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), analysis=SYN_ANALYSIS)


def _load(ws, name):
    return json.loads((ws.dir / name).read_text(encoding="utf-8"))


def _ti(cfg, **kw):
    return replace(cfg, titling=replace(cfg.titling, **kw))


def _hdr(cfg, **kw):
    return replace(cfg, titling=replace(cfg.titling, header=replace(cfg.titling.header, **kw)))


def _sha(doc):
    return hashlib.sha256(canonical_json(doc).encode()).hexdigest()


class NoSleep:
    def __init__(self):
        self.waits = []

    def __call__(self, s):
        self.waits.append(s)


# --- AC3: request -------------------------------------------------------------------------------------

def test_request_follows_g4(tcfg):
    make_titling_episode(tcfg.workspace.dir, prefix={2: "thế là còn"})
    fake = FakeClient()
    run_titling(EID, tcfg, client=fake)
    assert [c["clip"] for c in fake.calls] == [2, 7]  # one call per clip, clip order
    call = fake.calls[0]
    assert call["model"] == "qwen3:30b" and call["think"] is True
    assert call["options"] == {"temperature": 0, "seed": 42, "num_ctx": 16384}
    assert call["format"] == RESPONSE_SCHEMA
    system, user = call["messages"]
    assert system == {"role": "system", "content": system_prompt("v1", max_chars=60, n_options=3)}
    assert user["role"] == "user"
    assert user["content"].startswith("Video: Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập 9 - Lão Pháp Sư Tịnh Không\n"
                                      "Thời lượng Short: ")
    # head cut words are not in the clip text
    assert "\n\nLời nói của đoạn:\ný thứ 2 phần đầu chúng ta học kinh ý thứ 2 phần cuối" in user["content"]
    assert "thế là" not in user["content"]

    two = {n: [reply(*json.loads(good_reply(n))["options"][:2])] for n in (2, 7)}
    fake2 = FakeClient(two)
    run_titling(EID, _ti(tcfg, model="qwen3:14b", think=False, seed=7, num_ctx=8192, temperature=0.2,
                         max_chars=40, n_options=2), client=fake2, sleep=NoSleep())
    call = fake2.calls[0]
    assert (call["model"], call["think"]) == ("qwen3:14b", False)
    assert call["options"] == {"temperature": 0.2, "seed": 7, "num_ctx": 8192}
    assert "tối đa 40 ký tự" in call["messages"][0]["content"] and "đúng 2 phương án" in call["messages"][0]["content"]


# --- AC2 / AC4 / AC6: artifacts -----------------------------------------------------------------------------

BAD_FIRST = {2: [reply(option("Ý thứ 2 khi học kinh!", "ý thứ 2 phần đầu chúng ta học kinh"),
                       option("Ý thứ hai", "ý thứ 2 phần cuối"),                        # too short (9)
                       option("Nhớ kỹ ý thứ 2 khi học", "ý thứ 2 phần cuối xin nhớ kỹ"))]}


def test_titles_and_log_documents(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir, prefix={2: "thế là còn"})
    result = run_titling(EID, tcfg, client=FakeClient(BAD_FIRST))
    assert result.ran and (result.titled, result.clips) == (2, 2) and result.path == ws.dir / "titles.json"

    clips_doc, cands = _load(ws, "clips.json"), _load(ws, "candidates.json")
    doc = _load(ws, "titles.json")
    assert list(doc) == ["schema_version", "episode_id", "clips_sha256", "candidates_sha256", "header", "model",
                         "prompt_version", "prompt_sha256", "params", "stats", "titles"]
    assert doc["schema_version"] == 1 and doc["episode_id"] == EID
    assert doc["clips_sha256"] == _sha(clips_doc) and doc["candidates_sha256"] == _sha(cands)
    assert doc["header"]["lines"] == HEADER
    assert doc["header"]["sources"] == {"speaker": "config", "series": "metadata", "episode": "metadata"}
    assert doc["model"] == {"provider": "ollama", "name": "qwen3:30b", "think": True,
                            "options": {"temperature": 0, "seed": 42, "num_ctx": 16384}}
    assert doc["prompt_version"] == "v1" and doc["prompt_sha256"] == prompt_sha256("v1")
    assert doc["params"] == {"n_options": 3, "min_chars": 10, "max_chars": 60, "retries": 2}
    assert doc["stats"] == {"clips": 2, "ai_calls": 2, "titled": 2, "untitled": 0}
    t1, t2 = doc["titles"]
    assert (t1["clip_id"], t1["candidate_id"], t1["status"]) == ("k01", "c00008", "titled")
    assert list(t1) == ["clip_id", "candidate_id", "title", "evidence", "alternatives", "status"]
    # first valid option in AI order; no other valid option -> no alternatives
    assert (t1["title"], t1["evidence"], t1["alternatives"]) == \
        ("Nhớ kỹ ý thứ 2 khi học", "ý thứ 2 phần cuối xin nhớ kỹ", [])
    assert t2["title"] == "Ý thứ 7 khi học kinh" and [a["title"] for a in t2["alternatives"]] == \
        ["Nhớ kỹ ý thứ 7", "Học kinh phần đầu ý 7"]

    lg = _load(ws, "titling_log.json")
    assert list(lg) == ["schema_version", "episode_id", "clips_sha256", "model", "prompt_version", "prompt_sha256",
                        "system_prompt", "response_format", "header", "stats", "clips"]
    assert lg["stats"] == doc["stats"] and lg["response_format"] == RESPONSE_SCHEMA and lg["header"] == doc["header"]
    c1 = lg["clips"][0]
    assert (c1["clip_id"], c1["candidate_id"]) == ("k01", "c00008") and c1["text"].startswith("ý thứ 2 phần đầu")
    call = c1["ai_calls"][0]
    assert list(call) == ["attempt", "backoff_seconds", "seconds", "request", "response", "error", "options"]
    assert call["attempt"] == 1 and call["error"] is None and call["backoff_seconds"] == 0
    assert call["request"]["messages"][0]["content"] == lg["system_prompt"]
    assert call["request"]["stream"] is False and call["request"]["format"] == RESPONSE_SCHEMA
    assert call["response"] == {"content": BAD_FIRST[2][0], "thinking": "nghĩ", "eval_count": 10,
                                "prompt_eval_count": 100, "total_duration": 123, "done_reason": "stop"}
    assert [(o["status"], o["reject_reason"]) for o in call["options"]] == [
        ("invalid", "exclamation mark"), ("invalid", "too short (9 < 10 chars)"), ("valid", None)]

    entry = manifest_of(ws)["stages"]["titling"]
    assert entry["status"] == "done" and entry["artifacts"] == ARTIFACTS
    assert entry["inputs"] == [{"path": n, "sha256": sha256_file(ws.dir / n)}
                               for n in ("clips.json", "candidates.json", "metadata.json")]
    assert entry["config_hash"] == config_hash(used_config(tcfg, HEADER))


def test_used_config_keys(tcfg):
    used = used_config(tcfg, HEADER)
    assert set(used) == {f"titling.{k}" for k in ("model", "think", "temperature", "seed", "num_ctx", "prompt_version",
                                                   "n_options", "min_chars", "max_chars", "retries", "prompt_sha256",
                                                   "header.lines")}
    assert used_config(_ti(tcfg, ollama_host="http://x:1", timeout=5, retry_backoff=()), HEADER) == used


def test_empty_clips_done_without_ai(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir, selection={"w01": [response()], "w02": [response()]})
    assert _load(ws, "clips.json")["clips"] == []
    fake = FakeClient()
    result = run_titling(EID, tcfg, client=fake)
    assert result.ran and (result.titled, result.clips) == (0, 0) and fake.calls == []
    doc = _load(ws, "titles.json")
    assert doc["titles"] == [] and doc["stats"] == {"clips": 0, "ai_calls": 0, "titled": 0, "untitled": 0}
    assert manifest_of(ws)["stages"]["titling"]["status"] == "done"


def test_candidates_mismatch_fails(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir)
    cands = _load(ws, "candidates.json")
    cands["units"][0]["text"] += " x"
    (ws.dir / "candidates.json").write_text(json.dumps(cands, ensure_ascii=False), encoding="utf-8")
    fake = FakeClient()
    with pytest.raises(TitlingError, match="clips.json does not match candidates.json"):
        run_titling(EID, tcfg, client=fake)
    assert fake.calls == []
    _assert_failed(ws, "candidates_sha256")


def test_head_cut_mismatch_fails(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir, prefix={2: "thế là"})
    clips = _load(ws, "clips.json")
    clips["clips"][0]["head_cut"]["words"] = "cho nên"
    (ws.dir / "clips.json").write_text(json.dumps(clips, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TitlingError, match="head_cut words 'cho nên' do not match"):
        run_titling(EID, tcfg, client=FakeClient())
    _assert_failed(ws, "head_cut")


def _assert_failed(ws, error_part):
    entry = manifest_of(ws)["stages"]["titling"]
    assert entry["status"] == "failed" and error_part in entry["error"] and entry["artifacts"] == []
    assert not any((ws.dir / n).exists() for n in ARTIFACTS)


# --- AC1: header in the stage ----------------------------------------------------------------------------

def test_header_flags_and_missing_field(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir, title=None)  # no metadata title (like a local video)
    fake = FakeClient()
    with pytest.raises(TitlingError, match=r"series \(pass --series"):
        run_titling(EID, tcfg, client=fake)
    assert fake.calls == []
    _assert_failed(ws, "--episode")

    run_titling(EID, tcfg, series="Kinh Vô Lượng Thọ", episode="3", client=fake)
    doc = _load(ws, "titles.json")
    assert doc["header"]["lines"] == ["HT.Tịnh Không", "Kinh Vô Lượng Thọ (tập 3)"]
    assert doc["header"]["sources"] == {"speaker": "config", "series": "cli", "episode": "cli"}
    # a different resolved header re-runs; the same one skips; flags are not stored
    assert not run_titling(EID, tcfg, series="Kinh Vô Lượng Thọ", episode="3", client=fake).ran
    assert run_titling(EID, tcfg, series="Kinh Vô Lượng Thọ", episode="4", client=fake).ran
    assert run_titling(EID, _hdr(tcfg, series="Kinh Vô Lượng Thọ", episode="4"), client=fake).ran is False
    with pytest.raises(TitlingError):
        run_titling(EID, tcfg, client=fake)


# --- AC4 / P3: no valid option -> retry -> untitled --------------------------------------------------------------

ALL_BAD = reply(option("Quá ngắn", "ý thứ 7 phần đầu"), option("Ý thứ 7 🙏 học kinh", "ý thứ 7 phần đầu"),
                option("Ý thứ bảy của bài kinh", "một câu không có trong đoạn"))


def test_no_valid_option_retries_then_untitled(tcfg, caplog):
    ws = make_titling_episode(tcfg.workspace.dir)
    caplog.set_level("INFO", logger="auto_short")
    sleep = NoSleep()
    fake = FakeClient({7: [ALL_BAD]})
    result = run_titling(EID, tcfg, client=fake, sleep=sleep)
    assert result.ran and (result.titled, result.clips) == (1, 2)
    assert [c["clip"] for c in fake.calls] == [2, 7, 7, 7] and sleep.waits == [5.0, 15.0]
    doc = _load(ws, "titles.json")
    assert doc["stats"] == {"clips": 2, "ai_calls": 4, "titled": 1, "untitled": 1}
    assert doc["titles"][1] == {"clip_id": "k02", "candidate_id": "c00015", "title": None, "evidence": None,
                                "alternatives": [], "status": "untitled"}
    calls = _load(ws, "titling_log.json")["clips"][1]["ai_calls"]
    assert [(c["attempt"], c["backoff_seconds"], c["error"]) for c in calls] == \
        [(1, 0, "no valid option"), (2, 5.0, "no valid option"), (3, 15.0, "no valid option")]
    assert [o["reject_reason"] for o in calls[0]["options"]] == \
        ["too short (8 < 10 chars)", "emoji/pictograph", "evidence not in clip text"]
    assert manifest_of(ws)["stages"]["titling"]["status"] == "done"
    assert "WARNING: clip k02 untitled" in caplog.text and "WARNING: 1 clip(s) untitled: k02" in caplog.text


def test_invalid_then_valid_retry(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir)
    fake = FakeClient({2: [ALL_BAD.replace("7", "2"), http_error(), good_reply(2)]})
    run_titling(EID, tcfg, client=fake, sleep=NoSleep())
    doc = _load(ws, "titles.json")
    assert doc["titles"][0]["title"] == "Ý thứ 2 khi học kinh" and doc["stats"]["ai_calls"] == 4
    errors = [c["error"] for c in _load(ws, "titling_log.json")["clips"][0]["ai_calls"]]
    assert errors == ["no valid option", "HTTP 500 from fake: boom", None]


def test_mixed_invalid_and_errors_is_untitled(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir)
    run_titling(EID, tcfg, client=FakeClient({2: [ALL_BAD, http_error(), http_error()]}), sleep=NoSleep())
    assert _load(ws, "titles.json")["titles"][0]["status"] == "untitled"


# --- AC5: response errors --------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [http_error(), "không phải JSON", '{"options": []}',
                                 reply(option("Ý thứ 2 khi học kinh", "ý thứ 2 phần đầu chúng ta"))])
def test_error_then_success(tcfg, bad):
    ws = make_titling_episode(tcfg.workspace.dir)
    sleep = NoSleep()
    fake = FakeClient({2: [bad, good_reply(2)]})
    run_titling(EID, tcfg, client=fake, sleep=sleep)
    assert sleep.waits == [5.0]
    calls = _load(ws, "titling_log.json")["clips"][0]["ai_calls"]
    assert [c["attempt"] for c in calls] == [1, 2] and calls[0]["error"] and calls[1]["error"] is None
    assert calls[0]["options"] == []


def test_errors_exhaust_retries_fail(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir)
    run_titling(EID, tcfg, client=FakeClient())
    sleep = NoSleep()
    fake = FakeClient({7: ["{}"]})
    with pytest.raises(TitlingError, match=r"clip k02: .*\"options\" array \(after 3 attempts\)"):
        run_titling(EID, tcfg, force=True, client=fake, sleep=sleep)
    assert sleep.waits == [5.0, 15.0] and [c["clip"] for c in fake.calls] == [2, 7, 7, 7]
    _assert_failed(ws, "clip k02")

    fake = FakeClient({2: [http_error()]})
    with pytest.raises(TitlingError, match=r"clip k01: HTTP 500 .*\(after 1 attempts\)"):
        run_titling(EID, _ti(tcfg, retries=0), client=fake, sleep=NoSleep())
    assert len(fake.calls) == 1


# --- AC7: resume ---------------------------------------------------------------------------------------------

def test_rerun_skips_and_config_changes(tcfg, caplog):
    ws = make_titling_episode(tcfg.workspace.dir)
    assert run_titling(EID, tcfg, client=FakeClient()).ran
    before = {n: (ws.dir / n).read_bytes() for n in ARTIFACTS}
    caplog.set_level("INFO", logger="auto_short")
    fake = FakeClient()
    assert not run_titling(EID, tcfg, client=fake).ran and fake.calls == []
    assert "titling: skip (up to date)" in caplog.text
    assert (ws.dir / "titles.json").read_bytes() == before["titles.json"]
    # execution-only keys and other stages' config -> skip
    for cfg in (_ti(tcfg, ollama_host="http://x:1", timeout=5, retry_backoff=(1.0,)),
                replace(tcfg, selection=replace(tcfg.selection, min_score=9))):
        assert not run_titling(EID, cfg, client=fake).ran
    # hashed keys -> run
    for kw in ({"model": "qwen3:14b"}, {"think": False}, {"temperature": 0.5}, {"seed": 1}, {"num_ctx": 8192},
               {"n_options": 2}, {"min_chars": 5}, {"max_chars": 40}, {"retries": 1}):
        cfg = _ti(tcfg, **kw)
        n = kw.get("n_options", 3)
        f = FakeClient({2: [reply(*json.loads(good_reply(2))["options"][:n])],
                        7: [reply(*json.loads(good_reply(7))["options"][:n])]})
        assert run_titling(EID, cfg, client=f).ran, kw
        assert not run_titling(EID, cfg, client=f).ran, kw
    assert run_titling(EID, _hdr(tcfg, speaker="Pháp sư Tịnh Không"), client=fake).ran
    assert run_titling(EID, _hdr(tcfg, speaker="Pháp sư Tịnh Không"), force=True, client=fake).ran


def test_unknown_prompt_version(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir)
    with pytest.raises(TitlingError, match="unknown prompt_version 'v9'"):
        run_titling(EID, _ti(tcfg, prompt_version="v9"), client=FakeClient())
    assert "titling" not in manifest_of(ws)["stages"]


def test_selection_rerun_marks_titling_stale_and_reruns(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir)
    run_titling(EID, tcfg, client=FakeClient())
    run_selection(EID, tcfg, force=True, client=SelectionClient({"w01": [response(proposal("u0002", "u0005", 9))],
                                                                 "w02": [response()]}))
    assert manifest_of(ws)["stages"]["titling"]["status"] == "stale"
    fake = FakeClient()
    result = run_titling(EID, tcfg, client=fake)
    assert result.ran and result.clips == 1 and len(fake.calls) == 1


@pytest.mark.parametrize("status", ["failed", "stale", "running"])
def test_selection_not_done_fails(tcfg, status):
    ws = make_titling_episode(tcfg.workspace.dir)
    manifest = manifest_of(ws)
    manifest["stages"]["selection"]["status"] = status
    ws.save_manifest(manifest)
    fake = FakeClient()
    with pytest.raises(TitlingError, match="selection is not done"):
        run_titling(EID, tcfg, client=fake)
    assert fake.calls == []
    _assert_failed(ws, "run 'auto-short selection' first")


def test_missing_clips_file_fails(tcfg):
    ws = make_titling_episode(tcfg.workspace.dir)
    (ws.dir / "clips.json").unlink()
    with pytest.raises(TitlingError, match="selection is not done"):
        run_titling(EID, tcfg, client=FakeClient())


def test_no_manifest(tcfg):
    with pytest.raises(TitlingError, match="no manifest"):
        run_titling(EID, tcfg, client=FakeClient())


# --- CLI -----------------------------------------------------------------------------------------------------

def test_cli_titling(tcfg, tmp_path, monkeypatch, capsys):
    ws = make_titling_episode(tcfg.workspace.dir)
    cfg_file = tmp_path / "c.toml"
    cfg_file.write_text(f'[workspace]\ndir = "{tcfg.workspace.dir.as_posix()}"\n'
                        '[analysis]\noutro_window = 5.0\n', encoding="utf-8")
    fake = FakeClient()
    monkeypatch.setattr("auto_short.titling.stage.OllamaClient", lambda host, timeout: fake)
    assert main(["titling", EID, "--config", str(cfg_file)]) == 0
    out, err = capsys.readouterr()
    assert out == f"{EID}\ttitled (2/2 clips)\t{ws.dir / 'titles.json'}\n"
    assert "titling: header HT.Tịnh Không | Thập Thiện Nghiệp Đạo Kinh (tập 9)" in err
    assert "titling: clip k01: 'Ý thứ 2 khi học kinh' (3/3 options valid" in err
    assert main(["titling", EID, "--config", str(cfg_file)]) == 0
    assert capsys.readouterr().out == f"{EID}\tskipped (up to date)\t{ws.dir / 'titles.json'}\n"
    assert main(["titling", EID, "--config", str(cfg_file), "--speaker", "HT. Tịnh Không", "--episode", "10"]) == 0
    assert _load(ws, "titles.json")["header"]["lines"] == ["HT. Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 10)"]
    capsys.readouterr()
    assert main(["status", EID, "--config", str(cfg_file)]) == 0
    assert "titling     done" in capsys.readouterr().out

    fake.replies = {2: [http_error()]}
    cfg_file.write_text(cfg_file.read_text(encoding="utf-8") + "[titling]\nretry_backoff = []\n", encoding="utf-8")
    assert main(["titling", EID, "--config", str(cfg_file), "--force"]) == 1
    assert "auto-short: error: titling failed: clip k01: HTTP 500" in capsys.readouterr().err
    assert manifest_of(ws)["stages"]["titling"]["status"] == "failed"
    assert not any((ws.dir / n).exists() for n in ARTIFACTS)


def test_host_from_env(tcfg, monkeypatch):
    make_titling_episode(tcfg.workspace.dir)
    seen = {}

    def factory(host, timeout):
        seen.update(host=host, timeout=timeout)
        return FakeClient()

    monkeypatch.setattr("auto_short.titling.stage.OllamaClient", factory)
    monkeypatch.setenv("OLLAMA_HOST", "gpu:1234")
    run_titling(EID, _ti(tcfg, timeout=30))
    assert seen == {"host": "http://gpu:1234", "timeout": 30.0}
    monkeypatch.delenv("OLLAMA_HOST")
    run_titling(EID, tcfg, force=True)
    assert seen["host"] == "http://127.0.0.1:11437"


def test_example_config_titling_defaults():
    from pathlib import Path
    cfg = config_mod.load(Path(__file__).parents[1] / "config.example.toml")
    assert cfg.titling == Config().titling
