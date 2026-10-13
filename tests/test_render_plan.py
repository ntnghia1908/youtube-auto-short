"""Render R3 (segments), R4 (layout) and R6 (ffmpeg graph/command) — pure, no ffmpeg."""

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from auto_short.config import RenderConfig
from auto_short.render import plan

NTSC = Fraction(30000, 1001)


# --- R3 -------------------------------------------------------------------------------------------------------

def test_segments_trims_before_across_inside_after():
    trims = [[0.5, 0.9], [0.9, 1.4], [2.0, 2.5], [3.8, 4.5], [5.0, 6.0]]
    # [0.5,0.9] before the clip: ignored; [0.9,1.4] cut by source_start=1.0 -> [1.0,1.4] only;
    # [2.0,2.5] inside; [3.8,4.5] cut by source_end=4.0 -> [3.8,4.0]; [5.0,6.0] after: ignored.
    segs = plan.kept_segments(1.0, 4.0, trims)
    assert segs == [(1400, 2000), (2500, 3800)]
    assert plan.segments_seconds(segs) == [[1.4, 2.0], [2.5, 3.8]]
    assert plan.total_ms(segs) == 1900


def test_segments_start_at_source_start_after_head_cut():
    # real k04: head cut 1249.99 -> 1250.66, first trim later; segments start at the clip start
    segs = plan.kept_segments(1250.66, 1299.55, [[1256.84, 1262.97], [1265.94, 1265.96]])
    assert segs[0][0] == 1250660 and segs[-1] == (1265960, 1299550)


def test_segments_trim_touching_edges_and_duration_check():
    assert plan.kept_segments(1.0, 3.0, [[1.0, 1.5], [2.5, 3.0]]) == [(1500, 2500)]
    plan.check_duration("k01", [(1500, 2500)], 1.0)
    plan.check_duration("k01", [(1500, 2500)], 1.001)  # 1 ms tolerance
    with pytest.raises(plan.PlanError, match="k01: kept segments total 1.000 s .* 1.100 s"):
        plan.check_duration("k01", [(1500, 2500)], 1.1)
    with pytest.raises(plan.PlanError, match="overlapping"):
        plan.kept_segments(0, 5, [[1, 3], [2, 4]])
    with pytest.raises(plan.PlanError, match="empty"):
        plan.kept_segments(2, 2, [])


def test_frame_plan_keeps_video_within_half_a_frame_of_audio():
    segs = [(1000, 1517), (2000, 2333), (4000, 4001), (5000, 9999)]
    frames = plan.frame_plan(segs, NTSC)
    total = sum(n for _, n in frames)
    assert total == round(Fraction(plan.total_ms(segs), 1000) * NTSC)
    assert abs(plan.planned_video_seconds(segs, NTSC) - plan.total_ms(segs) / 1000) <= 0.5 / float(NTSC)
    assert frames[0][0] == round(Fraction(1000, 1000) * NTSC)


def test_output_fps():
    assert plan.output_fps(NTSC) == NTSC
    assert plan.output_fps(Fraction(25)) == 25
    assert plan.output_fps(Fraction(60000, 1001)) == 30
    assert plan.fps_text(NTSC) == "30000/1001" and plan.fps_text(Fraction(30)) == "30"


# --- R4 -------------------------------------------------------------------------------------------------------

def test_default_geometry_and_layout():
    """CP8.14 AC1: layout V16 (header at the top margin, video right below, title bottom at 1600 px)."""
    g = plan.geometry(RenderConfig())
    assert (g.header_w, g.header_h, g.video_h, g.title_w, g.title_h) == (918, 184, 1254, 810, 227)
    assert (g.gap_header_video, g.radius, g.min_frame_margin, g.title_bottom) == (5, 59, 22, 1600)
    # L3: 3 lines at the reference size (70 px): ceil(3 x 70 x 1.05 + 2 x 37.8) = ceil(296.1)
    assert g.title_max_h == 297
    assert not hasattr(RenderConfig(), "gap_video_title")
    lay = plan.layout(g, g.title_h, 1440, 1080)
    assert lay.as_dict() == {
        "header_panel": {"x": 81, "y": 22, "w": 918, "h": 184, "radius": 59},
        "video": {"x": 0, "y": 211, "w": 1080, "h": 1254, "crop": {"w": 930, "h": 1080, "x": 255, "y": 0}},
        "title_panel": {"x": 135, "y": 1373, "w": 810, "h": 227, "radius": 59},
    }


