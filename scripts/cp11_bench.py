#!/usr/bin/env python3
"""CP11 - performance measurements of the Auto Short pipeline (task: docs/tasks/CP11-performance-measure.md).

Measures render (E1), selection (E2), Whisper CPU (E3), analysis (E4), lane concurrency (E5) and cache reuse (E6),
plus which tuning knobs change a config hash. Only stdlib + the auto_short package. Everything is written under
the bench directory (default ~/.cache/auto-short-cp11-bench); the script refuses to run when the bench workspace or
output would point into the main repository. Raw results: <bench>/raw/<experiment>-<UTC time>.json.

Typical run (from the worktree, conda env auto-short):

    PYTHONPATH=src python scripts/cp11_bench.py setup            # copy the measured episodes (read-only source)
    PYTHONPATH=src python scripts/cp11_bench.py e1-capture       # real render of the bench episodes, keeps commands
    PYTHONPATH=src python scripts/cp11_bench.py e1               # threads / parallel / preset / decode-vs-encode
    PYTHONPATH=src python scripts/cp11_bench.py e2               # selection (needs an idle Ollama)
    PYTHONPATH=src python scripts/cp11_bench.py e3               # Whisper CPU on a cut of the audio
    PYTHONPATH=src python scripts/cp11_bench.py e4               # analysis passes
    PYTHONPATH=src python scripts/cp11_bench.py e5               # render concurrent with Whisper / analysis
    PYTHONPATH=src python scripts/cp11_bench.py e6               # cache reuse
    PYTHONPATH=src python scripts/cp11_bench.py hashes           # which knobs change config_hash / render_key

Every subcommand takes ``--quick`` (one short run) and ``--bench-dir``.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import dataclasses
import difflib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_MAIN = Path("/home/ntnghia/youtube-auto-short").resolve()
DEFAULT_BENCH = Path.home() / ".cache" / "auto-short-cp11-bench"
EPISODES = ("4oOZz2CBz3g", "4oOZz2CBz3g.kt", "E4QhRRXFbIM")
SHORT, KT, CAPTION = EPISODES
OLLAMA = "http://127.0.0.1:11437"

# clips used by the sweeps (ids come from clips.json of the bench copy)
SWEEP_CLIPS = {SHORT: ["k01", "k02", "k05"], KT: ["k01"], CAPTION: ["k01", "k04"]}
PARALLEL_CLIPS = {SHORT: ["k01", "k04", "k06", "k07"], KT: ["k01", "k03"]}
SAMPLE = (SHORT, "k02")  # Short kept for every preset


# --- common ---------------------------------------------------------------------------------------------------

def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def bench_paths(bench: Path) -> dict[str, Path]:
    bench = bench.expanduser().resolve()
    if bench == REPO_MAIN or REPO_MAIN in bench.parents:
        sys.exit(f"refusing: bench dir {bench} is inside the main repository")
    p = {"bench": bench, "work": bench / "work", "output": bench / "output", "raw": bench / "raw",
         "samples": bench / "samples", "tmp": bench / "tmp", "cmds": bench / "cmds", "config": bench / "config.toml"}
    for k in ("work", "output", "raw", "samples", "tmp", "cmds"):
        p[k].mkdir(parents=True, exist_ok=True)
    return p


def load_config(p: dict[str, Path]):
    from auto_short import config as cfgmod

    if not p["config"].is_file():
        sys.exit(f"{p['config']} missing: run 'setup' first")
    cfg = cfgmod.load(p["config"])
    for what, path in (("workspace.dir", cfg.workspace.dir), ("render.output_dir", cfg.render.output_dir)):
        r = Path(path).resolve()
        if r == REPO_MAIN or REPO_MAIN in r.parents or p["bench"] not in (r, *r.parents):
            sys.exit(f"refusing: {what} = {r} is not inside the bench dir {p['bench']}")
    return cfg


def save(p: dict[str, Path], name: str, data: dict) -> Path:
    out = p["raw"] / f"{name}-{utc()}.json"
    data = {"experiment": name, "when": utc(), "host_cpus": os.cpu_count(), "loadavg_end": os.getloadavg(), **data}
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"raw results: {out}")
    return out


def mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else float("nan")


def table(rows: list[dict], cols: list[str]) -> None:
    widths = [max(len(c), *(len(fmt(r.get(c))) for r in rows)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    for r in rows:
        print("  ".join(fmt(r.get(c)).ljust(w) for c, w in zip(cols, widths)))


def fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, float) else ("" if v is None else str(v))


CPU_LEDGER: list[float] = []  # user+sys seconds of every child run by timed_proc (used to spot foreign load)


def timed_proc(cmd: list[str]) -> tuple[dict, str]:
    """Run ``cmd``; returns ({wall, user, sys, rc, maxrss_mb}, stderr). CPU time from wait4 (this child only)."""
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
    err = proc.stderr.read()
    proc.stderr.close()
    _, status, ru = os.wait4(proc.pid, 0)
    wall = time.monotonic() - t0
    rc = os.waitstatus_to_exitcode(status)
    proc.returncode = rc
    CPU_LEDGER.append(ru.ru_utime + ru.ru_stime)
    return {"wall": wall, "user": ru.ru_utime, "sys": ru.ru_stime, "rc": rc, "maxrss_mb": ru.ru_maxrss / 1024}, err


def load1() -> float:
    return os.getloadavg()[0]


def sys_busy() -> tuple[float, float]:
    """(busy jiffies, total jiffies) of the whole machine from /proc/stat (idle and iowait count as not busy)."""
    f = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = f[3] + f[4]
    return sum(f) - idle, sum(f)


class CpuWindow:
    """Machine-wide CPU use (cores) between start() and stop(); ``foreign = busy - own`` tells whether something else
    (e.g. the production web on 8080) ran during a measurement."""

    def __enter__(self):
        self.t0, self.s0 = time.monotonic(), sys_busy()
        return self

    def __exit__(self, *exc):
        s1 = sys_busy()
        self.busy_cores = (s1[0] - self.s0[0]) / max(1.0, s1[1] - self.s0[1]) * (os.cpu_count() or 1)
        self.wall = time.monotonic() - self.t0

    def foreign(self, own_cpu_seconds: float) -> float:
        return self.busy_cores - own_cpu_seconds / max(self.wall, 1e-9)


FOREIGN_LIMIT = 2.0  # cores of other work tolerated during a measurement


def wait_quiet(what: str, timeout: float = 4 * 3600) -> bool:
    """Block until the machine is idle (< 1.5 busy cores for 3 samples of 5 s); False after ``timeout`` s."""
    t0, last = time.monotonic(), 0.0
    while True:
        ok = 0
        for _ in range(3):
            with CpuWindow() as w:
                time.sleep(5)
            if w.busy_cores < 1.5:
                ok += 1
            else:
                break
        if ok == 3:
            return True
        if time.monotonic() - t0 > timeout:
            print(f"[{what}] machine not quiet after {timeout:.0f} s", flush=True)
            return False
        if time.monotonic() - last > 300:
            print(f"[{what}] waiting for an idle machine (busy {w.busy_cores:.1f} cores, production job running)",
                  flush=True)
            last = time.monotonic()
        time.sleep(10)


def ffmpeg_ok(res: dict, err: str, what: str) -> None:
    if res["rc"] != 0:
        sys.exit(f"ffmpeg failed ({what}): {err.strip().splitlines()[-1:] }")


# --- setup ----------------------------------------------------------------------------------------------------

def cmd_setup(a) -> None:
    p = bench_paths(a.bench_dir)
    src_work = Path(a.source_work).resolve()
    before = []
    for ep in EPISODES:
        m = src_work / ep / "manifest.json"
        before.append(f"{_sha(m)}  {m}  mtime_ns={m.stat().st_mtime_ns}")
    (p["bench"] / "main_manifests_before.txt").write_text("\n".join(before) + "\n", encoding="utf-8")
    for ep in EPISODES:
        dst = p["work"] / ep
        dst.mkdir(parents=True, exist_ok=True)
        for f in (src_work / ep).iterdir():
            if f.name == "source.mp4":
                if not (dst / f.name).exists():
                    os.link(f, dst / f.name)  # hard link: no extra disk, never modified
            elif f.is_dir():
                shutil.copytree(f, dst / f.name, dirs_exist_ok=True)
            else:
                shutil.copy2(f, dst / f.name)  # a real copy: never a shared inode with the main repository
        man = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
        man["stages"].pop("render", None)  # its artifacts are absolute paths into the main output/
        for stage, entry in man["stages"].items():
            bad = [x for x in entry.get("artifacts", []) if Path(x).is_absolute()]
            if bad:
                sys.exit(f"{ep}: stage {stage} has absolute artifact paths {bad[:1]}; refusing")
        (dst / "manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    p["config"].write_text(
        "# CP11 bench config (generated by cp11_bench.py setup); no secrets.\n"
        f'[workspace]\ndir = "{p["work"]}"\n\n[render]\noutput_dir = "{p["output"]}"\n\n'
        f'[transcript.whisper]\nmodels_dir = "{Path(a.models_dir).resolve()}"\n', encoding="utf-8")
    print("bench ready:", p["bench"])
    print("\n".join(before))


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- E1 render ------------------------------------------------------------------------------------------------

def episode_clips(p: dict, ep: str) -> dict[str, dict]:
    doc = json.loads((p["work"] / ep / "clips.json").read_text(encoding="utf-8"))
    return {c["id"]: c for c in doc["clips"]}


def cmd_e1_capture(a) -> None:
    """Real render (force) of the bench episodes through run_render; every ffmpeg command is kept for E1 replays."""
    from auto_short.render import stage as rstage

    p = bench_paths(a.bench_dir)
    cfg = load_config(p)
    out = {"episodes": {}}
    for ep in a.episodes or (SHORT, KT):
        store: list[dict] = []
        pdir = p["cmds"] / ep / "files"

        def runner(cmd, store=store, ep=ep, pdir=pdir):
            if cmd[0] != "ffmpeg":
                return rstage._run(cmd)
            script = Path(cmd[cmd.index("-filter_complex_script") + 1])
            pdir.mkdir(parents=True, exist_ok=True)
            for f in script.parent.iterdir():
                if f.is_file():
                    text = f.read_bytes()
                    (pdir / f.name).write_bytes(text.replace(str(script.parent).encode(), str(pdir).encode())
                                                if f.suffix == ".filter" else text)
            keep = [str(pdir / script.name) if x == str(script) else x for x in cmd]
            res, err = timed_proc(cmd)
            clip = script.stem
            store.append({"clip_id": clip, "cmd": keep, **res, "size": _size(Path(cmd[-1]))})
            print(f"  {ep} {clip}: {res['wall']:.1f} s wall, cpu {res['user'] + res['sys']:.1f} s", flush=True)
            return subprocess.CompletedProcess(cmd, res["rc"], "", err)

        print(f"render {ep} (force, config as in production)")
        t0, l0 = time.monotonic(), load1()
        result = rstage.run_render(ep, cfg, force=True, run=runner)
        total = time.monotonic() - t0
        (p["cmds"] / ep / "commands.json").write_text(json.dumps(store, indent=1), encoding="utf-8")
        out["episodes"][ep] = {"wall_total": total, "load1_start": l0, "clips": result.clips,
                               "rendered": result.rendered, "encoded": result.encoded, "ffmpeg": store}
        print(f"{ep}: total {total:.1f} s, encoded {result.encoded}/{result.rendered}")
    save(p, "e1-capture", out)


def _size(path: Path) -> int | None:
    return path.stat().st_size if path.is_file() else None


def load_cmds(p: dict, ep: str) -> dict[str, dict]:
    f = p["cmds"] / ep / "commands.json"
    if not f.is_file():
        sys.exit(f"{f} missing: run 'e1-capture' first")
    return {c["clip_id"]: c for c in json.loads(f.read_text(encoding="utf-8"))}


def variant(base: list[str], *, threads=None, preset=None, out: Path | None = None, mode="full") -> list[str]:
    c = list(base)
    if mode == "decode":  # video decode (+ seek) only, no filters, no encode
        i = c.index("-ss")
        return [c[0], "-nostdin", "-hide_banner", "-v", "error", "-y", *c[i:c.index("-i") + 2],
                "-map", "0:v:0", "-f", "null", "-"]
    if mode == "noenc":  # decode + filter graph + audio path, no encode
        return c[:c.index("-c:v")] + ["-f", "null", "-"]
    if threads is not None:
        c[c.index("-threads") + 1] = str(threads)
    if preset is not None:
        c[c.index("-preset") + 1] = preset
    c[-1] = str(out)
    return c


def run_clip(p, base_cmd, tag, **kw) -> dict:
    out = p["tmp"] / f"{tag}.mp4"
    res, err = timed_proc(variant(base_cmd, out=out, **kw))
    ffmpeg_ok(res, err, tag)
    res["size"] = _size(out)
    res["cpu"] = res["user"] + res["sys"]
    if kw.get("mode", "full") == "full" and res["size"] is None:
        sys.exit(f"{tag}: no output")
    return res | {"out": out}


def cmd_e1(a) -> None:
    p = bench_paths(a.bench_dir)
    reps = 1 if a.quick else a.reps
    rows: list[dict] = []
    ssim: list[dict] = []
    for ep in a.episodes:
        cmds = load_cmds(p, ep)
        sweep = [c for c in SWEEP_CLIPS[ep] if c in cmds][:1 if a.quick else None]
        par = [c for c in PARALLEL_CLIPS.get(ep, []) if c in cmds][:2 if a.quick else None]
        exp = set(a.only or ("threads", "preset", "split", "parallel"))
        if "epar" in exp and a.only == ["epar"]:
            continue

        # configs: (experiment, label, kwargs)
        cfgs = []
        if "threads" in exp:
            cfgs += [("threads", f"threads={t}", {"threads": t}) for t in ((0, 8) if a.quick else (0, 8, 16))]
        if "preset" in exp:
            cfgs += [("preset", f"preset={pr}", {"preset": pr}) for pr in
                     (("medium", "fast") if a.quick else ("medium", "fast", "veryfast"))]
        if "split" in exp:
            cfgs += [("split", "decode-only", {"mode": "decode"}), ("split", "decode+filter", {"mode": "noenc"}),
                     ("split", "full(medium)", {})]
        for rep in range(reps):
            for experiment, label, kw in cfgs:
                total_wall = 0.0
                for clip in sweep:
                    tag = f"{ep}_{clip}_{label.replace('=', '')}_r{rep}".replace("+", "_").replace("(", "").replace(")", "")
                    l0 = load1()
                    r = run_clip(p, cmds[clip]["cmd"], tag, **kw)
                    dur = episode_clips(p, ep)[clip]["duration"]
                    keep = experiment == "preset" and (ep, clip) == SAMPLE and rep == 0
                    if keep:
                        dst = p["samples"] / f"cp11_{ep}_{clip}_preset-{kw['preset']}_crf22.mp4"
                        shutil.move(r["out"], dst)
                    else:
                        r["out"].unlink(missing_ok=True)
                    row = {"episode": ep, "experiment": experiment, "config": label, "clip": clip, "rep": rep,
                           "clip_seconds": dur, "wall": r["wall"], "cpu": r["cpu"], "size": r["size"],
                           "maxrss_mb": r["maxrss_mb"], "load1_start": l0}
                    rows.append(row)
                    total_wall += r["wall"]
                    print(f"{ep} {experiment} {label} {clip} rep{rep}: {r['wall']:.1f} s, cpu {r['cpu']:.1f} s, "
                          f"size {r['size']}", flush=True)
            # parallel batches
            if "parallel" in exp and par:
                pcfgs = [(pn, th) for th in (0, 8) for pn in ((1, 2) if a.quick else (1, 2, 3, 4))
                         if not (th == 8 and pn == 1) and pn <= max(len(par), 2)]
                if len(par) < 4 and not a.quick:
                    pcfgs = [(pn, th) for th in (0, 8) for pn in range(1, len(par) + 1) if not (th == 8 and pn == 1)]
                for pn, th in pcfgs:
                    l0, t0 = load1(), time.monotonic()
                    with cf.ThreadPoolExecutor(max_workers=pn) as pool:
                        futs = {c: pool.submit(run_clip, p, cmds[c]["cmd"], f"{ep}_{c}_p{pn}t{th}_r{rep}",
                                               threads=th) for c in par}
                        res = {c: f.result() for c, f in futs.items()}
                    batch = time.monotonic() - t0
                    for r in res.values():
                        r["out"].unlink(missing_ok=True)
                    rows.append({"episode": ep, "experiment": "parallel", "config": f"p={pn},threads={th}",
                                 "clip": "+".join(par), "rep": rep, "clip_seconds": sum(
                                     episode_clips(p, ep)[c]["duration"] for c in par),
                                 "wall": batch, "cpu": sum(r["cpu"] for r in res.values()),
                                 "size": sum(r["size"] for r in res.values()), "load1_start": l0,
                                 "maxrss_mb": sum(r["maxrss_mb"] for r in res.values())})
                    print(f"{ep} parallel p={pn} threads={th} rep{rep}: batch {batch:.1f} s "
                          f"(clips {'+'.join(par)})", flush=True)
    # whole-episode batches: all Shorts of the episode with p ffmpeg processes at a time (threads = default)
    if "epar" in set(a.only or ()):
        for ep in a.episodes:
            cmds = load_cmds(p, ep)
            allc = list(cmds)
            for rep in range(reps):
                for pn in ((2, 4, 7) if len(allc) >= 7 else (2, 3, len(allc))):
                    wait_quiet(f"e1 epar {ep} p={pn}")
                    mark = len(CPU_LEDGER)
                    with CpuWindow() as w:
                        t0 = time.monotonic()
                        with cf.ThreadPoolExecutor(max_workers=pn) as pool:
                            res = list(pool.map(lambda c: run_clip(p, cmds[c]["cmd"], f"{ep}_{c}_ep{pn}_r{rep}",
                                                                   threads=0), allc))
                        batch = time.monotonic() - t0
                    for r in res:
                        r["out"].unlink(missing_ok=True)
                    cpu = sum(CPU_LEDGER[mark:])
                    rows.append({"episode": ep, "experiment": "episode-parallel", "config": f"all {len(allc)} clips, p={pn}",
                                 "clip": "+".join(allc), "rep": rep,
                                 "clip_seconds": sum(episode_clips(p, ep)[c]["duration"] for c in allc),
                                 "wall": batch, "cpu": cpu, "size": sum(r["size"] for r in res),
                                 "maxrss_mb": sum(r["maxrss_mb"] for r in res), "load1_start": None,
                                 "foreign_cores": round(w.foreign(cpu), 2)})
                    print(f"{ep} episode-parallel p={pn} rep{rep}: batch {batch:.1f} s, foreign "
                          f"{w.foreign(cpu):.1f} cores", flush=True)
    # SSIM / PSNR of the fast / veryfast samples against medium
    base = p["samples"] / f"cp11_{SAMPLE[0]}_{SAMPLE[1]}_preset-medium_crf22.mp4"
    if base.is_file():
        for pr in ("fast", "veryfast"):
            other = p["samples"] / f"cp11_{SAMPLE[0]}_{SAMPLE[1]}_preset-{pr}_crf22.mp4"
            if other.is_file():
                ssim.append({"preset": pr, **quality(other, base)})
    # summary
    summ = []
    keyf = lambda r: (r["episode"], r["experiment"], r["config"])
    for k in sorted({keyf(r) for r in rows}):
        rs = [r for r in rows if keyf(r) == k]
        by_rep = {}
        for r in rs:
            by_rep.setdefault(r["rep"], []).append(r)
        # per rep: wall summed over the clips run one after another (or the batch wall for parallel)
        walls = [sum(x["wall"] for x in v) for v in by_rep.values()]
        cpus = [sum(x["cpu"] for x in v) for v in by_rep.values()]
        secs = sum(x["clip_seconds"] for x in next(iter(by_rep.values())))
        sizes = [sum(x["size"] or 0 for x in v) for v in by_rep.values()]
        summ.append({"episode": k[0], "experiment": k[1], "config": k[2], "reps": len(walls),
                     "wall_s(sum clips)": mean(walls), "wall_each_rep": [round(w, 1) for w in walls],
                     "cpu_s": mean(cpus), "cpu_cores": mean(cpus) / mean(walls),
                     "x_realtime": secs / mean(walls), "size_MB": mean(sizes) / 1e6})
    print()
    table(summ, ["episode", "experiment", "config", "reps", "wall_s(sum clips)", "wall_each_rep", "cpu_s",
                 "cpu_cores", "x_realtime", "size_MB"])
    for s in ssim:
        print("quality vs medium:", s)
    save(p, "e1", {"reps": reps, "rows": rows, "summary": summ, "quality_vs_medium": ssim,
                   "note": "wall_s = sum over the clips of a rep run one after another; for 'parallel' the batch wall"})


def quality(a: Path, ref: Path) -> dict:
    res, err = timed_proc(["ffmpeg", "-hide_banner", "-nostdin", "-v", "info", "-i", str(a), "-i", str(ref),
                           "-lavfi", "[0:v][1:v]ssim;[0:v][1:v]psnr", "-f", "null", "-"])
    s = re.search(r"SSIM.*All:([\d.]+)", err)
    q = re.search(r"PSNR.*average:([\d.]+)", err)
    return {"file": a.name, "size": a.stat().st_size, "ssim_all": float(s.group(1)) if s else None,
            "psnr_avg": float(q.group(1)) if q else None}


# --- E2 selection ---------------------------------------------------------------------------------------------

def ollama_get(path: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(OLLAMA + path, timeout=timeout) as r:
        return json.loads(r.read())


def production_running() -> list[str]:
    """Stages the production web (8080) currently marks running in the main work/ (read-only)."""
    running = []
    for m in sorted((REPO_MAIN / "work").glob("*/manifest.json")):
        try:
            stages = json.loads(m.read_text(encoding="utf-8"))["stages"]
        except (OSError, ValueError, KeyError):
            continue
        running += [f"{m.parent.name}:{n}" for n, e in stages.items() if e.get("status") == "running"]
    return running


def wait_ollama_idle(force: bool, timeout: float = 4 * 3600) -> dict:
    """D5: wait until production has no running stage and Ollama's loaded-model ``expires_at`` did not move for
    90 s (a finished request refreshes it); the queue may also hold stages that have not started, so this is
    re-checked before every variant (``production_running`` only)."""
    t0 = time.monotonic()
    while True:
        running = production_running()
        ps = ollama_get("/api/ps")
        first = {m.get("name"): m.get("expires_at") for m in ps.get("models", [])}
        if not running:
            time.sleep(90)
            running = production_running()
            second = {m.get("name"): m.get("expires_at") for m in ollama_get("/api/ps").get("models", [])}
            if not running and first == second:
                state = {"ollama_loaded_models": list(second), "running_stages": [], "loadavg": os.getloadavg(),
                         "expires_at_stable_90s": True}
                print("idle check:", state, flush=True)
                return state
        if force or time.monotonic() - t0 > timeout:
            sys.exit("BUSY: production still uses Ollama (D5); not measuring")
        print(f"waiting for production to leave Ollama alone (running: {running})", flush=True)
        time.sleep(60)


class RecordingClient:
    """Same request as OllamaClient (auto_short.selection.client) but keeps Ollama's timing fields."""

    def __init__(self, host: str, timeout: float):
        self.host, self.timeout, self.calls = host.rstrip("/"), timeout, []

    def chat(self, *, model, messages, format, options, think):
        from auto_short.selection import client as c

        body = json.dumps(c.request_body(model=model, messages=messages, format=format, options=options,
                                         think=think), ensure_ascii=False).encode()
        req = urllib.request.Request(f"{self.host}/api/chat", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            raise c.ChatUnavailable(str(exc)) from exc
        wall = time.monotonic() - t0
        ns = 1e9
        rec = {"wall": wall, "load_s": data.get("load_duration", 0) / ns, "total_s": data.get("total_duration", 0) / ns,
               "prompt_tokens": data.get("prompt_eval_count"), "prompt_s": data.get("prompt_eval_duration", 0) / ns,
               "eval_tokens": data.get("eval_count"), "eval_s": data.get("eval_duration", 0) / ns,
               "done_reason": data.get("done_reason"),
               "thinking_chars": len((data.get("message") or {}).get("thinking") or "")}
        rec["tok_per_s"] = rec["eval_tokens"] / rec["eval_s"] if rec["eval_s"] else None
        self.calls.append(rec)
        m = data["message"]
        return c.ChatResult(content=m["content"], thinking=m.get("thinking") or None, eval_count=data.get("eval_count"),
                            prompt_eval_count=data.get("prompt_eval_count"),
                            total_duration=data.get("total_duration"), extra={"done_reason": data.get("done_reason")})


SEL_VARIANTS = {
    "base": {},                                          # qwen3:30b, think on, num_ctx 32768 (production)
    "ctx16k": {"num_ctx": 16384},
    "ctx24k": {"num_ctx": 24576},
    "nothink": {"think": False},
    "14b": {"model": "qwen3:14b"},                       # think on
    "14b-nothink": {"model": "qwen3:14b", "think": False},
}


def overlap_match(base: list[dict], other: list[dict]) -> dict:
    def ov(x, y):
        inter = max(0.0, min(x["source_end"], y["source_end"]) - max(x["source_start"], y["source_start"]))
        return inter / min(x["duration"], y["duration"])

    matched = sum(1 for b in base if any(ov(b, o) >= 0.5 for o in other))
    return {"baseline_clips": len(base), "clips": len(other), "baseline_matched(>=50% overlap)": matched,
            "identical_ranges": sum(1 for b in base if any(abs(b["source_start"] - o["source_start"]) < 0.01
                                                           and abs(b["source_end"] - o["source_end"]) < 0.01
                                                           for o in other))}


def cmd_e2(a) -> None:
    from auto_short.selection import stage as sstage
    from auto_short.selection.client import resolve_host

    p = bench_paths(a.bench_dir)
    cfg0 = load_config(p)
    state = wait_ollama_idle(a.force_busy)
    variants = a.variants or (["nothink"] if a.quick else list(SEL_VARIANTS))
    reps = 1 if a.quick else a.reps
    results = []
    for ep in a.episodes:
        base_clips = json.loads((p["work"] / ep / "clips.json").read_text(encoding="utf-8"))["clips"]
        prod_log = json.loads((p["work"] / ep / "selection_log.json").read_text(encoding="utf-8"))
        prod_calls = [c["seconds"] for w in prod_log["windows"] for c in w["ai_calls"]]
        for rep in range(reps):
            for name in variants:
                if a.quick and name != "nothink":
                    continue
                over = SEL_VARIANTS[name]
                if production_running():
                    wait_ollama_idle(False)
                run_root = p["tmp"] / f"sel-{ep}-{name}-{rep}"
                if run_root.exists():
                    shutil.rmtree(run_root)
                ws_dir = run_root / ep
                ws_dir.mkdir(parents=True)
                for f in (p["work"] / ep).iterdir():
                    if f.is_file() and f.name != "source.mp4":
                        shutil.copy2(f, ws_dir / f.name)
                cfg = dataclasses.replace(
                    cfg0, workspace=dataclasses.replace(cfg0.workspace, dir=run_root),
                    selection=dataclasses.replace(cfg0.selection, **over))
                cli = RecordingClient(resolve_host(cfg.selection.ollama_host), cfg.selection.timeout)
                t0 = time.monotonic()
                try:
                    res = sstage.run_selection(ep, cfg, force=True, client=cli, sleep=time.sleep)
                    err = None
                except Exception as exc:  # noqa: BLE001
                    res, err = None, f"{type(exc).__name__}: {exc}"
                wall = time.monotonic() - t0
                row = {"episode": ep, "variant": name, "overrides": over, "rep": rep, "wall": wall, "error": err,
                       "calls": cli.calls, "ai_calls": len(cli.calls),
                       "eval_tokens": sum(c["eval_tokens"] or 0 for c in cli.calls),
                       "load_s": sum(c["load_s"] for c in cli.calls)}
                if res is not None:
                    clips = json.loads((ws_dir / "clips.json").read_text(encoding="utf-8"))["clips"]
                    slog = json.loads((ws_dir / "selection_log.json").read_text(encoding="utf-8"))
                    row["retries"] = sum(max(0, len(w["ai_calls"]) - 1) for w in slog["windows"])
                    row["stats"] = slog["stats"]
                    row["vs_production_clips"] = overlap_match(base_clips, clips)
                    row["clip_ranges"] = [[c["source_start"], c["source_end"]] for c in clips]
                    keep = p["raw"] / "sel" / f"{ep}-{name}-r{rep}"
                    keep.mkdir(parents=True, exist_ok=True)
                    for n in ("clips.json", "selection_log.json"):
                        shutil.copy2(ws_dir / n, keep / n)
                shutil.rmtree(run_root, ignore_errors=True)
                results.append(row)
                print(f"{ep} {name} rep{rep}: {wall:.1f} s, {len(cli.calls)} calls, tokens {row['eval_tokens']}, "
                      f"load {row['load_s']:.1f} s, err={err}", flush=True)
        results.append({"episode": ep, "variant": "production(main manifest, for reference)",
                        "call_seconds": prod_calls, "wall": sum(prod_calls)})
    print()
    table([{"episode": r["episode"], "variant": r["variant"], "rep": r.get("rep"), "wall_s": r["wall"],
            "calls": r.get("ai_calls"), "eval_tok": r.get("eval_tokens"), "load_s": r.get("load_s"),
            "retries": r.get("retries"), "match": (r.get("vs_production_clips") or {}).get(
                "baseline_matched(>=50% overlap)"), "clips": (r.get("vs_production_clips") or {}).get("clips")}
           for r in results], ["episode", "variant", "rep", "wall_s", "calls", "eval_tok", "load_s", "retries",
                               "match", "clips"])
    save(p, "e2", {"idle_state": state, "results": results})


# --- E3 Whisper CPU -------------------------------------------------------------------------------------------

def cut_audio(p: dict, ep: str, start: float, seconds: float) -> Path:
    wav = p["bench"] / f"whisper-cut-{ep}-{int(start)}-{int(seconds)}.wav"
    if not wav.is_file():
        res, err = timed_proc(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-ss", str(start), "-t",
                               str(seconds), "-i", str(p["work"] / ep / "source.mp4"), "-vn", "-ac", "1", "-ar",
                               "16000", str(wav)])
        ffmpeg_ok(res, err, "cut audio")
    return wav


