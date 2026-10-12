"""SR1.1: SutraStore (S4): slug, atomic files, recitations, delete guards."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from auto_short.sutra.markup import MarkupError
from auto_short.sutra.store import SLUG_RE, SutraConflict, SutraError, SutraNotFound, SutraStore, slugify

TEXT = "= Kinh Đại Thử\n@ Chính kinh\n# Phẩm một\nDòng a\nDòng b\n\n# Phẩm hai\nDòng c\n"


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 12, 1, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.t += timedelta(seconds=30)
        return self.t


@pytest.fixture
def store(tmp_path):
    return SutraStore(tmp_path / "work" / "_sutras", clock=Clock())


def test_slugify():
    assert slugify("Phật Thuyết A Di Đà Kinh") == "phat-thuyet-a-di-da-kinh"
    assert slugify("Đức  ĐỊA--tạng!!") == "duc-dia-tang"
    assert slugify("!!!") == "kinh"
    assert len(slugify("a" * 100)) == 60 and SLUG_RE.match(slugify("é" * 100))


def test_create_files_and_dedupe(store):
    s1 = store.create(TEXT)
    s2 = store.create(TEXT)
    s3 = store.create(TEXT)
    assert (s1, s2, s3) == ("kinh-dai-thu", "kinh-dai-thu-2", "kinh-dai-thu-3")
    d = store.root / s1
    assert sorted(p.name for p in d.iterdir()) == ["meta.json", "recitations.json", "sutra.txt"]
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["slug"] == s1 and meta["title"] == "Kinh Đại Thử" and meta["schema_version"] == 1
    assert meta["created_at"] == meta["updated_at"] and meta["created_at"].endswith("Z")
    assert json.loads((d / "recitations.json").read_text()) == {"schema_version": 1, "entries": []}
    assert store.text(s1)["sha256"] == meta["sha256"]


def test_create_invalid_leaves_nothing(store):
    with pytest.raises(MarkupError):
        store.create("# no title\nx\n")
    assert store.list() == [] and not any(store.root.iterdir()) if store.root.exists() else True


def test_list_get_sorted_and_skips(store):
    store.create("= Zeta\n# M\nx\n")
    store.create("= Alpha\n# M\nx\n# N\ny\n")
    (store.root / "_hidden").mkdir()
    (store.root / ".tmp").mkdir()
    (store.root / "nometa").mkdir()
    bad = store.root / "broken"
    bad.mkdir()
    (bad / "meta.json").write_text("{}")
    (bad / "sutra.txt").write_text("not valid")
    rows = store.list()
    assert [r["slug"] for r in rows] == ["alpha", "zeta"]
    assert rows[0]["sections"] == 2 and rows[0]["recitations"] == {"total": 0, "last_at": None}
    doc = store.get("alpha")
    assert doc["slug"] == "alpha" and doc["groups"][0]["sections"][0]["id"] == "s1"
    assert doc["recitations"] == {"total": 0, "entries": []}


def test_list_sorts_without_diacritics(store):
    for t in ("Kinh Địa Tạng", "Đại Thế Chí", "Bát Nhã", "Ăn chay", "Zen"):
        store.create(f"= {t}\n# M\nx\n")
    assert [r["title"] for r in store.list()] == ["Ăn chay", "Bát Nhã", "Đại Thế Chí", "Kinh Địa Tạng", "Zen"]


def test_missing_and_bad_slugs(store, tmp_path):
    store.create(TEXT)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "meta.json").write_text("{}")
    (store.root / "link").symlink_to(outside, target_is_directory=True)
    for bad in ("nope", "../outside", "Link", "", "a/b", "link", ".", ".."):
        with pytest.raises(SutraNotFound):
            store.get(bad)
        assert not store.exists(bad)
    with pytest.raises(SutraNotFound):
        store.delete("link")
    assert outside.exists() and (outside / "meta.json").exists()


def test_symlinked_text_file_refused(store, tmp_path):
    slug = store.create(TEXT)
    secret = tmp_path / "secret.txt"
    secret.write_text("= X\n# M\ny\n")
    (store.root / slug / "sutra.txt").unlink()
    (store.root / slug / "sutra.txt").symlink_to(secret)
    with pytest.raises(Exception):
        store.text(slug)


def test_update_sha_check(store):
    slug = store.create(TEXT)
    old = store.text(slug)["sha256"]
    res = store.update(slug, "= Tên Mới\n# Mục\nnội dung\n", old)
    assert res["sha256"] != old and store.text(slug)["text"].startswith("= Tên Mới")
    assert store.list()[0]["title"] == "Tên Mới" and store.list()[0]["slug"] == slug  # slug unchanged
    meta = json.loads((store.root / slug / "meta.json").read_text(encoding="utf-8"))
    assert meta["sha256"] == res["sha256"] and meta["updated_at"] > meta["created_at"]
    with pytest.raises(SutraConflict):
        store.update(slug, TEXT, old)
    with pytest.raises(MarkupError):
        store.update(slug, "bad", res["sha256"])
    assert store.text(slug)["sha256"] == res["sha256"]


def test_recitations_add_undo(store):
    slug = store.create(TEXT)
    with pytest.raises(SutraConflict):
        store.undo_recitation(slug)
    a = store.add_recitation(slug)
    b = store.add_recitation(slug)
    assert a["total"] == 1 and b["total"] == 2 and a["entry"]["at"] < b["entry"]["at"]
    assert store.list()[0]["recitations"] == {"total": 2, "last_at": b["entry"]["at"]}
    assert store.undo_recitation(slug) == {"total": 1}
    doc = store.get(slug)
    assert doc["recitations"] == {"total": 1, "entries": [a["entry"]]}
    assert store.undo_recitation(slug) == {"total": 0}
    with pytest.raises(SutraConflict):
        store.undo_recitation(slug)


def test_recitation_detail_keeps_last_400(store):
    slug = store.create(TEXT)
    for _ in range(405):
        store.add_recitation(slug)
    rec = store.get(slug)["recitations"]
    assert rec["total"] == 405 and len(rec["entries"]) == 400


def test_delete_only_that_sutra(store):
    a = store.create(TEXT)
    b = store.create(TEXT)
    store.delete(a)
    assert not (store.root / a).exists() and (store.root / b).is_dir()
    with pytest.raises(SutraNotFound):
        store.delete(a)


def test_writes_are_atomic_no_temp_left(store, monkeypatch):
    slug = store.create(TEXT)
    store.add_recitation(slug)
    assert not [p for p in (store.root / slug).iterdir() if p.name.endswith(".tmp")]
    import auto_short.sutra.store as mod

    def boom(path, data):
        raise OSError("disk full")
    monkeypatch.setattr(mod, "atomic_write_bytes", boom)
    with pytest.raises(OSError):
        store.create("= Khác\n# M\nx\n")
    assert [p.name for p in store.root.iterdir()] == [slug]  # failed create cleaned up


def test_episode_scans_ignore_sutras_dir(store, tmp_path):
    from auto_short.workspace import iter_manifests
    store.create(TEXT)
    assert list(iter_manifests(tmp_path / "work")) == []


def test_default_clock_and_umask(tmp_path):
    s = SutraStore(tmp_path / "_sutras")
    slug = s.create(TEXT)
    assert s.add_recitation(slug)["entry"]["at"].endswith("Z")
    assert os.access(s.root / slug / "sutra.txt", os.R_OK)


def test_corrupt_recitations_never_overwritten(store):
    slug = store.create(TEXT)
    store.add_recitation(slug)
    rec = store.root / slug / "recitations.json"
    for junk in ("{not json", '{"entries": 5}', '{"entries": [1]}', '[]'):
        rec.write_text(junk, encoding="utf-8")
        with pytest.raises(SutraError):
            store.add_recitation(slug)
        with pytest.raises(SutraError):
            store.undo_recitation(slug)
        assert rec.read_text(encoding="utf-8") == junk  # untouched
        assert store.get(slug)["recitations"]["total"] == 0  # display stays tolerant
        assert store.list()[0]["recitations"]["total"] == 0


def test_new_slug_is_reserved(store):
    assert store.create("= New\n# a\nx\n") == "new-2"
