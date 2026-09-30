"""CP8.15 P5 image library, P5a upload."""

from __future__ import annotations

import pytest

from auto_short.post import images
from image_fixtures import make_jpeg, make_png


def test_sniff_and_validate(tmp_path):
    png = make_png(700, 900)
    ext, w, h = images.validate(png)
    assert (ext, w, h) == (".png", 700, 900)
    jpg = make_jpeg(1000, 600)
    assert images.validate(jpg) == (".jpg", 1000, 600)


def test_validate_rejects_bad_magic_too_small_and_too_large():
    with pytest.raises(images.ImageError):
        images.validate(b"not an image at all")
    with pytest.raises(images.ImageError):
        images.validate(make_png(400, 500))  # short edge 400 < 600
    huge = make_png(700, 900) + b"\x00" * (images.MAX_BYTES + 1)
    with pytest.raises(images.ImageError):
        images.validate(huge)


def test_clean_name_and_unique_name(tmp_path):
    assert images.clean_name("Ảnh HT Tịnh Không (1).JPG", ".jpg") == "Anh-HT-Tinh-Khong-1.jpg"
    (tmp_path / "photo.jpg").write_bytes(b"x")
    assert images.unique_name(tmp_path, "photo.jpg") == "photo-2.jpg"
    (tmp_path / "photo-2.jpg").write_bytes(b"x")
    assert images.unique_name(tmp_path, "photo.jpg") == "photo-3.jpg"


def test_save_image_stores_validates_and_dedups(tmp_path):
    lib = tmp_path / "lib"
    data = make_png(700, 900)
    name, dup = images.save_image(lib, data, original_name="Ảnh 01.png")
    assert dup is False
    assert (lib / name).is_file()
    assert (lib / name).read_bytes() == data

    name2, dup2 = images.save_image(lib, data, original_name="khac-ten.png")
    assert dup2 is True and name2 == name  # same content -> no new file

    other = make_png(800, 1000)
    name3, dup3 = images.save_image(lib, other, original_name="Ảnh 01.png")  # same cleaned name, different content
    assert dup3 is False and name3 != name


def test_save_image_rejects_invalid(tmp_path):
    with pytest.raises(images.ImageError):
        images.save_image(tmp_path / "lib", b"nope", original_name="a.png")


def test_list_images_skips_non_images_and_subdirectories(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    images.save_image(lib, make_png(700, 900), original_name="a.png")
    (lib / "not-an-image.png").write_bytes(b"garbage")
    (lib / "readme.txt").write_text("x")
    (lib / "sub").mkdir()
    listed = images.list_images(lib)
    assert [i.name for i in listed] == ["a.png"]
    assert listed[0].width == 700 and listed[0].height == 900


def test_resolve_rejects_path_traversal_and_unknown_names(tmp_path):
    lib = tmp_path / "lib"
    name, _ = images.save_image(lib, make_png(700, 900), original_name="a.png")
    assert images.resolve(lib, name) == lib / name
    assert images.resolve(lib, "../secret.png") is None
    assert images.resolve(lib, "sub/dir.png") is None
    assert images.resolve(lib, "missing.png") is None
    assert images.resolve(lib, "a.png; rm -rf") is None


def test_delete_image(tmp_path):
    lib = tmp_path / "lib"
    name, _ = images.save_image(lib, make_png(700, 900), original_name="a.png")
    assert images.delete_image(lib, name) is True
    assert not (lib / name).is_file()
    assert images.delete_image(lib, name) is False


def test_least_used_counts_across_workspaces(tmp_path):
    lib, work = tmp_path / "lib", tmp_path / "work"
    n1, _ = images.save_image(lib, make_png(700, 900), original_name="a.png")
    n2, _ = images.save_image(lib, make_jpeg(700, 900), original_name="b.jpg")
    assert images.least_used(lib, work) in (n1, n2)  # empty usage: tie -> alphabetical

    ep1 = work / "ep1"
    ep1.mkdir(parents=True)
    (ep1 / "posts.json").write_text(
        '{"schema_version": 1, "episode_id": "ep1", "posts": [' +
        '{"clip_id": "k01", "candidate_id": "c1", "source_sha256": "' + "a" * 64 + '", "paragraphs": ["x"], ' +
        '"origin": "ai", "image": "' + n1 + '", "link": null, "posted_at": null, ' +
        '"updated_at": "2026-09-29T10:00:00Z"}]}', encoding="utf-8")
    assert images.least_used(lib, work) == n2


def test_least_used_empty_library(tmp_path):
    assert images.least_used(tmp_path / "empty-lib", tmp_path / "work") is None
