"""CP8.23 scratch measurement (read-only): stored candidates.json vs regenerated with the adaptive ladder.

Usage: PYTHONPATH=src python tools/measure_adaptive_boundary.py <work_dir> [config.toml]
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

from auto_short.analysis.candidates import (boundary_ladder, build_units, coarse_fraction, detect_content_window,
                                            find_cut_points)
from auto_short.analysis.stage import analyze
from auto_short.config import load as load_config
from auto_short.khaithi import load_effective

work = Path(sys.argv[1])
cfg0 = load_config(Path(sys.argv[2])) if len(sys.argv) > 2 else load_config(None)
print("episode\tkt\tstored_thr\tnew_thr\tsame\tfrac@ladder\tcands\tin_target\tunits\tstatus")
for d in sorted(work.iterdir()):
    need = ["candidates.json", "shots.json", "silences.json", "transcript.json", "metadata.json"]
    if not all((d / n).is_file() for n in need):
        continue
    j = lambda n: json.loads((d / n).read_text())
    cfg, kt = load_effective(cfg0, d)
    a = cfg.analysis
    stored, tr, md = j("candidates.json"), j("transcript.json"), j("metadata.json")
    sil = [(x["start"], x["end"]) for x in j("silences.json")["silences"]]
    try:
        shots, sd, new = analyze(d.name, tr, md, j("shots.json")["changes"], sil, a)
    except Exception as exc:  # noqa
        print(f"{d.name}\t{bool(kt)}\t-\t-\t-\t-\t-\t-\t-\tERR {exc}")
        continue
    window = detect_content_window(tr["segments"], sil, float(md["duration"]), a)
    fr = []
    for t in boundary_ladder(a):
        c = replace(a, min_boundary_silence=t)
        u = build_units(tr["segments"], sil, find_cut_points(tr["segments"], sil, window, c), c)
        fr.append(f"{t:g}:{coarse_fraction(u, a):.2f}")
    same = new == stored
    print(f"{d.name}\t{int(bool(kt))}\t{stored['params']['min_boundary_silence']}\t{new['params']['min_boundary_silence']}\t"
          f"{int(same)}\t{' '.join(fr)}\t{stored['stats']['candidates']}->{new['stats']['candidates']}\t"
          f"{stored['stats']['in_target']}->{new['stats']['in_target']}\t{stored['stats']['units']}->{new['stats']['units']}\t")
