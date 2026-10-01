"""[render] config parsing (CP7)."""

from pathlib import Path

import pytest

from auto_short import config as config_mod
from auto_short.config import ConfigError, RenderConfig, from_dict


def test_example_config_render_defaults():
    cfg = config_mod.load(Path(__file__).parents[1] / "config.example.toml")
    assert cfg.render == RenderConfig()


def test_render_config_parsing():
    cfg = from_dict({"render": {"crf": 20, "preset": "slow", "title_font_size": 0.08, "output_dir": "/tmp/o",
                                "threads": 4, "audio_bitrate": "160k", "dissolve": 0}}).render
    assert cfg.dissolve == 0.0
    assert (cfg.crf, cfg.preset, cfg.title_font_size, cfg.threads, cfg.audio_bitrate) == \
        (20, "slow", 0.08, 4, "160k")
    assert cfg.output_dir == Path("/tmp/o")


@pytest.mark.parametrize("data", [
    {"title_source": "review"}, {"font_file": "/etc/f.ttf"}, {"font_file": "../x.ttf"}, {"preset": "fastest"},
    {"crf": 60}, {"crf": 1.5}, {"audio_bitrate": "192"}, {"line_spacing": 3}, {"min_font_scale": 0},
    {"header_panel_width": 1.5}, {"threads": -1}, {"jobs": 0}, {"jobs": 17}, {"jobs": 1.5}, {"jobs": "4"}, {"jobs": True}, {"output_dir": ""},
    {"dissolve": -0.1}, {"dissolve": 2}, {"dissolve": "0.15"},
    {"title_bottom": 0}, {"title_bottom": 2.5}, {"title_bottom": "1600"}, {"title_bottom": True},
])
def test_render_config_invalid(data):
    with pytest.raises(ConfigError, match="render"):
        from_dict({"render": data})


def test_render_encode_defaults():
    cfg = RenderConfig()
    assert (cfg.crf, cfg.preset, cfg.audio_bitrate) == (22, "medium", "192k")  # P4 as amended 2026-09-27
    assert cfg.dissolve == 0.15  # CP8.1 V1/P2: on by default


def test_render_layout_defaults_v16():
    """CP8.14 L2: new defaults, title_bottom added, gap_video_title removed (an old key is ignored)."""
    cfg = RenderConfig()
    assert (cfg.header_panel_width, cfg.header_panel_height, cfg.header_font_size, cfg.video_height,
            cfg.title_panel_width, cfg.title_panel_height, cfg.title_font_size, cfg.title_bottom,
            cfg.min_frame_margin, cfg.gap_header_video) == (0.85, 0.17, 0.045, 1.16, 0.75, 0.21, 0.065, 1.4815,
                                                            0.02, 0.005)
    assert from_dict({"render": {"title_bottom": 1.45}}).render.title_bottom == 1.45
    assert from_dict({"render": {"gap_video_title": 0.01}}).render == RenderConfig()


def test_render_jobs_default_and_parse():
    assert RenderConfig().jobs == 1
    assert from_dict({"render": {"jobs": 4}}).render.jobs == 4
    assert from_dict({"render": {"jobs": 16}}).render.jobs == 16