def cmd_e3_once(a) -> None:
    """One Whisper run in this process (a fresh process per measurement). Prints WHISPER_LOADED, then JSON."""
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    t0 = time.monotonic()
    model = WhisperModel(a.model, device="cpu", compute_type=a.compute, cpu_threads=a.threads or (os.cpu_count() or 1),
                         download_root=str(a.models_dir))
    load = time.monotonic() - t0
    print("WHISPER_LOADED", flush=True)
    t1 = time.monotonic()
    if a.batch:
        segs, _ = BatchedInferencePipeline(model).transcribe(str(a.wav), language="vi", vad_filter=True,
                                                             word_timestamps=True, batch_size=a.batch)
    else:
        segs, _ = model.transcribe(str(a.wav), language="vi", vad_filter=True, word_timestamps=True)
    out = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]
    dur = time.monotonic() - t1
    ru = os.times()
    print("RESULT " + json.dumps({"load_s": load, "transcribe_s": dur, "cpu_s": ru.user + ru.system,
                                  "segments": out}, ensure_ascii=False), flush=True)


def whisper_proc(p, wav: Path, threads: int, compute: str, batch: int, models_dir: Path) -> subprocess.Popen:
    cmd = [sys.executable, str(Path(__file__).resolve()), "_e3-once", "--wav", str(wav), "--threads", str(threads),
           "--compute", compute, "--batch", str(batch), "--models-dir", str(models_dir), "--bench-dir", str(p["bench"])]
    env = {**os.environ, "HF_HUB_OFFLINE": "1"}
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def whisper_result(proc: subprocess.Popen) -> dict:
    """Result JSON of a ``_e3-once`` run, or ``{"error": ...}`` when the process died (e.g. a segfault)."""
    out, err = proc.communicate()
    for line in out.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[7:])
    return {"error": f"exit code {proc.returncode} (negative = killed by signal); stderr tail: {err[-300:]!r}"}


