import pytest

from auto_short import config as config_mod
from auto_short.config import ConfigError


def test_example_config_equals_defaults():
    assert config_mod.load(config_mod.Path(__file__).parents[1] / "config.example.toml") == config_mod.Config()


def test_transcript_config_parsing():
    cfg = config_mod.from_dict({"transcript": {
        "min_coverage": 0.6,
        "providers": {"youtube": False},
        "whisper": {"model": "small", "cpu_threads": 4, "models_dir": "/tmp/m"},
    }})
    t = cfg.transcript
    assert t.min_coverage == 0.6 and t.min_vietnamese_ratio == 0.3
    assert (t.providers.youtube, t.providers.local_subtitle, t.providers.whisper) == (False, True, True)
    assert t.whisper.model == "small" and t.whisper.effective_cpu_threads == 4
    assert str(t.whisper.models_dir) == "/tmp/m"
    assert config_mod.Config().transcript.whisper.effective_cpu_threads >= 1


@pytest.mark.parametrize("data", [
    {"transcript": {"min_coverage": 2}},
    {"transcript": {"min_words_per_minute": "x"}},
    {"transcript": {"providers": {"whisper": "no"}}},
    {"transcript": {"whisper": {"cpu_threads": -1}}},
    {"transcript": {"whisper": {"model": ""}}},
    {"transcript": {"providers": []}},
])
def test_transcript_config_invalid(data):
    with pytest.raises(ConfigError):
        config_mod.from_dict(data)


def test_analysis_config_parsing():
    a = config_mod.from_dict({"analysis": {"max_pause": 0.7, "scale_width": 480, "min_duration": 20}}).analysis
    assert a.max_pause == 0.7 and a.scale_width == 480 and a.min_duration == 20.0
    assert a.min_boundary_silence == 3.0 and a.hard_break_silence == 10.0 and a.silence_noise_db == -45.0


@pytest.mark.parametrize("data", [
    {"analysis": {"scene_threshold": 1.5}},
    {"analysis": {"scale_width": 320.5}},
    {"analysis": {"silence_noise_db": 5}},
    {"analysis": {"max_pause": "1"}},
    {"analysis": {"min_duration": 200}},  # > max_duration
    {"analysis": {"target_min": 100}},  # > target_max
    {"analysis": {"min_boundary_silence": 12}},  # > hard_break_silence
    {"analysis": []},
])
def test_analysis_config_invalid(data):
    with pytest.raises(ConfigError):
        config_mod.from_dict(data)


def test_selection_config_parsing():
    s = config_mod.from_dict({"selection": {"model": "qwen3:30b", "think": True, "temperature": 0.2,
                                            "max_clips": 10, "timeout": 30}}).selection
    assert (s.model, s.think, s.temperature, s.max_clips, s.timeout) == ("qwen3:30b", True, 0.2, 10, 30.0)
    d = config_mod.Config().selection
    assert (d.model, d.think, d.temperature, d.seed, d.num_ctx) == ("qwen3:30b", True, 0.0, 42, 32768)
    assert (d.prompt_version, d.max_clips, d.min_score, d.max_window_words, d.retries) == ("v3", 25, 7, 2500, 2)
    assert d.ollama_host == "http://127.0.0.1:11437" and d.retry_backoff == (5.0, 15.0)
    assert d.head_cut_words[:2] == ("cho nên", "vì vậy") and len(d.head_cut_words) == 11 and d.head_cut_pad == 0.1
    assert d.prompt_version == "v3"
    assert config_mod.from_dict({"selection": {"head_cut_words": []}}).selection.head_cut_words == ()
    assert config_mod.from_dict({"selection": {"head_cut_pad": 0.2}}).selection.head_cut_pad == 0.2


