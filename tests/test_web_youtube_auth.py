"""SCH1 O8 HTTP/auth tests; written for ORCHESTRATOR, fake OAuth transport only."""
from threading import Event
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from auto_short.publish import youtube
from auto_short.workspace import atomic_write_json, read_json_dict
from test_post_links import service  # noqa: F401
from test_publish_thumbs import Clock, DEVICE, SECRETS, TOKEN, Wire
from web_helpers import login, make_app


@pytest.fixture
def auth_web(service, monkeypatch, tmp_path):
    _, ctx, _ = service
    credentials = tmp_path / "client.json"
    atomic_write_json(credentials, dict(client_id="id", client_secret=SECRETS[2]))
    for path in youtube.token_paths().values():
        atomic_write_json(path, dict(read_json_dict(path), client_path=str(credentials)))
    clock = Clock()
    state = SimpleNamespace(wire=Wire(DEVICE, TOKEN), clock=clock, gate=Event(), finished=Event(), calls=0,
                            started=False)
    start_device, poll_device = youtube.start_device, youtube.poll_device

    def start(client):
        state.calls += 1
        return start_device(client, transport=state.wire, now=clock.now)

    def poll(session, path):
        state.started = True
        try:
            assert state.gate.wait(5), "test did not release OAuth poller"
            return poll_device(session, path, transport=state.wire, sleep=clock.sleep, now=clock.now)
        finally:
            state.finished.set()

    monkeypatch.setattr(youtube, "start_device", start)
    monkeypatch.setattr(youtube, "poll_device", poll)
    with TestClient(make_app(ctx.config), follow_redirects=False) as client:
        try:
            yield client, state
        finally:
            state.gate.set()
            if state.started:
                assert state.finished.wait(5)


@pytest.mark.parametrize("stem", ["unknown", "..%2Foutside", "%2Ftmp%2Foutside", "linked", "default.json"])
def test_auth_requires_login_rejects_unknown_paths_and_symlink(auth_web, stem):
    client, state = auth_web
    (youtube.default_tokens_dir() / "linked.json").symlink_to(youtube.default_token())
    url = f"/api/youtube-tokens/{stem}/auth"
    for method in (client.get, client.post):
        assert method(url).status_code == 401
    login(client)
    for method in (client.get, client.post):
        assert method(url).status_code == 404
    assert not state.wire.calls


@pytest.mark.parametrize("stem", ["b", "default"])
@pytest.mark.parametrize("outcome", ["success", "access_denied", "network"])
def test_auth_single_waiting_session_then_background_result_and_secret_projection(auth_web, stem, outcome):
    client, state = auth_web
    pending, slow = (400, dict(error="authorization_pending")), (400, dict(error="slow_down"))
    final = TOKEN if outcome == "success" else (400, dict(error="access_denied", error_description=" ".join(SECRETS)))
    wire = Wire(DEVICE, pending, slow, final)

    def transport(*args):
        if outcome == "network" and args[1] == youtube.TOKEN_URL:
            raise OSError(" ".join(SECRETS))
        return wire(*args)

    state.wire = transport
    login(client)
    url = f"/api/youtube-tokens/{stem}/auth"
    assert client.get(url).status_code == 404
    path = youtube.token_paths()[stem]
    binding = read_json_dict(path)["client_path"]
    before = path.read_bytes()
    response = client.post(url)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == dict(status="waiting", message="", verification_url=DEVICE["verification_url"],
                                   user_code=DEVICE["user_code"], expires_in=DEVICE["expires_in"])
    assert client.post(url).json() == response.json() and state.calls == 1
    assert client.get(url).json()["status"] == "waiting"
    state.gate.set()
    assert state.finished.wait(5)
    # finished is set just before the route worker updates its public state.
    for _ in range(100):
        result = client.get(url)
        if result.json()["status"] != "waiting":
            break
    assert result.json()["status"] == ("done" if outcome == "success" else "error")
    assert not any(secret in response.text + result.text for secret in SECRETS)
    assert "client_path" not in result.text and "device_code" not in result.text
    if outcome == "success":
        saved = read_json_dict(path)
        assert saved["client_path"] == binding
        assert saved["authorized_at"] == state.clock.time and saved["refresh_token"] == TOKEN["refresh_token"]
        assert not wire.responses
    else:
        assert path.read_bytes() == before
    # A completed or failed attempt can be replaced, unlike a waiting attempt.
    state.gate.clear()
    state.finished.clear()
    state.wire = Wire(DEVICE, TOKEN)
    assert client.post(url).json()["status"] == "waiting" and state.calls == 2


@pytest.mark.parametrize("broken", ["missing_client", "start_failure"])
def test_auth_start_errors_are_sanitized_without_replacing_token(auth_web, broken):
    client, state = auth_web
    path = youtube.default_token()
    if broken == "missing_client":
        atomic_write_json(path, dict(access_token=SECRETS[0], refresh_token=SECRETS[1]))
    else:
        state.wire = Wire((400, dict(error="access_denied", error_description=" ".join(SECRETS))))
    before = path.read_bytes()
    login(client)
    response = client.post("/api/youtube-tokens/default/auth")
    assert response.status_code == (422 if broken == "missing_client" else 502)
    assert not any(secret in response.text for secret in SECRETS) and path.read_bytes() == before
