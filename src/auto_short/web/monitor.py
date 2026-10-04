"""CP8.28 "Theo dõi" tab: VM CPU / RAM / disk / top processes from ``/proc`` (no psutil), a short in-memory history,
Ollama ``/api/ps``, the enhance workers' GPU numbers and a readable label + progress of queue jobs. stdlib only.
Everything that touches the system is injectable (``proc`` directory, ``disk_usage``, clocks, ``opener``) so tests use
a fake ``/proc``. Task: docs/tasks/CP8.28-monitor.md."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path

from ..config import Config
from .. import khaithi
from ..enhance.state import parse_iso
from ..titling import playlist as playlist_mod
from ..titling.logic import match_title
from . import episodes as ep

log = logging.getLogger("auto_short")

HISTORY_SECONDS = 3600.0  # M2: about one hour of samples, in RAM only
SAMPLE_SECONDS = 5.0
TOP_PROCESSES = 10
CMD_MAX = 160
GPU_STALE_SECONDS = 180.0  # M4: numbers older than this are shown as stale
OLLAMA_TIMEOUT = 3.0
OLLAMA_CACHE_SECONDS = 3.0
_STAT_RE = re.compile(r"^(\d+) \((.*)\) (.*)$", re.S)
_CLIP_RE = re.compile(r"render: clip (\S+): ")


# --- /proc readers ---------------------------------------------------------------------------------------------


def _read(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def read_cpu_times(proc: Path) -> tuple[tuple[int, int], list[tuple[int, int]]] | None:
    """``/proc/stat`` -> ``((total, idle) of all cores, [(total, idle) per core])`` in clock ticks, None if unreadable."""
    text = _read(proc / "stat")
    if text is None:
        return None
    total: tuple[int, int] | None = None
    cores: list[tuple[int, int]] = []
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        name, _, rest = line.partition(" ")
        try:
            vals = [int(x) for x in rest.split()]
        except ValueError:
            continue
        if len(vals) < 4:
            continue
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        entry = (sum(vals[:8]), idle)  # user nice system idle iowait irq softirq steal (guest is inside user)
        if name == "cpu":
            total = entry
        else:
            cores.append(entry)
    return (total, cores) if total is not None else None


def read_meminfo(proc: Path) -> dict | None:
    """``/proc/meminfo`` -> ``{total, available, used}`` in bytes."""
    text = _read(proc / "meminfo")
    if text is None:
        return None
    kb: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        try:
            kb[key] = int(rest.split()[0])
        except (ValueError, IndexError):
            continue
    if "MemTotal" not in kb:
        return None
    avail = kb.get("MemAvailable", kb.get("MemFree", 0))
    return {"total": kb["MemTotal"] * 1024, "available": avail * 1024, "used": (kb["MemTotal"] - avail) * 1024}


def read_loadavg(proc: Path) -> list[float] | None:
    text = _read(proc / "loadavg")
    try:
        return [float(x) for x in (text or "").split()[:3]] if text else None
    except ValueError:
        return None


def read_processes(proc: Path) -> dict[int, dict]:
    """Every ``/proc/<pid>``: ``{pid: {ppid, comm, ticks (utime+stime), rss (bytes), cmd}}`` (processes that vanish
    while being read are skipped)."""
    out: dict[int, dict] = {}
    try:
        names = [n for n in os.listdir(proc) if n.isdigit()]
    except OSError:
        return out
    page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    for name in names:
        text = _read(proc / name / "stat")
        m = _STAT_RE.match(text.strip()) if text else None
        if m is None:
            continue
        f = m.group(3).split()
        try:
            ppid, ticks, rss = int(f[1]), int(f[11]) + int(f[12]), int(f[21]) * page
        except (ValueError, IndexError):
            continue
        cmd = (_read(proc / name / "cmdline") or "").replace("\0", " ").strip()
        out[int(name)] = {"ppid": ppid, "comm": m.group(2), "ticks": ticks, "rss": rss,
                          "cmd": (cmd or m.group(2))[:CMD_MAX]}
    return out


def read_children(proc: Path, pid: int, tid: int) -> list[int]:
    text = _read(proc / str(pid) / "task" / str(tid) / "children")
    try:
        return [int(x) for x in (text or "").split()]
    except ValueError:
        return []


# --- sampler ---------------------------------------------------------------------------------------------------


class Sampler:
    """Samples CPU / RAM / load every ``interval`` seconds (background thread, or call :meth:`sample` yourself) and
    keeps ``history_seconds`` of them in RAM. ``lane_tids()`` (lane worker native thread ids) and ``lane_jobs()``
    (lane -> job id / episode id of the running job) let the top-process list say which job a process belongs to."""

    def __init__(self, *, proc: str | Path = "/proc", workdir: str | Path = ".", interval: float = SAMPLE_SECONDS,
                 history_seconds: float = HISTORY_SECONDS, clock: Callable[[], float] = time.time,
                 disk_usage: Callable = shutil.disk_usage, pid: int | None = None,
                 lane_tids: Callable[[], dict[int, str]] | None = None,
                 lane_jobs: Callable[[], dict[str, dict]] | None = None, clk_tck: int | None = None) -> None:
        self.proc, self.workdir, self.interval = Path(proc), Path(workdir), interval
        self.clock, self.disk_usage = clock, disk_usage
        self.pid = pid if pid is not None else os.getpid()
        self.lane_tids, self.lane_jobs = lane_tids, lane_jobs
        self.clk_tck = clk_tck or (os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100)
        self.history: deque[dict] = deque(maxlen=max(1, int(history_seconds / max(interval, 0.001))))
        self._lock = threading.Lock()
        self._prev_cpu = None
        self._prev_procs: dict[int, int] = {}
        self._prev_t: float | None = None
        self._latest: dict | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # lifecycle

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="auto-short-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample()
            except Exception:  # a bad /proc read must never kill the sampler
                log.exception("monitor: sample failed")
            self._stop.wait(self.interval)

    # sampling

    @staticmethod
    def _pct(prev: tuple[int, int], cur: tuple[int, int]) -> float:
        dt, di = cur[0] - prev[0], cur[1] - prev[1]
        return round(max(0.0, min(100.0, 100.0 * (dt - di) / dt)), 1) if dt > 0 else 0.0

    def _lane_of_pids(self, procs: dict[int, dict]) -> dict[int, str]:
        """pid -> lane for the processes that descend from a child of a lane worker thread."""
        roots: dict[int, str] = {}
        for tid, lane in (self.lane_tids() if self.lane_tids else {}).items():
            for child in read_children(self.proc, self.pid, tid):
                roots[child] = lane
        out: dict[int, str] = {}
        for pid in procs:
            cur = pid
            for _ in range(12):
                if cur in roots:
                    out[pid] = roots[cur]
                    break
                nxt = procs.get(cur, {}).get("ppid")
                if nxt is None or nxt in (0, 1, cur):
                    break
                cur = nxt
        return out

    def sample(self) -> dict:
        now = self.clock()
        cpu = read_cpu_times(self.proc)
        procs = read_processes(self.proc)
        mem, load = read_meminfo(self.proc), read_loadavg(self.proc)
        sample: dict = {"t": now, "cpu": None, "cores": [], "ram_pct": None, "load1": load[0] if load else None}
        top: list[dict] = []
        with self._lock:
            if cpu is not None and self._prev_cpu is not None:
                sample["cpu"] = self._pct(self._prev_cpu[0], cpu[0])
                sample["cores"] = [self._pct(a, b) for a, b in zip(self._prev_cpu[1], cpu[1])]
            if mem:
                sample["ram_pct"] = round(100.0 * mem["used"] / mem["total"], 1) if mem["total"] else None
            lanes = self._lane_of_pids(procs) if self.lane_tids else {}
            jobs = self.lane_jobs() if self.lane_jobs else {}
            if self._prev_t is not None and now > self._prev_t:
                dt = now - self._prev_t
                for pid, p in procs.items():
                    before = self._prev_procs.get(pid)
                    if before is None:
                        continue
                    pct = 100.0 * max(0, p["ticks"] - before) / (self.clk_tck * dt)  # 100 = one core
                    if pct <= 0:
                        continue
                    row = {"pid": pid, "comm": p["comm"], "cmd": p["cmd"], "cpu_pct": round(pct, 1),
                           "rss_mb": round(p["rss"] / 2 ** 20, 1), "lane": None, "job": None}
                    lane = lanes.get(pid)
                    if lane is not None:
                        row["lane"], row["job"] = lane, jobs.get(lane)
                    elif pid == self.pid:
                        row["comm"] = "auto-short web"
                        row["lane"], row["job"] = "web", {"jobs": list(jobs.values())}
                    top.append(row)
                top.sort(key=lambda r: -r["cpu_pct"])
                del top[TOP_PROCESSES:]
            self._prev_cpu, self._prev_t = cpu, now
            self._prev_procs = {pid: p["ticks"] for pid, p in procs.items()}
            self.history.append({k: sample[k] for k in ("t", "cpu", "ram_pct", "load1")})
            self._latest = {**sample, "top": top, "load": load, "mem": mem, "ncpu": len(cpu[1]) if cpu else None}
        return self._latest

    def snapshot(self) -> dict:
        """Latest sample + disk of the work dir + history (``[t, cpu%, ram%, load1]`` rows). Samples once when the
        thread has not run yet."""
        with self._lock:
            latest = self._latest
        if latest is None:
            latest = self.sample()
        try:
            total, used, free = tuple(self.disk_usage(self.workdir))[:3]
            disk = {"total": total, "used": used, "free": free, "path": str(self.workdir)}
        except (OSError, ValueError):
            disk = None
        with self._lock:
            hist = [[h["t"], h["cpu"], h["ram_pct"], h["load1"]] for h in self.history]
        return {"cpu_pct": latest["cpu"], "cores": latest["cores"], "ncpu": latest["ncpu"], "load": latest["load"],
                "mem": latest["mem"], "ram_pct": latest["ram_pct"], "disk": disk, "top": latest["top"],
                "history": hist, "interval": self.interval, "sampled_at": latest["t"]}


# --- Ollama ----------------------------------------------------------------------------------------------------


def fetch_ollama_ps(host: str, *, opener: Callable | None = None, timeout: float = OLLAMA_TIMEOUT) -> dict:
    """``GET <host>/api/ps`` (read-only) -> ``{connected, host, models: [{name, size_mb, vram_mb, expires_at}], error}``;
    a dead Ollama gives ``connected: false`` (never raises)."""
    open_ = opener or urllib.request.urlopen
    out: dict = {"connected": False, "host": host, "models": [], "error": None}
    try:
        with open_(urllib.request.Request(host.rstrip("/") + "/api/ps"), timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (OSError, urllib.error.URLError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return out
    out["connected"] = True
    for m in data.get("models", []) if isinstance(data, dict) else []:
        if not isinstance(m, dict):
            continue
        size, vram = m.get("size"), m.get("size_vram")
        out["models"].append({
            "name": str(m.get("name") or m.get("model") or "?")[:100],
            "size_mb": round(size / 2 ** 20) if isinstance(size, (int, float)) else None,
            "vram_mb": round(vram / 2 ** 20) if isinstance(vram, (int, float)) else None,
            "expires_at": re.sub(r"\.\d+", "", m["expires_at"]) if isinstance(m.get("expires_at"), str) else None})
    return out


class OllamaView:
    """Cached (a few seconds) ``/api/ps`` of the Ollama host, so many open tabs do not hammer it."""

    def __init__(self, fetch: Callable[[], dict], clock: Callable[[], float] = time.monotonic,
                 ttl: float = OLLAMA_CACHE_SECONDS) -> None:
        self.fetch, self.clock, self.ttl = fetch, clock, ttl
        self._lock = threading.Lock()
        self._at = -1e9
        self._value: dict = {}

    def get(self) -> dict:
        with self._lock:
            now = self.clock()
            if now - self._at >= self.ttl:
                try:
                    self._value = self.fetch()
                except Exception as exc:  # an injected fetch may raise: still report it
                    self._value = {"connected": False, "host": None, "models": [], "error": str(exc)[:200]}
                self._at = now
            return dict(self._value)


# --- labels / progress / GPU workers ---------------------------------------------------------------------------


LABEL_CACHE_SECONDS = 20.0  # labels / stored bộ kinh are re-read at most this often (the tab refreshes every 4 s)
_label_lock = threading.Lock()
_label_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_playlist_cache: dict[str, tuple[float, dict[str, tuple[str | None, str | None, str | None]]]] = {}


def _load_playlist_index(workspace_dir: str) -> dict[str, tuple[str | None, str | None, str | None]]:
    """``video_id -> (series, episode, entry title)`` over every stored ``_playlists/*.json`` (first playlist wins)."""
    out: dict[str, tuple[str | None, str | None, str | None]] = {}
    root = Path(workspace_dir) / playlist_mod.PLAYLISTS_DIR
    try:
        paths = sorted(root.glob("*.json"))
    except OSError:
        return out
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
            continue
        series = playlist_mod.stored_series(doc)
        for entry in doc["entries"]:
            vid = entry.get("video_id") if isinstance(entry, dict) else None
            if not isinstance(vid, str) or vid in out:
                continue
            number = entry.get("episode")
            if not (isinstance(number, str) and number.strip()):
                idx = entry.get("index")
                number = str(idx) if isinstance(idx, int) and not isinstance(idx, bool) else None
            title = entry.get("title")
            out[vid] = (series, number.strip() if number else None, " ".join(title.split()) if isinstance(title, str) and title.strip() else None)
    return out


def _playlist_info(config: Config, video_id: str) -> tuple[str | None, str | None, str | None]:
    key, now = str(config.workspace.dir), time.monotonic()
    with _label_lock:
        hit = _playlist_cache.get(key)
        if hit is None or now - hit[0] >= LABEL_CACHE_SECONDS:
            hit = _playlist_cache[key] = (now, _load_playlist_index(key))
        return hit[1].get(video_id, (None, None, None))


def _metadata_info(config: Config, video_id: str) -> tuple[str | None, str | None]:
    """(series, episode) from the title in ``<workspace>/<id>/metadata.json`` via ``[titling.header] title_patterns``."""
    try:
        meta = json.loads((Path(config.workspace.dir) / video_id / "metadata.json").read_text(encoding="utf-8"))
        m = match_title(config.titling.header.title_patterns, meta.get("title"))
    except (OSError, ValueError, AttributeError, re.error):
        return None, None
    if m is None:
        return None, None
    groups = m.re.groupindex
    series = " ".join(m.group("series").split()) if "series" in groups and m.group("series") else None
    number = m.group("episode") if "episode" in groups and m.group("episode") else None
    return series, number


def _compute_label(config: Config, base: str) -> dict:
    series = number = None
    kind, plain = "short", base
    try:
        kf = ep.kind_fields(config, base)
        kind = kf["kind"]
        plain = kf["base_episode_id"] or base
        series, number = ep._series(config, base), ep._label(config, base, kf)
    except Exception:
        pass
    if base.endswith(khaithi.SUFFIX):  # a khai thị job that has not been ingested yet has no khaithi.json
        kind, plain = khaithi.KIND, plain if plain != base else base[: -len(khaithi.SUFFIX)]
    if number in (base, plain):  # ``_label`` falls back to the episode id: that is "no number"
        number = None
    title = None
    if not series or not number:
        m_series, m_number = _metadata_info(config, plain)
        series, number = series or m_series, number or m_number
    if not series or not number:
        p_series, p_number, title = _playlist_info(config, plain)
        series, number = series or p_series, number or p_number
    parts = [series or None, f"Tập {number}" if number else None]
    label = " · ".join(p for p in parts if p) or ("" if series or number else title) or plain
    return {"episode_id": base, "series": series, "episode": number, "kind": kind,
            "label": label + (" (khai thị)" if kind == khaithi.KIND else "")}


def episode_label(config: Config, episode_id: str) -> dict:
    """Readable name of an episode: ``{episode_id, series, episode, kind, label}``. Sources in order: ``titles.json``
    (CP8.11), the ``metadata.json`` title through ``title_patterns``, the stored bộ kinh (``_playlists``) and finally
    the video id. Cached for ``LABEL_CACHE_SECONDS`` so the 4 s refresh does not re-read every file."""
    base = episode_id.split("#", 1)[0]
    key, now = (str(config.workspace.dir), base), time.monotonic()
    with _label_lock:
        hit = _label_cache.get(key)
        if hit is not None and now - hit[0] < LABEL_CACHE_SECONDS:
            return dict(hit[1])
    value = _compute_label(config, base)
    with _label_lock:
        if len(_label_cache) > 2000:
            _label_cache.clear()
        _label_cache[key] = (now, value)
    return dict(value)


def render_progress(config: Config, job_logs, episode_id: str) -> dict | None:
    """``{done, total}`` clips of the running render step, from the ``render: clip <id>: ..`` lines of the job log
    (best effort: the log keeps the last 200 lines) and ``clips.json``; None when unknown."""
    seen = {m.group(1) for line in list(job_logs) if (m := _CLIP_RE.search(line))}
    try:
        doc = json.loads((Path(config.workspace.dir) / episode_id.split("#", 1)[0] / "clips.json").read_text())
        total = len(doc.get("clips", []))
    except (OSError, ValueError, AttributeError):
        return None
    return {"done": min(len(seen), total), "total": total} if total else None


def _age(value: object, now: float) -> float | None:
    ts = parse_iso(value)
    return None if ts is None else max(0.0, now - ts)


def gpu_workers(status_workers: list[dict], token_names: list[str], now: float, label: Callable[[str], dict]) -> list[dict]:
    """Worker rows of the monitor from ``EnhanceService.status()["workers"]`` (+ tokens that never connected):
    GPU numbers (None = "chưa có số liệu GPU"), whether they are stale, and the episode being enhanced."""
    rows: dict[str, dict] = {}
    for w in status_workers:
        seen = _age(w.get("last_seen"), now)
        stats_age = _age(w.get("gpu_stats_at"), now)
        eid = w.get("episode_id")
        rows[w["name"]] = {
            "name": w["name"], "label": w.get("label") or w["name"], "gpu": w.get("gpu"), "connected": True,
            "last_seen": w.get("last_seen"), "seen_seconds": seen, "yield": bool(w.get("yield")),
            "episode": label(eid) if eid else None, "progress": w.get("progress"),
            "gpu_stats": w.get("gpu_stats"), "gpu_stats_age": stats_age,
            "gpu_stats_stale": stats_age is not None and stats_age > GPU_STALE_SECONDS}
    for name in token_names:
        rows.setdefault(name, {"name": name, "label": name, "gpu": None, "connected": False, "last_seen": None,
                               "seen_seconds": None, "yield": False, "episode": None, "progress": None,
                               "gpu_stats": None, "gpu_stats_age": None, "gpu_stats_stale": False})
    return sorted(rows.values(), key=lambda r: r["name"])
