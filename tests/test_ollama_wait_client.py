"""FIX-ollama-wait AC1 / AC2: Ollama error classification (client, preflight) and the no-retry rule of the stages
(docs/tasks/FIX-ollama-wait.md O1-O3)."""

from __future__ import annotations

import io
import json
import socket
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from auto_short.config import Config, PostConfig, RenderConfig, SelectionConfig, TitlingConfig, WorkspaceConfig
from auto_short.pipeline import OllamaUnavailable, PreflightError, ollama_preflight
from auto_short.post import stage as post_stage
from auto_short.post import store as post_store
from auto_short.review import shorts as S
from auto_short.selection import SelectionError, run_selection
from auto_short.selection.client import ChatError, ChatResult, ChatUnavailable, OllamaClient
from auto_short.titling import TitlingError, run_titling
from auto_short.titling.added import title_added
from cp9_helpers import EID as CP9_EID, make_cp9_episode
from post_helpers import make_post_episode
from selection_helpers import SYN_ANALYSIS, FakeClient as SelectionClient, make_selection_episode
from titling_helpers import FakeClient as TitlingClient, make_titling_episode
from transcript_helpers import manifest_of

MSGS = [{"role": "user", "content": "x"}]


def chat(client):
    return client.chat(model="m", messages=MSGS, format=None, options={}, think=False)


class _Handler(BaseHTTPRequestHandler):
    chat_mode = "ok"  # ok | 503 | 400 | reset | slow | badjson
    tags_ok = True

    def _send(self, code, data=b"{}"):
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if type(self).tags_ok:
            self._send(200, b'{"models": []}')
        else:
            self._send(503, b"{}")

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers["Content-Length"]))
        mode = type(self).chat_mode
        if mode == "reset":
            self.connection.close()
        elif mode == "slow":
            time.sleep(1.0)
        elif mode in ("503", "400"):
            self._send(int(mode), b'{"error":"x"}')
        elif mode == "badjson":
            self._send(200, b'{"nope": 1}')
        else:
            self._send(200, json.dumps({"message": {"content": "hi"}}).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    _Handler.chat_mode, _Handler.tags_ok = "ok", True
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_client_ok(server):
    assert chat(OllamaClient(server, timeout=5)).content == "hi"


def test_client_connection_refused_is_unavailable():
    with pytest.raises(ChatUnavailable, match="cannot reach Ollama"):
        chat(OllamaClient(f"http://127.0.0.1:{closed_port()}", timeout=5))


@pytest.mark.parametrize("mode", ["reset", "503"])
def test_client_reset_and_503_are_unavailable(server, mode):
    _Handler.chat_mode = mode
    with pytest.raises(ChatUnavailable):
        chat(OllamaClient(server, timeout=5))


@pytest.mark.parametrize("mode,match", [("400", "HTTP 400"), ("badjson", "invalid Ollama response envelope")])
def test_client_other_errors_are_plain_chat_error(server, mode, match):
    _Handler.chat_mode = mode
    with pytest.raises(ChatError, match=match) as exc:
        chat(OllamaClient(server, timeout=5))
    assert not isinstance(exc.value, ChatUnavailable)


def test_client_timeout_with_tags_failing_is_unavailable(server):
    _Handler.chat_mode, _Handler.tags_ok = "slow", False
    with pytest.raises(ChatUnavailable, match="timeout after 0.3 s"):
        chat(OllamaClient(server, timeout=0.3))


def test_client_timeout_with_tags_ok_is_plain_timeout(server):
    _Handler.chat_mode, _Handler.tags_ok = "slow", True
    with pytest.raises(ChatError, match="timeout after 0.3 s") as exc:
        chat(OllamaClient(server, timeout=0.3))
    assert not isinstance(exc.value, ChatUnavailable)


# --- preflight (E8) -----------------------------------------------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_of(reply):
    def opener(req, timeout):
        if isinstance(reply, Exception):
            raise reply
        return _Resp(json.dumps(reply).encode())
    return opener


CFG = Config(selection=SelectionConfig(model="a", ollama_host="http://h:1"),
             titling=TitlingConfig(model="b", ollama_host="http://h:1"))


@pytest.mark.parametrize("exc", [urllib.error.URLError(ConnectionRefusedError(111, "refused")), TimeoutError(),
                                 ConnectionResetError(), urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO(b""))])
def test_ollama_preflight_connection_errors_are_unavailable(exc):
    with pytest.raises(OllamaUnavailable):
        ollama_preflight(CFG, opener=opener_of(exc))


@pytest.mark.parametrize("reply", [{"models": [{"name": "a", "model": "a"}]}, {"nope": 1}])
def test_ollama_preflight_missing_model_or_bad_response_is_plain(reply):
    with pytest.raises(PreflightError) as exc:
        ollama_preflight(CFG, opener=opener_of(reply))
    assert not isinstance(exc.value, OllamaUnavailable)