def prod_words(p: dict, ep: str, start: float, end: float) -> list[str]:
    doc = json.loads((p["work"] / ep / "transcript.json").read_text(encoding="utf-8"))
    text = " ".join(s["text"] for s in doc["segments"] if s.get("kind") == "speech" and start <= s["start"] < end)
    return norm_words(text)


def norm_words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def cmd_e3(a) -> None:
    p = bench_paths(a.bench_dir)
    load_config(p)
    seconds = 60.0 if a.quick else a.seconds
    wav = cut_audio(p, a.episode, a.start, seconds)
    md = Path(a.models_dir).resolve()
    configs = [("threads=0(48) int8", 0, "int8", 0), ("threads=8 int8", 8, "int8", 0),
               ("threads=16 int8", 16, "int8", 0), ("threads=24 int8", 24, "int8", 0),
               ("threads=32 int8", 32, "int8", 0), ("threads=24 int8_float32", 24, "int8_float32", 0),
               ("batched8 threads=16 int8", 16, "int8", 8), ("batched8 threads=24 int8", 24, "int8", 8),
               ("batched8 threads=0(48) int8", 0, "int8", 8)]
    if a.extra:  # finer thread grid around the optimum and other batch sizes
        configs = [("threads=20 int8", 20, "int8", 0), ("threads=28 int8", 28, "int8", 0),
                   ("batched4 threads=24 int8", 24, "int8", 4), ("batched16 threads=24 int8", 24, "int8", 16),
                   ("batched8 threads=20 int8", 20, "int8", 8), ("batched8 threads=28 int8", 28, "int8", 8)]
    if a.quick:
        configs = [configs[3], configs[6]]
    ref_words = prod_words(p, a.episode, a.start, a.start + seconds)
    rows, texts = [], {}
    reps = 1 if a.quick else a.reps
    for rep in range(reps):
        for label, th, comp, batch in configs:
            attempts = []
            for attempt in range(4):
                quiet = wait_quiet(f"e3 {label}")
                l0 = load1()
                with CpuWindow() as w:
                    proc = whisper_proc(p, wav, th, comp, batch, md)
                    r = whisper_result(proc)
                foreign = w.foreign(r.get("cpu_s", 0.0))
                attempts.append({"foreign_cores": round(foreign, 2), "quiet_at_start": quiet})
                if "error" in r or foreign <= FOREIGN_LIMIT:
                    break
                print(f"{label} rep{rep}: contaminated by other work ({foreign:.1f} cores); retrying", flush=True)
            if "error" in r:
                rows.append({"config": label, "rep": rep, "audio_s": seconds, "error": r["error"]})
                print(f"{label} rep{rep}: FAILED {r['error']}", flush=True)
                continue
            words = norm_words(" ".join(s["text"] for s in r["segments"]))
            sm = difflib.SequenceMatcher(None, ref_words, words, autojunk=False)
            texts.setdefault(label, []).append([s["text"] for s in r["segments"]])
            rows.append({"config": label, "rep": rep, "audio_s": seconds, "load_s": r["load_s"],
                         "transcribe_s": r["transcribe_s"], "rtf": r["transcribe_s"] / seconds,
                         "cpu_s": r["cpu_s"], "segments": len(r["segments"]), "words": len(words),
                         "word_ratio_vs_production": sm.ratio(), "load1_start": l0,
                         "foreign_cores": attempts[-1]["foreign_cores"], "attempts": attempts})
            print(f"{label} rep{rep}: load {r['load_s']:.1f} s, transcribe {r['transcribe_s']:.1f} s "
                  f"(RTF {r['transcribe_s'] / seconds:.3f}), ratio vs production {sm.ratio():.3f}", flush=True)
    # text identity between reps and with the first config
    ref_label = next((l for l, *_ in configs if l in texts), None)
    base_words = norm_words(" ".join(sum(texts[ref_label][:1], []))) if ref_label else []
    ident = {}
    for label, runs in texts.items():
        ws = [norm_words(" ".join(sum([r], []))) for r in runs]
        ident[label] = {"identical_between_reps": all(w == ws[0] for w in ws),
                        "ratio_vs_ref_config": difflib.SequenceMatcher(None, base_words, ws[0],
                                                                         autojunk=False).ratio()}
    summ = []
    for label, *_ in configs:
        allrs = [r for r in rows if r["config"] == label]
        rs = [r for r in allrs if "error" not in r]
        if not rs:
            summ.append({"config": label, "reps": len(allrs), "transcribe_s": None, "each": allrs[0]["error"][:60]})
            continue
        summ.append({"config": label, "reps": len(rs), "transcribe_s": mean([r["transcribe_s"] for r in rs]),
                     "each": [round(r["transcribe_s"], 1) for r in rs], "rtf": mean([r["rtf"] for r in rs]),
                     "cpu_s": mean([r["cpu_s"] for r in rs]), "load_s": mean([r["load_s"] for r in rs]),
                     "ratio_prod": mean([r["word_ratio_vs_production"] for r in rs]),
                     "same_text_as_ref_cfg": ident[label]["ratio_vs_ref_config"],
                     "reps_identical": ident[label]["identical_between_reps"]})
    print()
    table(summ, ["config", "reps", "transcribe_s", "each", "rtf", "cpu_s", "load_s", "ratio_prod",
                 "same_text_as_ref_cfg", "reps_identical"])
    save(p, "e3-extra" if a.extra else "e3", {"episode": a.episode, "start": a.start, "audio_seconds": seconds, "rows": rows, "summary": summ,
                   "identity": ident, "note": "production transcript.json speech text of the same window is the "
                   "reference for ratio_prod (difflib on lower-cased words)"})


