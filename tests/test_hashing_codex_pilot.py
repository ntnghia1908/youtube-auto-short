import hashlib
import os

import pytest

from auto_short import hashing


@pytest.mark.parametrize("content", [b"", bytes(range(256)) * 4097])
def test_sha256_file_matches_known_binary_content(tmp_path, content):
    path = tmp_path / "binary.dat"
    path.write_bytes(content)

    assert hashing.sha256_file(path) == hashlib.sha256(content).hexdigest()


def test_fingerprint_fields_and_matching_cache_skip_hash(tmp_path, monkeypatch):
    path = tmp_path / "binary.dat"
    content = b"\x00\xff\x80binary\n"
    path.write_bytes(content)
    monkeypatch.chdir(tmp_path)

    result = hashing.fingerprint(path.relative_to(tmp_path))
    stat = path.stat()
    assert result.path == path.resolve()
    assert result.size == len(content)
    assert result.mtime_ns == stat.st_mtime_ns
    assert result.sha256 == hashlib.sha256(content).hexdigest()

    def unexpected_hash(_path):
        pytest.fail("matching fingerprint must reuse the cached hash")

    monkeypatch.setattr(hashing, "sha256_file", unexpected_hash)
    assert hashing.fingerprint(path, cache=[result]) == result


@pytest.mark.parametrize("change", ["size", "mtime"])
def test_fingerprint_rehashes_when_cache_metadata_changes(tmp_path, monkeypatch, change):
    path = tmp_path / "binary.dat"
    path.write_bytes(b"old")
    cached = hashing.fingerprint(path)
    if change == "size":
        content = b"larger content"
        path.write_bytes(content)
        os.utime(path, ns=(cached.mtime_ns, cached.mtime_ns))
        assert path.stat().st_mtime_ns == cached.mtime_ns
        assert path.stat().st_size != cached.size
    else:
        content = b"new"
        path.write_bytes(content)
        os.utime(path, ns=(cached.mtime_ns, cached.mtime_ns + 2_000_000_000))
        assert path.stat().st_size == cached.size
        assert path.stat().st_mtime_ns != cached.mtime_ns

    calls = []
    real_hash = hashing.sha256_file

    def recording_hash(resolved_path):
        calls.append(resolved_path)
        return real_hash(resolved_path)

    monkeypatch.setattr(hashing, "sha256_file", recording_hash)
    result = hashing.fingerprint(path, cache=[cached])

    assert calls == [path.resolve()]
    assert result.path == path.resolve()
    assert result.size == len(content)
    assert result.mtime_ns == path.stat().st_mtime_ns
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert result.sha256 != cached.sha256


def test_canonical_json_and_config_hash_ignore_nested_key_order():
    config = {"title": "Bài giảng", "analysis": {"threshold": 0.5, "enabled": True}}
    reordered = {"analysis": {"enabled": True, "threshold": 0.5}, "title": "Bài giảng"}
    expected = '{"analysis":{"enabled":true,"threshold":0.5},"title":"Bài giảng"}'

    assert hashing.canonical_json(config) == expected
    assert hashing.canonical_json(reordered) == expected
    assert hashing.config_hash(config) == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert hashing.config_hash(config) == hashing.config_hash(reordered)
    changed = {**config, "analysis": {"threshold": 0.75, "enabled": True}}
    assert hashing.config_hash(changed) != hashing.config_hash(config)
