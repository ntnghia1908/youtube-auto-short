"""PST1 pure scheduling + local LNK1 integration; fake transport, no sockets."""
from __future__ import annotations

from datetime import timedelta
from itertools import islice

import pytest

from auto_short.post import links, schedule, store
from auto_short.workspace import atomic_write_json, read_json_dict
from test_post_links import EID, EID2, PID, PID2, SHORTS, seed, service, video


@pytest.mark.parametrize("instant,expected", [
    ("2026-11-19T01:59:59Z", "2026-11-19T09:00:00+07:00"),
    ("2026-11-19T09:00:00+07:00", "2026-11-19T09:00:00+07:00"),
    ("2026-11-19T02:00:01Z", "2026-11-19T15:00:00+07:00"),
    ("2026-11-19T15:00:00+07:00", "2026-11-19T15:00:00+07:00"),
    ("2026-11-19T20:30:00+07:00", "2026-11-19T20:30:00+07:00"),
    ("2026-12-31T20:30:01+07:00", "2027-01-01T09:00:00+07:00"),
])
def test_slots_after_boundaries_and_vietnam_timezone(instant, expected):  # AC2
    slots = list(islice(schedule.slots_after(schedule.timestamp(instant)), 5))
    assert slots[0].isoformat() == expected
    assert slots == sorted(slots) and all(s >= schedule.timestamp(instant) for s in slots)
    assert all((s.hour, s.minute) in {(9, 0), (15, 0), (20, 30)} for s in slots)


def test_plan_orders_reserves_only_ticked_slots_and_puts_unknown_last():  # AC2–3
    posts = [dict(episode_id=eid, clip_id=cid, code=code, posted_at=posted) for eid, cid, code, posted in [
        ("unknown", "k01", "T1_S01", None), ("ten", "k01", "T10_S01", None),
        ("two", "k02", "T2_S02", None), ("two", "k01", "T2_S01", None),
        ("old", "k01", "T20_S01", None), ("ticked", "k01", "T1_S01", "old"),
        ("legacy", "k01", "T1_S02", "old"), ("future", "k01", "T1_S03", None),
    ]]
    times = {f'{p["episode_id"]}/{p["clip_id"]}': {"video_at": "2026-11-19T00:00:00Z"}
             for p in posts if p["episode_id"] != "unknown"}
    times["old/k01"]["video_at"] = "2026-11-18T00:00:00Z"
    times["future/k01"]["video_at"] = "2026-11-21T08:00:01Z"
    times["ticked/k01"]["slot_at"] = "2026-11-19T09:00:00+07:00"
    times["two/k01"]["slot_at"] = "2026-11-19T08:00:00Z"  # unticked: not occupied
    before = repr((posts, times))
    planned = schedule.plan(posts, times, schedule.timestamp("2026-11-19T01:50:00Z"))
    assert list(planned)[3:] == ["two/k01", "two/k02", "ten/k01", "future/k01", "unknown/k01"]
    assert [planned[k] for k in list(planned)[3:]] == [
        "2026-11-19T08:00:00Z", "2026-11-19T13:30:00Z", "2026-11-20T02:00:00Z",
        "2026-11-21T13:30:00Z", None,
    ]
    assert planned["old/k01"] is None and planned["legacy/k01"] is None and repr((posts, times)) == before
    assert schedule.slot_fields(planned["two/k01"]) == {
        "slot_at": "2026-11-19T08:00:00Z", "slot_label": "19/11 3:00 PM"}
    assert schedule.slot_fields("2026-11-22T02:00:00Z")["slot_label"] == "22/11 9:00 AM"