def test_taller_title_panel_grows_upwards_over_the_video():
    """CP8.14 L1: no vertical centring; header and video stay put, the title bottom stays at title_bottom."""
    g = plan.geometry(RenderConfig())
    base = plan.layout(g, g.title_h, 1440, 1080)
    lay = plan.layout(g, g.title_max_h, 1440, 1080)
    assert (lay.header, lay.video, lay.crop) == (base.header, base.video, base.crop)
    assert (lay.title.x, lay.title.y, lay.title.w, lay.title.h) == (135, 1303, 810, 297)
    for t in (base.title, lay.title):
        assert t.y + t.h == 1600 < 1625  # AC2: above the Shorts channel row
        assert lay.video.y < t.y < lay.video.y + lay.video.h  # the title overlaps the bottom of the video
    assert lay.video.y + lay.video.h - lay.title.y == 162 and base.video.y + base.video.h - base.title.y == 92


def test_title_max_height_matches_the_fit():
    """L3: title_max_h is exactly what fit_title needs for 3 lines at the reference size (other settings)."""
    import math

    from auto_short.render.text import block_height
    for kw in ({}, {"title_font_size": 0.08}, {"line_spacing": 1.2, "panel_padding_y": 0.02},
               {"title_font_size": 0.0815, "title_panel_height": 0.3}):
        cfg = replace(RenderConfig(), **kw)
        size0 = plan.px(cfg.title_font_size)
        need = block_height(3, size0 * cfg.line_spacing, cfg.panel_padding_y * plan.WIDTH)
        assert plan.title_max_height(cfg) == math.ceil(need - 1e-9) and need <= plan.title_max_height(cfg)


def test_center_crop_other_aspects():
    assert plan.center_crop(1920, 1080, 1080, 1210) == plan.Crop(964, 1080, 478, 0)  # 16:9 keeps ~50 %
    assert plan.center_crop(1080, 1920, 1080, 1210) == plan.Crop(1080, 1210, 0, 355)  # vertical: crop height
    assert plan.center_crop(1440, 1080, 1080, 1254) == plan.Crop(930, 1080, 255, 0)  # V16, 4:3 source


@pytest.mark.parametrize("kw, match", [
    ({"title_bottom": 1.8}, "title_bottom gives 1944 px > frame height 1920"),
    ({"video_height": 1.7}, "video end at 2047 px > frame height 1920"),
    ({"header_panel_height": 0.4, "min_frame_margin": 0.1, "video_height": 1.3},
     "video end at 1949 px > frame height 1920"),
    ({"title_bottom": 0.4}, "above the header bottom 206 px"),
    ({"header_panel_height": 1.0, "video_height": 0.5, "title_bottom": 1.2}, "above the header bottom 1102 px"),
    ({"title_panel_height": 0.3}, "title_panel_height gives 324 px > the 297 px"),
    ({"header_panel_width": 1.05}, "header_panel_width gives 1134 px > frame width 1080"),
    ({"title_panel_width": 1.01}, "title_panel_width gives 1091 px > frame width 1080"),
])
def test_geometry_rejects_impossible_layouts(kw, match):
    """CP8.14 L4."""
    with pytest.raises(plan.PlanError, match=match):
        plan.geometry(replace(RenderConfig(), **kw))


def test_geometry_edge_cases_accepted():
    # title bottom at the frame edge; tallest title touching the header bottom exactly
    assert plan.geometry(replace(RenderConfig(), title_bottom=1920 / 1080)).title_bottom == 1920
    g = plan.geometry(replace(RenderConfig(), title_bottom=(22 + 184 + 297) / 1080))
    assert g.title_bottom - g.title_max_h == g.header_y + g.header_h


# --- R6 -------------------------------------------------------------------------------------------------------

def test_escape_option():
    assert plan.escape_option("/a b/f.ttf") == "/a b/f.ttf"
    assert plan.escape_option("C:/x'y,z") == "C\\\\:/x\\\\\\'y\\,z"


def _graph(segments, **kw):
    g = plan.geometry(RenderConfig())
    lay = plan.layout(g, g.title_max_h, 1440, 1080)
    lines = [plan.TextLine(Path("/t/h0.txt"), 100)]
    return plan.filter_graph(segments=segments, fps=NTSC, lay=lay, font_file=Path("/f/font.ttf"),
                             header_lines=lines, header_size=49, title_lines=lines, title_size=70, **kw)


