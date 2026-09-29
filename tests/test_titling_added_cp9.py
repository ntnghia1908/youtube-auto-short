"""CP9 C6: AI title of one added Short with the CP6 prompt / validation / retries; result in review.json
``added[]``, every call appended to ``review_titling_log.json``; failures leave the Short untitled."""

import json

import pytest

from auto_short.config import Config, RenderConfig, WorkspaceConfig
from auto_short.review import shorts as S
from auto_short.selection.client import ChatError, ChatResult
from auto_short.titling.added import LOG_NAME, title_added
from auto_short.titling.prompt import prompt_sha256
from cp9_helpers import EID, make_cp9_episode


class Client:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def chat(self, *, model, messages, format, options, think):
        self.calls.append(messages)
        item = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(item, Exception):
            raise item
        return ChatResult(content=item, eval_count=1, prompt_eval_count=2, total_duration=3)


def reply(*pairs):
    return json.dumps({"options": [{"evidence": e, "title": t} for t, e in pairs]}, ensure_ascii=False)


GOOD = reply(("Lời giảng về tâm an", "dòng 62 lời giảng thứ 62"), ("Tâm an khi nghe giảng", "lời giảng thứ 63 về tâm"),
             ("TIÊU ĐỀ VIẾT HOA HẾT", "dòng 64 lời giảng"))


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "out"))


@pytest.fixture
def ws(cfg):
    ws = make_cp9_episode(cfg.workspace.dir)
    S.add_short(EID, cfg, start_segment="s00062", end_segment="s00070")
    return ws


def _review(ws):
    return json.loads((ws.dir / "review.json").read_text(encoding="utf-8"))


def test_title_added_stores_result_and_logs(ws, cfg):
    client = Client(GOOD)
    res = title_added(EID, cfg, "m01", client=client, sleep=lambda s: None)
    assert (res.status, res.title, res.error, res.stored) == ("titled", "Lời giảng về tâm an", None, True)
    m = _review(ws)["added"][0]
    assert (m["title"], m["ai_title"]) == ("Lời giảng về tâm an", "Lời giảng về tâm an")
    assert m["alternatives"] == [{"title": "Tâm an khi nghe giảng", "evidence": "lời giảng thứ 63 về tâm"}]
    user = client.calls[0][1]["content"]
    assert user.startswith("Video: Kinh tập 1\nThời lượng Short: ") and "dòng 62 lời giảng" in user
    assert "dòng 60 " not in user and "dòng 61 lời" in user and "dòng 69 lời" in user and "dòng 70 " not in user
    log = json.loads((ws.dir / LOG_NAME).read_text(encoding="utf-8"))
    assert log["episode_id"] == EID and len(log["entries"]) == 1
    e = log["entries"][0]
    assert (e["clip_id"], e["candidate_id"], e["source"], e["status"]) == ("m01", "manual", "transcript", "titled")
    assert e["prompt_sha256"] == prompt_sha256(cfg.titling.prompt_version) and len(e["ai_calls"]) == 1
    assert e["ai_calls"][0]["options"][2]["reject_reason"] == "all caps"
    # a second call (e.g. job re-run) keeps the stored result and appends to the log
    title_added(EID, cfg, "m01", client=Client(GOOD), sleep=lambda s: None)
    assert _review(ws)["added"][0] == m and len(json.loads((ws.dir / LOG_NAME).read_text())["entries"]) == 2


def test_no_valid_option_leaves_untitled(ws, cfg):
    bad = reply(("A!", "dòng 62 lời giảng"), ("B!", "dòng 62 lời giảng"), ("C!", "dòng 62 lời giảng"))
    client = Client(bad)
    res = title_added(EID, cfg, "m01", client=client, sleep=lambda s: None)
    assert (res.status, res.title, res.error, res.stored) == ("untitled", None, None, False)
    assert len(client.calls) == 1 + cfg.titling.retries
    assert _review(ws)["added"][0]["title"] is None


def test_connection_error_is_reported(ws, cfg):
    waits = []
    res = title_added(EID, cfg, "m01", client=Client(ChatError("connection refused")), sleep=waits.append)
    assert res.status == "untitled" and "connection refused" in res.error and "after 3 attempts" in res.error
    assert waits == [5, 15]
    assert json.loads((ws.dir / LOG_NAME).read_text())["entries"][0]["error"] == res.error