@pytest.mark.parametrize("now,first", [
    ("2026-11-19T01:50:00Z", "2026-11-19T02:00:00Z"),
    ("2026-11-19T01:50:01Z", "2026-11-19T08:00:00Z"),
])
def test_plan_five_videos_per_day_delays_without_a_limit(now, first):  # AC2
    posts, times = [], {}
    for n in range(10):
        eid = f"episode{n:02}"
        posts.append(dict(episode_id=eid, clip_id="k01", code=f"T{n + 1}_S01", posted_at=None))
        times[f"{eid}/k01"] = {"video_at": f"2026-11-{19 + n // 5}T00:00:00Z"}
    instant = schedule.timestamp(now)
    planned = schedule.plan(list(reversed(posts)), times, instant)
    assert list(planned.values())[0] == first
    assert list(planned.values()) == [schedule._iso(s) for s in islice(
        schedule.slots_after(instant + timedelta(minutes=10)), 10)]
    assert len(set(planned.values())) == 10
    assert schedule.timestamp(list(planned.values())[-1]).day >= 22
    for key, at in planned.items():
        assert schedule.timestamp(at) >= max(schedule.timestamp(times[key]["video_at"]),
                                            instant + timedelta(minutes=10))


@pytest.mark.parametrize("status,snippet,expected", [
    ({"privacyStatus": "private", "publishAt": "2026-12-01T13:30:00Z"},
     {"publishedAt": "2026-10-01T00:00:00Z"}, "2026-12-01T13:30:00Z"),
    ({"privacyStatus": "public"}, {"publishedAt": "2026-11-18T02:00:00Z"}, "2026-11-18T02:00:00Z"),
    ({"privacyStatus": "private"}, {"publishedAt": "2026-11-18T02:00:00Z"}, None),
    ({"privacyStatus": "unlisted"}, {"publishedAt": "2026-11-18T02:00:00Z"}, None),
])
def test_sync_records_video_time_and_keeps_slot_without_changing_lnk1(service, status, snippet, expected):  # AC1,5
    svc, ctx, wire = service
    seed(ctx, posted=False)
    result = svc.add(PID, f"https://youtube.com/playlist?list={SHORTS}")
    assert result["last_scan"]["counts"]["filled"] == 1
    key = f"{EID}/k01"
    times = schedule.read(svc.times_path)
    assert times[key] == {"video_id": "youtube0001", "video_at": "2026-12-01T00:00:00Z"}
    times[key]["slot_at"] = "2026-12-01T02:00:00Z"
    schedule.write(svc.times_path, times)
    entry = wire.videos[SHORTS][0]
    entry["status"] = status
    entry["snippet"].update(snippet)
    doc = store.read_posts(ctx.posts_path(EID), EID)
    targets, _ = svc._targets(ctx.playlists.load(PID))
    expected_result = links.plan([entry], targets, {(EID, "k01"): doc["posts"][0]["link"]})
    scan = svc.sync(PID)["last_scan"]
    assert scan["counts"] == expected_result["counts"] and scan["rows"] == [] and scan["errors"] == []
    assert schedule.read(svc.times_path)[key] == {
        "video_id": "youtube0001", "video_at": expected, "slot_at": "2026-12-01T02:00:00Z"}
    assert store.read_posts(ctx.posts_path(EID), EID) == doc
    assert read_json_dict(svc.times_path)["schema_version"] == 1


@pytest.mark.parametrize("reason", ["waiting", "different", "duplicate"])
def test_sync_matched_rows_and_ambiguous_codes(service, reason):  # AC1
    svc, ctx, wire = service
    if reason != "waiting":
        seed(ctx, link="https://youtube.com/shorts/manual00001")
    if reason == "duplicate":
        wire.videos[SHORTS].append(video("youtube0003"))
    scan = svc.add(PID, f"https://youtube.com/playlist?list={SHORTS}")["last_scan"]
    assert scan["counts"][reason] == (2 if reason == "duplicate" else 1)
    assert (f"{EID}/k01" in schedule.read(svc.times_path)) == (reason != "duplicate")


