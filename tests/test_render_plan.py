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
    g = plan.geometry(RenderConfig())
    assert (g.header_w, g.header_h, g.video_h, g.title_w, g.title_h) == (853, 292, 1210, 875, 292)
    assert (g.gap_header_video, g.gap_video_title, g.radius, g.min_frame_margin) == (5, 11, 59, 22)
    assert g.title_max_h == 1920 - 2 * 22 - (292 + 5 + 1210 + 11) == 358
    lay = plan.layout(g, g.title_h, 1440, 1080)
    assert lay.as_dict() == {
        "header_panel": {"x": 113, "y": 55, "w": 853, "h": 292, "radius": 59},
        "video": {"x": 0, "y": 352, "w": 1080, "h": 1210, "crop": {"w": 964, "h": 1080, "x": 238, "y": 0}},
        "title_panel": {"x": 102, "y": 1573, "w": 875, "h": 292, "radius": 59},
    }


def test_taller_title_panel_recentres_block():
    g = plan.geometry(RenderConfig())
    lay = plan.layout(g, 353, 1440, 1080)
    top = lay.header.y
    bottom = lay.title.y + lay.title.h
    assert top == (1920 - (1518 + 353)) // 2 == 24
    assert abs(top - (1920 - bottom)) <= 1
    assert lay.video.y == top + 292 + 5 and lay.title.y == lay.video.y + 1210 + 11


def test_center_crop_other_aspects():
    assert plan.center_crop(1920, 1080, 1080, 1210) == plan.Crop(964, 1080, 478, 0)  # 16:9 keeps ~50 %
    assert plan.center_crop(1080, 1920, 1080, 1210) == plan.Crop(1080, 1210, 0, 355)  # vertical: crop height


def test_geometry_rejects_block_taller_than_frame():
    with pytest.raises(plan.PlanError, match="does not fit"):
        plan.geometry(replace(RenderConfig(), video_height=1.5))


# --- R6 -------------------------------------------------------------------------------------------------------

def test_escape_option():
    assert plan.escape_option("/a b/f.ttf") == "/a b/f.ttf"
    assert plan.escape_option("C:/x'y,z") == "C\\\\:/x\\\\\\'y\\,z"


def _graph(segments, **kw):
    g = plan.geometry(RenderConfig())
    lay = plan.layout(g, 353, 1440, 1080)
    lines = [plan.TextLine(Path("/t/h0.txt"), 100)]
    return plan.filter_graph(segments=segments, fps=NTSC, lay=lay, font_file=Path("/f/font.ttf"),
                             header_lines=lines, header_size=67, title_lines=lines, title_size=88, **kw)


def test_filter_graph_structure():
    graph = _graph([(1100, 2000), (2500, 4000)])
    assert graph.startswith("[0:v]fps=30000/1001,select='between(round(t*30000/1001),33,59)+"
                            "between(round(t*30000/1001),75,119)'")
    assert "crop=964:1080:238:0,scale=1080:1210:flags=lanczos" in graph
    assert "pad=1080:1920:0:321" in graph
    assert "[0:a]asplit=2[as0][as1]" in graph
    assert "[as0]atrim=start=1.1:end=2,asetpts=PTS-STARTPTS[a0]" in graph
    assert "[as1]atrim=start=2.5:end=4,asetpts=PTS-STARTPTS[a1]" in graph
    assert "[a0][a1]concat=n=2:v=0:a=1" in graph
    assert "drawtext=fontfile=/f/font.ttf:textfile=/t/h0.txt:expansion=none:text_shaping=1:fontsize=67" in graph
    assert "y_align=baseline:y=100" in graph
    assert "[vid][hp]overlay=113:24" in graph and "[v1][tp]overlay=102:1542" in graph
    assert "color=c=0xFEDB00:s=875x353" in graph
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
             "setpts=N/(30000/1001)/TB,crop=964:1080:238:0,scale=1080:1210:flags=lanczos,setsar=1,"
             "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,pad=1080:1920:0:321:color=0x000000[vid];")


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
    per_frame = ("crop=964:1080:238:0,scale=1080:1210:flags=lanczos,setsar=1,"
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
    assert f"[x3]setpts=N/({f})/TB,pad=1080:1920:0:321:color=0x000000[vid];" in graph
    # audio unchanged: hard cuts
    assert "[a0][a1][a2][a3]concat=n=4:v=0:a=1" in graph and "afade" not in graph and "acrossfade" not in graph
