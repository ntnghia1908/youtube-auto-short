"""Cooperative cancellation for background store work; no effect outside a stop scope."""
from __future__ import annotations

import hashlib
import http.client
import os
import signal
import subprocess
import time
import socket
import threading
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

_CURRENT = ContextVar("store_stop", default=None)


class OffloadStopped(Exception):
    """Shutdown interrupted private work; never record this as an upload failure."""


def current_stop(stop=None):
    return stop if stop is not None else _CURRENT.get()


def check_stop(stop=None):
    stop = current_stop(stop)
    if stop is not None and stop.is_set():
        raise OffloadStopped()


@contextmanager
def stop_scope(stop):
    token = _CURRENT.set(stop)
    try:
        check_stop()
        yield
    finally:
        _CURRENT.reset(token)


def cancellable(function):
    @wraps(function)
    def run(*args, **kwargs):
        with stop_scope(current_stop(kwargs.get("stop"))):
            return function(*args, **kwargs)
    return run


def sha256_file(path, stop=None):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            check_stop(stop)
            chunk = stream.read(1024 * 1024)
            check_stop(stop)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


@contextmanager
def urlopen(request, timeout, *, handlers=()):
    """Keep normal HTTP timeouts, but shut down an active socket when cancellation arrives.

    The socket is retained even after HTTPConnection hands it to HTTPResponse. A daemon watcher
    belongs to one request and always exits when that response closes.
    """
    stop = current_stop()
    check_stop(stop)
    if stop is None:
        opener = urllib.request.build_opener(*handlers).open if handlers else urllib.request.urlopen
        with opener(request, timeout=timeout) as response:
            yield response
        return
    sockets, done = [], threading.Event()

    def connect_socket(address, timeout=timeout, source_address=None, **kwargs):
        deadline = time.monotonic() + timeout
        while True:
            check_stop(stop)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("connection timed out")
            try:
                sock = socket.create_connection(address, min(.25, remaining), source_address, **kwargs)
            except TimeoutError:
                continue
            sock.settimeout(timeout)
            sockets.append(sock)
            try:
                check_stop(stop)
            except OffloadStopped:
                sock.close()
                raise
            return sock

    class ConnectionMixin:
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = connect_socket

        def connect(self):
            check_stop(stop)
            super().connect()
            sockets.append(self.sock)
            check_stop(stop)

    class HTTP(ConnectionMixin, http.client.HTTPConnection):
        pass

    class HTTPS(ConnectionMixin, http.client.HTTPSConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            context = self._context

            class Context:
                def __getattr__(self, name):
                    return getattr(context, name)

                def wrap_socket(self, *args, **kwargs):
                    sock = context.wrap_socket(*args, **{**kwargs, "do_handshake_on_connect": False})
                    sockets.append(sock)
                    check_stop(stop)
                    sock.do_handshake()
                    check_stop(stop)
                    return sock

            self._context = Context()

    class HTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(HTTP, req)

    class HTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(HTTPS, req, context=self._context)

    def watch():
        while not done.wait(.05):
            if stop.is_set():
                for sock in list(sockets):
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                # Repeat until the request exits, including sockets connected after stop.

    watcher = threading.Thread(target=watch, name="store-http-stop", daemon=True)
    watcher.start()
    try:
        with urllib.request.build_opener(HTTPHandler(), HTTPSHandler(), *handlers).open(
                request, timeout=timeout) as response:
            check_stop(stop)
            yield response
            check_stop(stop)
    except Exception:
        check_stop(stop)
        raise
    finally:
        done.set()
        watcher.join(timeout=.2)


def run_captured(command, **kwargs):
    """subprocess.run(capture_output, text, check=False); inside a stop scope, terminate -> kill after 3 s."""
    stop = current_stop()
    if stop is None:
        return subprocess.run(command, capture_output=True, text=True, check=False, **kwargs)
    check_stop(stop)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=True, **kwargs)
    try:
        while True:
            try:
                out, err = process.communicate(timeout=.05)
                break
            except subprocess.TimeoutExpired:
                check_stop(stop)
        check_stop(stop)
        return subprocess.CompletedProcess(command, process.returncode, out, err)
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=1)


def run_process(command, **kwargs):
    """Own the process group so yt-dlp's ffmpeg/node children cannot survive cancellation."""
    check_stop()
    process = subprocess.Popen(command, start_new_session=True, **kwargs)
    try:
        while process.poll() is None:
            check_stop()
            time.sleep(.05)
        check_stop()
        return process.returncode
    finally:
        if process.poll() is None or (current_stop() is not None and current_stop().is_set()):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=1)