def test_schedule_view_selects_linked_playlist_and_isolates_channels(service):  # AC2,4
    svc, ctx, _ = service
    seed(ctx, posted=False)
    seed(ctx, EID + ".kt", posted=False)
    seed(ctx, EID2, posted=False)
    doc = ctx.playlists.load(PID2)
    doc["entries"].append({"video_id": EID})
    atomic_write_json(ctx.playlists.path(PID2), doc)
    ctx.playlists.set_link_playlist(PID2, SHORTS)
    times = {f"{eid}/k01": {"video_id": "youtube0001", "video_at": "2026-11-19T00:00:00Z"}
             for eid in (EID, EID + ".kt", EID2)}
    schedule.write(svc.times_path, times)
    with ctx.post_lock:
        slots, next_episode = svc.schedule_view(EID, schedule.timestamp("2026-11-19T00:00:00Z"))
        assert set(slots) == set(times) and next_episode == EID2
        assert svc.schedule_view(EID + ".kt", schedule.timestamp("2026-11-19T00:00:00Z")) == (slots, next_episode)
    doc["entries"] = [{"video_id": EID2}]
    atomic_write_json(ctx.playlists.path(PID2), doc)
    with ctx.post_lock:
        a, _ = svc.schedule_view(EID, schedule.timestamp("2026-11-19T00:00:00Z"))
        b, _ = svc.schedule_view(EID2, schedule.timestamp("2026-11-19T00:00:00Z"))
        assert min(a.values()) == b[f"{EID2}/k01"]  # independent website playlists
        assert svc.schedule_view("unlisted001", schedule.timestamp("2026-11-19T00:00:00Z")) == ({}, None)
    # A posted clip still occupies its saved slot after it disappears from the rendered targets.
    seed(ctx, EID + ".kt", posted=True)
    times[f"{EID}.kt/k01"]["slot_at"] = "2026-11-19T02:00:00Z"
    schedule.write(svc.times_path, times)
    manifest_path = ctx.config.render.output_dir / (EID + ".kt") / "render_manifest.json"
    manifest = read_json_dict(manifest_path)
    manifest["shorts"][0]["status"] = "skipped"
    atomic_write_json(manifest_path, manifest)
    with ctx.post_lock:
        slots, _ = svc.schedule_view(EID, schedule.timestamp("2026-11-19T00:00:00Z"))
        assert slots[f"{EID}/k01"] == "2026-11-19T08:00:00Z"
        assert slots[f"{EID}.kt/k01"] == "2026-11-19T02:00:00Z"


def test_time_file_corruption_is_not_overwritten_and_sync_result_survives(service):  # AC1,3
    svc, ctx, _ = service
    seed(ctx)
    svc.times_path.parent.mkdir(parents=True, exist_ok=True)
    svc.times_path.write_text('{"schema_version": 9}')
    with pytest.raises(ValueError, match="schema"):
        schedule.read(svc.times_path)
    scan = svc.add(PID, f"https://youtube.com/playlist?list={SHORTS}")["last_scan"]
    assert scan["counts"]["filled"] == 1 and scan["errors"] == []
    assert svc.times_path.read_text() == '{"schema_version": 9}'


@pytest.mark.parametrize("video_at,group", [
    ("2026-11-18T16:59:59Z", "legacy"),
    ("2026-11-19T00:00:00+07:00", "scheduled"),
    ("2026-11-18T17:00:01Z", "scheduled"),
])
def test_legacy_cutoff_backlog_does_not_delay_new_posts_or_release_saved_ticks(video_at, group):  # AC6
    posts = [dict(episode_id=f"old{n}", clip_id="k01", code=f"T{n}_S01", posted_at=None)
             for n in range(148)]
    posts += [dict(episode_id=eid, clip_id="k01", code=f"T{n}_S01", posted_at="ticked" if eid == "saved" else None)
              for n, eid in enumerate(("boundary", "future", "unknown", "saved"), 200)]
    times = {f"old{n}/k01": {"video_at": "2026-11-18T16:59:59Z"} for n in range(148)}
    times["old0/k01"]["slot_at"] = "2026-11-24T13:30:00Z"  # unticked saved state cannot reserve a slot
    times.update({"boundary/k01": {"video_at": video_at},
                  "future/k01": {"video_at": "2026-11-24T13:30:00Z"},
                  "saved/k01": {"video_at": "2026-11-18T16:59:59Z", "slot_at": "2026-11-19T02:00:00Z"}})
    before = repr((posts, times))
    slots = schedule.plan(posts, times, schedule.timestamp("2026-11-19T00:00:00Z"))
    assert schedule.LEGACY_BEFORE.isoformat() == "2026-11-19T00:00:00+07:00"
    assert all(slots[f"old{n}/k01"] is None for n in range(148))
    assert slots["boundary/k01"] == (None if group == "legacy" else "2026-11-19T08:00:00Z")
    assert slots["future/k01"] == "2026-11-24T13:30:00Z"
    assert slots["saved/k01"] == "2026-11-19T02:00:00Z" and slots["unknown/k01"] is None
    by_id = {p["episode_id"]: p for p in posts}
    for eid, expected in (("old0", "legacy"), ("boundary", group), ("future", "scheduled"),
                          ("unknown", "unscheduled"), ("saved", "scheduled")):
        key = f"{eid}/k01"
        assert schedule.slot_group(by_id[eid], times.get(key, {}), slots[key]) == expected
    assert repr((posts, times)) == before