def test_filter_graph_structure():
    graph = _graph([(1100, 2000), (2500, 4000)])
    assert graph.startswith("[0:v]fps=30000/1001,select='between(round(t*30000/1001),33,59)+"
                            "between(round(t*30000/1001),75,119)'")
    assert "crop=930:1080:255:0,scale=1080:1254:flags=lanczos" in graph
    assert "pad=1080:1920:0:211" in graph
    assert "[0:a]asplit=2[as0][as1]" in graph
    assert "[as0]atrim=start=1.1:end=2,asetpts=PTS-STARTPTS[a0]" in graph
    assert "[as1]atrim=start=2.5:end=4,asetpts=PTS-STARTPTS[a1]" in graph
    assert "[a0][a1]concat=n=2:v=0:a=1" in graph
    assert "drawtext=fontfile=/f/font.ttf:textfile=/t/h0.txt:expansion=none:text_shaping=1:fontsize=49" in graph
    assert "y_align=baseline:y=100" in graph
    # video first, then header, then title on top (CP8.14 AC2: the title is drawn over the video)
    assert graph.index("[vid]") < graph.index("[vid][hp]overlay=81:22") < graph.index("[v1][tp]overlay=135:1303")
    assert "color=c=0xFEDB00:s=810x297" in graph
    single = _graph([(0, 1000)])
    assert "[0:a]anull[as0]" in single and "concat=n=1" in single


def test_ffmpeg_command():
    cmd = plan.ffmpeg_command(ffmpeg="ffmpeg", source=Path("/w/source.mp4"), output=Path("/o/k01.mp4"),
                              graph_script=Path("/t/g"), segments=[(1100, 2000), (2500, 4000)], fps=NTSC,
                              crf=18, preset="medium", audio_bitrate="192k", threads=0)
    joined = " ".join(cmd)
    assert "-ss 0.1 -t 3.966733 -copyts -i /w/source.mp4" in joined
    assert "-c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -r 30000/1001" in joined
    assert "-c:a aac -b:a 192k -ar 48000 -ac 2" in joined
    assert "-fflags +bitexact" in joined and "-movflags +faststart" in joined and cmd[-1] == "/o/k01.mp4"


# --- CP8.1: video dissolve at junctions -------------------------------------------------------------------------

def test_dissolve_half_frames():
    assert plan.dissolve_half(0.15, NTSC) == 2  # 0.15 x 29.97 / 2 = 2.25 -> D = 4 frames
    assert plan.dissolve_half(0, NTSC) == 0
    assert plan.dissolve_half(0.25, NTSC) == 4 and plan.dissolve_half(0.5, Fraction(25)) == 6


def test_dissolve_plan_clamps_to_trimmed_gap():
    # segments of 100 frames; gaps between them: 50, 4, 3, 2, 1, 0
    frames, pos = [], 0
    for gap in (50, 4, 3, 2, 1, 0, None):
        frames.append((pos, 100))
        pos += 100 + (gap or 0)
    dp = plan.dissolve_plan(frames, NTSC, 0.15)
    assert dp.frames == [4, 4, 2, 2, 0, 0]  # D_j = 2 * min(e, gap // 2)
    assert dp.active
    assert dp.extend == [(0, 2), (2, 2), (2, 1), (1, 1), (1, 0), (0, 0), (0, 0)]
    # never outside the clip: the first segment is not extended backwards nor the last one forwards
    assert dp.extend[0][0] == 0 and dp.extend[-1][1] == 0
    # extensions stay inside the trimmed gap: extended neighbours never share a source frame
    for (f0, n0), (f1, _), (_, e_out), (e_in, _) in zip(frames, frames[1:], dp.extend, dp.extend[1:]):
        assert f0 + n0 + e_out - 1 < f1 - e_in
    assert plan.dissolve_plan(frames, NTSC, 0).frames == [0] * 6 and not plan.dissolve_plan(frames, NTSC, 0).active


def test_dissolve_plan_one_segment_negative_gap_and_short_segments():
    one = plan.dissolve_plan([(10, 50)], NTSC, 0.15)
    assert one.frames == [] and one.extend == [(0, 0)] and not one.active
    # rounding can make neighbouring segments touch or overlap by a frame: hard cut, never negative
    assert plan.dissolve_plan([(0, 30), (29, 30)], NTSC, 0.15).frames == [0]
    # guard: a segment gives at most half its frames to each side (no overlapping windows, xfade inputs long enough)
    dp = plan.dissolve_plan([(0, 30), (40, 3), (53, 0), (60, 30)], NTSC, 0.15)
    assert dp.frames == [2, 0, 0] and dp.extend == [(0, 1), (1, 0), (0, 0), (0, 0)]


