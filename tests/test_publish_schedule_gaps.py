"""PUB3.2: code-ordered reservations, gap filling and resumable private reflow."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from auto_short.publish import PublishError, check, schedule, youtube
from auto_short.publish.__main__ import main
from auto_short.publish.overview import _iso as iso
from auto_short.workspace import atomic_write_json, read_json_dict
from test_publish_schedule import NOW, local, video  # noqa: F401
from test_publish_thumbs import Wire, listing, no_sockets, oauth  # noqa: F401


def kt(ident, number, clip, **kwargs):
    return video(ident, f"T{number}_KT{clip:02d}_Bài giảng.mp4", **kwargs)


@pytest.mark.parametrize("kind", ["vertical", "kt", "short"])
def test_reservations_follow_inventory_and_exclude_pending_tail(kind):
    names = {"vertical": lambda n: f"[HD Mobile] Bộ A - Tập {n}.mp4",
             "kt": lambda n: f"T{n}_KT01_a.mp4", "short": lambda n: f"T{n}_S01_a.mp4"}
    clip = 0 if kind == "vertical" else 1
    stock = {(kind, n, clip) for n in (29, 30, 31, 32)}
    first_name = "Bộ A_Tập29_Doc.mp4" if kind == "vertical" else names[kind](29)
    sources = [video("next", names[kind](31)), video("first", first_name)]
    before = deepcopy((sources, stock))
    rows = schedule.plan(sources, NOW, stock)
    assigned = [row for row in rows if row["publish_at"]]
    assert [row["episode"] for row in assigned] == [29, 30, 31]
    assert [row["status"] for row in assigned] == ["sẵn sàng", "giữ chỗ", "sẵn sàng"]
    after = NOW.replace(hour=23, minute=59, second=59)
    for row in assigned:
        after = schedule._next_slot(kind, after, NOW + timedelta(hours=1))
        assert row["publish_at"] == iso(after)
    assert assigned[1]["youtube_id"] == "" and "(thiếu)" in assigned[1]["reason"]
    assert (sources, stock) == before


@pytest.mark.parametrize("full", [False, True])
def test_fill_reserved_slot_or_warn_when_interval_is_full(full):
    stock = {("kt", 30, 5), ("kt", 30, 6), ("kt", 31, 1), ("kt", 32, 1)}
    first = kt("first", 30, 5)
    last = kt("last", 31, 1)
    original = schedule.plan([last, first], NOW, stock)
    reservation = next(row for row in original if row["status"] == "giữ chỗ")
    for source in (first, last):
        source["status"]["publishAt"] = next(row["publish_at"] for row in original
                                               if row["youtube_id"] == source["id"])
    sources = [first, kt("fill", 30, 6), last]
    if full:
        # A scheduled unexpected code still occupies a slot of this kind.
        sources.append(kt("blocker", 90, 1, publish_at=reservation["publish_at"]))
    row = next(row for row in schedule.plan(sources, NOW, stock) if row["youtube_id"] == "fill")
    assert row["status"] == "sẵn sàng"
    if full:
        assert row["publish_at"] == iso(schedule._next_slot("kt", schedule._timestamp(last["status"]["publishAt"]), NOW))
        assert "lệch thứ tự" in row["reason"]
    else:
        assert row["publish_at"] == reservation["publish_at"] and not row["reason"]
    assert first["status"]["publishAt"] == original[0]["publish_at"]


@pytest.mark.parametrize("existing", ["draft", "public", "scheduled"])
def test_duplicate_selection_and_cli_summary(local, monkeypatch, capsys, existing):
    cfg, args = local
    stock = {("kt", 30, 5)}
    monkeypatch.setattr(check, "inventory", lambda config, pid: stock)
    oldest = kt("oldest", 30, 5, uploaded="2026-11-01T00:00:00Z")
    duplicate = kt("duplicate", 30, 5)
    if existing == "public":
        oldest["status"]["privacyStatus"] = "public"
    elif existing == "scheduled":
        oldest["status"]["publishAt"] = "2026-11-19T05:30:00Z"
    rows = schedule.plan([duplicate, oldest], NOW, stock)
    assert [row["youtube_id"] for row in rows if row["status"] == "sẵn sàng"] == \
        (["oldest"] if existing == "draft" else [])
    skipped = next(row for row in rows if row["youtube_id"] == "duplicate")
    assert skipped["status"] == "bỏ qua" and skipped["reason"] == "đã có bản oldest"
    wire = Wire(*listing(duplicate, oldest), dict(items=[]))
    assert main(args + ["--playlist", "PLtest"], transport=wire, now=NOW.timestamp) == 0
    output = capsys.readouterr().out
    assert "trùng — chưa lên lịch" in output and "Trùng — chưa lên lịch (1): duplicate" in output
    assert all(call[0] == "GET" for call in wire.calls) and not wire.responses
    assert not (cfg.workspace.dir / "_publish" / "schedule.json").exists()


@pytest.mark.parametrize("reflow", [False, True])
def test_reflow_guard_fixed_anchors_and_repeatability(reflow):
    # The first hole is in published history; the later hole can be opened.
    stock = {("kt", 30, n) for n in range(1, 9)} | {("kt", 31, 1)}
    sources = [kt("before", 30, 1, publish_at="2026-11-19T05:30:00Z"),
               kt("public", 30, 3, privacy="public", uploaded="2026-11-18T00:00:00Z"),
               kt("unlisted", 30, 4, privacy="unlisted", publish_at="2026-11-18T03:15:00Z"),
               kt("near", 30, 5, publish_at=iso(NOW + timedelta(minutes=59))),
               kt("eligible", 30, 7, publish_at=iso(NOW + timedelta(hours=1))),
               kt("later", 30, 8, publish_at="2026-11-18T13:30:00Z")]
    before = deepcopy(sources)
    rows = schedule.plan(sources, NOW, stock, reflow=reflow)
    moved = [row for row in rows if row["status"] == "dời"]
    assert {row["youtube_id"] for row in moved} == ({"eligible", "later"} if reflow else set())
    assert all(not row["publish_at"] for row in rows if row["youtube_id"] in ("before", "public", "unlisted", "near"))
    past_hole = next(row for row in rows if row["key"] == "T30_KT02")
    assert past_hole["status"] == "bỏ qua" and not past_hole["publish_at"]
    if reflow:
        sequence = [row for row in rows if row["publish_at"]]
        assert [row["key"] for row in sequence] == ["T30_KT06", "T30_KT07", "T30_KT08"]
        # The immutable "before" video still occupies 19/11 12:30.
        assert [row["publish_at"] for row in sequence] == ["2026-11-18T05:30:00Z", "2026-11-18T13:30:00Z",
                                                         "2026-11-19T13:30:00Z"]
        assert moved[0]["previous_publish_at"] == iso(NOW + timedelta(hours=1))
        for row in moved:
            next(source for source in sources if source["id"] == row["youtube_id"])["status"]["publishAt"] = row["publish_at"]
        assert not any(row["status"] == "dời" for row in schedule.plan(sources, NOW, stock, reflow=True))
    else:
        assert sources == before
    assert schedule.plan(before, NOW) == schedule.plan(before, NOW, expected=None, reflow=True)


@pytest.mark.parametrize("mode", ["dry-run", "apply", "limit", "only"])
def test_cli_reflow_inventory_filters_and_writable_status(local, monkeypatch, capsys, mode):
    cfg, args = local
    sources = [kt("first", 30, 5, publish_at="2026-11-19T05:30:00Z"),
               kt("last", 31, 1, publish_at="2026-11-19T13:30:00Z"),
               kt("tail", 31, 2, publish_at="2026-11-20T05:30:00Z")]
    fields = dict(selfDeclaredMadeForKids=True, embeddable=False, license="creativeCommon",
                  publicStatsViewable=True, containsSyntheticMedia=True)
    for source in sources:
        source["status"].update(fields, madeForKids=True, failureReason="read-only")
    stock = {("kt", 30, 5), ("kt", 30, 6), ("kt", 30, 7), ("kt", 31, 1), ("kt", 31, 2)}
    calls = []
    def inventory(config, pid):
        calls.append((config.workspace.dir, pid))
        return stock
    monkeypatch.setattr(check, "inventory", inventory)
    flags = [] if mode == "dry-run" else ["--apply"]
    flags += ["--limit", "1"] if mode == "limit" else ["--only", "tail"] if mode == "only" else []
    expected_ids = [] if mode == "dry-run" else ["last"] if mode == "limit" else ["tail"] if mode == "only" else ["last", "tail"]
    wire = Wire(*listing(*sources), dict(items=[]), *(dict(id=ident) for ident in expected_ids))
    assert main(args + ["--playlist", "PLtest", "--reflow", *flags], transport=wire, now=NOW.timestamp) == 0
    assert calls == [(cfg.workspace.dir, "PLtest")]
    output = capsys.readouterr().out
    result = json.loads(output[output.index('{\n  "mode"'):])
    moves = [row for row in result["rows"] if row["status"] in ("dời", "đã dời")]
    assert [row["youtube_id"] for row in moves] == (["last", "tail"] if mode == "dry-run" else expected_ids)
    puts = [json.loads(call[3]) for call in wire.calls if call[0] == "PUT"]
    assert [body["id"] for body in puts] == expected_ids
    targets = {"last": "2026-11-20T13:30:00Z", "tail": "2026-11-21T05:30:00Z"}
    for body in puts:
        assert body["status"] == dict(fields, privacyStatus="private", publishAt=targets[body["id"]])
    path = cfg.workspace.dir / "_publish" / "schedule.json"
    if mode == "dry-run":
        assert "giữ chỗ cho T30_KT06 (thiếu)" in output and "giữ chỗ cho T30_KT07 (thiếu)" in output
        assert "19/11 20:30 → 20/11 20:30" in output and not path.exists()
        assert all(call[0] == "GET" for call in wire.calls)
    else:
        assert [record["youtube_id"] for record in read_json_dict(path)["records"]] == expected_ids
    assert not wire.responses


@pytest.mark.parametrize("audience", [None, False, True])
def test_reflow_quota_stop_retains_history_and_resumes_idempotently(local, oauth, audience):
    cfg, _ = local
    sources = [kt("anchor", 30, 5, publish_at="2026-11-19T05:30:00Z"),
               kt("last", 31, 1, publish_at="2026-11-19T13:30:00Z"),
               kt("tail", 31, 2, publish_at="2026-11-20T05:30:00Z")]
    if audience is not None:
        for source in sources:
            source["status"]["selfDeclaredMadeForKids"] = audience
    stock = {("kt", 30, 5), ("kt", 30, 6), ("kt", 31, 1), ("kt", 31, 2)}
    path = cfg.workspace.dir / "_publish" / "schedule.json"
    old_records = [dict(youtube_id=source["id"], kind="kt", key=schedule.classify(source)["key"],
                        publish_at=source["status"]["publishAt"], set_at="2026-11-17T00:00:00Z") for source in sources]
    atomic_write_json(path, dict(schema_version=1, records=old_records))
    rows = schedule.plan(sources, NOW, stock, reflow=True)
    wire = Wire(dict(id="last"), (403, dict(error=dict(errors=[dict(reason="quotaExceeded")]))))
    with pytest.raises(PublishError, match="quotaExceeded"):
        schedule.apply(cfg, rows, youtube.YouTube(*oauth, transport=wire, now=NOW.timestamp))
    records = read_json_dict(path)["records"]
    assert records[:3] == old_records and [record["youtube_id"] for record in records[3:]] == ["last"]
    sources[1]["status"]["publishAt"] = records[-1]["publish_at"]
    resumed = schedule.plan(sources, NOW, stock, reflow=True)
    assert [row["youtube_id"] for row in resumed if row["status"] == "dời"] == ["tail"]
    tail = next(row for row in rows if row["youtube_id"] == "tail")
    wire2 = Wire(dict(id="tail"))
    schedule.apply(cfg, resumed, youtube.YouTube(*oauth, transport=wire2, now=NOW.timestamp))
    body = json.loads(wire2.calls[0][3])
    assert body["status"].get("selfDeclaredMadeForKids") is audience
    assert body["status"]["publishAt"] == tail["publish_at"]
    sources[2]["status"]["publishAt"] = tail["publish_at"]
    records = read_json_dict(path)["records"]
    assert records[:3] == old_records and [record["youtube_id"] for record in records[3:]] == ["last", "tail"]
    assert not any(row["status"] == "dời" for row in schedule.plan(sources, NOW, stock, reflow=True))
    assert not wire.responses and not wire2.responses
