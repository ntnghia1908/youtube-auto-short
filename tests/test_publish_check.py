"""PUB3.1 C3/C4: website artifacts, pure comparison and read-only CLI."""
from copy import deepcopy
import json
import unicodedata

import pytest

from auto_short.packaging import khaithi_thumbs
from auto_short.publish import check, schedule
from auto_short.publish.__main__ import main
from auto_short.render.full import vertical_path
from auto_short.review.logic import empty_review
from auto_short.workspace import atomic_write_json, read_json_dict
from test_publish_kt import IDS, PID, cli, workspace  # noqa: F401
from test_publish_schedule import NOW, video
from test_publish_thumbs import Wire, listing, no_sockets  # noqa: F401


@pytest.mark.parametrize("name,title,kind,episode", [
    ("Thái Thượng Cảm Ứng Thiên_Tập25_Doc.mp4", "", "vertical", 25),
    ("  THÁI THƯỢNG CẢM ỨNG THIÊN_tẬp025_dOC.MP4  ", "", "vertical", 25),
    ("Thái Thượng Cảm Ứng Thiên_Tập25_Doc", "", "vertical", 25),
    ("upload-cu.mp4", "[HD mobile] Thái Thượng Cảm Ứng Thiên - PS. Tịnh Không - Tập 25", "vertical", 25),
    (None, "[HD mobile] Thái Thượng Cảm Ứng Thiên - PS. Tịnh Không - Tập 25", "vertical", 25),
    ("T2_S01_nguyên bản.mp4", "[HD mobile] Bộ khác - Tập 25", "short", 2),
    ("Thái Thượng Cảm Ứng Thiên_Tập25_Doc.mp4", "[HD mobile] Bộ khác - Tập 99", "vertical", 25),
    (None, "Giữ tâm thanh tịnh", None, None),
    ("Thái Thượng Cảm Ứng Thiên_Tập25_Doc.mp4.bak", "", None, None),
])
def test_legacy_vertical_classification_and_title_fallback(name, title, kind, episode):
    source = video(name=unicodedata.normalize("NFD", name) if name else name,
                   title=unicodedata.normalize("NFD", title))
    fields = schedule.classify(source)
    if kind is None:
        assert fields is None
    else:
        assert (fields["kind"], fields["episode"]) == (kind, episode)
        if kind == "vertical" and "_" in (name or ""):
            assert fields["series"] == "thái thượng cảm ứng thiên"


def test_check_legacy_verticals_fill_25_episodes_and_leave_29_unknown():
    sources = [video(f"vertical{n}", f"Thái Thượng Cảm Ứng Thiên_Tập{n}_Doc.mp4",
                     title=f"[HD mobile] Thái Thượng Cảm Ứng Thiên - PS. Tịnh Không - Tập {n}",
                     privacy="public") for n in range(1, 26)]
    sources += [video(f"old-clip{n}", None, title="Giữ tâm thanh tịnh") for n in range(29)]
    result = check.compare(sources, {("vertical", n, 0) for n in range(1, 26)})
    assert result["summary"]["vertical"]["channel"] == 25
    assert result["summary"]["vertical"]["missing"] == result["summary"]["vertical"]["pending"] == 0
    assert len(result["rows"]) == 29
    assert all(row["group"] == "unexpected" and row["reason"] == "không nhận ra loại"
               for row in result["rows"])


@pytest.mark.parametrize("privacy,publish_at", [("public", None), ("unlisted", None),
                                               ("private", "2026-11-25T00:00:00Z"), ("private", None)])
def test_legacy_vertical_blocks_modern_draft_without_merging_other_series(privacy, publish_at):
    old = video("old", "Thái Thượng Cảm Ứng Thiên_Tập25_Doc.mp4", privacy=privacy,
                publish_at=publish_at, uploaded="2026-11-16T00:00:00Z")
    draft = video("draft", "[HD Mobile] Thái Thượng Cảm Ứng Thiên - PS. Tịnh Không - Tập 25.mp4")
    other = video("other", "[HD Mobile] Thái Thượng Cảm Ứng Thiên Chú Giải - PS. Tịnh Không - Tập 25.mp4")
    assert schedule.classify(old)["key"] != schedule.classify(draft)["key"]
    for sources in ([draft, old, other], [old, other, draft]):
        rows = {row["youtube_id"]: row for row in schedule.plan(sources, NOW)}
        assert rows["draft"]["reason"] == "đã có bản old" and not rows["draft"]["publish_at"]
        assert rows["other"]["status"] == "sẵn sàng"
        assert rows["old"]["status"] == ("sẵn sàng" if privacy == "private" and not publish_at else "bỏ qua")