# --- E4 analysis ----------------------------------------------------------------------------------------------

def analysis_cmds(cfg, media: Path) -> tuple[list[str], list[str], list[str]]:
    a = cfg.analysis
    base = ["ffmpeg", "-hide_banner", "-nostdin", "-nostats"]
    vf = f"scale={a.scale_width}:-2,select='gt(scene,{a.scene_threshold:g})',showinfo"
    af = f"silencedetect=noise={a.silence_noise_db:g}dB:d={a.silence_min:g}"
    shot = base + ["-i", str(media), "-an", "-vf", vf, "-f", "null", "-"]
    sil = base + ["-i", str(media), "-vn", "-af", af, "-f", "null", "-"]
    merged = base + ["-i", str(media), "-map", "0:v:0", "-an", "-vf", vf, "-f", "null", "-",
                     "-map", "0:a:0", "-vn", "-af", af, "-f", "null", "-"]
    return shot, sil, merged


def media_duration(media: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(media)], capture_output=True, text=True).stdout
    return float(out.strip())


def cmd_e4(a) -> None:
    from auto_short.analysis import detect

    p = bench_paths(a.bench_dir)
    cfg = load_config(p)
    reps = 1 if a.quick else a.reps
    rows, ident = [], {}
    for ep in a.episodes:
        media = p["work"] / ep / "source.mp4"
        shot, sil, merged = analysis_cmds(cfg, media)
        prod_shots = json.loads((p["work"] / ep / "shots.json").read_text(encoding="utf-8"))
        prod_sil = json.loads((p["work"] / ep / "silences.json").read_text(encoding="utf-8"))
        dur = prod_shots["duration"]
        outputs = {}
        for rep in range(reps):
            def one(kind, cmd):
                res, err = timed_proc(cmd)
                ffmpeg_ok(res, err, kind)
                return res, err

            # a) the two passes one after another (what the stage does)
            l0, t0 = load1(), time.monotonic()
            r1, e1 = one("shot", shot)
            r2, e2 = one("silence", sil)
            seq = time.monotonic() - t0
            rows += [{"episode": ep, "config": "sequential: shot pass", "rep": rep, "wall": r1["wall"],
                      "cpu": r1["user"] + r1["sys"], "load1_start": l0},
                     {"episode": ep, "config": "sequential: silence pass", "rep": rep, "wall": r2["wall"],
                      "cpu": r2["user"] + r2["sys"]},
                     {"episode": ep, "config": "sequential total", "rep": rep, "wall": seq,
                      "cpu": r1["user"] + r1["sys"] + r2["user"] + r2["sys"]}]
            outputs["sequential"] = (e1, e2)
            # b) the two passes in parallel
            t0 = time.monotonic()
            with cf.ThreadPoolExecutor(2) as pool:
                fa, fb = pool.submit(one, "shot", shot), pool.submit(one, "silence", sil)
                (ra, ea), (rb, eb) = fa.result(), fb.result()
            par = time.monotonic() - t0
            rows.append({"episode": ep, "config": "parallel (2 processes)", "rep": rep, "wall": par,
                         "cpu": ra["user"] + ra["sys"] + rb["user"] + rb["sys"]})
            outputs["parallel"] = (ea, eb)
            # c) one ffmpeg, two outputs (decode the file once)
            rm, em = one("merged", merged)
            rows.append({"episode": ep, "config": "merged (1 process, 2 outputs)", "rep": rep, "wall": rm["wall"],
                         "cpu": rm["user"] + rm["sys"]})
            outputs["merged"] = (em, em)
            print(f"{ep} rep{rep}: seq {seq:.1f} s (shot {r1['wall']:.1f} + silence {r2['wall']:.1f}), parallel "
                  f"{par:.1f} s, merged {rm['wall']:.1f} s", flush=True)
        for name, (es, ei) in outputs.items():
            changes = detect.normalize_changes(detect.parse_showinfo(es), dur)
            silences = detect.parse_silencedetect(ei, dur)
            ident[f"{ep}:{name}"] = {
                "shots_equal_production": changes == prod_shots.get("changes", prod_shots.get("shot_changes", changes)),
                "n_shots": len(changes), "n_silences": len(silences),
                "silences_equal_production": [list(x) for x in silences] == [
                    [s["start"], s["end"]] if isinstance(s, dict) else list(s)
                    for s in prod_sil.get("silences", prod_sil.get("intervals", []))]}
    summ = []
    for ep in a.episodes:
        for cfgname in dict.fromkeys(r["config"] for r in rows if r["episode"] == ep):
            rs = [r for r in rows if r["episode"] == ep and r["config"] == cfgname]
            summ.append({"episode": ep, "config": cfgname, "reps": len(rs), "wall_s": mean([r["wall"] for r in rs]),
                         "each": [round(r["wall"], 1) for r in rs], "cpu_s": mean([r["cpu"] for r in rs])})
    print()
    table(summ, ["episode", "config", "reps", "wall_s", "each", "cpu_s"])
    for k, v in ident.items():
        print("identical?", k, v)
    save(p, "e4", {"rows": rows, "summary": summ, "identity_vs_production_json": ident})


