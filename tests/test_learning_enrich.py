"""CL1.2 AI enrichment (C7): payload, batch validation, retry/log, preflight, [learning] config keys."""

import io
import json
import urllib.error

import pytest
from learning_helpers import FakeChat, fake_enrichment, learning_config

from auto_short.config import ConfigError, LearningConfig, from_dict
from auto_short.learning.enrich import EnrichmentError, batches, enrich, validate_batch
from auto_short.learning.preflight import LearningPreflightError, learning_preflight
from auto_short.learning.prompt import OUTPUT_SCHEMA, PROMPT_VERSION, batch_payload, prompt_sha256, prompt_texts
from auto_short.selection.client import ChatError

LINES = [{"id": f"s{i:05d}", "start": float(i), "end": i + 0.8, "zh": zh}
         for i, zh in enumerate(["大家好", "我是你们的老师", "今天学习中文", "你吃饭了吗", "再见"], start=1)]
IDS = [ln["id"] for ln in LINES]


def _answer(items, **override):
    """A valid response for ``items`` with per-id overrides ``{id: {field: value}}``."""
    out = []
    for it in items:
        pinyin, vi = fake_enrichment(it["zh"])
        out.append({"id": it["id"], "pinyin": pinyin, "vi": vi, **override.get(it["id"], {})})
    return json.dumps({"lines": out}, ensure_ascii=False)


def _cfg(**kw):
    return LearningConfig(**{"retry_backoff": (5.0, 15.0), **kw})


# --- AC1: payload ------------------------------------------------------------------------------

def test_payload_is_exactly_id_and_zh():
    chat = FakeChat()
    enrich("ep", LINES, _cfg(batch_lines=2), chat, sleep=lambda s: None)
    assert len(chat.calls) == 3
    sent = []
    for call in chat.calls:
        system, user = call["messages"]
        assert system == {"role": "system", "content": prompt_texts("v1")}
        assert user["role"] == "user"
        items = json.loads(user["content"])
        assert all(list(it) == ["id", "zh"] for it in items)
        sent += items
        assert call["format"] == OUTPUT_SCHEMA and call["think"] is False and call["model"] == "qwen3:14b"
        assert call["options"] == {"temperature": 0, "seed": 42, "num_ctx": 8192}
    assert sent == [{"id": ln["id"], "zh": ln["zh"]} for ln in LINES]
    assert batch_payload(LINES[:1]) == '[{"id": "s00001", "zh": "大家好"}]'
    for word in ("start", "end", "0.8", "duration"):
        assert word not in "".join(c["messages"][1]["content"] for c in chat.calls)


def test_batches_are_consecutive():
    assert [[ln["id"] for ln in b] for b in batches(LINES, 2)] == [IDS[:2], IDS[2:4], IDS[4:]]
    assert batches(LINES, 20) == [LINES]


def test_prompt_version_and_sha():
    assert PROMPT_VERSION == "v1" and len(prompt_sha256("v1")) == 64
    with pytest.raises(ValueError, match="unknown prompt_version 'v9'"):
        prompt_texts("v9")


# --- AC3: validation ---------------------------------------------------------------------------

def test_validate_accepts_and_strips_and_ignores_other_fields():
    content = json.dumps({"lines": [
        {"id": "s00002", "pinyin": "  wǒ shì nǐmen de lǎoshī ", "vi": " Tôi là giáo viên của các bạn ",
         "zh": "别的", "start": 99, "end": 100},
        {"id": "s00001", "pinyin": "dà jiā hǎo, lü4 !", "vi": "Chào mọi người", "extra": 1},
    ]}, ensure_ascii=False)
    assert validate_batch(["s00001", "s00002"], content) == {
        "s00001": ("dà jiā hǎo, lü4 !", "Chào mọi người"),
        "s00002": ("wǒ shì nǐmen de lǎoshī", "Tôi là giáo viên của các bạn")}


