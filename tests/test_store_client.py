"""HD2a part B: store client (against the real tools/store/store.py on 127.0.0.1), borrowed HD source of released
videos (vertical job, Short render), "đợi 3090" waiting state and the store-off (HD1) behaviour."""

import csv
import hashlib
import importlib.util
import json
import threading
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from auto_short.config import Config, RenderConfig, StoreConfig, WorkspaceConfig, from_dict  # noqa: E402
from auto_short.enhance import state as st  # noqa: E402
from auto_short.render import full, stage  # noqa: E402
from auto_short.render.stage import RenderError, StoreWait  # noqa: E402
from auto_short.store.borrow import borrow_hd  # noqa: E402
from auto_short.store.client import StoreClient, StoreMismatch, StoreUnavailable  # noqa: E402

from test_hd_backup import HD, HD_SHA, KT, VID, confirm_both, logged, make_ep, wsdir  # noqa: E402

SPEC = importlib.util.spec_from_file_location("hd2_store", Path(__file__).parents[1] / "tools/store/store.py")
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)

TOKEN = "t0k" * 20
BIG = bytes(range(256)) * 4000  # ~1 MB


class FakeStore:
    """The real store server on a free loopback port, serving one series folder."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.root = tmp / "store-root"
        self.folder = tmp / "store-series"
        self.root.mkdir()
        self.folder.mkdir()
        (tmp / "token.txt").write_text(TOKEN, encoding="utf-8")
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps(dict(root="store-root", token_file="token.txt", series={"PL1": "store-series"})))
        self.store = store.Store(store.load_config(cfg))
        self.rows = []
        self.sums = []
        self.server = None

    def add(self, video_id: str, data: bytes, kind="HD"):
        name = f"[{kind}] {video_id}.mp4"
        (self.folder / name).write_bytes(data)
        self.rows.append(dict(tap="001", loai=kind, file=name, video_id=video_id, tieu_de="t"))
        self.sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
        with (self.folder / "index.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=store.COLUMNS, quoting=csv.QUOTE_ALL)
            w.writeheader()
            w.writerows(self.rows)
        (self.folder / "SHA256SUMS.txt").write_text("\n".join(self.sums) + "\n", encoding="utf-8")

    def start(self, port=0):
        self.server = ThreadingHTTPServer(("127.0.0.1", port), store.StoreHandler)
        self.server.store = self.store
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    @property
    def port(self):
        return self.server.server_address[1]

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        port = self.port
        self.server.shutdown()
        self.server.server_close()
        self.server = None
        return port

    def client(self, token=TOKEN):
        return StoreClient(self.url, token, timeout=5)


@pytest.fixture
def fake(tmp_path):
    s = FakeStore(tmp_path)
    s.start()
    yield s
    if s.server is not None:
        s.stop()


@pytest.fixture
def tcfg(tmp_path) -> Config:
    return Config(workspace=WorkspaceConfig(dir=tmp_path / "work"),
                  render=RenderConfig(output_dir=tmp_path / "output", preset="ultrafast", threads=2))


def with_store(cfg: Config, url: str, **kw) -> Config:
    return replace(cfg, store=StoreConfig(enabled=True, url=url, timeout_seconds=5, retry_seconds=5, **kw))


# --- client ---------------------------------------------------------------------------------------------------

def test_client_index_head_fetch(fake, tmp_path):
    fake.add(VID, BIG)
    c = fake.client()
    assert c.available()
    idx = c.index()
    assert [(e["video_id"], e["kind"]) for e in idx] == [(VID, "hd")]
    sha = hashlib.sha256(BIG).hexdigest()
    assert c.head(VID, "hd") == {"size": len(BIG), "sha256": sha}
    dest = tmp_path / "out" / "x.mp4"
    dest.parent.mkdir()
    assert c.fetch(VID, "hd", dest, sha) == dest
    assert dest.read_bytes() == BIG and not dest.with_name("x.mp4.part").exists()


def test_client_resumes_part_with_range(fake, tmp_path):
    fake.add(VID, BIG)
    sha = hashlib.sha256(BIG).hexdigest()
    dest = tmp_path / "x.mp4"
    dest.with_name("x.mp4.part").write_bytes(BIG[:300_000])
    seen = []
    c = fake.client()
    real = c._open
    c._open = lambda path, **kw: (seen.append(kw.get("headers")), real(path, **kw))[1]
    c.fetch(VID, "hd", dest, sha)
    assert dest.read_bytes() == BIG
    assert {"Range": "bytes=300000-"} in seen


def test_client_sha_mismatch_and_missing(fake, tmp_path):
    fake.add(VID, BIG)
    c = fake.client()
    dest = tmp_path / "x.mp4"
    with pytest.raises(StoreMismatch):
        c.fetch(VID, "hd", dest, "0" * 64)  # the store holds another file
    with pytest.raises(StoreMismatch):
        c.fetch("bbbbbbbbbb2", "hd", dest, hashlib.sha256(BIG).hexdigest())  # no such file
    # corrupt part of the right length: the sha check deletes it
    dest.with_name("x.mp4.part").write_bytes(b"\0" * len(BIG))
    with pytest.raises(StoreMismatch):
        c.fetch(VID, "hd", dest, hashlib.sha256(BIG).hexdigest())
    assert not dest.exists() and not dest.with_name("x.mp4.part").exists()


def test_client_bad_token_no_token_and_down(fake, tmp_path):
    fake.add(VID, BIG)
    bad = fake.client("wrong")
    assert not bad.available()
    with pytest.raises(StoreUnavailable) as e:
        bad.index()
    assert "wrong" not in str(e.value)
    assert not StoreClient(fake.url, None).available()
    port = fake.stop()
    assert not StoreClient(f"http://127.0.0.1:{port}", TOKEN, timeout=2).available()


def test_client_token_from_env_only(monkeypatch):
    monkeypatch.setenv("AUTO_SHORT_STORE_TOKEN", " abc \n")
    assert StoreClient.from_config(StoreConfig()).token == "abc"
    monkeypatch.delenv("AUTO_SHORT_STORE_TOKEN")
    assert StoreClient.from_config(StoreConfig()).token is None


def test_config_store_section():
    d = Config().store
    assert d.enabled is False and d.url == "http://127.0.0.1:18090" and d.retry_seconds == 300
    c = from_dict({"store": {"enabled": True, "url": "http://127.0.0.1:1", "retry_seconds": 60}})
    assert c.store.enabled and c.store.retry_seconds == 60


# --- AC2: released episode + store on -> the job uses the fetched file ---------------------------------------------

def release(cfg, eid=VID):
    for name in ("candidates.json", "metadata.json"):
        (wsdir(cfg, eid) / name).write_text("{}", encoding="utf-8")
    c = logged(cfg)
    confirm_both(c, eid)
    assert c.post(f"/api/episodes/{eid}/release", json={}).status_code == 200
    return c


def test_vertical_uses_store_file_and_deletes_it(tcfg, fake, monkeypatch, tmp_path):
    make_ep(tcfg)
    release(tcfg)
    fake.add(VID, HD)
    cfg = with_store(tcfg, fake.url)
    monkeypatch.setenv("AUTO_SHORT_STORE_TOKEN", TOKEN)
    hd = wsdir(tcfg) / "source_hd.mp4"
    assert not hd.exists()
    seen = {}

    def sentinel(path, *a, **kw):
        fp = st.hd_fingerprint(wsdir(tcfg))
        seen.update(exists=hd.read_bytes() == HD, sha=fp.sha256 if fp else None,
                    src=st.effective_source(cfg, VID))
        raise RenderError("sentinel")

    monkeypatch.setattr(full, "read_stage_json", sentinel)
    with pytest.raises(RenderError, match="sentinel"):
        full.run_vertical(VID, cfg)
    assert seen["exists"] and seen["sha"] == HD_SHA
    assert seen["src"].kind == st.SRC_HD and seen["src"].sha256 == HD_SHA  # same sha as before: render keys unchanged
    assert not hd.exists() and not hd.with_name("source_hd.mp4.part").exists()
    assert st.read(wsdir(tcfg))["released"] is True and st.is_released(wsdir(tcfg))


def test_kt_owner_vertical_uses_store(tcfg, fake, monkeypatch):
    make_ep(tcfg, kt=True)
    release(tcfg, KT)
    import shutil
    (wsdir(tcfg, KT) / "titles.json").write_text('{"header": {}}', encoding="utf-8")
    shutil.rmtree(wsdir(tcfg))  # only the khai thị workspace is left (FIX-hd-owner-kt)
    fake.add(VID, HD)
    cfg = with_store(tcfg, fake.url)
    monkeypatch.setenv("AUTO_SHORT_STORE_TOKEN", TOKEN)
    assert st.owner_for(cfg, VID) == KT
    seen = {}

    def sentinel(*a, **kw):
        seen["file"] = (wsdir(tcfg, KT) / "source_hd.mp4").read_bytes()
        raise RenderError("sentinel")

    monkeypatch.setattr(full, "read_stage_json", sentinel)
    with pytest.raises(RenderError, match="sentinel"):
        full.run_vertical(KT, cfg)
    assert seen["file"] == HD and not (wsdir(tcfg, KT) / "source_hd.mp4").exists()


def test_run_render_uses_store_file_same_inputs(tcfg, fake, monkeypatch):
    make_ep(tcfg)
    release(tcfg)
    fake.add(VID, HD)
    cfg = with_store(tcfg, fake.url)
    monkeypatch.setenv("AUTO_SHORT_STORE_TOKEN", TOKEN)
    hd = wsdir(tcfg) / "source_hd.mp4"
    mpath = wsdir(tcfg) / "manifest.json"
    doc = json.loads(mpath.read_text(encoding="utf-8"))
    doc["source"]["path"] = "source.mp4"  # (the helper episode has none; the HD replaces it anyway)
    mpath.write_text(json.dumps(doc), encoding="utf-8")
    manifest_before = (wsdir(tcfg) / "manifest.json").read_bytes()
    seen = {}

    def fake_stage(ws, manifest, name, *, inputs, cfg_hash, force, action):
        seen["inputs"] = inputs
        seen["exists"] = hd.is_file()
        return False

    monkeypatch.setattr(stage, "run_stage", fake_stage)
    stage.run_render(VID, cfg)
    assert seen["exists"]
    media = [i for i in seen["inputs"] if i["path"].endswith("source_hd.mp4")]
    assert media and media[0]["sha256"] == HD_SHA  # the recorded media sha256 = the one the Shorts were rendered from
    assert not hd.exists()
    assert (wsdir(tcfg) / "manifest.json").read_bytes() == manifest_before
    assert st.is_released(wsdir(tcfg))


def test_concurrent_borrowers_share_one_file(tcfg, fake, monkeypatch):
    make_ep(tcfg)
    release(tcfg)
    fake.add(VID, HD)
    cfg = with_store(tcfg, fake.url)
    monkeypatch.setenv("AUTO_SHORT_STORE_TOKEN", TOKEN)
    hd = wsdir(tcfg) / "source_hd.mp4"
    with borrow_hd(cfg, VID):
        with borrow_hd(cfg, VID):
            assert hd.is_file()
        assert hd.is_file()  # the first borrower still needs it
    assert not hd.exists()


# --- AC3: store off the air / file missing / sha differs -> waiting, never the original -----------------------------

def test_store_down_missing_or_other_sha_waits(tcfg, fake, monkeypatch):
    make_ep(tcfg)
    release(tcfg)
    cfg = with_store(tcfg, fake.url)
    monkeypatch.setenv("AUTO_SHORT_STORE_TOKEN", TOKEN)
    with pytest.raises(StoreWait, match="^đợi 3090"):  # the store has no file for the video
        full.run_vertical(VID, cfg)
    fake.add(VID, HD + b"x")  # another file (sha differs)
    with pytest.raises(StoreWait, match="^đợi 3090"):
        stage.run_render(VID, cfg)
    port = fake.stop()
    down = with_store(tcfg, f"http://127.0.0.1:{port}")
    with pytest.raises(StoreWait, match="^đợi 3090"):
        full.run_vertical(VID, down)
    monkeypatch.delenv("AUTO_SHORT_STORE_TOKEN")
    with pytest.raises(StoreWait, match="token"):
        full.run_vertical(VID, cfg)
    assert not (wsdir(tcfg) / "source_hd.mp4").exists()
    assert isinstance(StoreWait("x"), RenderError)


def test_vertical_job_waits_then_reruns_when_store_back(tcfg, fake, monkeypatch, request):
    make_ep(tcfg)
    release(tcfg)
    cfg = with_store(tcfg, fake.url)
    monkeypatch.setenv("AUTO_SHORT_STORE_TOKEN", TOKEN)
    port = fake.stop()
    cfg = with_store(tcfg, f"http://127.0.0.1:{port}")
    c = logged(cfg)
    runner = c.app.state.runner
    runner.start()
    request.addfinalizer(runner.stop)
    # released view with the store on: the vertical button is offered
    h = c.get(f"/api/episodes/{VID}").json()["hd_video"]
    assert h["released"] is True and h["store"] is True and h["vertical"] is not None
    r = c.post(f"/api/episodes/{VID}/vertical")
    assert r.status_code == 202
    assert runner.wait_idle(20)
    job = runner.latest_vertical(VID)
    assert job.status == "interrupted" and job.error.startswith("đợi 3090")  # not "failed"
    assert c.app.state.store_retry_pass() == []  # the store is still down: nothing re-queued
    # the store answers again, with the file
    fake.add(VID, HD)
    fake.start(port)
    seen = {}

    def sentinel(*a, **kw):
        seen["file"] = (wsdir(tcfg) / "source_hd.mp4").read_bytes()
        raise RenderError("sentinel")

    monkeypatch.setattr(full, "read_stage_json", sentinel)
    assert c.app.state.store_retry_pass() == [VID]
    assert runner.wait_idle(20)
    again = runner.latest_vertical(VID)
    assert again is not job and again.status == "failed" and "sentinel" in again.error
    assert seen["file"] == HD and not (wsdir(tcfg) / "source_hd.mp4").exists()


def test_render_job_waits_not_fails(tcfg, fake, monkeypatch, request):
    make_ep(tcfg)
    release(tcfg)
    monkeypatch.setenv("AUTO_SHORT_STORE_TOKEN", TOKEN)
    port = fake.stop()
    cfg = with_store(tcfg, f"http://127.0.0.1:{port}")
    c = logged(cfg)
    runner = c.app.state.runner
    runner.start()
    request.addfinalizer(runner.stop)
    from auto_short.web.jobs import KIND_RENDER, render_target
    runner.submit(VID, KIND_RENDER, render_target(cfg))
    assert runner.wait_idle(20)
    job = runner.latest(VID)
    assert job.status == "interrupted" and job.error.startswith("đợi 3090")


# --- AC4: [store] enabled = false -> HD1 behaviour ----------------------------------------------------------------

def test_store_off_keeps_hd1_refusal(tcfg):
    make_ep(tcfg)
    release(tcfg)
    assert not tcfg.store.enabled
    with pytest.raises(RenderError, match="HD đã chuyển ra máy ngoài") as e:
        full.run_vertical(VID, tcfg)
    assert not isinstance(e.value, StoreWait)
    with pytest.raises(RenderError, match="HD đã chuyển ra máy ngoài"):
        stage.run_render(VID, tcfg)
    c = logged(tcfg)
    assert c.post(f"/api/episodes/{VID}/vertical").status_code == 404
    assert c.app.state.store_retry_pass() == []
    h = c.get(f"/api/episodes/{VID}").json()["hd_video"]
    assert h["released"] is True and "store" not in h and h["vertical"] is None
