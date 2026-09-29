"""CP8.15 P1/P3 orchestration: compose_posts (AI punctuation with retries / raw fallback), post_log.json, preflight."""

from __future__ import annotations

import http.server
import json
import threading

import pytest

from auto_short.config import Config, PostConfig, RenderConfig, WorkspaceConfig
from auto_short.pipeline import PreflightError
from auto_short.post import stage, store
from auto_short.selection.client import ChatError, ChatResult
from post_helpers import make_post_episode


def _config(tmp_path, **post_over):
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                 render=RenderConfig(output_dir=tmp_path / "output"),
                 post=PostConfig(image_dir=tmp_path / "images", retries=1, retry_backoff=(0.0,), **post_over))


class FakeClient:
    """``replies`` (optional): a queue of items consumed one per ``chat()`` call, in order (missing/exhausted ->
    a trivially valid punctuation of the chunk text); a str is raw JSON content, an Exception is raised."""

    def __init__(self, replies: list | None = None):
        self.replies = list(replies) if replies is not None else []
        self.calls: list[dict] = []

    def chat(self, *, model, messages, format, options, think):
        text = messages[-1]["content"].split("\n", 1)[1]
        self.calls.append({"model": model, "text": text})
        item = self.replies.pop(0) if self.replies else None
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            content = item
        else:
            para = text[0].upper() + text[1:] + "."
            content = json.dumps({"paragraphs": [para]}, ensure_ascii=False)
        return ChatResult(content=content, thinking=None, eval_count=1, prompt_eval_count=1, total_duration=1)


def sleep_noop(_seconds: float) -> None:
    pass


def test_compose_posts_one_clip_ai_origin(tmp_path):
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _config(tmp_path)
    client = FakeClient()
    summary = stage.compose_posts("post8TestEp1", cfg, ["k01"], client=client, sleep=sleep_noop)
    assert (summary.ai, summary.raw, summary.errors) == (1, 0, {})

    doc = store.read_posts(tmp_path / "work" / "post8TestEp1" / "posts.json", "post8TestEp1")
    entry = store.find(doc, "k01")
    assert entry["origin"] == store.AI
    assert entry["candidate_id"] == "c00001"
    assert entry["paragraphs"][0].startswith("Dòng 1")
    assert entry["image"] is None  # empty library -> "thiếu ảnh"
    assert entry["link"] is None and entry["posted_at"] is None

    log_doc = json.loads((tmp_path / "work" / "post8TestEp1" / "post_log.json").read_text(encoding="utf-8"))
    assert len(log_doc["entries"]) == 1
    assert log_doc["entries"][0]["clip_id"] == "k01" and log_doc["entries"][0]["origin"] == "ai"


def test_compose_posts_falls_back_to_raw_after_retries_exhausted(tmp_path):
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _config(tmp_path)
    # Every attempt returns a response with a changed word: never validates (retries = 1 -> 2 attempts total).
    bad = json.dumps({"paragraphs": ["Một câu hoàn toàn khác."]})
    client = FakeClient([bad, bad])
    summary = stage.compose_posts("post8TestEp1", cfg, ["k01"], client=client, sleep=sleep_noop)
    assert (summary.ai, summary.raw) == (0, 1)
    assert len(client.calls) == 2  # both attempts used

    doc = store.read_posts(tmp_path / "work" / "post8TestEp1" / "posts.json", "post8TestEp1")
    entry = store.find(doc, "k01")
    assert entry["origin"] == store.RAW
    assert entry["paragraphs"][0].startswith("Dòng 1")  # raw_fallback of the real source text


def test_compose_posts_retries_then_succeeds(tmp_path):
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _config(tmp_path)
    bad = json.dumps({"paragraphs": ["Một câu hoàn toàn khác."]})
    client = FakeClient([bad])  # attempt 1 fails, attempt 2 (no queued reply) succeeds trivially
    summary = stage.compose_posts("post8TestEp1", cfg, ["k01"], client=client, sleep=sleep_noop)
    assert (summary.ai, summary.raw) == (1, 0)
    assert len(client.calls) == 2


