"""SCH1 AC1–3: pure helpers and injected CLI transport, without sockets."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from auto_short.publish import PublishError, check, overview, schedule
from auto_short.publish.__main__ import main
from auto_short.workspace import atomic_write_json, read_json_dict
from test_publish_kt import IDS, PID, cli, workspace  # noqa: F401
from test_publish_schedule import NOW, video
from test_publish_thumbs import SECRETS, Wire, listing, no_sockets  # noqa: F401


def test_summarize_all_kinds_dates_distinct_ids_and_no_mutation():  # AC1
    sources = []
    for kind, name in (("vertical", "Bộ kinh_Tập{n}_Doc.mp4"),
                       ("kt", "T{n}_KT01_bài.mp4"), ("short", "T{n}_S01_bài.mp4")):
        for n, at in ((2, NOW + timedelta(days=9)), (99, NOW + timedelta(days=2))):
            sources.append(video(f"{kind}{n}", name.format(n=n), publish_at=at.isoformat()))
        sources.extend([
            video(kind + "public", name.format(n=3), privacy="public", uploaded=NOW.isoformat()),
            video(kind + "old", name.format(n=4), privacy="public", uploaded=(NOW - timedelta(days=1)).isoformat()),
            video(kind + "unlisted", name.format(n=5), privacy="unlisted", publish_at=(NOW + timedelta(days=30)).isoformat()),
            video(kind + "draft", name.format(n=6)),
            video(kind + "past", name.format(n=7), publish_at=(NOW - timedelta(seconds=1)).isoformat()),
            video(kind + "exact", name.format(n=8), publish_at=NOW.isoformat()),
            video(kind + "bad", name.format(n=9), publish_at="bad", uploaded="bad"),
            video(kind + "future-public", name.format(n=10), privacy="public",
                  uploaded=(NOW + timedelta(days=20)).isoformat()),
        ])
    sources.extend([deepcopy(sources[0]), video("unknown", "plain.mp4", privacy="public")])
    before = deepcopy(sources)
    result = overview.summarize(sources, NOW)
    for kind in schedule.KINDS:
        code = "" if kind == "vertical" else "_KT01" if kind == "kt" else "_S01"
        assert result[kind] == dict(
            last_scheduled=dict(key="T2" + code, publish_at=overview._iso(NOW + timedelta(days=9))),
            scheduled_count=2, last_public=dict(key="T3" + code, published_at=overview._iso(NOW)))
    assert sources == before
    assert all(g == dict(last_scheduled=None, scheduled_count=0, last_public=None)
               for g in overview.summarize([], NOW).values())
    with pytest.raises(PublishError, match="múi giờ"):
        overview.summarize([], NOW.replace(tzinfo=None))


def test_issues_reuses_check_keep_decision_holes_pending_and_strips_titles():  # AC2
    sources = [video("keep", "T2_S01_a.mp4", privacy="public"), video("delete", "T2_S01_b.mp4"),
               video("kt", "T1_KT01_a.mp4"), video("odd", "other.mp4"), video("not-in-site", "T5_S07_a.mp4")]
    expected = {(kind, n, 0 if kind == "vertical" else 1)
                for kind in schedule.KINDS for n in range(1, 7)}
    compared = check.compare(sources, expected)
    before = deepcopy(compared)
    result = overview.issues(compared)
    assert result["missing"] == dict(vertical=[], kt=[], short=["T1_S01", "T3_S01", "T4_S01", "T5_S01"])
    assert result["duplicates"] == [dict(kind="short", key="T2_S01", copies=[
        dict(youtube_id="keep", keep=True), dict(youtube_id="delete", keep=False)])]
    assert result["unrecognized_count"] == 1  # recognized but unexpected is not unrecognized
    assert result["pending"] == {k: dict(count=compared["summary"][k]["pending"],
                                        episodes=compared["summary"][k]["pending_episodes"])
                                 for k in schedule.KINDS}
    assert "title" not in json.dumps(result) and compared == before


def test_expired_private_schedule_keeps_final_code_with_zero_coverage():  # AC1,3
    stamp = NOW - timedelta(seconds=1)
    group = overview.summarize([video("expired", "T1_S01_a.mp4", publish_at=stamp.isoformat())], NOW)["short"]
    assert group["last_scheduled"] == dict(key="T1_S01", publish_at=overview._iso(stamp))
    assert group["scheduled_count"] == overview.coverage(group, NOW)["days_remaining"] == 0


def test_cli_writes_snapshot_after_success_and_preserves_it_on_error(workspace, cli, capsys):  # AC1–2,5
    sources = [video("keep", "T11_KT01_a.mp4", publish_at="2026-12-01T13:30:00Z"),
               video("delete", "T11_KT01_a.mp4"), video("unknown", "plain.mp4")]
    sources[0]["snippet"]["channelTitle"] = "Kênh thử"
    replies = listing(*sources)
    replies[0]["items"][0]["id"] = "UCoverview"
    wire = Wire(*replies, dict(items=[]), dict(items=[]))
    args = ["check", "--playlist", PID, *cli[5:]]
    assert main(args, transport=wire, now=NOW.timestamp) == 0
    file = workspace.workspace.dir / "_publish/channels/UCoverview.json"
    saved = read_json_dict(file)
    assert saved == dict(schema_version=1, channel_id="UCoverview", channel_title="Kênh thử",
                         playlist_id=PID, updated_at=overview._iso(NOW),
                         kinds=overview.summarize(sources, NOW),
                         **overview.issues(check.compare(sources, check.inventory(workspace, PID))))
    assert all(call[0] == "GET" for call in wire.calls) and not wire.responses
    output = capsys.readouterr().out
    assert "Trùng:" in output and "Tổng khai thị:" in output
    assert all(secret not in file.read_text() for secret in SECRETS)
    assert '"title"' not in file.read_text()
    original = file.read_bytes()
    # The channel read succeeded, but the later playlist read failed: no fresh snapshot.
    wire = Wire(*replies, dict(items=[]), (403, dict(error=dict(message="quota"))))
    assert main(args, transport=wire, now=lambda: NOW.timestamp() + 3600) == 1
    assert file.read_bytes() == original and not wire.responses
    file.unlink()
    assert main(args, transport=Wire((403, dict(error=dict(message="quota")))), now=NOW.timestamp) == 1
    assert not file.exists()


def test_snapshot_read_sort_missing_broken_and_unsafe_id(workspace):  # AC4
    assert overview.read(workspace) == []
    for ident, title in (("UCb", "B"), ("UCa", "A")):
        overview.write(workspace, dict(schema_version=1, channel_id=ident, channel_title=title,
                                       playlist_id=PID, updated_at=overview._iso(NOW),
                                       kinds=overview.summarize([], NOW)))
    folder = workspace.workspace.dir / "_publish/channels"
    (folder / "broken.json").write_text("{")
    atomic_write_json(folder / "unsupported.json", dict(schema_version=2))
    atomic_write_json(folder / "wrong.json", dict(schema_version=1, channel_id="UCa"))
    assert [d["channel_id"] for d in overview.read(workspace)] == ["UCa", "UCb"]
    with pytest.raises(PublishError, match="id kênh"):
        overview.write(workspace, dict(channel_id="../unsafe"))


@pytest.mark.parametrize("seconds,days,warn", [
    (-1, 0, True), (0, 0, True), (1, 1, True), (86400, 1, True),
    (6 * 86400, 6, True), (6 * 86400 + 1, 7, False), (7 * 86400, 7, False),
])
def test_coverage_ceil_and_seven_day_boundary(seconds, days, warn):  # AC3
    group = dict(last_scheduled=dict(key="T1", publish_at=overview._iso(NOW + timedelta(seconds=seconds))))
    before = deepcopy(group)
    assert overview.coverage(group, NOW) == dict(group, days_remaining=days, warning=warn)
    assert group == before
    assert overview.coverage({}, NOW) == dict(days_remaining=0, warning=True)


def test_stale_strictly_over_36_hours_and_timezone_equivalence():  # AC3
    for hours, seconds, stale in ((35, 0, False), (36, 0, False), (36, 1, True)):
        doc = dict(updated_at=(NOW - timedelta(hours=hours, seconds=seconds)).isoformat())
        assert overview.stale(doc, NOW) is stale


def test_post_summary_only_ticked_saved_slots_instant_boundary_and_final_past_slot():  # AC3
    posts = [dict(episode_id="source00001", clip_id=f"k{n:02d}", code=f"T1_S{n:02d}",
                  posted_at=None if n == 4 else "tick") for n in range(1, 6)]
    times = {f'source00001/k{n:02d}': dict(slot_at=overview._iso(NOW + timedelta(days=n - 2)),
                                         video_at="2099-01-01T00:00:00Z") for n in range(1, 5)}
    times["other-episode/k01"] = dict(slot_at="2099-01-01T00:00:00Z")
    before = deepcopy((posts, times))
    result = overview.summarize_posts(posts + [posts[2]], times, NOW)
    assert result == dict(last_scheduled=dict(key="T1_S03", publish_at=overview._iso(NOW + timedelta(days=1))),
                          scheduled_count=1, last_public=dict(key="T1_S02", published_at=overview._iso(NOW)))
    assert (posts, times) == before
    later = NOW + timedelta(days=10)
    group = overview.summarize_posts(posts, times, later)
    assert group["last_scheduled"]["key"] == group["last_public"]["key"] == "T1_S03"
    assert overview.coverage(group, later)["days_remaining"] == 0