# --- E5 concurrency -------------------------------------------------------------------------------------------

def cmd_e5(a) -> None:
    p = bench_paths(a.bench_dir)
    cfg = load_config(p)
    md = Path(a.models_dir).resolve()
    cmds = load_cmds(p, SHORT)
    clips = [c for c in ("k01", "k04", "k06") if c in cmds]
    seconds = 60.0 if a.quick else a.seconds
    wav = cut_audio(p, SHORT, a.start, seconds)
    media = p["work"] / SHORT / "source.mp4"
    shot, sil, _ = analysis_cmds(cfg, media)
    reps = 1 if a.quick else a.reps
    rows = []

    import threading

    def render_solo(tag: str, rth: int) -> list[float]:
        walls = []
        for c in clips:
            r = run_clip(p, cmds[c]["cmd"], f"e5_{tag}_{c}", threads=rth)
            r["out"].unlink(missing_ok=True)
            walls.append(r["wall"])
        return walls

    def render_during(alive, tag: str, rth: int) -> list[dict]:
        """Render clips in a loop while ``alive()`` is true; keep only renders that finished while it still was."""
        out, i = [], 0
        while alive():
            c = clips[i % len(clips)]
            r = run_clip(p, cmds[c]["cmd"], f"e5_{tag}_{i}", threads=rth)
            r["out"].unlink(missing_ok=True)
            out.append({"clip": c, "wall": r["wall"], "overlapped": alive()})
            i += 1
        return out

    def scenario(label: str, fn) -> dict:
        """Run ``fn`` on a quiet machine; repeat (max 3 times) when other work used more than FOREIGN_LIMIT cores."""
        tries = []
        for _ in range(3):
            wait_quiet(f"e5 {label}")
            mark = len(CPU_LEDGER)
            with CpuWindow() as w:
                out = fn()
            own = sum(CPU_LEDGER[mark:]) + out.pop("_own_cpu", 0.0)
            foreign = w.foreign(own)
            tries.append(round(foreign, 2))
            if foreign <= FOREIGN_LIMIT:
                break
            print(f"{label}: contaminated by other work ({foreign:.1f} cores); retrying", flush=True)
        return {**out, "foreign_cores": tries[-1], "tries_foreign_cores": tries}

    def whisper_solo(th: int) -> dict:
        r = whisper_result(whisper_proc(p, wav, th, "int8", 0, md))
        return {"whisper_s": r["transcribe_s"], "_own_cpu": r["cpu_s"]}

    def analysis_solo() -> dict:
        r1, _ = timed_proc(shot)
        r2, _ = timed_proc(sil)
        return {"analysis_s": r1["wall"] + r2["wall"]}

    def with_whisper(wth: int, rth: int) -> dict:
        proc = whisper_proc(p, wav, wth, "int8", 0, md)
        proc.stdout.readline()  # WHISPER_LOADED (model load excluded from the overlap)
        done, box = {"v": False}, {}

        def waiter():
            box["r"] = whisper_result(proc)
            done["v"] = True

        th = threading.Thread(target=waiter)
        th.start()
        rend = render_during(lambda: not done["v"], f"ww{wth}", rth)
        th.join()
        ov = [x["wall"] for x in rend if x["overlapped"]]
        return {"whisper_s": box["r"]["transcribe_s"], "render_clips_overlapped": len(ov),
                "render_mean_s": mean(ov), "render_walls": [round(x, 1) for x in ov],
                "_own_cpu": box["r"]["cpu_s"]}

    def with_analysis() -> dict:
        done, box = {"v": False}, {}

        def bg():
            t0 = time.monotonic()
            timed_proc(shot)
            timed_proc(sil)
            box["wall"] = time.monotonic() - t0
            done["v"] = True

        th = threading.Thread(target=bg)
        th.start()
        rend = render_during(lambda: not done["v"], "an", 0)
        th.join()
        ov = [x["wall"] for x in rend if x["overlapped"]]
        return {"analysis_s": box["wall"], "render_clips_overlapped": len(ov), "render_mean_s": mean(ov),
                "render_walls": [round(x, 1) for x in ov]}

    for rep in range(reps):
        solo = {}
        solo["render0"] = scenario("render solo threads=0", lambda: {"walls": render_solo(f"s0_{rep}", 0)})
        solo["render8"] = scenario("render solo threads=8", lambda: {"walls": render_solo(f"s8_{rep}", 8)})
        solo["whisper0"] = scenario("whisper solo threads=0", lambda: whisper_solo(0))
        solo["whisper24"] = scenario("whisper solo threads=24", lambda: whisper_solo(24))
        solo["analysis"] = scenario("analysis solo", analysis_solo)
        rows.append({"rep": rep, "scenario": "solo", **solo})
        print(f"rep{rep} solo: render(0) {[round(x, 1) for x in solo['render0']['walls']]}, render(8) "
              f"{[round(x, 1) for x in solo['render8']['walls']]}, whisper(48) {solo['whisper0']['whisper_s']:.1f}, "
              f"whisper(24) {solo['whisper24']['whisper_s']:.1f}, analysis {solo['analysis']['analysis_s']:.1f}",
              flush=True)
        for wth, rth in ((0, 0), (24, 0), (24, 8)):
            r = scenario(f"whisper({wth}) + render({rth})", lambda wth=wth, rth=rth: with_whisper(wth, rth))
            base_render = mean(solo["render0" if rth == 0 else "render8"]["walls"])
            base_w = solo["whisper0" if wth == 0 else "whisper24"]["whisper_s"]
            rows.append({"rep": rep, "scenario": f"whisper(threads={wth}) + render(threads={rth})", **r,
                         "whisper_solo_s": base_w, "render_solo_mean_s": base_render})
            print(f"rep{rep} whisper({wth})+render({rth}): whisper {r['whisper_s']:.1f} s (solo {base_w:.1f}), render "
                  f"mean {r['render_mean_s']:.1f} s over {r['render_clips_overlapped']} clips (solo "
                  f"{base_render:.1f}), foreign {r['foreign_cores']}", flush=True)
        r = scenario("analysis + render", with_analysis)
        base_render = mean(solo["render0"]["walls"])
        rows.append({"rep": rep, "scenario": "analysis + render(threads=0)", **r,
                     "analysis_solo_s": solo["analysis"]["analysis_s"], "render_solo_mean_s": base_render})
        print(f"rep{rep} analysis+render: analysis {r['analysis_s']:.1f} s (solo {solo['analysis']['analysis_s']:.1f}), "
              f"render mean {r['render_mean_s']:.1f} s over {r['render_clips_overlapped']} clips (solo "
              f"{base_render:.1f}), foreign {r['foreign_cores']}", flush=True)
    save(p, "e5", {"whisper_audio_s": seconds, "clips": clips, "rows": rows})


