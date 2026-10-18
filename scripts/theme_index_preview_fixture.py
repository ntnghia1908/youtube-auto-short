"""TC-WEB1: offline synthetic dataset + isolated launcher for the TC1 theme-index preview.

    python scripts/theme_index_preview_fixture.py seed  <scratch-root>
    AUTO_SHORT_WEB_PASSWORD=... python scripts/theme_index_preview_fixture.py serve <scratch-root> [--port 8081]

``seed`` refuses a non-empty root, writes ``<root>/config.toml`` (workspace / output / queue / secret all under the
root), builds fake episodes (byte sentinels, no playable media) and seeds ``theme_index.json`` through the real TC1
``build_index`` with a deterministic fake client. ``serve`` builds the web app with every service callable replaced by a
refusing stub and binds loopback only. Nothing here contacts a network, an AI model, ffmpeg or yt-dlp.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from auto_short import config as config_mod
from auto_short import hashing, khaithi
from auto_short.compilation import store
from auto_short.config import Config
from auto_short.review import logic
from auto_short.selection.client import ChatResult
from auto_short.theme_index import build_index
from auto_short.workspace import Workspace, atomic_write_json

MARKER = ".theme_index_preview.json"
FAKE_MODEL = "synthetic-fake-model (không phải AI thật)"


class FakeClient:
    """Deterministic fake generation: metadata quoting the first evidence segment exactly."""

    def __init__(self):
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        evidence = json.loads(kwargs["messages"][1]["content"])["evidence"]
        ref = {k: evidence[0][k] for k in ("evidence_id", "text")}
        doc = dict(topic="Tu học (giả lập)", subtopic="Chuyên tâm (giả lập)", synopsis=ref, key_messages=[ref],
                   uncertainty=[])
        return ChatResult(json.dumps(doc, ensure_ascii=False))


def write_config(root: Path, *, port: int = 8081) -> Path:
    root = Path(root).resolve()
    text = (f'[workspace]\ndir = "{(root / "work").as_posix()}"\n'
            f'[render]\noutput_dir = "{(root / "output").as_posix()}"\n'
            f'[selection]\nmodel = "{FAKE_MODEL}"\nollama_host = "http://127.0.0.1:9"\n'
            f'[post]\nimage_dir = "{(root / "post-images").as_posix()}"\n'
            f'corrections_path = "{(root / "post-corrections.json").as_posix()}"\n'
            f'[storage]\nauto_archive = false\n[enhance]\nenabled = false\n'
            f'[web]\nhost = "127.0.0.1"\nport = {port}\nprepare_workers = 1\nrender_workers = 1\n')
    path = root / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def make_episode(cfg: Config, pid: str, base: str, *, duration: float = 350, trims=((100, 110),)) -> dict:
    """One khai thi episode ``<base>.kt`` with clip ``k01`` of ``duration`` seconds, rendered (sentinel bytes)."""
    eid = f"{base}.kt"
    ws = Workspace(Path(cfg.workspace.dir), eid)
    ws.dir.mkdir(parents=True, exist_ok=True)
    src = ws.dir / "source.mp4"
    src.write_bytes(b"landscape-original-" + base.encode())
    sha = hashing.sha256_file(src)
    ws.save_manifest(ws.new_manifest(dict(path="source.mp4", sha256=sha)))
    khaithi.write(ws.dir, khaithi.KhaiThi(base, 5, 7))
    trim_total = sum(b - a for a, b in trims)
    end = duration + trim_total
    segments, cursor = [], 0
    for a, b in trims:
        segments.append([cursor, a])
        cursor = b
    segments.append([cursor, end])
    clips = dict(clips=[dict(id="k01", candidate_id="c1", source_start=0, source_end=end, duration=duration)])
    candidates = dict(candidates=[dict(id="c1", trims=[list(t) for t in trims])], params=dict(max_pause=1))
    t0, t1 = trims[0]
    transcript = dict(media_sha256=sha, segments=[
        dict(id="outside", start=end + 40, end=end + 50, kind="speech", text="OUTSIDE (ngoài final ranges)"),
        dict(id="s1", start=10, end=20, kind="speech", text="Phải chuyên tâm tu học."),
        dict(id="cut", start=t0 + 1, end=t1 - 1, kind="speech", text="REMOVED (đã bị cắt)"),
        dict(id="cross", start=t0 - 1, end=t1 + 1, kind="speech", text="CROSSING (vắt qua ranh giới cắt)")])
    digest = hashing.config_hash(transcript["segments"])
    transcript["transcript_sha256"] = digest
    candidates["transcript_sha256"] = digest
    for name, doc in (("clips.json", clips), ("candidates.json", candidates), ("titles.json", {}),
                      ("transcript.json", transcript)):
        atomic_write_json(ws.dir / name, doc)
    out = Path(cfg.render.output_dir) / eid
    (out / "shorts").mkdir(parents=True, exist_ok=True)
    video = out / "shorts" / "k01.mp4"
    video.write_bytes(b"rendered-sentinel-" + base.encode())
    record = dict(clip_id="k01", candidate_id="c1", status="rendered", file="shorts/k01.mp4",
                  sha256=hashing.sha256_file(video), source_start=0, source_end=end, segments=segments,
                  duration=duration, origin="ai", cut=None)
    atomic_write_json(out / "render_manifest.json", dict(
        episode_id=eid, source_sha256=sha, clips_sha256=hashing.config_hash(clips),
        candidates_sha256=hashing.config_hash(candidates), titles_sha256=hashing.config_hash({}), shorts=[record]))
    return dict(episode_id=eid, base=base, ws=ws, out=out, pid=pid)


def make_playlist(cfg: Config, pid: str, bases: list[str], favorites: list[dict] | dict | None) -> Path:
    atomic_write_json(Path(cfg.workspace.dir) / "_playlists" / f"{pid}.json", dict(
        playlist_id=pid, title=f"Synthetic {pid}", entries=[dict(video_id=b, available=True) for b in bases]))
    folder = store.directory(Path(cfg.render.output_dir), pid)
    if favorites is not None:
        doc = favorites if isinstance(favorites, dict) else dict(schema_version=1, items=favorites)
        atomic_write_json(folder / "favorites.json", doc)
    return folder


def seed_index(cfg: Config, pid: str) -> dict:
    return build_index(cfg, pid, client=FakeClient())


def build_dataset(cfg: Config) -> dict[str, str]:
    """All scenarios; returns ``{playlist_id: description}``."""
    fav = lambda ep: dict(episode_id=ep["episode_id"], clip="k01")  # noqa: E731
    e = make_episode(cfg, "PLeligible", "eligible")
    make_playlist(cfg, "PLeligible", [e["base"]], [fav(e)])
    seed_index(cfg, "PLeligible")
    m = make_episode(cfg, "PLmissingcache", "miss")
    make_playlist(cfg, "PLmissingcache", [m["base"]], [fav(m)])  # eligible, cache never seeded -> ai_error
    ok = make_episode(cfg, "PLmixedcases", "mixok")
    lost = make_episode(cfg, "PLmixedcases", "mixlost")
    (lost["ws"].dir / "source.mp4").unlink()
    short_dur = make_episode(cfg, "PLmixedcases", "mixdur", duration=190)
    rej = make_episode(cfg, "PLmixedcases", "mixrej")
    atomic_write_json(rej["ws"].dir / "review.json",
                      logic.with_rejected(logic.empty_review(rej["episode_id"]), ["k01"], clip_id="k01", candidate_id="c1"))
    plain = make_episode(cfg, "PLmixedcases", "mixplain")
    (plain["ws"].dir / "khaithi.json").unlink()
    kept = dict(episode_id="mixkept.kt", clip="k01", kept=dict(
        path="kept/mixkept.mp4", title="Kept-only", duration=350, episode_number="01", clip_number=1, clip_total=1,
        saved_at="2026-10-18T00:00:00Z"))
    make_playlist(cfg, "PLmixedcases", [x["base"] for x in (ok, lost, short_dur, rej, plain)] + ["mixkept"],
                  [fav(x) for x in (ok, lost, short_dur, rej, plain)] + [kept, dict(episode_id="", clip=3)])
    seed_index(cfg, "PLmixedcases")
    make_playlist(cfg, "PLemptyfavs", [], [])
    make_playlist(cfg, "PLmalformed", [], dict(schema_version=99, items="oops"))
    c = make_episode(cfg, "PLcorruptcache", "corrupt")
    folder = make_playlist(cfg, "PLcorruptcache", [c["base"]], [fav(c)])
    seed_index(cfg, "PLcorruptcache")
    idx = folder / "theme_index.json"
    doc = json.loads(idx.read_text(encoding="utf-8"))
    doc["records"][0]["metadata"]["synopsis"]["text"] = "invented, không có trong evidence"
    atomic_write_json(idx, doc)
    return {"PLeligible": "1 eligible 350 s, cache hit", "PLmissingcache": "eligible, chưa seed cache (ai_error)",
            "PLmixedcases": "eligible + mất nguồn / duration / rejected / không phải khai thị / kept-only / favorite hỏng",
            "PLemptyfavs": "favorites rỗng", "PLmalformed": "favorites.json hỏng (422)",
            "PLcorruptcache": "cache metadata bị sửa (ai_error)"}


def seed(root: Path) -> Config:
    root = Path(root).resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"refusing to seed non-empty root: {root}")
    root.mkdir(parents=True, exist_ok=True)
    cfg = config_mod.load(write_config(root))
    Path(cfg.workspace.dir).mkdir(parents=True, exist_ok=True)
    atomic_write_json(Path(cfg.workspace.dir) / MARKER, dict(synthetic=True, note="TC-WEB1 synthetic preview data"))
    print(json.dumps(build_dataset(cfg), ensure_ascii=False, indent=1))
    return cfg


def _refuse(name: str):
    def refuse(*_a, **_k):
        raise RuntimeError(f"{name} is disabled in the theme-index preview sandbox")
    return refuse


def assert_sandbox(cfg: Config, root: Path) -> None:
    root = Path(root).resolve()
    if not (Path(cfg.workspace.dir) / MARKER).is_file():
        raise SystemExit("not a seeded synthetic preview root (marker missing)")
    if cfg.storage.auto_archive or cfg.enhance.enabled:
        raise SystemExit("auto_archive / enhance must be disabled in the preview sandbox")
    for p in (cfg.workspace.dir, cfg.render.output_dir, cfg.post.image_dir, cfg.post.corrections_path):
        if not Path(p).resolve().is_relative_to(root):
            raise SystemExit(f"config path outside scratch root: {p}")
    if cfg.web.host != "127.0.0.1":
        raise SystemExit("preview must bind loopback")


ALLOWED = (  # (method, path regex): the only requests the sandbox launcher lets reach the app
    ("GET", r"/login"), ("POST", r"/login"), ("POST", r"/logout"),
    ("GET", r"/static/style\.css"), ("GET", r"/static/theme_index\.js"),
    ("GET", r"/playlists/[A-Za-z0-9_-]{10,64}/theme-index"),
    ("GET", r"/api/playlists/[A-Za-z0-9_-]{10,64}/theme-index"))


class Allowlist:
    """ASGI wrapper (launcher only): any other HTTP request is answered 404 before it reaches a handler or the auth
    middleware; the existing auth of the wrapped app is untouched for allowed requests."""

    def __init__(self, app):
        self.app, self.state, self.routes = app, app.state, app.routes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        if scope["type"] == "http" and not any(
                scope["method"] == m and re.fullmatch(rx, scope["path"]) for m, rx in ALLOWED):
            body = b'{"detail":"not available in the theme-index preview sandbox"}'
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            return await send({"type": "http.response.body", "body": body})
        await self.app(scope, receive, send)


def build_app(cfg: Config, password: str, *, restrict: bool = True):
    """Web app whose every external service callable is a refusing stub; ``restrict`` adds the route allowlist."""
    from auto_short.web.app import create_app
    from auto_short.enhance.service import EnhanceService
    app = create_app(
        cfg, password, preflight=None, pipeline=_refuse("pipeline"), render=_refuse("render"),
        playlist_lister=_refuse("playlist_lister"), titler=_refuse("titler"), post_compose=_refuse("post_compose"),
        post_preflight=None, post_search=_refuse("post_search"), keyword_search=_refuse("keyword_search"),
        doc_prepare=_refuse("doc_prepare"), auto_archive_interval=0, enhance_tokens={},
        enhance_service=EnhanceService(cfg), ollama_ps=lambda: {}, monitor_interval=3600.0,
        vertical=_refuse("vertical"), vertical_downloader=_refuse("vertical_downloader"))
    return Allowlist(app) if restrict else app


def serve(root: Path, port: int) -> None:
    import uvicorn
    from auto_short.web.auth import password_from_env
    root = Path(root).resolve()
    cfg = config_mod.load(root / "config.toml")
    assert_sandbox(cfg, root)
    app = build_app(cfg, password_from_env())
    uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", access_log=False)).run()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed").add_argument("root", type=Path)
    s = sub.add_parser("serve")
    s.add_argument("root", type=Path)
    s.add_argument("--port", type=int, default=8081)
    args = ap.parse_args(argv)
    if args.cmd == "seed":
        seed(args.root)
    else:
        serve(args.root, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