# PST2: append-only coverage; the PST1 cases above remain unchanged.
def test_anchor_file_roundtrip_preserves_times_and_legacy_files(tmp_path):  # AC1
    file = tmp_path / "post_times.json"
    assert schedule.read(file) == {} and schedule.read_anchors(file) == {}
    times = {"episode/k01": {"video_at": None, "slot_at": "2027-05-31T02:00:00Z"}}
    atomic_write_json(file, {"schema_version": 1, "times": times})
    assert schedule.read(file) == times and schedule.read_anchors(file) == {}
    anchors = {PID: {"code": "T35_S06", "slot_at": "2027-05-30T20:30:00+07:00"},
               PID2: {"code": "T30_KT07", "slot_at": "2027-03-06T15:00:00+07:00"}}
    schedule.write(file, times, anchors)
    expected = {pid: {**a, "slot_at": schedule._iso(schedule.timestamp(a["slot_at"]))}
                for pid, a in anchors.items()}
    assert schedule.read(file) == times and schedule.read_anchors(file) == expected
    times["new/k01"] = {"video_at": "2027-06-01T00:00:00Z"}
    schedule.write(file, times)  # ordinary video-sync / tick writes must retain both anchors
    assert schedule.read_anchors(file) == expected
    expected.pop(PID)
    schedule.write(file, times, expected)
    assert schedule.read_anchors(file) == expected and schedule.read(file) == times
    assert read_json_dict(file)["schema_version"] == 1


@pytest.mark.parametrize("anchor", [
    None, [], {}, {"code": None, "slot_at": "2027-05-30T13:30:00Z"},
    {"code": "T35_S00", "slot_at": "2027-05-30T13:30:00Z"},
    {"code": "T35_S06_title", "slot_at": "2027-05-30T13:30:00Z"},
    {"code": "T35_S06", "slot_at": "2027-05-30T20:30:00"},
    {"code": "T35_S06", "slot_at": "2027-02-30T20:30:00+07:00"},
    {"code": "T35_S06", "slot_at": 123},
])
def test_anchor_file_rejects_invalid_state_without_overwriting(tmp_path, anchor):  # AC1
    file = tmp_path / "post_times.json"
    atomic_write_json(file, {"schema_version": 1, "times": {}, "anchors": {PID: anchor}})
    before = file.read_bytes()
    with pytest.raises(ValueError):
        schedule.read(file)
    with pytest.raises(ValueError):
        schedule.write(file, {})
    assert file.read_bytes() == before