# --- E6 cache -------------------------------------------------------------------------------------------------

class Forbidden:
    """Stub for AI / Whisper backends: E6 must never reach them (every stage has to be skipped)."""

    version = "forbidden"

    def __getattr__(self, name):
        raise RuntimeError("E6: a stage tried to run its backend; the episode was not up to date")


def cmd_e6(a) -> None:
    from auto_short.analysis import run_analysis
    from auto_short.render import run_render
    from auto_short.review import logic as rl
    from auto_short.selection import run_selection
    from auto_short.titling import run_titling
    from auto_short.transcript import run_transcript

    p = bench_paths(a.bench_dir)
    cfg = load_config(p)
    out = {"episodes": {}}
    for ep in (SHORT, KT):
        man = json.loads((p["work"] / ep / "manifest.json").read_text(encoding="utf-8"))
        if "render" not in man["stages"] or man["stages"]["render"]["status"] != "done":
            sys.exit(f"{ep}: no finished render in the bench; run 'e1-capture' first")
        rec = {"rerun_unchanged": {}}
        t_all = time.monotonic()
        for name, fn, kw in (("transcript", run_transcript, {"backend": Forbidden()}),
                             ("analysis", run_analysis, {"analyzer": Forbidden()}),
                             ("selection", run_selection, {"client": Forbidden()}),
                             ("titling", run_titling, {"client": Forbidden()}),
                             ("render", run_render, {})):
            t0 = time.monotonic()
            r = fn(ep, cfg, **kw)
            rec["rerun_unchanged"][name] = {"ran": r.ran, "seconds": time.monotonic() - t0}
        rec["rerun_unchanged_total_s"] = time.monotonic() - t_all
        print(f"{ep}: unchanged re-run: {rec['rerun_unchanged']}")
        # execution-only change (render.threads) must not re-run anything
        cfg8 = dataclasses.replace(cfg, render=dataclasses.replace(cfg.render, threads=8))
        t0 = time.monotonic()
        r = run_render(ep, cfg8)
        rec["threads_8_render"] = {"ran": r.ran, "seconds": time.monotonic() - t0}
        print(f"{ep}: render with threads=8: ran={r.ran}")
        if ep == SHORT:
            rm_path = p["output"] / ep / "render_manifest.json"
            before = {s["clip_id"]: s["sha256"] for s in json.loads(rm_path.read_text())["shorts"]
                      if s["status"] == "rendered"}
            clip = "k03"
            clips = json.loads((p["work"] / ep / "clips.json").read_text())["clips"]
            order = [c["id"] for c in clips]
            cand = next(c["candidate_id"] for c in clips if c["id"] == clip)
            review = rl.with_override(rl.empty_review(ep), order, clip_id=clip, candidate_id=cand,
                                      title="Tiêu đề thử nghiệm CP11", origin=rl.MANUAL)
            (p["work"] / ep / rl.REVIEW_NAME).write_text(json.dumps(review, ensure_ascii=False, indent=2),
                                                        encoding="utf-8")
            t0 = time.monotonic()
            r = run_render(ep, cfg)
            wall = time.monotonic() - t0
            after = {s["clip_id"]: s["sha256"] for s in json.loads(rm_path.read_text())["shorts"]
                     if s["status"] == "rendered"}
            rec["title_edit_one_clip"] = {"clip": clip, "ran": r.ran, "encoded": r.encoded, "reused": r.reused,
                                          "seconds": wall,
                                          "files_changed": [c for c in after if before.get(c) != after[c]]}
            print(f"{ep}: title edit of {clip}: encoded {r.encoded}, reused {r.reused}, {wall:.1f} s, changed "
                  f"{rec['title_edit_one_clip']['files_changed']}")
            # reset the override; the clip is encoded again (title back to the AI one)
            (p["work"] / ep / rl.REVIEW_NAME).unlink()
            t0 = time.monotonic()
            r = run_render(ep, cfg)
            rec["title_reset"] = {"encoded": r.encoded, "reused": r.reused, "seconds": time.monotonic() - t0}
            print(f"{ep}: override removed: encoded {r.encoded}, reused {r.reused}")
        out["episodes"][ep] = rec
    save(p, "e6", out)