@pytest.mark.parametrize("content, reason", [
    ("not json", "response is not JSON"),
    ('{"lines": {}}', 'not an object with a "lines" array'),
    ('[]', 'not an object with a "lines" array'),
    ('{"lines": [{"id": "s00001", "pinyin": 1, "vi": "x"}]}', 'lines[0] is not an object with string'),
    ('{"lines": [{"id": "s00001", "pinyin": "a", "vi": "x"}, {"id": "s00001", "pinyin": "a", "vi": "x"},'
     ' {"id": "s00002", "pinyin": "a", "vi": "x"}]}', "duplicate id: s00001"),
    ('{"lines": [{"id": "s00001", "pinyin": "a", "vi": "x"}]}', "missing id: s00002"),
    ('{"lines": [{"id": "s00001", "pinyin": "a", "vi": "x"}, {"id": "s00002", "pinyin": "a", "vi": "x"},'
     ' {"id": "s00009", "pinyin": "a", "vi": "x"}]}', "unexpected id: s00009"),
    ('{"lines": [{"id": "s00001", "pinyin": "  ", "vi": "x"}, {"id": "s00002", "pinyin": "a", "vi": "x"}]}',
     "s00001: empty pinyin"),
    ('{"lines": [{"id": "s00001", "pinyin": "a", "vi": "x"}, {"id": "s00002", "pinyin": "nǐ 好", "vi": "x"}]}',
     "s00002: pinyin contains Han character '好'"),
    ('{"lines": [{"id": "s00001", "pinyin": "a", "vi": "x"}, {"id": "s00002", "pinyin": "ni хорошо", "vi": "x"}]}',
     "s00002: pinyin contains non-Latin letter"),
    ('{"lines": [{"id": "s00001", "pinyin": "a", "vi": ""}, {"id": "s00002", "pinyin": "a", "vi": "x"}]}',
     "s00001: empty vi"),
])
def test_validate_rejects(content, reason):
    result = validate_batch(["s00001", "s00002"], content)
    assert isinstance(result, str) and reason in result


def test_validate_extension_a_han_rejected():
    content = json.dumps({"lines": [{"id": "s00001", "pinyin": "a 㐀", "vi": "x"}]}, ensure_ascii=False)
    assert "Han character" in validate_batch(["s00001"], content)


# --- AC3: retry, log, exhaustion ---------------------------------------------------------------

@pytest.mark.parametrize("bad, reason", [
    (lambda items: _answer(items[:-1]), "missing id"),
    (lambda items: _answer(items + [{"id": "s09999", "zh": "多"}]), "unexpected id: s09999"),
    (lambda items: json.dumps({"lines": json.loads(_answer(items))["lines"] * 2}), "duplicate id"),
    (lambda items: _answer(items, s00001={"pinyin": ""}), "s00001: empty pinyin"),
    (lambda items: _answer(items, s00001={"vi": "   "}), "s00001: empty vi"),
    (lambda items: _answer(items, s00001={"pinyin": "dà jiā 好"}), "s00001: pinyin contains Han character"),
])
def test_retry_then_success_logs_every_attempt(bad, reason):
    chat = FakeChat(script=[bad, ChatError("timeout after 600 s")])
    waits = []
    result, log_doc = enrich("ep", LINES[:2], _cfg(), chat, sleep=waits.append)
    assert result == {ln["id"]: fake_enrichment(ln["zh"]) for ln in LINES[:2]}
    assert waits == [5.0, 15.0] and len(chat.calls) == 3
    assert list(log_doc) == ["schema_version", "episode_id", "model", "prompt_version", "prompt_sha256", "options",
                             "think", "batches"]
    assert log_doc["prompt_sha256"] == prompt_sha256("v1") and log_doc["episode_id"] == "ep"
    (batch,) = log_doc["batches"]
    assert batch["index"] == 1 and batch["ids"] == IDS[:2] and batch["accepted_attempt"] == 3
    a1, a2, a3 = batch["attempts"]
    assert [a["attempt"] for a in (a1, a2, a3)] == [1, 2, 3]
    assert reason in a1["rejection"] and a1["response"] is not None and "error" not in a1
    assert a2["error"] == "timeout after 600 s" and a2["response"] is None and "rejection" not in a2
    assert "error" not in a3 and "rejection" not in a3 and json.loads(a3["response"])
    for a in (a1, a2, a3):
        assert set(a["request"]) == {"messages", "format", "options"}
        assert isinstance(a["duration_s"], float)


def test_retry_exhaustion_raises_with_batch_reason_and_log():
    chat = FakeChat(script=[None, lambda items: _answer(items[:1])] + [lambda items: _answer(items[:1])] * 5)
    with pytest.raises(EnrichmentError) as info:
        enrich("ep", LINES[:4], _cfg(batch_lines=2, retries=1, retry_backoff=(1.0,)), chat, sleep=lambda s: None)
    exc = info.value
    assert str(exc) == "batch 2 (s00003..s00004): missing id: s00004 (after 2 attempts)"
    assert exc.batch == 2 and exc.reason == "missing id: s00004"
    b1, b2 = exc.log["batches"]
    assert b1["accepted_attempt"] == 1 and b2["accepted_attempt"] is None
    assert [a["rejection"] for a in b2["attempts"]] == ["missing id: s00004"] * 2
    assert all(a["response"] for a in b2["attempts"]) and len(chat.calls) == 3


