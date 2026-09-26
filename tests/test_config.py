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
    assert (d.prompt_version, d.max_clips, d.min_score, d.max_window_words, d.retries) == ("v2", 25, 7, 2500, 2)
    assert d.ollama_host == "http://127.0.0.1:11437" and d.retry_backoff == (5.0, 15.0)
    assert d.start_blocklist[:2] == ("cho nên", "vì vậy") and len(d.start_blocklist) == 19 and d.start_blocklist[-3:] == ("tại vì", "tại vì sao", "vì sao")
    assert config_mod.from_dict({"selection": {"start_blocklist": []}}).selection.start_blocklist == ()
    assert config_mod.from_dict({"selection": {"start_blocklist": ["à"]}}).selection.start_blocklist == ("à",)


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
    {"selection": {"start_blocklist": "cho nên"}},
    {"selection": {"start_blocklist": ["cho nên", ""]}},
    {"selection": {"start_blocklist": ["  "]}},
    {"selection": {"start_blocklist": [1]}},
    {"selection": {"retry_backoff": 5}},
    {"selection": {"retry_backoff": [-1]}},
    {"selection": {"retry_backoff": ["5"]}},
    {"selection": {"retry_backoff": [True]}},
])
def test_selection_config_invalid(data):
    with pytest.raises(ConfigError):
        config_mod.from_dict(data)