# --- hashes ---------------------------------------------------------------------------------------------------

def cmd_hashes(a) -> None:
    from auto_short import hashing
    from auto_short.analysis import stage as astage
    from auto_short.render import plan, stage as rstage
    from auto_short.selection import stage as sstage
    from auto_short.transcript import stage as tstage

    p = bench_paths(a.bench_dir)
    cfg = load_config(p)
    font_sha = hashing.sha256_file(rstage.font_path(cfg.render))

    def hashes(c) -> dict:
        return {"transcript": hashing.config_hash(tstage.used_config(c)),
                "analysis": hashing.config_hash(astage.used_config(c)),
                "selection": hashing.config_hash(sstage.used_config(c)),
                "render": hashing.config_hash(rstage.used_config(c.render, font_sha))}

    def rep(**sections):
        c = cfg
        for sec, over in sections.items():
            if sec == "whisper":
                c = dataclasses.replace(c, transcript=dataclasses.replace(
                    c.transcript, whisper=dataclasses.replace(c.transcript.whisper, **over)))
            else:
                c = dataclasses.replace(c, **{sec: dataclasses.replace(getattr(c, sec), **over)})
        return c

    base = hashes(cfg)
    variants = {
        "render.threads=8 (or 16)": rep(render={"threads": 8}),
        "render.preset=fast": rep(render={"preset": "fast"}),
        "render.preset=veryfast": rep(render={"preset": "veryfast"}),
        "render.crf=24": rep(render={"crf": 24}),
        "whisper.cpu_threads=16": rep(whisper={"cpu_threads": 16}),
        "whisper.compute_type=int8_float32": rep(whisper={"compute_type": "int8_float32"}),
        "selection.think=false": rep(selection={"think": False}),
        "selection.model=qwen3:14b": rep(selection={"model": "qwen3:14b"}),
        "selection.num_ctx=16384": rep(selection={"num_ctx": 16384}),
        "selection.ollama_host / timeout": rep(selection={"ollama_host": "http://x:1", "timeout": 60.0}),
        "analysis.scale_width=160": rep(analysis={"scale_width": 160}),
    }
    rows = []
    for name, c in variants.items():
        h = hashes(c)
        rows.append({"change": name, **{f"{k}_hash_changes": h[k] != base[k] for k in base}})
    print(f"render plan version {plan.RENDER_PLAN_VERSION}; render_key includes render_config_hash (stage.render_key)")
    table(rows, ["change", "transcript_hash_changes", "analysis_hash_changes", "selection_hash_changes",
                 "render_hash_changes"])
    print("\nNo config key exists for: parallel jobs, batched Whisper, merged/parallel analysis passes; those change "
          "code paths only. Output changes still change downstream input sha256 (inputs list) and re-run stages.")
    print("render_key changes iff render_config_hash changes (or font/source/fps/segments/dissolves/layout/header/"
          "title/plan_version), so the render column above is also the render_key answer.")
    save(p, "hashes", {"base": base, "variants": rows,
                       "render_exec_keys": list(rstage.EXEC_KEYS), "render_plan_version": plan.RENDER_PLAN_VERSION})


