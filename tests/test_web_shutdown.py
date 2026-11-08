"""Shutdown acceptance tests: fake I/O only; measure real worker/process completion."""
import asyncio
import hashlib
import logging
import signal
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_short.config import StoreConfig
from auto_short.store import cancellation as cancel
from auto_short.store import offload
from auto_short.store.client import StoreClient
from auto_short.web import app as web
from test_post_links import service  # noqa: F401  (fixture)


def test_watchdog_repeats_until_closed_and_server_registers_usr1(cfg, monkeypatch, caplog):
    from auto_short.web import server

    dumps = []
    monkeypatch.setattr(web.faulthandler, "dump_traceback", lambda **kw: dumps.append(kw))
    with caplog.at_level(logging.INFO, logger="auto_short"):
        watchdog = web._ShutdownWatchdog(delay=.02, interval=.02)
        watchdog.start()
        deadline = time.monotonic() + 1
        while len(dumps) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        watchdog.close()
    assert len(dumps) >= 2 and all(d == {"all_threads": True} for d in dumps)
    assert "stack mọi thread" in caplog.text
    count = len(dumps)
    time.sleep(.03)
    assert len(dumps) == count and not watchdog.thread.is_alive()

    registered, exited = [], []
    fake_runner = SimpleNamespace(begin_stop=lambda: exited.append("begin_stop"))
    state = SimpleNamespace(runner=fake_runner, shutdown_watchdog=web._ShutdownWatchdog())
    monkeypatch.setattr(server, "create_app", lambda *a: SimpleNamespace(state=state))
    monkeypatch.setattr(server, "password_from_env", lambda: "pw")
    monkeypatch.setattr(server.faulthandler, "register", lambda *a, **kw: registered.append((a, kw)))
    monkeypatch.setattr(server.faulthandler, "unregister", lambda sig: exited.append(sig))
    monkeypatch.setattr(server.uvicorn.Server, "handle_exit", lambda *a: exited.append("uvicorn"))

    def run(self):
        assert self.config.timeout_graceful_shutdown == 5
        self.handle_exit(signal.SIGTERM, None)
        assert state.shutdown_watchdog.thread.is_alive()

    monkeypatch.setattr(server.uvicorn.Server, "run", run)
    server.serve(cfg, host="127.0.0.1", port=8080)
    if hasattr(signal, "SIGUSR1"):
        assert registered == [((signal.SIGUSR1,), {"all_threads": True})]
        assert signal.SIGUSR1 in exited
    assert exited[:2] == ["begin_stop", "uvicorn"]
    assert not state.shutdown_watchdog.thread.is_alive()


@pytest.mark.parametrize("phase", ["hash", "upload", "fetch", "replace", "head", "index"])
def test_slow_io_stops_real_worker_within_five_seconds(tmp_path, monkeypatch, phase):
    path = tmp_path / "source.mp4"
    data = b"x" * (2 * 1024 * 1024)
    path.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    stop, entered, released = threading.Event(), threading.Event(), threading.Event()
    failures = []

    def wait():
        entered.set()
        assert stop.wait(2)
        return b"x" * 64

    if phase == "hash":
        real_open = Path.open

        class SlowFile:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self, size):
                return wait()

        monkeypatch.setattr(Path, "open", lambda p, *a, **kw: SlowFile() if p == path else real_open(p, *a, **kw))
        work = lambda: offload._sha256_file(path, stop)
    else:
        # Exercise the actual StoreClient methods, upload reader and interrupted fetch publication.
        class Response:
            status = 200
            headers = {"X-Sha256": sha, "Content-Length": str(len(data))}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self, size=-1):
                return wait()

        def open_request(request, timeout):
            if phase in ("head", "index"):
                wait()
            if request.method == "PUT":
                assert request.data.read(1024) == data[:1024]
                wait()
                request.data.read(1024)
            return Response()

        # Scoped requests use a custom opener; no socket or service is opened.
        monkeypatch.setattr(cancel.urllib.request, "build_opener",
                            lambda *a: SimpleNamespace(open=open_request))
        client = StoreClient("http://fake", "token")
        if phase not in ("head", "index"):
            monkeypatch.setattr(client, "head", lambda *a: {"size": len(data), "sha256": sha})
        if phase == "upload":
            # A missing/different vertical permits PUT.
            monkeypatch.setattr(client, "head", lambda *a: {"size": 1, "sha256": "0" * 64})
            work = lambda: client.put("aaaaaaaaaaa", "vertical", "PL1", "source.mp4", path, sha)
        elif phase == "replace":
            monkeypatch.setattr(client, "head", lambda *a: {"size": 1, "sha256": "0" * 64})
            work = lambda: client.replace("aaaaaaaaaaa", "hd", "PL1", "hd.mp4", path, sha,
                                          current_sha256="0" * 64)
        elif phase == "fetch":
            work = lambda: client.fetch("aaaaaaaaaaa", "source", tmp_path / "dest.mp4", sha)
        elif phase == "head":
            work = lambda: client.head("aaaaaaaaaaa", "source")
        else:
            work = client.index

    def run():
        try:
            with cancel.stop_scope(stop):
                work()
        except BaseException as exc:
            failures.append(exc)
        finally:
            released.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert entered.wait(2)
        start = time.monotonic()
        stop.set()
        assert released.wait(5)
        thread.join(timeout=.1)
        elapsed = time.monotonic() - start
        assert elapsed <= 5 and not thread.is_alive()
        assert len(failures) == 1 and isinstance(failures[0], cancel.OffloadStopped)
        assert not (tmp_path / "dest.mp4").exists()
        print(f"{phase}: stop {elapsed:.3f}s")
    finally:
        stop.set()
        thread.join(timeout=1)