def test_compose_posts_recompose_keeps_image_link_posted(tmp_path):
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _config(tmp_path)
    posts_path = tmp_path / "work" / "post8TestEp1" / "posts.json"
    stage.compose_posts("post8TestEp1", cfg, ["k01"], client=FakeClient(), sleep=sleep_noop)
    doc = store.read_posts(posts_path, "post8TestEp1")
    doc = store.with_fields(doc, ["k01", "k02"], "k01", {"link": "https://youtube.com/shorts/AbCdEfGhIjK",
                                                          "image": "manual.jpg"}, now="2026-09-29T10:00:00Z")
    doc = store.with_posted(doc, ["k01", "k02"], "k01", True, now="2026-09-29T10:00:01Z")
    store.write(posts_path, doc)

    stage.compose_posts("post8TestEp1", cfg, ["k01"], client=FakeClient(), sleep=sleep_noop)
    doc = store.read_posts(posts_path, "post8TestEp1")
    entry = store.find(doc, "k01")
    assert entry["image"] == "manual.jpg"
    assert entry["link"] == "https://youtube.com/shorts/AbCdEfGhIjK"
    assert entry["posted_at"] == "2026-09-29T10:00:01Z"


def test_compose_posts_all_skips_valid_non_stale(tmp_path):
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _config(tmp_path)
    client = FakeClient()
    stage.compose_posts("post8TestEp1", cfg, ["k01"], client=client, sleep=sleep_noop)
    assert len(client.calls) == 1
    summary = stage.compose_posts("post8TestEp1", cfg, "all", client=client, sleep=sleep_noop)
    # k01 already has a valid, non-stale post: skipped; k02 has none yet: composed
    assert summary.clip_ids == ["k02"]
    assert len(client.calls) == 2  # one more call, for k02


def test_compose_posts_unknown_clip_raises(tmp_path):
    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _config(tmp_path)
    with pytest.raises(stage.PostComposeError):
        stage.compose_posts("post8TestEp1", cfg, ["k99"], client=FakeClient(), sleep=sleep_noop)


def test_compose_posts_no_rendered_shorts_raises(tmp_path):
    cfg = _config(tmp_path)
    with pytest.raises(stage.PostComposeError):
        stage.compose_posts("no-such-episode", cfg, ["k01"], client=FakeClient(), sleep=sleep_noop)


def test_compose_posts_least_used_image_assigned_round_robin(tmp_path):
    from auto_short.post import images
    from image_fixtures import make_png

    make_post_episode(tmp_path / "work", tmp_path / "output")
    cfg = _config(tmp_path)
    n1, _ = images.save_image(cfg.post.image_dir, make_png(700, 900), original_name="a.png")
    n2, _ = images.save_image(cfg.post.image_dir, make_png(800, 1000), original_name="b.png")
    summary = stage.compose_posts("post8TestEp1", cfg, "all", client=FakeClient(), sleep=sleep_noop)
    assert (summary.ai, summary.raw) == (2, 0)
    doc = store.read_posts(tmp_path / "work" / "post8TestEp1" / "posts.json", "post8TestEp1")
    assigned = {e["clip_id"]: e["image"] for e in doc["posts"]}
    assert set(assigned.values()) == {n1, n2}  # each Short's compose picks the image used the least so far


# --- preflight (P1) -------------------------------------------------------------------------------------------


class _TagsHandler(http.server.BaseHTTPRequestHandler):
    models: list[str] = []

    def do_GET(self):
        body = json.dumps({"models": [{"name": m} for m in self.models]}).encode()
        self.send_response(200 if self.path == "/api/tags" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def ollama_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _TagsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_preflight_ok(tmp_path, ollama_server):
    _TagsHandler.models = ["qwen3:14b"]
    cfg = _config(tmp_path)
    cfg = Config(**{**cfg.__dict__, "post": PostConfig(**{**cfg.post.__dict__, "ollama_host": ollama_server})})
    stage.preflight(cfg)  # no raise


def test_preflight_model_missing(tmp_path, ollama_server):
    _TagsHandler.models = ["other:model"]
    cfg = _config(tmp_path)
    cfg = Config(**{**cfg.__dict__, "post": PostConfig(**{**cfg.post.__dict__, "ollama_host": ollama_server})})
    with pytest.raises(PreflightError):
        stage.preflight(cfg)


def test_preflight_unreachable(tmp_path):
    cfg = _config(tmp_path)
    cfg = Config(**{**cfg.__dict__, "post": PostConfig(**{**cfg.post.__dict__,
                                                           "ollama_host": "http://127.0.0.1:1"})})
    with pytest.raises(PreflightError):
        stage.preflight(cfg, timeout=1.0)
