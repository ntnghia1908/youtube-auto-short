"""SCH1 Amendment A: device helpers and refresh, injected transports only."""
import stat
from urllib.parse import parse_qs

import pytest

from auto_short.publish import PublishError, youtube
from auto_short.workspace import atomic_write_json, read_json_dict
from test_publish_thumbs import Clock, DEVICE, SECRETS, TOKEN, Wire, no_sockets, oauth  # noqa: F401


@pytest.mark.parametrize("fallback", [None, "start", "poll"])
def test_device_steps_and_cli_keep_scope_fallback_pending_slow_down_and_private_save(oauth, fallback, capsys):
    client, path = oauth
    invalid = (400, dict(error="invalid_scope", error_description=" ".join(SECRETS)))
    for cli in (False, True):
        clock = Clock()
        replies = [invalid] if fallback == "start" else [DEVICE, invalid] if fallback == "poll" else []
        wire = Wire(*replies, DEVICE, (400, dict(error="authorization_pending")),
                    (400, dict(error="slow_down")), TOKEN)
        if cli:
            youtube.auth(client, path, transport=wire, sleep=clock.sleep, now=clock.now)
        else:
            session = youtube.start_device(client, transport=wire, now=clock.now)
            assert session["user_code"] == DEVICE["user_code"] and session["expires_in"] == DEVICE["expires_in"]
            assert len(wire.calls) == (2 if fallback == "start" else 1)  # start never polls
            youtube.poll_device(session, path, transport=wire, sleep=clock.sleep, now=clock.now)
        saved = read_json_dict(path)
        assert saved["authorized_at"] == clock.time
        assert saved["client_path"] == str(client.resolve())
        assert saved["scope"] == (youtube.FULL_SCOPE if fallback else youtube.SCOPES)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600 and not wire.responses
        assert clock.sleeps == ([2, 2, 2, 7] if fallback == "poll" else [2, 2, 7])
        assert parse_qs(wire.calls[-1][3].decode())["grant_type"] == ["urn:ietf:params:oauth:grant-type:device_code"]
    assert not any(secret in capsys.readouterr().out for secret in SECRETS)


@pytest.mark.parametrize("failure", ["authorization_pending", "slow_down", "access_denied", "expired_token",
                                     "invalid_grant", "network", "malformed"])
def test_device_poll_failure_preserves_token_and_never_echoes_credentials(oauth, failure):
    client, path = oauth
    before = path.read_bytes()
    clock = Clock()
    wire = Wire(dict(DEVICE, expires_in=5), *((400, dict(error=failure, error_description=" ".join(SECRETS)))
                                           for _ in range(2)))
    session = youtube.start_device(client, transport=wire, now=clock.now)

    def send(*args):
        if failure == "network":
            raise OSError(" ".join(SECRETS))
        if failure == "malformed":
            return 200, {}, b"not-json"
        return wire(*args)

    with pytest.raises(PublishError) as caught:
        youtube.poll_device(session, path, transport=send, sleep=clock.sleep, now=clock.now)
    assert path.read_bytes() == before and not any(secret in str(caught.value) for secret in SECRETS)


@pytest.mark.parametrize("damage", [dict(user_code=""), dict(device_code=None), dict(verification_url="http://evil"),
                                    dict(expires_in=0), dict(interval=-1)])
def test_device_start_rejects_invalid_fields(oauth, damage):
    with pytest.raises(PublishError):
        youtube.start_device(oauth[0], transport=Wire(dict(DEVICE, **damage)))


@pytest.mark.parametrize("authorized", [None, 1000])
def test_refresh_preserves_authorized_at_or_unknown_legacy_token(oauth, authorized):
    client, path = oauth
    doc = dict(read_json_dict(path), client_path=str(client), expires_at=0)
    if authorized is not None:
        doc["authorized_at"] = authorized
    atomic_write_json(path, doc)
    api = youtube.YouTube(token_path=path, transport=Wire(dict(access_token="new", expires_in=60)), now=lambda: 5000)
    api._refresh()
    saved = read_json_dict(path)
    assert saved.get("authorized_at") == authorized and saved["client_path"] == str(client)
    assert saved["expires_at"] == 5060 and saved["refresh_token"] == doc["refresh_token"]


def test_token_allowlist_existing_files_default_reserved_and_no_symlinks(tmp_path, monkeypatch):
    folder = tmp_path / "tokens"
    default = tmp_path / "youtube-token.json"
    monkeypatch.setattr(youtube, "default_tokens_dir", lambda: folder)
    monkeypatch.setattr(youtube, "default_token", lambda: default)
    for file in (folder / "channel-a.json", folder / "default.json", folder / "bad.name.json", default):
        atomic_write_json(file, {})
    (folder / "linked.json").symlink_to(default)
    (folder / "directory.json").mkdir()
    assert youtube.token_paths() == {"channel-a": folder / "channel-a.json", "default": default}
    assert youtube.token_stem(default) == "default"
    assert youtube.token_stem(folder / "channel-a.json") == "channel-a"
    assert youtube.token_stem(tmp_path / "outside.json") is None