@pytest.mark.parametrize("ignore_term", [False, True])
def test_long_subprocess_terminates_then_kills_within_five_seconds(tmp_path, ignore_term):
    stop, finished = threading.Event(), threading.Event()
    ready = tmp_path / "ready"
    errors = []
    code = ("import signal,time,pathlib; "
            + ("signal.signal(signal.SIGTERM, signal.SIG_IGN); " if ignore_term else "")
            + f"pathlib.Path({str(ready)!r}).touch(); time.sleep(120)")

    def run():
        try:
            with cancel.stop_scope(stop):
                cancel.run_process([sys.executable, "-c", code])
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists()
        start = time.monotonic()
        stop.set()
        assert finished.wait(5)
        elapsed = time.monotonic() - start
        assert elapsed <= 5
        assert len(errors) == 1 and isinstance(errors[0], cancel.OffloadStopped)
        print(f"process ignore_term={ignore_term}: stop {elapsed:.3f}s")
    finally:
        stop.set()
        thread.join(timeout=5)


def test_lifespan_waits_for_all_seven_workers_and_logs_steps(cfg, monkeypatch, caplog):
    from auto_short.store import backup, borrow, redownload, shorts
    from auto_short.web.jobs import INTERRUPTED, KIND_RENDER

    config = replace(cfg, store=StoreConfig(enabled=True, backup_source=True, offload=True,
                                           offload_shorts=True, redownload=True, retry_seconds=.01),
                     storage=replace(cfg.storage, auto_archive=True),
                     post=replace(cfg.post, link_sync_hours=1))
    entered, finished = set(), set()
    lock = threading.Lock()

    def slow(name):
        def work(*a, **kw):
            with lock:
                entered.add(name)
            try:
                event = cancel.current_stop()
                assert event is not None and event.wait(3)
                cancel.check_stop()
            finally:
                with lock:
                    finished.add(name)
        return work

    monkeypatch.setattr(web, "episode_sizes", slow("auto_archive"))
    monkeypatch.setattr(web.PostLinks, "sync_all", slow("post_link"))
    monkeypatch.setattr(backup, "backup_order", slow("source_backup"))
    monkeypatch.setattr(offload, "candidates", slow("offload"))
    monkeypatch.setattr(shorts, "candidates", slow("shorts"))
    monkeypatch.setattr(redownload, "pending", slow("redownload"))
    monkeypatch.setattr(web.shutil, "which", lambda _: "/fake/node")
    monkeypatch.setattr(borrow, "released_hd_sha", lambda *a: "0" * 64)
    monkeypatch.setattr(StoreClient, "from_config", lambda cfg: SimpleNamespace(head=slow("store_retry")))
    app = web.create_app(config, "pw", preflight=None, post_preflight=None,
                         disk_usage=lambda _: (100 * 10**9, 0, 100 * 10**9))
    runner = app.state.runner
    job, _ = runner.submit("aaaaaaaaaaa", KIND_RENDER, lambda _: None)
    job.status, job.error = INTERRUPTED, borrow.WAIT_PREFIX
    for obj in (runner, app.state.monitor_sampler):
        monkeypatch.setattr(obj, "start", lambda: None)
        monkeypatch.setattr(obj, "stop", lambda **kw: None)
    monkeypatch.setattr(runner, "restore", lambda: None)

    async def exercise():
        async with app.router.lifespan_context(app):
            deadline = time.monotonic() + 2
            while len(entered) < 7 and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            assert len(entered) == 7, entered
            start = time.monotonic()
        elapsed = time.monotonic() - start
        assert elapsed <= 10
        assert entered == finished
        assert job.status == INTERRUPTED  # retry never submitted a job after the stop request
        print(f"lifespan all workers: {elapsed:.3f}s; finished={sorted(finished)}")

    with caplog.at_level(logging.INFO, logger="auto_short"):
        asyncio.run(exercise())
    for step in ("sampler.stop", "runner.stop", "lifespan", "đặt mọi cờ dừng"):
        assert f"tắt: {step} xong sau" in caplog.text
    assert "quá hạn" not in caplog.text