# --- main -----------------------------------------------------------------------------------------------------

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--bench-dir", type=Path, default=DEFAULT_BENCH, help=argparse.SUPPRESS)
        sp.add_argument("--quick", action="store_true", help="one short run")
        sp.set_defaults(fn=fn)
        return sp

    sp = add("setup", cmd_setup, "copy the measured episodes into the bench dir (source read-only)")
    sp.add_argument("--source-work", default=str(REPO_MAIN / "work"))
    sp.add_argument("--models-dir", default=str(REPO_MAIN / "models"))
    sp = add("e1-capture", cmd_e1_capture, "real render of the bench episodes; keeps the ffmpeg commands")
    sp.add_argument("--episodes", nargs="*", choices=EPISODES)
    sp = add("e1", cmd_e1, "render: threads / parallel / preset / decode-vs-encode")
    sp.add_argument("--episodes", nargs="+", default=[SHORT, KT], choices=EPISODES)
    sp.add_argument("--only", nargs="+", choices=["threads", "preset", "split", "parallel", "epar"])
    sp.add_argument("--reps", type=int, default=2)
    sp = add("e2", cmd_e2, "selection variants against Ollama (needs an idle queue, D5)")
    sp.add_argument("--episodes", nargs="+", default=[SHORT], choices=EPISODES)
    sp.add_argument("--variants", nargs="+", choices=list(SEL_VARIANTS))
    sp.add_argument("--reps", type=int, default=2)
    sp.add_argument("--force-busy", action="store_true")
    sp = add("e3", cmd_e3, "Whisper CPU threads / compute type / batched, on a cut of the audio")
    sp.add_argument("--episode", default=SHORT, choices=EPISODES)
    sp.add_argument("--start", type=float, default=600.0)
    sp.add_argument("--seconds", type=float, default=300.0)
    sp.add_argument("--reps", type=int, default=2)
    sp.add_argument("--models-dir", default=str(REPO_MAIN / "models"))
    sp.add_argument("--extra", action="store_true", help="finer thread grid + other batch sizes")
    sp = add("e4", cmd_e4, "analysis passes: sequential / parallel / merged")
    sp.add_argument("--episodes", nargs="+", default=[SHORT, CAPTION], choices=EPISODES)
    sp.add_argument("--reps", type=int, default=2)
    sp = add("e5", cmd_e5, "render concurrent with Whisper / analysis")
    sp.add_argument("--start", type=float, default=600.0)
    sp.add_argument("--seconds", type=float, default=300.0)
    sp.add_argument("--reps", type=int, default=2)
    sp.add_argument("--models-dir", default=str(REPO_MAIN / "models"))
    add("e6", cmd_e6, "cache reuse: unchanged re-run, execution-only change, one title edit")
    add("hashes", cmd_hashes, "which knobs change config_hash / render_key")
    sp = sub.add_parser("_e3-once", help=argparse.SUPPRESS)
    sp.add_argument("--wav", type=Path, required=True)
    sp.add_argument("--threads", type=int, default=0)
    sp.add_argument("--compute", default="int8")
    sp.add_argument("--batch", type=int, default=0)
    sp.add_argument("--models-dir", type=Path, required=True)
    sp.add_argument("--bench-dir", type=Path, default=DEFAULT_BENCH)
    sp.add_argument("--model", default="large-v3-turbo")
    sp.set_defaults(fn=cmd_e3_once)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
