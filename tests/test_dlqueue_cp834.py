"""CP8.34: the pure queue logic of ``static/dlqueue.js`` (AC1, AC3, AC4, AC5), run with Node (skipped without it)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
MODULE = Path(__file__).resolve().parents[1] / "src" / "auto_short" / "web" / "static" / "dlqueue.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def run_js(body: str):
    script = f"""
const Q = require({json.dumps(str(MODULE))});
let n = 0; const tok = () => "tok" + (++n).toString().padStart(8, "0");
const specs = (k) => Array.from({{length: k}}, (_, i) => ({{key: "v" + i + ":zip", name: "f" + i, url: "/f/" + i, kind: "zip"}}));
const status = (q) => q.items.map((i) => i.status).join(",");
{body}
"""
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_never_more_than_k_sending_and_next_starts_after_done():
    r = run_js("""
const res = [];
for (const k of [1, 2, 3]) {
  const q = Q.createQueue({concurrency: k}); q.add(specs(6));
  let t = 0, maxSending = 0, doneOrder = [];
  for (let guard = 0; guard < 100 && q.active(); guard++) {
    q.step(t, tok);
    maxSending = Math.max(maxSending, q.counts().sending);
    const sending = q.items.filter((i) => i.status === "sending");
    if (sending.length) q.report(sending[0].id, sending[0].token, {state: "done", bytes_sent: 5, bytes_total: 5}, t);
    t += 1000;
  }
  res.push([k, maxSending, q.counts().done]);
}
console.log(JSON.stringify(res));
""")
    assert r == [[1, 1, 6], [2, 2, 6], [3, 3, 6]]


def test_retry_twice_then_error_and_other_files_continue():
    r = run_js("""
const q = Q.createQueue({concurrency: 1}); q.add(specs(2));
let t = 0, starts = 0;
const startsOf0 = [];
for (let guard = 0; guard < 200 && q.active(); guard++) {
  for (const s of q.step(t, tok)) { if (s.item.name === "f0") startsOf0.push(t); }
  const s0 = q.items[0];
  if (s0.status === "sending") q.report(s0.id, s0.token, {state: "aborted", bytes_sent: 1, bytes_total: null}, t);
  const s1 = q.items[1];
  if (s1.status === "sending") q.report(s1.id, s1.token, {state: "done", bytes_sent: 1, bytes_total: 1}, t);
  t += 1000;
}
console.log(JSON.stringify({attempts: q.items[0].attempts, status: status(q), gaps: startsOf0.slice(1).map((x, i) => x - startsOf0[i]), starts: startsOf0.length}));
""")
    assert r["attempts"] == 3 and r["starts"] == 3 and r["status"] == "error,done"  # 1 try + exactly 2 retries
    assert all(g >= 5000 for g in r["gaps"])


def test_manual_retry_resets_attempts_and_new_token_each_try():
    r = run_js("""
const q = Q.createQueue({concurrency: 1}); q.add(specs(1));
const tokens = [];
let t = 0;
for (let i = 0; i < 40 && q.active(); i++) {
  for (const s of q.step(t, tok)) tokens.push(s.token);
  const it = q.items[0];
  if (it.status === "sending") q.report(it.id, it.token, {state: "aborted"}, t);
  t += 6000;
}
const afterFail = status(q);
const ok = q.retry(q.items[0].id);
q.step(t, tok);
console.log(JSON.stringify({afterFail, ok, status: status(q), unique: new Set(tokens).size, n: tokens.length}));
""")
    assert r["afterFail"] == "error" and r["ok"] and r["status"] == "sending" and r["unique"] == r["n"] == 3


def test_no_request_seen_within_60s_is_error_but_seen_sending_is_not():
    r = run_js("""
const q = Q.createQueue({concurrency: 2, maxRetries: 0}); q.add(specs(2));
q.step(0, tok);
const [a, b] = q.items;
q.report(a.id, a.token, null, 59000);
const s1 = a.status;
q.report(a.id, a.token, null, 61000);
q.report(b.id, b.token, {state: "sending", bytes_sent: 10, bytes_total: null}, 10000);
q.report(b.id, b.token, null, 200000);  // already seen: a 404 later does not fail it
console.log(JSON.stringify([s1, a.status, b.status]));
""")
    assert r == ["sending", "error", "sending"]


def test_pause_resume_and_skipped_kinds_and_stale_token():
    r = run_js("""
const q = Q.createQueue({concurrency: 2});
q.add([{key: "a:vertical", name: "a", url: null, kind: "vertical", skipped: "chưa có bản dọc"}, ...specs(3)]);
q.pause();
const none = q.step(0, tok).length;
q.resume();
const started = q.step(0, tok).length;
const it = q.items.find((i) => i.status === "sending");
q.report(it.id, "stale-token-xx", {state: "done"}, 1);  // a report for an old token is ignored
q.pause();
q.report(it.id, it.token, {state: "done", bytes_sent: 1}, 2);
const startedWhilePaused = q.step(3, tok).length;
console.log(JSON.stringify({none, started, startedWhilePaused, counts: q.counts(), reason: q.items[0].reason,
  dup: q.add(specs(3).slice(2)).length, conc: [Q.createQueue({concurrency: 9}).getConcurrency(), Q.createQueue({concurrency: 3}).getConcurrency()],
  url: Q.withToken("/a?b=1", "t k"), url2: Q.withToken("/a", "tt")}));
""")
    assert r["none"] == 0 and r["started"] == 2 and r["startedWhilePaused"] == 0
    assert r["counts"]["skipped"] == 1 and r["counts"]["done"] == 1 and r["reason"] == "chưa có bản dọc"
    assert r["dup"] == 0  # same key already live
    assert r["conc"] == [2, 3]
    assert r["url"] == "/a?b=1&dl=t%20k" and r["url2"] == "/a?dl=tt"


def test_hung_status_request_blocks_only_its_own_item():
    r = run_js("""
const q = Q.createQueue({concurrency: 2}); q.add(specs(2));
q.step(0, tok);
const [a, b] = q.items;
const r1 = q.pollTargets().map((i) => i.name);     // both polled
const r2 = q.pollTargets().map((i) => i.name);     // a and b still in flight: nothing new
q.report(b.id, b.token, {state: "sending", bytes_sent: 3, bytes_total: 9}, 1); q.pollDone(b.id, b.token);
const r3 = q.pollTargets().map((i) => i.name);     // b polls again while a's request hangs
q.report(a.id, a.token, {state: "done", bytes_sent: 1, bytes_total: 1}, 2); q.pollDone(a.id, a.token);
console.log(JSON.stringify([r1, r2, r3, a.status, a.polling]));
""")
    assert r == [["f0", "f1"], [], ["f1"], "done", False]