@pytest.mark.parametrize("operation", ["source", "vertical", "shorts", "redownload"])
def test_interruption_does_not_confirm_release_or_finish_and_can_retry(cfg, monkeypatch, operation):
    from auto_short.store import backup, redownload, shorts
    from auto_short.review import backup as hd_backup
    from auto_short.workspace import read_json_dict
    from test_store_backup import MemoryStore as SourceStore, seed as seed_source, VID as SOURCE_ID
    from test_store_offload import MemoryStore as VerticalStore, seed as seed_vertical, VID as VERTICAL_ID
    from test_store_redownload import MemoryStore as RedownloadStore, download, enough_disk, seed as seed_archived
    from test_store_shorts import MemoryShortStore, NOW, VID as SHORT_ID, prepared_shorts
    from auto_short.theme_render import sources

    config = replace(cfg, store=StoreConfig(enabled=True, backup_source=True, offload=True,
                                           offload_shorts=True, redownload=True))
    stop = threading.Event()
    if operation == "source":
        path = seed_source(config)
        client = SourceStore()
        work = lambda: backup.push_source(config, SOURCE_ID, client=client, stop=stop)
        done = lambda result: result["backed_up"]
    elif operation == "vertical":
        folder, path = seed_vertical(config)
        client = VerticalStore()
        work = lambda: offload.push_vertical(config, VERTICAL_ID, client=client, stop=stop)
        done = lambda result: result["released"]
    elif operation == "shorts":
        # Reuse the established artifact builder, including genuine manifest hashes and publish ticks.
        config = prepared_shorts.__wrapped__(cfg)()
        path = config.render.output_dir / SHORT_ID / "shorts/k01.mp4"
        client = MemoryShortStore()
        work = lambda: shorts.push_video(config, SHORT_ID, client=client, stop=stop, clock=lambda: NOW)
        done = lambda result: result["released"]
    else:
        folder = seed_archived(config, "aaaaaaaaaaa")
        monkeypatch.setattr(sources.probe, "probe", lambda _: dict(duration=3600, height=720))
        client = RedownloadStore()
        path = folder / "archive.json"
        work = lambda: redownload.step(config, "aaaaaaaaaaa", client=client, stop=stop,
                                       downloader=download, disk_usage=enough_disk)
        done = lambda result: result["status"] == "done"

    original_put = client.put

    def interrupted_put(*args, **kwargs):
        original_put(*args, **kwargs)
        stop.set()

    monkeypatch.setattr(client, "put", interrupted_put)
    with pytest.raises(cancel.OffloadStopped):
        work()
    assert path.is_file()
    if operation == "vertical":
        doc = hd_backup.read_backup(folder)
        assert not doc["confirmed"] and not doc["released"]
    elif operation == "shorts":
        assert not (config.render.output_dir / SHORT_ID / "store.json").exists()
    elif operation == "source":
        key = (str(config.workspace.dir.resolve()), config.store.url, SOURCE_ID)
        assert backup._MEMO[key].confirmed is None
    else:
        assert not list(sources.cache_dir(config).glob(".*-redownload-*"))
        assert read_json_dict(folder / "archive.json").get("archived_at")
    stop.clear()
    monkeypatch.setattr(client, "put", original_put)
    assert done(work())


def test_http_watchdog_interrupts_a_blocked_socket_without_shortening_timeout(monkeypatch):
    stop, entered, socket_stopped = threading.Event(), threading.Event(), threading.Event()
    errors = []

    class Socket:
        def shutdown(self, how):
            socket_stopped.set()

    def connect(connection):
        connection.sock = Socket()

    def do_open(handler, connection_type, request, **kw):
        connection = connection_type("fake", timeout=30)
        connection.connect()
        entered.set()
        assert socket_stopped.wait(2)
        raise OSError("interrupted socket read")

    monkeypatch.setattr(cancel.http.client.HTTPConnection, "connect", connect)
    monkeypatch.setattr(cancel.urllib.request.HTTPHandler, "do_open", do_open)

    def worker():
        try:
            with cancel.stop_scope(stop):
                StoreClient("http://fake", "token", timeout=30).head("aaaaaaaaaaa", "source")
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        assert entered.wait(2)
        start = time.monotonic()
        stop.set()
        thread.join(timeout=5)
        elapsed = time.monotonic() - start
        assert not thread.is_alive() and elapsed <= 5
        assert len(errors) == 1 and isinstance(errors[0], cancel.OffloadStopped)
        print(f"blocked socket: stop {elapsed:.3f}s")
    finally:
        stop.set()
        socket_stopped.set()
        thread.join(timeout=1)