def test_inventory_local_released_vertical_and_resolved_titles(workspace):
    cfg = workspace
    assert check.inventory(cfg, PID) == {("kt", n, clip) for n in (7, 11) for clip in (1, 2, 3)}
    path = vertical_path(cfg, IDS[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"vertical")
    atomic_write_json(cfg.workspace.dir / IDS[1] / "backup.json",
                      dict(schema_version=1, released=dict(vertical=dict(sha256="a" * 64, size=123))))
    for ident in IDS:
        atomic_write_json(cfg.workspace.dir / ident / "titles.json", dict(
            header=dict(fields=dict(series="Bộ kinh", episode="11" if ident == IDS[0] else "7")),
            titles=[dict(clip_id=cid, candidate_id=f"c{i:02d}", title="Bình an", status="titled")
                    for i, cid in enumerate(("k01", "k04"), 1)]))
    # Number only the visible resolved titles, independent of digits in clip ids or thumbnail records.
    review = empty_review(IDS[0] + ".kt")
    review["rejected"] = [dict(clip_id="k02", candidate_id="c03")]
    atomic_write_json(cfg.workspace.dir / (IDS[0] + ".kt") / "review.json", review)
    marker = cfg.workspace.dir / (IDS[1] + ".kt") / "khaithi.json"
    marker.unlink()  # titles.json by itself cannot create a KT inventory.
    expected = {("vertical", 11, 0), ("vertical", 7, 0), ("kt", 11, 1), ("kt", 11, 2),
                *(("short", n, clip) for n in (7, 11) for clip in (1, 2))}
    assert check.inventory(cfg, PID) == expected
    assert khaithi_thumbs.titles(cfg, IDS[1] + ".kt") == []


@pytest.mark.parametrize("privacy,publish_at", [("public", None), ("unlisted", None),
                                               ("private", "2026-11-25T00:00:00Z"), ("private", None)])
def test_compare_duplicate_keep_priority_and_earliest_upload(privacy, publish_at):
    sources = [video("late", "T2_S01_a.mp4", uploaded="2026-11-18T00:00:00Z"),
               video("first", "T2_S01_a.mp4", uploaded="2026-11-16T02:00:00+02:00"),
               video("priority", "T2_S01_a.mp4", privacy=privacy, publish_at=publish_at),
               video("vertical1", "[HD Mobile] Bộ A - Tập 2.mp4"),
               video("vertical2", "[HD Dọc] Bộ B - Tập 2.mp4"),
               video("kt", "T2_KT01_b.mp4")]
    stock = {("short", 2, 1), ("kt", 2, 1), ("vertical", 2, 0)}
    before = deepcopy((sources, stock))
    result = check.compare(sources, stock)
    duplicates = [r for r in result["rows"] if r["group"] == "duplicate"]
    kept = {r["key"]: r["youtube_id"] for r in duplicates if r["keep"]}
    assert kept == dict(T2="vertical1", T2_S01="first" if privacy == "private" and not publish_at else "priority")
    assert {r["youtube_id"] for r in duplicates} == {"late", "first", "priority", "vertical1", "vertical2"}
    assert all(r["uploaded_at"] and r["privacy"] for r in duplicates)
    assert result["summary"]["short"]["duplicates"] == result["summary"]["vertical"]["duplicates"] == 1
    assert not [r for r in result["rows"] if r["group"] in ("missing", "unexpected")]
    assert (sources, stock) == before


def test_compare_holes_pending_and_unexpected_by_independent_kind():
    stock = {(kind, n, 0 if kind == "vertical" else clip)
             for kind in schedule.KINDS for n in (1, 2, 3, 4) for clip in (1, 2)}
    sources = [video("short", "T3_S01_a.mp4", privacy="public"),
               video("kt", "T1_KT02_b.mp4", privacy="unlisted"),
               video("odd-clip", "T3_S05_b.mp4"), video("unknown", "foreign.mp4")]
    result = check.compare(sources, stock)
    holes = {r["key"] for r in result["rows"] if r["group"] == "missing"}
    assert holes == {"T1_S01", "T1_S02", "T2_S01", "T2_S02", "T3_S02", "T1_KT01"}
    assert {r["youtube_id"] for r in result["rows"] if r["group"] == "unexpected"} == {"odd-clip", "unknown"}
    for kind, pending, episodes in (("short", 2, [4]), ("kt", 6, [2, 3, 4]), ("vertical", 4, [1, 2, 3, 4])):
        assert result["summary"][kind]["pending"] == pending
        assert result["summary"][kind]["pending_episodes"] == episodes
    lines = []
    check.report(result, output=lines.append)
    output = "\n".join(lines)
    assert "chưa đăng T4–T4 (2 video)" in output and "chưa đăng T2–T4 (6 video)" in output
    assert "không nhận ra loại" in output and "odd-clip" in output
    assert sum(line.startswith("Tổng ") for line in lines) == 3
    assert check.compare([], set())["rows"] == []


@pytest.mark.parametrize("refresh", [False, True])
def test_check_cli_get_only_and_refresh_cache(workspace, cli, capsys, refresh):
    args = ["check", "--playlist", PID, *cli[5:]]
    source = video("short", "T11_S01_a.mp4")
    replies = listing(source)
    replies[0]["items"][0]["id"] = "UCcheck"
    wire = Wire(*replies, dict(items=[], nextPageToken="p2"), dict(items=[]), dict(items=[]))
    assert main(args + (["--refresh"] if refresh else []), transport=wire, now=NOW.timestamp) == 0
    output = capsys.readouterr().out
    assert all(label in output for label in ("Trùng:", "Thiếu:", "Lạ:", "Tổng khai thị:", "search: 2 lượt"))
    assert all(call[0] == "GET" for call in wire.calls) and not wire.responses
    path = workspace.workspace.dir / "_publish" / "videos" / "UCcheck.json"
    assert read_json_dict(path)["ids"] == ["short"]
    # Incremental mode stops on an empty first page; --refresh must keep going.
    wire = Wire(*replies, dict(items=[], nextPageToken="p2"), *([dict(items=[])] if refresh else []), dict(items=[]))
    assert main(args + (["--refresh"] if refresh else []), transport=wire, now=NOW.timestamp) == 0
    assert f"search: {2 if refresh else 1} lượt" in capsys.readouterr().out
    assert all(call[0] == "GET" for call in wire.calls) and not wire.responses


@pytest.mark.parametrize("refresh", [False, True])
def test_schedule_playlist_warnings_preserve_slots_and_apply(workspace, cli, capsys, refresh):
    sources = [video("s2", "T11_S02_b.mp4"), video("s1", "T11_S01_a.mp4"),
               video("duplicate", "T11_S01_a.mp4", uploaded="2026-11-18T00:00:00Z")]
    args = ["schedule", *cli[5:], *(["--refresh"] if refresh else [])]
    results = []
    replies = listing(*sources)
    replies[0]["items"][0]["id"] = "UCschedule"
    for index, playlist in enumerate(([], ["--playlist", PID])):
        wire = Wire(*replies, dict(items=[], nextPageToken="p2"),
                    *([dict(items=[])] if refresh or index == 0 else []), dict(items=[]))
        assert main(args + playlist, transport=wire, now=NOW.timestamp) == 0
        output = capsys.readouterr().out
        results.append(json.loads(output[output.index('{\n  "mode"'):]))
        if playlist:
            assert output.index("Trùng:") < output.index("Giờ VN dự kiến")
            assert "giữ" in output and "duplicate" in output
        assert f"search: {2 if refresh or index == 0 else 1} lượt" in output
        assert all(call[0] == "GET" for call in wire.calls) and not wire.responses
    assert results[0] == results[1]
    wire = Wire(*replies, dict(items=[]), dict(items=[]), dict(id="s1"))
    assert main(args + ["--playlist", PID, "--apply", "--only", "s1"],
                transport=wire, now=NOW.timestamp) == 0
    output = capsys.readouterr().out
    result = json.loads(output[output.index('{\n  "mode"'):])
    row = next(r for r in results[0]["rows"] if r["youtube_id"] == "s1")
    assert result["rows"][0]["publish_at"] == row["publish_at"]
    assert [call[0] for call in wire.calls].count("PUT") == 1 and not wire.responses


def test_check_requires_playlist_and_validates_local_before_http(cli):
    with pytest.raises(SystemExit) as exc:
        main(["check"])
    assert exc.value.code == 2
    wire = Wire()
    assert main(["check", "--playlist", "PLmissing123", *cli[5:]], transport=wire) == 1
    assert not wire.calls