def test_dissolves_manifest_entries():
    segs = [(1100, 2000), (2500, 4000), (4050, 5000)]
    frames = plan.frame_plan(segs, NTSC)
    assert frames == [(33, 27), (75, 45), (121, 28)]
    # junction at output frames 27 and 72; gaps 15 and 1 frame(s)
    assert plan.dissolves(segs, NTSC, 0.15) == [{"at": 0.901, "frames": 4}, {"at": 2.402, "frames": 0}]
    assert plan.dissolves(segs, NTSC, 0) == [{"at": 0.901, "frames": 0}, {"at": 2.402, "frames": 0}]
    assert plan.dissolves([(0, 1000)], NTSC, 0.15) == []


CP7_VIDEO = ("[0:v]fps=30000/1001,select='between(round(t*30000/1001),33,59)+between(round(t*30000/1001),75,119)',"
             "setpts=N/(30000/1001)/TB,crop=930:1080:255:0,scale=1080:1254:flags=lanczos,setsar=1,"
             "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,pad=1080:1920:0:211:color=0x000000[vid];")


def test_filter_graph_dissolve_zero_is_the_cp7_graph():
    graph = _graph([(1100, 2000), (2500, 4000)])  # default dissolve = 0
    assert graph.startswith(CP7_VIDEO)
    assert _graph([(1100, 2000), (2500, 4000)], dissolve=0) == graph
    # a dissolve with no junction to blend (one segment, or gaps of 1 frame) keeps the CP7 graph too
    assert _graph([(0, 1000)], dissolve=0.15) == _graph([(0, 1000)])
    assert _graph([(1100, 2000), (2020, 3000)], dissolve=0.15) == _graph([(1100, 2000), (2020, 3000)])


def test_filter_graph_dissolve_structure():
    segs = [(1100, 2000), (2500, 4000), (4050, 5000), (5500, 6000)]  # D = 4, 0, 4
    graph = _graph(segs, dissolve=0.15)
    f = "30000/1001"
    per_frame = ("crop=930:1080:255:0,scale=1080:1254:flags=lanczos,setsar=1,"
                 "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p")
    assert graph.startswith(f"[0:v]fps={f},split=4[s0][s1][s2][s3];"
                            f"[s0]trim=start_pts=33:end_pts=62,setpts=PTS-STARTPTS,{per_frame}[v0];"
                            f"[s1]trim=start_pts=73:end_pts=120,setpts=PTS-STARTPTS,{per_frame}[v1];"
                            f"[s2]trim=start_pts=121:end_pts=151,setpts=PTS-STARTPTS,{per_frame}[v2];"
                            f"[s3]trim=start_pts=163:end_pts=180,setpts=PTS-STARTPTS,{per_frame}[v3];")
    # offsets: (accumulated length - D) / fps; D = 0 -> concat
    assert f"[v0][v1]xfade=transition=fade:duration=0.133467:offset=0.834167[x1]" in graph  # 29 - 4 = 25 frames
    assert f"[x1][v2]concat=n=2:v=1:a=0,settb=1/({f}),setpts=N[x2]" in graph  # 29 + 47 - 4 = 72 frames, + 30
    assert f"[x2][v3]xfade=transition=fade:duration=0.133467:offset=3.269933[x3]" in graph  # 72 + 30 - 4 = 98
    assert f"[x3]setpts=N/({f})/TB,pad=1080:1920:0:211:color=0x000000[vid];" in graph
    # audio unchanged: hard cuts
    assert "[a0][a1][a2][a3]concat=n=4:v=0:a=1" in graph and "afade" not in graph and "acrossfade" not in graph


# --- FIX-render-vfr F1: source_fps ----------------------------------------------------------------------------

@pytest.mark.parametrize("r,avg", [("30000/1001", "50304000/1678477"), ("30000/1001", "2495575/83269"),
                                   ("30000/1001", "112318000/3747677"), ("30000/1001", "30000/1001"),
                                   ("1000/1", "2495575/83269"), ("30000/1001", None), (None, "2495575/83269"),
                                   ("0/0", "50304000/1678477"), ("1000/1", "0/0")])
def test_source_fps_vfr_cases_give_ntsc(r, avg):
    stream = {k: v for k, v in (("r_frame_rate", r), ("avg_frame_rate", avg)) if v is not None}
    expect = Fraction(1000, 1) if (r == "1000/1" and avg == "0/0") else NTSC
    assert plan.source_fps(stream) == expect


