"""PUB3 AC1–8: fixed clocks and injected HTTP; no live network or sockets."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unicodedata
from urllib.parse import parse_qs, urlparse

import pytest

from auto_short.config import Config, WorkspaceConfig
from auto_short.publish import PublishError, schedule, youtube
from auto_short.publish.__main__ import main
from auto_short.workspace import atomic_write_json, read_json_dict
from test_publish_thumbs import SECRETS, TOKEN, Wire, listing, no_sockets, oauth  # noqa: F401

NOW = datetime(2026, 11, 18, 10, tzinfo=schedule.VN)
VERTICAL_FILE = "[HD Mobile] Kinh Địa Tạng Bồ Tát Bổn Nguyện - PS. Tịnh Không - Tập 99.mp4"
VERTICAL_TITLE = "HD Mobile Kinh Địa Tạng Bồ Tát Bổn Nguyện   PS  Tịnh Không   Tập 99"


def video(ident="private001", name="T23 S08 Tai họa.mp4", *, title="", privacy="private",
          upload="processed", uploaded="2026-11-17T00:00:00Z", publish_at=None):
    status = dict(privacyStatus=privacy, uploadStatus=upload)
    if publish_at is not None:
        status["publishAt"] = publish_at
    return dict(id=ident, fileDetails=dict(fileName=name), snippet=dict(title=title, publishedAt=uploaded),
                status=status)


@pytest.fixture
def local(tmp_path, oauth):
    cfg = Config(workspace=WorkspaceConfig(tmp_path / "work"))
    config = tmp_path / "config.toml"
    config.write_text(f'[workspace]\ndir = "{cfg.workspace.dir}"\n')
    return cfg, ["schedule", "--config", str(config), "--client", str(oauth[0]), "--token", str(oauth[1])]


@pytest.mark.parametrize("name,title,kind,number,clip", [
    ("  T23 S08 Tai họa.mp4  ", "T99 KT01 Khác", "short", 23, 8),
    ("t031_kt001_Thân và tâm.mp4", "", "kt", 31, 1),
    (None, " T31_KT01_Thân và tâm… ", "kt", 31, 1),
    ("", "t23_s123 Tai họa", "short", 23, 123),
    (VERTICAL_FILE, "", "vertical", 99, 0),
    (None, VERTICAL_TITLE, "vertical", 99, 0),
    ("[hd dỌc] Bộ Kinh - Tập 3.MP4", "", "vertical", 3, 0),
    ("T23 S1234 lỗi.mp4", "", None, None, None),
    ("T31 KT1234 lỗi.mp4", "", None, None, None),
    ("không nhận ra.mp4", "T23 S08 không được dùng", None, None, None),
    (None, "[HD] Bộ Kinh - Tập 3", None, None, None),
])
def test_classification_filename_priority_and_fallback(name, title, kind, number, clip):
    source = video(name=unicodedata.normalize("NFD", name) if name else name,
                   title=unicodedata.normalize("NFD", title))
    actual = schedule.classify(source)
    if kind is None:
        assert actual is None
        row = schedule.plan([source], NOW)[0]
        assert row["status"] == "bỏ qua" and row["reason"] == "không nhận ra loại"
    else:
        assert (actual["kind"], actual["episode"], actual["clip_number"]) == (kind, number, clip)


def test_vertical_filename_and_generated_title_share_key():
    file_key = schedule.classify(video(name=VERTICAL_FILE))["key"]
    title_key = schedule.classify(video(name=None, title=VERTICAL_TITLE))["key"]
    assert file_key == title_key == "kinh địa tạng bồ tát bổn nguyện ps tịnh không:T99"


@pytest.mark.parametrize("privacy,upload,publish_at,reason", [
    ("public", "processed", None, "không phải video riêng tư"),
    ("unlisted", "processed", None, "không phải video riêng tư"),
    ("private", "processed", "2026-11-20T00:00:00Z", "đã có lịch"),
    ("private", "uploaded", None, "chưa xử lý xong"),
    ("private", "failed", None, "chưa xử lý xong"),
    ("private", None, None, "chưa xử lý xong"),
])
def test_only_processed_unscheduled_private_videos_are_candidates(privacy, upload, publish_at, reason):
    sources = [video("excluded", privacy=privacy, upload=upload, publish_at=publish_at),
               video("candidate", "T24 S01 ứng viên.mp4")]
    before = deepcopy(sources)
    rows = {row["youtube_id"]: row for row in schedule.plan(sources, NOW)}
    assert rows["excluded"]["status"] == "bỏ qua" and rows["excluded"]["reason"] == reason
    assert rows["excluded"]["publish_at"] == "" and rows["candidate"]["status"] == "sẵn sàng"
    assert sources == before


@pytest.mark.parametrize("privacy,publish_at", [("public", None), ("unlisted", None),
                                               ("private", "2026-11-20T00:00:00Z")])
@pytest.mark.parametrize("name,title", [("T23 S08 Tai họa.mp4", ""),
                                       ("T31_KT01_Thân và tâm.mp4", ""),
                                       (VERTICAL_FILE, VERTICAL_TITLE)])
def test_existing_public_unlisted_or_scheduled_copy_blocks_candidate(privacy, publish_at, name, title):
    existing = video("existing", name if not title else None, title=title, privacy=privacy, publish_at=publish_at)
    rows = schedule.plan([video("duplicate", name), existing], NOW)
    duplicate = next(row for row in rows if row["youtube_id"] == "duplicate")
    assert duplicate["status"] == "bỏ qua" and duplicate["reason"] == "đã có bản existing"
    assert not any(row["status"] == "sẵn sàng" for row in rows)


def test_duplicate_candidates_keep_earliest_upload_and_kinds_are_independent():
    sources = [video("later", uploaded="2026-11-17T02:00:00Z"),
               video("earlier", uploaded="2026-11-17T01:00:00+01:00"),
               video("kt", "T23 KT08 khác loại.mp4")]
    rows = {row["youtube_id"]: row for row in schedule.plan(sources, NOW)}
    assert rows["later"]["reason"] == "đã có bản earlier"
    assert rows["earlier"]["status"] == rows["kt"]["status"] == "sẵn sàng"


@pytest.mark.parametrize("kind,names,times", [
    ("vertical", [f"[HD Mobile] Bộ A - Tập {i}.mp4" for i in range(1, 6)], ["06:00"]),
    ("kt", [f"T1_KT{i:02d}_Khai thị.mp4" for i in range(1, 6)], ["12:30", "20:30"]),
    ("short", [f"T1 S{i:02d} Short.mp4" for i in range(1, 6)], ["07:00", "11:00", "18:45"]),
])
@pytest.mark.parametrize("has_history", [False, True])
def test_slots_append_after_latest_or_start_tomorrow_across_days(kind, names, times, has_history):
    sources = [video(f"v{i}", name) for i, name in reversed(list(enumerate(names)))]
    if has_history:
        sources += [video("old", names[0].replace("Tập 1", "Tập 90").replace("T1", "T90"),
                          publish_at=f"2026-11-19T{times[0]}:00+07:00"),
                    video("last", names[0].replace("Tập 1", "Tập 91").replace("T1", "T91"),
                          publish_at=f"2026-11-20T{times[-1]}:00+07:00")]
    rows = [row for row in schedule.plan(sources, NOW) if row["status"] == "sẵn sàng"]
    day = datetime(2026, 11, 21 if has_history else 19, tzinfo=schedule.VN)
    expected = [f"{(day + timedelta(days=i // len(times))):%Y-%m-%d} {times[i % len(times)]}" for i in range(5)]
    actual = [datetime.fromisoformat(row["publish_at"].replace("Z", "+00:00"))
              .astimezone(schedule.VN).strftime("%Y-%m-%d %H:%M") for row in rows]
    assert actual == expected
    assert [row["youtube_id"] for row in rows] == [f"v{i}" for i in range(5)]
    assert all(row["kind"] == kind for row in rows)


@pytest.mark.parametrize("hour,minute,expected", [(10, 0, "11:00"), (10, 1, "18:45"), (18, 0, "07:00")])
def test_one_hour_guard_and_strictly_after_anchor(hour, minute, expected):
    moment = NOW.replace(hour=hour, minute=minute)
    sources = [video("history", "T1 S01 a", publish_at="2026-11-18T07:00:00+07:00"), video()]
    row = next(row for row in schedule.plan(sources, moment) if row["status"] == "sẵn sàng")
    day = 19 if hour == 18 else 18
    assert row["publish_at"] == datetime.fromisoformat(f"2026-11-{day}T{expected}:00+07:00") \
        .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_order_by_series_episode_clip_and_independent_kind_anchors():
    sources = [video("b1", "[HD Mobile] B - Tập 1.mp4"), video("a10", "[HD Mobile] A - Tập 10.mp4"),
               video("a2", "[HD Mobile] A - Tập 2.mp4"), video("s10", "T2 S10 a"),
               video("s2", "T2 S02 a"), video("s1", "T1 S99 a"), video("kt", "T1 KT01 a"),
               video("history", "T9 S01 a", publish_at="2026-12-01T18:45:00+07:00")]
    rows = [row for row in schedule.plan(sources, NOW) if row["status"] == "sẵn sàng"]
    assert [row["youtube_id"] for row in rows] == ["a2", "a10", "b1", "kt", "s1", "s2", "s10"]
    assert rows[0]["publish_at"] == "2026-11-18T23:00:00Z"
    assert rows[3]["publish_at"] == "2026-11-19T05:30:00Z"
    assert rows[4]["publish_at"] == "2026-12-02T00:00:00Z"


@pytest.mark.parametrize("filters,ids", [([], ["first", "second", "third"]),
                                        (["--only", " third, second "], ["second", "third"]),
                                        (["--limit", "2"], ["first", "second"]),
                                        (["--only", " third, second ", "--limit", "1"], ["second"])])
@pytest.mark.parametrize("do_apply", [False, True])
def test_cli_filters_after_full_plan_and_dry_run_never_writes(local, capsys, filters, ids, do_apply):
    cfg, args = local
    sources = [video("third", "T1 S03 a"), video("first", "T1 S01 a"), video("second", "T1 S02 a")]
    expected = {row["youtube_id"]: row["publish_at"] for row in schedule.plan(sources, NOW)}
    wire = Wire(*listing(*sources), dict(items=[]), *([dict(id=ident) for ident in ids] if do_apply else []))
    assert main(args + filters + (["--apply"] if do_apply else []), transport=wire, now=NOW.timestamp) == 0
    output = capsys.readouterr().out
    result = json.loads(output[output.index('{\n  "mode"'):])
    assert [row["youtube_id"] for row in result["rows"]] == ids
    assert all(row["publish_at"] == expected[row["youtube_id"]] for row in result["rows"])
    assert "2026-11-19" in output and "Giờ VN dự kiến" in output
    assert "Tổng bản dọc:" in output and "Tổng khai thị:" in output and "Tổng Short:" in output
    puts = [json.loads(call[3]) for call in wire.calls if call[0] == "PUT"]
    if do_apply:
        assert [body["id"] for body in puts] == ids
        assert all(body["status"]["publishAt"] == expected[body["id"]] for body in puts)
        assert [record["youtube_id"] for record in
                read_json_dict(cfg.workspace.dir / "_publish" / "schedule.json")["records"]] == ids
    else:
        assert all(call[0] == "GET" for call in wire.calls)
        assert not (cfg.workspace.dir / "_publish").exists()
    assert not wire.responses


def test_apply_preserves_writable_status_and_journals_each_success(local, capsys, monkeypatch):
    cfg, args = local
    source = video()
    fields = dict(embeddable=False, license="creativeCommon", publicStatsViewable=False,
                  selfDeclaredMadeForKids=False, containsSyntheticMedia=True)
    source["status"].update(fields, madeForKids=True, failureReason="ignored")
    sources = [source, video("next", "T24 S01 tiếp"), video("skipped", "unknown.mp4")]
    wire = Wire(*listing(*sources), dict(items=[]), dict(id=source["id"]), dict(id="next"))
    writes = []
    real_write = schedule.atomic_write_json

    def record_write(path, doc):
        assert len([call for call in wire.calls if call[0] == "PUT"]) == len(writes) + 1
        writes.append(deepcopy(doc))
        real_write(path, doc)

    monkeypatch.setattr(schedule, "atomic_write_json", record_write)
    assert main(args + ["--apply"], transport=wire, now=NOW.timestamp) == 0
    put = next(call for call in wire.calls if call[0] == "PUT")
    assert urlparse(put[1]).path.endswith("/videos") and parse_qs(urlparse(put[1]).query) == {"part": ["status"]}
    assert put[2]["Content-Type"] == "application/json"
    assert json.loads(put[3]) == dict(id=source["id"], status=dict(fields, privacyStatus="private",
                                                               publishAt="2026-11-19T00:00:00Z"))
    journal = read_json_dict(cfg.workspace.dir / "_publish" / "schedule.json")
    assert len(writes) == 2 and [len(doc["records"]) for doc in writes] == [1, 2]
    assert journal == writes[-1] and journal["schema_version"] == 1
    record = journal["records"][0]
    assert record.items() >= dict(youtube_id=source["id"], kind="short", key="T23_S08",
                                 publish_at="2026-11-19T00:00:00Z").items()
    assert record["set_at"].endswith("Z") and not wire.responses
    assert "đã đặt lịch" in capsys.readouterr().out


@pytest.mark.parametrize("status,reason", [(403, "quotaExceeded"), (403, "forbidden"), (401, "unauthorized")])
def test_apply_api_error_stops_and_retains_prior_journal(local, capsys, caplog, status, reason):
    cfg, args = local
    sources = [video(f"v{i}", f"T1 S{i:02d} a") for i in range(1, 4)]
    error = (status, dict(error=dict(errors=[dict(reason=reason)], message=" ".join(SECRETS))))
    wire = Wire(*listing(*sources), dict(items=[]), dict(id="v1"), error,
                *([TOKEN, error] if status == 401 else []))
    assert main(args + ["--apply"], transport=wire, now=NOW.timestamp) == 1
    puts = [call for call in wire.calls if call[0] == "PUT"]
    assert [json.loads(call[3])["id"] for call in puts] == (["v1", "v2", "v2"] if status == 401 else ["v1", "v2"])
    assert [row["youtube_id"] for row in read_json_dict(cfg.workspace.dir / "_publish" / "schedule.json")["records"]] == ["v1"]
    output = capsys.readouterr()
    assert (reason if status == 403 else "chạy lại auth") in output.err
    assert not any(secret in output.out + output.err + caplog.text for secret in SECRETS)
    assert not wire.responses


@pytest.mark.parametrize("detail", [False, True])
def test_force_ssl_scope_and_missing_permission_requires_auth(local, capsys, detail):
    assert "https://www.googleapis.com/auth/youtube.force-ssl" in youtube.SCOPES.split()
    cfg, args = local
    error = dict(details=[dict(reason="ACCESS_TOKEN_SCOPE_INSUFFICIENT")]) if detail else \
        dict(errors=[dict(reason="insufficientPermissions")])
    wire = Wire(*listing(video()), dict(items=[]), (403, dict(error=error)))
    assert main(args + ["--apply"], transport=wire, now=NOW.timestamp) == 1
    assert "token chưa có quyền sửa video; chạy lại auth" in capsys.readouterr().err
    assert not (cfg.workspace.dir / "_publish" / "schedule.json").exists() and not wire.responses


def test_all_videos_search_pagination_missing_id_batches_and_deduplication(oauth):
    known = video("known")
    ids = [f"private{i:03d}" for i in range(103)]
    pages = [dict(items=[dict(id=dict(videoId=i)) for i in ["known", *ids[:50]]], nextPageToken="p2"),
             dict(items=[dict(id=dict(videoId=i)) for i in [ids[0], *ids[50:100]]], nextPageToken="p3"),
             dict(items=[dict(id=dict(videoId=i)) for i in ids[100:]])]
    batches = [dict(items=[video(i) for i in ids[offset:offset + 50]]) for offset in range(0, len(ids), 50)]
    wire = Wire(*listing(known), *pages, *batches)
    actual = youtube.YouTube(*oauth, transport=wire, now=NOW.timestamp).all_videos()
    assert [v["id"] for v in actual] == ["known", *ids]
    queries = [parse_qs(urlparse(call[1]).query) for call in wire.calls[3:]]
    assert queries[0] == dict(part=["id"], forMine=["true"], type=["video"], maxResults=["50"])
    assert [query.get("pageToken") for query in queries[:3]] == [None, ["p2"], ["p3"]]
    assert [len(query["id"][0].split(",")) for query in queries[3:]] == [50, 50, 3]
    assert all(query["part"] == ["fileDetails,snippet,status"] for query in queries[3:]) and not wire.responses


@pytest.mark.parametrize("invalid", ["repeated-page", "invalid-id", "invalid-batch"])
def test_all_videos_rejects_invalid_search_responses(oauth, invalid):
    if invalid == "repeated-page":
        responses = [dict(items=[], nextPageToken="p"), dict(items=[], nextPageToken="p")]
    elif invalid == "invalid-id":
        responses = [dict(items=[dict(id=dict(videoId=None))])]
    else:
        responses = [dict(items=[dict(id=dict(videoId="private"))]), dict(items=None)]
    wire = Wire(*listing()[:2], *responses)
    with pytest.raises(PublishError, match="không hợp lệ"):
        youtube.YouTube(*oauth, transport=wire).all_videos()
    assert not wire.responses


@pytest.mark.parametrize("damage", ["not json", '{"schema_version": 2, "records": []}',
                                  '{"schema_version": 1, "records": [{}]}'])
def test_invalid_schedule_journal_is_not_overwritten(local, oauth, damage):
    cfg, _ = local
    path = cfg.workspace.dir / "_publish" / "schedule.json"
    path.parent.mkdir(parents=True)
    path.write_text(damage)
    wire = Wire()
    with pytest.raises(PublishError, match="nhật ký lịch đăng không hợp lệ"):
        schedule.apply(cfg, schedule.plan([video()], NOW), youtube.YouTube(*oauth, transport=wire))
    assert path.read_text() == damage and not wire.calls


def test_old_scope_read_and_thumbnail_still_work_and_web_cannot_update(oauth):
    token = read_json_dict(oauth[1])
    token["scope"] = "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload"
    atomic_write_json(oauth[1], token)
    wire = Wire(*listing(video()), dict(items=[]))
    client = youtube.YouTube(*oauth, transport=wire)
    assert len(client.videos()) == 1
    client.set_thumbnail("private001", b"jpeg")
    assert wire.calls[-1][0] == "POST" and wire.calls[-1][2]["Content-Type"] == "image/jpeg"
    read_only = youtube.YouTube(*oauth, transport=wire, read_only=True)
    with pytest.raises(PublishError, match="web chỉ được đọc"):
        read_only.update_status("private001", dict(privacyStatus="private"))
    assert len(wire.calls) == 4 and not wire.responses