@pytest.mark.parametrize("data", [
    {"selection": {"model": ""}},
    {"selection": {"think": "no"}},
    {"selection": {"seed": 1.5}},
    {"selection": {"max_clips": 0}},
    {"selection": {"min_score": 11}},
    {"selection": {"retries": -1}},
    {"selection": {"num_ctx": True}},
    {"selection": {"timeout": 0}},
    {"selection": []},
    {"selection": {"head_cut_words": "cho nên"}},
    {"selection": {"head_cut_words": ["cho nên", ""]}},
    {"selection": {"head_cut_words": ["  "]}},
    {"selection": {"head_cut_words": [1]}},
    {"selection": {"head_cut_pad": -0.1}},
    {"selection": {"head_cut_pad": 2}},
    {"selection": {"retry_backoff": 5}},
    {"selection": {"retry_backoff": [-1]}},
    {"selection": {"retry_backoff": ["5"]}},
    {"selection": {"retry_backoff": [True]}},
])
def test_selection_config_invalid(data):
    with pytest.raises(ConfigError):
        config_mod.from_dict(data)


def test_web_config():
    w = config_mod.from_dict({"web": {"host": "127.0.0.1", "port": 9000, "session_days": 7}}).web
    assert (w.host, w.port, w.session_days) == ("127.0.0.1", 9000, 7)
    d = config_mod.Config().web
    assert (d.host, d.port, d.session_days) == ("0.0.0.0", 8080, 30)
    for bad in ({"port": 0}, {"port": 70000}, {"session_days": 0}, {"host": ""}, {"port": "80"}):
        with pytest.raises(ConfigError):
            config_mod.from_dict({"web": bad})


def test_learning_config():
    le = config_mod.Config().learning
    assert (le.window_seconds, le.min_han_ratio, le.media_format) == (300.0, 0.5, "bv*[height<=720]+ba/b[height<=720]")
    le = config_mod.from_dict({"learning": {"window_seconds": 120, "min_han_ratio": 0.8, "media_format": "b"}}).learning
    assert (le.window_seconds, le.min_han_ratio, le.media_format) == (120.0, 0.8, "b")
    # other sections (and therefore Auto Short stage hashes) are unaffected by [learning]
    assert config_mod.from_dict({"learning": {"window_seconds": 60}}).transcript == config_mod.Config().transcript


@pytest.mark.parametrize("data", [
    {"learning": {"window_seconds": 0}},
    {"learning": {"window_seconds": "300"}},
    {"learning": {"window_seconds": True}},
    {"learning": {"min_han_ratio": 1.5}},
    {"learning": {"min_han_ratio": -0.1}},
    {"learning": {"media_format": ""}},
    {"learning": []},
])
def test_learning_config_invalid(data):
    with pytest.raises(ConfigError):
        config_mod.from_dict(data)


def test_post_config():
    d = config_mod.Config().post
    assert (d.model, d.chunk_words, d.retries, d.prompt_version) == ("qwen3:14b", 400, 2, "v1")
    assert d.image_dir.is_absolute() and "~" not in str(d.image_dir)
    p = config_mod.from_dict({"post": {
        "model": "qwen3:30b", "chunk_words": 250, "retries": 1, "image_dir": "/tmp/post-images",
        "image_sources": ["https://example.com/a"],
    }}).post
    assert (p.model, p.chunk_words, p.retries) == ("qwen3:30b", 250, 1)
    assert str(p.image_dir) == "/tmp/post-images"
    assert p.image_sources == ("https://example.com/a",)
    # other sections are unaffected
    assert config_mod.from_dict({"post": {"model": "x"}}).titling == config_mod.Config().titling


@pytest.mark.parametrize("data", [
    {"post": {"chunk_words": 10}},
    {"post": {"chunk_words": "400"}},
    {"post": {"retries": -1}},
    {"post": {"model": ""}},
    {"post": {"image_dir": ""}},
    {"post": {"image_sources": ["", "x"]}},
    {"post": {"image_sources": "x"}},
    {"post": []},
])
def test_post_config_invalid(data):
    with pytest.raises(ConfigError):
        config_mod.from_dict(data)
