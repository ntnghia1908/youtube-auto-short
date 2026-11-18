"""PUB3.1 C1/C2: real atomic cache files with injected YouTube transport."""
from urllib.parse import parse_qs, urlparse

import pytest

from auto_short.publish import PublishError, youtube
from auto_short.workspace import atomic_write_json, read_json_dict
from test_publish_schedule import NOW, video
from test_publish_thumbs import Wire, listing, no_sockets, oauth  # noqa: F401

CHANNEL = "UCcache_channel"
STAMP = "2026-11-17T00:00:00Z"


def uploads(*videos, channel=CHANNEL):
    replies = listing(*videos)
    replies[0]["items"][0]["id"] = channel
    return replies if videos else replies[:2]


def search(*ids, page=None):
    result = dict(items=[dict(id=dict(videoId=ident)) for ident in ids])
    if page:
        result["nextPageToken"] = page
    return result


def saved(cache, ids, *, channel=CHANNEL):
    path = cache / f"{channel}.json"
    atomic_write_json(path, dict(schema_version=1, channel_id=channel, ids=ids,
                                full_scan_at=STAMP, updated_at=STAMP))
    return path


def queries(wire, resource):
    return [parse_qs(urlparse(call[1]).query) for call in wire.calls
            if urlparse(call[1]).path.endswith("/" + resource)]


def test_first_scan_and_repeat_read_private_metadata_in_batches(oauth, tmp_path):
    cache = tmp_path / "videos"
    ids = [f"private{i:03d}" for i in range(103)]
    batches = [dict(items=[video(i) for i in ids[n:n + 50]]) for n in range(0, len(ids), 50)]
    first = Wire(*uploads(video("public", privacy="public")),
                 search("public", *ids[:50], page="p2"), search(*ids[50:], page="p3"), search(), *batches)
    client = youtube.YouTube(*oauth, transport=first, now=NOW.timestamp)
    actual = client.all_videos(cache=cache)
    assert [v["id"] for v in actual] == ["public", *ids]
    assert client.search_calls == 3 and not first.responses
    assert all(query["order"] == ["date"] for query in queries(first, "search"))
    path = cache / f"{CHANNEL}.json"
    doc = read_json_dict(path)
    assert doc == dict(schema_version=1, channel_id=CHANNEL, ids=["public", *ids],
                       full_scan_at="2026-11-18T03:00:00Z", updated_at="2026-11-18T03:00:00Z")
    batches[0]["items"][0]["status"].update(publishAt="2026-11-22T00:00:00Z")
    second = Wire(*uploads(video("public", privacy="unlisted")), *batches, search(ids[0], page="ignored"))
    client.send = second
    client.now = lambda: NOW.timestamp() + 60
    actual = client.all_videos(cache=cache)
    assert client.search_calls == 1 and not second.responses
    assert actual[0]["status"]["privacyStatus"] == "unlisted"
    assert actual[1]["status"]["publishAt"] == "2026-11-22T00:00:00Z"
    assert [len(query["id"][0].split(",")) for query in queries(second, "videos")] == [1, 50, 50, 3]
    assert read_json_dict(path)["full_scan_at"] == doc["full_scan_at"]
    assert read_json_dict(path)["updated_at"] != doc["updated_at"]
    assert all(call[0] == "GET" for call in first.calls + second.calls)


def test_incremental_search_continues_for_new_upload_and_new_private(oauth, tmp_path):
    cache = tmp_path / "videos"
    path = saved(cache, ["old"])
    wire = Wire(*uploads(video("new-upload")), dict(items=[video("old")]),
                search("new-upload", "new-private", page="p2"), search("old", page="p3"),
                dict(items=[video("new-private")]))
    client = youtube.YouTube(*oauth, transport=wire, now=NOW.timestamp)
    result = client.all_videos(cache=cache)
    assert {v["id"] for v in result} == {"old", "new-upload", "new-private"}
    assert client.search_calls == 2 and not wire.responses
    assert set(read_json_dict(path)["ids"]) == {v["id"] for v in result}


def test_deleted_ids_pruned_and_caches_isolated_by_channel(oauth, tmp_path):
    cache = tmp_path / "videos"
    path = saved(cache, ["deleted", "old"])
    other = saved(cache, ["other"], channel="UCother")
    before = other.read_bytes()
    wire = Wire(*uploads(), dict(items=[video("old")]), search("old"))
    client = youtube.YouTube(*oauth, transport=wire, now=NOW.timestamp)
    assert [v["id"] for v in client.all_videos(cache=cache)] == ["old"]
    assert read_json_dict(path)["ids"] == ["old"] and other.read_bytes() == before
    assert client.search_calls == 1 and not wire.responses


@pytest.mark.parametrize("damage", ["not json", '[]', '{"schema_version": 2}',
                                  '{"schema_version": 1, "channel_id": "foreign", "ids": []}',
                                  "bad-ids", "bad-date"])
def test_damaged_cache_forces_full_scan(oauth, tmp_path, damage):
    cache = tmp_path / "videos"
    path = saved(cache, ["old"])
    if damage in ("bad-ids", "bad-date"):
        doc = read_json_dict(path)
        doc["ids" if damage == "bad-ids" else "full_scan_at"] = [None] if damage == "bad-ids" else "invalid"
        atomic_write_json(path, doc)
    else:
        path.write_text(damage)
    wire = Wire(*uploads(), search("old", page="p2"), search("old"), dict(items=[video("old")]))
    client = youtube.YouTube(*oauth, transport=wire, now=NOW.timestamp)
    assert len(client.all_videos(cache=cache)) == 1
    assert client.search_calls == 2 and not wire.responses
    assert read_json_dict(path)["ids"] == ["old"]
    assert read_json_dict(path)["full_scan_at"] != STAMP


def test_refresh_scans_all_pages_despite_known_ids(oauth, tmp_path):
    cache = tmp_path / "videos"
    path = saved(cache, ["old"])
    wire = Wire(*uploads(), dict(items=[video("old")]), search("old", page="p2"),
                search("hidden"), dict(items=[video("hidden")]))
    client = youtube.YouTube(*oauth, transport=wire, now=NOW.timestamp)
    assert [v["id"] for v in client.all_videos(cache=cache, refresh=True)] == ["old", "hidden"]
    assert client.search_calls == 2 and not wire.responses
    assert read_json_dict(path)["full_scan_at"] != STAMP


@pytest.mark.parametrize("stage", ["cached", "search", "new-metadata", "bad-search"])
@pytest.mark.parametrize("has_cache", [False, True])
def test_error_never_replaces_old_or_creates_partial_cache(oauth, tmp_path, stage, has_cache):
    cache = tmp_path / "videos"
    path = saved(cache, ["old"]) if has_cache else cache / f"{CHANNEL}.json"
    before = path.read_bytes() if has_cache else None
    error = (403, dict(error=dict(errors=[dict(reason="quotaExceeded")])))
    replies = uploads()
    if has_cache:
        replies.append(error if stage == "cached" else dict(items=[video("old")]))
    if not has_cache or stage != "cached":
        if stage == "bad-search":
            replies.append(dict(items=[dict(id=dict(videoId=None))]))
        else:
            replies.append(search("new", page="p2"))
            replies.append(error if stage != "new-metadata" else search())
            if stage == "new-metadata":
                replies.append(error)
    wire = Wire(*replies)
    with pytest.raises(PublishError):
        youtube.YouTube(*oauth, transport=wire, now=NOW.timestamp).all_videos(cache=cache)
    assert (path.read_bytes() if path.exists() else None) == before
    assert not wire.responses