def test_ollama_preflight_http_400_is_plain():
    with pytest.raises(PreflightError) as exc:
        ollama_preflight(CFG, opener=opener_of(urllib.error.HTTPError("u", 400, "x", {}, io.BytesIO(b""))))
    assert not isinstance(exc.value, OllamaUnavailable)


def test_post_preflight_classification(tmp_path, server):
    cfg = Config(post=PostConfig(image_dir=tmp_path, ollama_host=server, model="m"))
    with pytest.raises(PreflightError) as exc:  # tags reachable, model missing
        post_stage.preflight(cfg)
    assert not isinstance(exc.value, OllamaUnavailable)
    down = Config(post=PostConfig(image_dir=tmp_path, ollama_host=f"http://127.0.0.1:{closed_port()}"))
    with pytest.raises(OllamaUnavailable):
        post_stage.preflight(down, timeout=1.0)


# --- AC2: stages do not retry an unavailable Ollama ---------------------------------------------------------

class Sleep:
    def __init__(self):
        self.waits = []

    def __call__(self, s):
        self.waits.append(s)


UNAVAILABLE = ChatUnavailable("cannot reach Ollama at http://x")


def test_selection_unavailable_is_one_call_no_sleep(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), analysis=SYN_ANALYSIS)
    ws = make_selection_episode(cfg.workspace.dir)
    fake, sleep = SelectionClient({"w01": [UNAVAILABLE]}), Sleep()
    with pytest.raises(SelectionError, match="cannot reach Ollama"):
        run_selection("rbjfCfFq3Dk", cfg, client=fake, sleep=sleep)
    assert [c["window"] for c in fake.calls] == ["w01"] and sleep.waits == []
    assert manifest_of(ws)["stages"]["selection"]["status"] == "failed"


def test_selection_other_chat_error_still_retries(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), analysis=SYN_ANALYSIS)
    make_selection_episode(cfg.workspace.dir)
    fake, sleep = SelectionClient({"w01": [ChatError("HTTP 500 from fake")]}), Sleep()
    with pytest.raises(SelectionError, match="after 3 attempts"):
        run_selection("rbjfCfFq3Dk", cfg, client=fake, sleep=sleep)
    assert len(fake.calls) == 3 and sleep.waits == [5.0, 15.0]


def test_titling_unavailable_stops_stage_without_untitled_clip(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), analysis=SYN_ANALYSIS)
    ws = make_titling_episode(cfg.workspace.dir)
    fake, sleep = TitlingClient({7: [UNAVAILABLE]}), Sleep()  # clip 2 titled, then clip 7 hits the outage
    with pytest.raises(TitlingError, match="cannot reach Ollama"):
        run_titling("rbjfCfFq3Dk", cfg, client=fake, sleep=sleep)
    assert [c["clip"] for c in fake.calls] == [2, 7] and sleep.waits == []
    assert manifest_of(ws)["stages"]["titling"]["status"] == "failed"
    assert not (ws.dir / "titles.json").exists()


def test_added_short_title_unavailable_one_call_untitled(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "out"))
    ws = make_cp9_episode(cfg.workspace.dir)
    S.add_short(CP9_EID, cfg, start_segment="s00062", end_segment="s00070")
    calls = []

    class Client:
        def chat(self, **kw):
            calls.append(1)
            raise UNAVAILABLE

    sleep = Sleep()
    res = title_added(CP9_EID, cfg, "m01", client=Client(), sleep=sleep)
    assert len(calls) == 1 and sleep.waits == [] and res.title is None and "cannot reach Ollama" in res.error


class PostClient:
    def __init__(self, items):
        self.items, self.calls = list(items), 0

    def chat(self, *, model, messages, format, options, think):
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return ChatResult(content=item)


def _post_cfg(tmp_path):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"), render=RenderConfig(output_dir=tmp_path / "output"),
                  post=PostConfig(image_dir=tmp_path / "images", retries=2, retry_backoff=(5.0,)))


def test_post_compose_unavailable_stops_job_without_raw(tmp_path):
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg, sleep, client = _post_cfg(tmp_path), Sleep(), PostClient([UNAVAILABLE])
    with pytest.raises(ChatUnavailable):
        post_stage.compose_posts("post8TestEp1", cfg, ["k01"], client=client, sleep=sleep)
    assert client.calls == 1 and sleep.waits == []
    assert not (tmp_path / "work" / "post8TestEp1" / post_store.POSTS_NAME).exists()  # no `raw` post written


def test_post_compose_other_error_still_retries(tmp_path):
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg, sleep = _post_cfg(tmp_path), Sleep()
    client = PostClient([ChatError("HTTP 500"), ChatError("HTTP 500"), ChatError("HTTP 500")])
    summary = post_stage.compose_posts("post8TestEp1", cfg, ["k01"], client=client, sleep=sleep)
    assert client.calls == 3 and summary.raw == 1 and sleep.waits == [5.0, 5.0]