def test_idle_runner_and_sampler_stop_within_budget(cfg):
    app = web.create_app(cfg, "pw", preflight=None, post_preflight=None)
    runner, sampler = app.state.runner, app.state.monitor_sampler
    runner.start()
    sampler.start()
    timings = {}
    try:
        for name, stop in (("sampler.stop", sampler.stop), ("runner.stop", lambda: runner.stop(timeout=5))):
            start = time.monotonic()
            stop()
            timings[name] = time.monotonic() - start
            assert timings[name] <= 5
        print(f"idle lifecycle: {timings}")
    finally:
        sampler.stop()
        if runner._threads:
            runner.stop(timeout=1)


def _run_stoppable(work, entered, stop, errors):
    """Run work in a stop scope; return elapsed seconds from stop.set() to worker exit."""
    finished = threading.Event()

    def run():
        try:
            with cancel.stop_scope(stop):
                work()
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert entered.wait(3)
        start = time.monotonic()
        stop.set()
        assert finished.wait(5)
        return time.monotonic() - start
    finally:
        stop.set()
        thread.join(timeout=5)


def test_ffprobe_child_is_stopped_within_five_seconds(tmp_path):
    from auto_short.ingest import probe

    entered, stop, errors = threading.Event(), threading.Event(), []
    marker = tmp_path / "started"
    script = tmp_path / "ffprobe"
    script.write_text(f"#!/bin/sh\ntouch {marker}\nexec sleep 120\n")
    script.chmod(0o755)

    def work():
        threading.Thread(target=lambda: [time.sleep(.01) for _ in iter(marker.exists, True)] and entered.set(),
                         daemon=True).start()
        probe.probe(tmp_path / "x.mp4", str(script))

    elapsed = _run_stoppable(work, entered, stop, errors)
    assert len(errors) == 1 and isinstance(errors[0], cancel.OffloadStopped)
    print(f"ffprobe: stop {elapsed:.3f}s")


def test_source_validator_hash_stops_between_blocks(tmp_path, monkeypatch):
    from auto_short.theme_render import sources

    path = tmp_path / "source.mp4"
    path.write_bytes(b"x")
    entered, stop, errors = threading.Event(), threading.Event(), []
    real_open = Path.open

    class SlowFile:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self, size):
            entered.set()
            time.sleep(.05)
            return b"x" * 1024

    monkeypatch.setattr(Path, "open", lambda p, *a, **kw: SlowFile() if p == path else real_open(p, *a, **kw))
    elapsed = _run_stoppable(lambda: sources._sha256(path), entered, stop, errors)
    assert len(errors) == 1 and isinstance(errors[0], cancel.OffloadStopped)
    print(f"source hash: stop {elapsed:.3f}s")


def test_youtube_transport_and_post_link_sync_stop_without_writing_journal(service, monkeypatch):
    from auto_short.publish import youtube
    from auto_short.workspace import atomic_write_json
    from test_post_links import PID, SHORTS

    entered, stop, errors = threading.Event(), threading.Event(), []

    def blocked(request, timeout):
        entered.set()
        stop.wait(2)
        raise OSError("socket shut down")

    monkeypatch.setattr(cancel.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=blocked))
    elapsed = _run_stoppable(lambda: youtube.urllib_transport("GET", "https://example.invalid/x", {}, None),
                             entered, stop, errors)
    assert len(errors) == 1 and isinstance(errors[0], cancel.OffloadStopped)
    print(f"youtube transport: stop {elapsed:.3f}s")

    svc, ctx, wire = service
    doc = ctx.playlists.load(PID)
    atomic_write_json(ctx.playlists.path(PID), {**doc, "link_playlists": [SHORTS]})
    entered, stop, errors = threading.Event(), threading.Event(), []
    real_call = wire.__call__

    def slow_wire(method, url, headers, body):
        entered.set()
        stop.wait(2)
        return real_call(method, url, headers, body)

    monkeypatch.setattr(type(wire), "__call__", lambda self, *a: slow_wire(*a))
    elapsed = _run_stoppable(svc.sync_all, entered, stop, errors)
    assert len(errors) == 1 and isinstance(errors[0], cancel.OffloadStopped)
    assert not svc.path.exists()
    print(f"post link sync: stop {elapsed:.3f}s")