def test_source_fps_snaps_and_falls_back():
    assert plan.source_fps({"avg_frame_rate": "2501/100"}) == 25
    assert plan.source_fps({"r_frame_rate": "25/1", "avg_frame_rate": "2501/100"}) == 25
    assert plan.source_fps({"avg_frame_rate": "30000/1001"}) == NTSC
    # not within 1 % of a standard rate -> limit_denominator(1001)
    assert plan.source_fps({"avg_frame_rate": "15/1"}) == 15
    assert plan.source_fps({"avg_frame_rate": "123456/10007"}) == Fraction(123456, 10007).limit_denominator(1001)


@pytest.mark.parametrize("stream", [{}, {"r_frame_rate": "0/0", "avg_frame_rate": "0/0"},
                                    {"r_frame_rate": "x", "avg_frame_rate": None}])
def test_source_fps_none_valid(stream):
    from auto_short.render import RenderError
    from auto_short.render.stage import _rate
    with pytest.raises(ValueError):
        plan.source_fps(stream)
    with pytest.raises(RenderError, match="source frame rate"):
        _rate(stream)


def test_render_key_unchanged_for_equal_r_and_avg():
    from auto_short.render.stage import _rate, render_key
    stream = {"r_frame_rate": "30000/1001", "avg_frame_rate": "30000/1001"}
    layout = {"a": 1}
    from types import SimpleNamespace
    hdr = SimpleNamespace(lines=["h"], font_size=10)
    ttl = SimpleNamespace(lines=["t"], font_size=12)
    kw = dict(cfg_hash="c", font_sha="f", source_sha="s", segments=[[0, 1000]], dissolves=[], layout=layout,
              header=hdr, title=ttl)
    assert render_key(fps=plan.output_fps(_rate(stream)), **kw) == render_key(fps=NTSC, **kw)


# --- FIX-render-video-tail ---------------------------------------------------------------------------------

def test_tail_missing_counts_planned_frames_after_the_video_end():
    from auto_short.render.stage import video_end_seconds
    frames = plan.frame_plan([(1100, 2000), (2500, 4000)], NTSC)  # (33, 27), (75, 45): grid frames 33..119
    assert plan.tail_missing(frames, NTSC, None) == 0  # unknown end = old behaviour
    assert plan.tail_missing(frames, NTSC, 4.0) == 0  # 120 frames available
    assert plan.tail_missing(frames, NTSC, 120 / float(NTSC)) == 0
    assert plan.tail_missing(frames, NTSC, 118 / float(NTSC)) == 2
    assert plan.tail_missing(frames, NTSC, 0.0) == 72  # nothing available: all frames
    assert plan.tail_missing([(5, 0)], NTSC, 0.0) == 0  # empty segment
    assert plan.tail_clone_limit(NTSC) == 3 and plan.tail_clone_limit(Fraction(60)) == 6
    # video end from the probe: start_time + duration, else nb_frames / fps, else unknown
    assert video_end_seconds({"start_time": "0.5", "duration": "3.0"}, NTSC) == 3.5
    assert video_end_seconds({"nb_frames": "30"}, Fraction(30)) == 1.0
    assert video_end_seconds({"duration": "N/A"}, NTSC) is None
    # real file: 99752 frames end at 3328.392 s; a clip to 3328.44 s needs grid frames up to 99753 -> 2 missing
    assert plan.tail_missing(plan.frame_plan([(2950710, 3328440)], NTSC), NTSC, 3328.392) == 2


def test_filter_graph_tail_default_is_unchanged_and_tail_adds_tpad():
    segs = [(1100, 2000), (2500, 4000)]
    assert _graph(segs, tail=0) == _graph(segs) and "tpad" not in _graph(segs)
    g = _graph(segs, tail=2)
    assert "format=yuv444p,tpad=stop_mode=clone:stop=2,pad=1080:1920:0:211" in g
    assert g.replace("tpad=stop_mode=clone:stop=2,", "") == _graph(segs)
    segs = [(1100, 2000), (2500, 4000), (4050, 5000), (5500, 6000)]
    d = _graph(segs, dissolve=0.15, tail=2)
    assert "setpts=N/(30000/1001)/TB,tpad=stop_mode=clone:stop=2,pad=1080:1920:0:211" in d
    assert d.replace("tpad=stop_mode=clone:stop=2,", "") == _graph(segs, dissolve=0.15)
