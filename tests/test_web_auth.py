import os
import stat

import pytest

from auto_short.web.auth import (PASSWORD_ENV, SECRET_FILE, AuthError, SessionSigner, load_or_create_secret,
                                 password_from_env)


def test_password_from_env():
    assert password_from_env({PASSWORD_ENV: "pw"}) == "pw"
    for env in ({}, {PASSWORD_ENV: ""}):
        with pytest.raises(AuthError, match=PASSWORD_ENV):
            password_from_env(env)


def test_secret_created_once_with_mode_600(tmp_path):
    root = tmp_path / "work"
    key = load_or_create_secret(root)
    path = root / SECRET_FILE
    assert len(key) == 32 and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_or_create_secret(root) == key  # restart keeps the key
    os.chmod(path, 0o644)
    assert load_or_create_secret(root) == key and stat.S_IMODE(path.stat().st_mode) == 0o600


def test_secret_invalid(tmp_path):
    (tmp_path / SECRET_FILE).write_text("abcd\n")
    with pytest.raises(AuthError):
        load_or_create_secret(tmp_path)
    (tmp_path / SECRET_FILE).write_text("not hex\n")
    with pytest.raises(AuthError):
        load_or_create_secret(tmp_path)


def test_token_roundtrip_expiry_and_tampering():
    now = [1_000_000.0]
    signer = SessionSigner(b"s" * 32, "pw", 30, clock=lambda: now[0])
    token = signer.issue()
    assert signer.max_age == 30 * 86400 and signer.verify(token)
    version, expires, sig = token.split(".")
    assert int(expires) == 1_000_000 + 30 * 86400
    assert not signer.verify(f"{version}.{int(expires) + 1}.{sig}")  # extended expiry
    assert not signer.verify(f"{version}.{expires}.{sig[:-1]}{'0' if sig[-1] != '0' else '1'}")
    assert not signer.verify(f"v2.{expires}.{sig}")
    for bad in (None, "", "x", "v1..", "v1.abc.def", f"v1.{expires}.é", "v1.²." + sig, "a" * 500):
        assert not signer.verify(bad)
    now[0] += 30 * 86400
    assert not signer.verify(token)  # expired


def test_password_change_or_new_secret_invalidates_tokens():
    token = SessionSigner(b"s" * 32, "pw", 30).issue()
    assert SessionSigner(b"s" * 32, "pw", 30).verify(token)
    assert not SessionSigner(b"s" * 32, "other", 30).verify(token)
    assert not SessionSigner(b"t" * 32, "pw", 30).verify(token)


def test_check_password():
    signer = SessionSigner(b"s" * 32, "mật khẩu", 1)
    assert signer.check_password("mật khẩu")
    assert not signer.check_password("mat khau") and not signer.check_password("")
