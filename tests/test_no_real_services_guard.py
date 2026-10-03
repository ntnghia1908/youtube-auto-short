"""FIX-test-speed T2: the conftest guard makes a connection to the real Ollama / outside network fail loudly."""

import socket

import pytest


@pytest.mark.parametrize("addr", [("127.0.0.1", 11437), ("127.0.0.1", 11434), ("93.184.216.34", 80)])
def test_connect_to_real_services_is_blocked(addr):
    s = socket.socket()
    try:
        with pytest.raises(AssertionError, match="real service"):
            s.connect(addr)
        with pytest.raises(AssertionError, match="real service"):
            s.connect_ex(addr)
    finally:
        s.close()


def test_loopback_fake_server_still_allowed():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    c = socket.socket()
    try:
        c.connect(srv.getsockname())
    finally:
        c.close()
        srv.close()