def test_anchor_sequence_manual_group_and_saved_slots():  # AC2–3,5
    codes = ["T35_KT01", "T36_S01", "T35_S08", "T35_S06", "T35_S07", "T35_S05", "T34_KT07"]
    posts = [dict(episode_id=code, clip_id="k01", code=code, posted_at=None) for code in codes]
    posts.append(dict(episode_id="saved", clip_id="k01", code="T35_S01", posted_at="old tick"))
    posts.append(dict(episode_id="oldtick", clip_id="k01", code="T35_S02", posted_at="old tick"))
    times = {"saved/k01": {"slot_at": "2027-05-31T08:00:00Z"},
             "T35_S07/k01": {"video_at": "2026-11-18T00:00:00Z"},  # P3a replaced
             "T35_S06/k01": {"slot_at": "2027-05-31T02:00:00Z"}}  # unticked, does not occupy
    anchor = {"code": "T35_S06", "slot_at": "2027-05-30T20:30:00+07:00"}
    before = repr((posts, times, anchor))
    slots = schedule.plan(posts, times, schedule.timestamp("2026-11-20T00:00:00Z"), anchor)
    assert [slots[f"{c}/k01"] for c in ("T35_S07", "T35_S08", "T35_KT01", "T36_S01")] == [
        "2027-05-31T02:00:00Z", "2027-05-31T13:30:00Z", "2027-06-01T02:00:00Z", "2027-06-01T08:00:00Z"]
    assert slots["saved/k01"] == "2027-05-31T08:00:00Z"
    for post in posts:
        key = f'{post["episode_id"]}/k01'
        group = schedule.slot_group(post, times.get(key, {}), slots[key], anchor)
        if post["code"] in {"T35_S06", "T35_S05", "T34_KT07"}:
            assert slots[key] is None and group == "manual"
        elif post["episode_id"] == "oldtick":
            assert slots[key] is None and group == "unscheduled"
        else:
            assert group == "scheduled"
    assert repr((posts, times, anchor)) == before
    assert schedule.plan(posts, times, schedule.timestamp("2026-11-20T00:00:00Z")) == schedule.plan(
        posts, times, schedule.timestamp("2026-11-20T00:00:00Z"), anchor=None)


@pytest.mark.parametrize("now,video,expected", [
    ("2027-03-06T00:00:00Z", None, "2027-03-06T13:30:00Z"),
    ("2027-03-06T13:20:00Z", None, "2027-03-06T13:30:00Z"),
    ("2027-03-06T13:20:01Z", None, "2027-03-07T02:00:00Z"),
    ("2027-03-06T00:00:00Z", "2027-03-08T02:00:01Z", "2027-03-08T08:00:00Z"),
])
def test_kt_anchor_numeric_order_and_time_floors(now, video, expected):  # AC2
    codes = ["T31_KT01", "T30_S99", "T31_S10", "T30_KT07", "T31_S02", "T31_S01"]
    posts = [dict(episode_id=c, clip_id="k01", code=c, posted_at=None) for c in codes]
    anchor = {"code": "T30_KT07", "slot_at": "2027-03-06T15:00:00+07:00"}
    times = {"T31_S01/k01": {"video_at": video}}
    slots = schedule.plan(posts, times, schedule.timestamp(now), anchor)
    assert slots["T30_S99/k01"] is None and slots["T30_KT07/k01"] is None
    assert slots["T31_S01/k01"] == expected
    after = [slots[f"{c}/k01"] for c in ("T31_S01", "T31_S02", "T31_S10", "T31_KT01")]
    assert after == sorted(set(after))


def test_anchor_schedule_view_uses_selected_playlist_and_sync_keeps_anchor(service):  # AC1–3
    svc, ctx, _ = service
    for eid in (EID, EID + ".kt", EID2):
        seed(ctx, eid, posted=False)
    doc = ctx.playlists.load(PID2)
    doc["entries"].append({"video_id": EID})
    atomic_write_json(ctx.playlists.path(PID2), doc)
    ctx.playlists.set_link_playlist(PID, SHORTS)
    anchors = {PID: {"code": "T1_S01", "slot_at": "2027-05-30T13:30:00Z"},
               PID2: {"code": "T99_KT01", "slot_at": "2027-06-30T13:30:00Z"}}
    schedule.write(svc.times_path, {}, anchors)
    with ctx.post_lock:
        slots, nxt, selected, anchor = svc.schedule_view(
            EID, schedule.timestamp("2026-11-20T00:00:00Z"), with_anchor=True)
    assert selected == PID and anchor == anchors[PID]
    assert slots[f"{EID}/k01"] is None and slots[f"{EID}.kt/k01"] == "2027-05-31T02:00:00Z"
    assert nxt is None  # EID2 belongs to another playlist, whose posts are all manual
    svc.sync(PID)
    assert schedule.read_anchors(svc.times_path) == anchors
    with ctx.post_lock:
        other, nxt = svc.schedule_view(EID2, schedule.timestamp("2026-11-20T00:00:00Z"))
    assert all(slot is None for slot in other.values()) and nxt is None