def test_chat_error_exhaustion():
    chat = FakeChat(script=[ChatError("cannot reach Ollama")] * 3)
    with pytest.raises(EnrichmentError, match=r"batch 1 \(s00001..s00002\): cannot reach Ollama \(after 3 attempts\)"):
        enrich("ep", LINES[:2], _cfg(), chat, sleep=lambda s: None)


# --- AC6: preflight ----------------------------------------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(body=None, fail=None):
    calls = []

    def opener(req, timeout):
        calls.append((req.full_url, req.get_method(), timeout))
        if fail is not None:
            raise fail
        return _Resp(json.dumps(body).encode())
    opener.calls = calls
    return opener


def test_preflight_ok_and_latest(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    op = _opener({"models": [{"name": "qwen3:14b", "model": "qwen3:14b"}, {"name": "llama:latest"}]})
    learning_preflight(learning_config(tmp_path), opener=op)
    assert op.calls == [("http://127.0.0.1:11437/api/tags", "GET", 10.0)]
    learning_preflight(learning_config(tmp_path, model="llama"), opener=op)


def test_preflight_env_host(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "otherhost:1234")
    op = _opener({"models": [{"name": "qwen3:14b"}]})
    learning_preflight(learning_config(tmp_path), opener=op)
    assert op.calls[0][0] == "http://otherhost:1234/api/tags"


def test_preflight_unreachable(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    with pytest.raises(LearningPreflightError, match="cannot reach Ollama at http://127.0.0.1:11437"):
        learning_preflight(learning_config(tmp_path), opener=_opener(fail=urllib.error.URLError("refused")))


def test_preflight_missing_model(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    with pytest.raises(LearningPreflightError, match=r"model 'qwen3:30b' \(\[learning\] model\) is not available "
                                                     r"at http://127.0.0.1:11437 \(ollama pull qwen3:30b\)"):
        learning_preflight(learning_config(tmp_path, model="qwen3:30b"),
                           opener=_opener({"models": [{"name": "qwen3:14b"}]}))


def test_preflight_invalid_response(tmp_path):
    with pytest.raises(LearningPreflightError, match="invalid response"):
        learning_preflight(learning_config(tmp_path), opener=_opener({"nope": 1}))


# --- [learning] C7 config keys -----------------------------------------------------------------

def test_learning_config_defaults():
    cfg = from_dict({}).learning
    assert (cfg.model, cfg.think, cfg.temperature, cfg.seed, cfg.num_ctx, cfg.prompt_version, cfg.batch_lines,
            cfg.retries) == ("qwen3:14b", False, 0.0, 42, 8192, "v1", 20, 2)
    assert (cfg.ollama_host, cfg.timeout, cfg.retry_backoff) == ("http://127.0.0.1:11437", 600.0, (5.0, 15.0))
    assert cfg.window_seconds == 300.0  # CL1.1 keys unchanged


def test_learning_config_values():
    cfg = from_dict({"learning": {"model": "qwen3:30b", "think": True, "temperature": 0.2, "seed": 1,
                                  "num_ctx": 4096, "prompt_version": "v1", "batch_lines": 5, "retries": 0,
                                  "ollama_host": "h:1", "timeout": 30, "retry_backoff": [1, 2.5]}}).learning
    assert (cfg.model, cfg.think, cfg.temperature, cfg.seed, cfg.num_ctx, cfg.batch_lines, cfg.retries) == (
        "qwen3:30b", True, 0.2, 1, 4096, 5, 0)
    assert (cfg.ollama_host, cfg.timeout, cfg.retry_backoff) == ("h:1", 30.0, (1.0, 2.5))


@pytest.mark.parametrize("key, value, msg", [
    ("batch_lines", 0, "learning.batch_lines"),
    ("retries", -1, "learning.retries"),
    ("model", "", "learning.model"),
    ("think", "no", "learning.think"),
    ("temperature", 3, "learning.temperature"),
    ("num_ctx", 100, "learning.num_ctx"),
    ("timeout", 0, "learning.timeout"),
    ("retry_backoff", [1, "x"], "learning.retry_backoff"),
    ("prompt_version", "", "learning.prompt_version"),
])
def test_learning_config_invalid(key, value, msg):
    with pytest.raises(ConfigError, match=msg):
        from_dict({"learning": {key: value}})


def test_example_config_parses():
    import tomllib
    from pathlib import Path
    data = tomllib.loads((Path(__file__).parent.parent / "config.example.toml").read_text(encoding="utf-8"))
    cfg = from_dict(data).learning
    assert (cfg.model, cfg.batch_lines, cfg.prompt_version, cfg.retry_backoff) == ("qwen3:14b", 20, "v1",
                                                                                  (5.0, 15.0))
