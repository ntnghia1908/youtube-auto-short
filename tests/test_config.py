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
