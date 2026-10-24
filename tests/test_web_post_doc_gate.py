"""FIX-post-doc-gate AC4: execute the post card's real JS click handlers without sockets or browser dependencies."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[1] / "src/auto_short/web/static/app.js"
NODE = shutil.which("node")

HARNESS = r"""
const fs = require("fs"), vm = require("vm");
let gesture = false, copies = 0, copyOk = JSON.parse(process.argv[3]);
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.hidden = false; this.style = {}; }
  setAttribute(k, v) { this[k] = k === "hidden" ? true : v; }
  append(...nodes) { this.children.push(...nodes); for (const n of nodes) if (typeof n === "object") n.parent = this; }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  addEventListener(k, f) { (this.listeners[k] ||= []).push(f); }
  querySelectorAll(sel) {
    const descendants = this.children.filter(n => typeof n === "object");
    return descendants.flatMap(n => [
      ...(sel.startsWith(".") && (n.className || "").split(" ").includes(sel.slice(1)) ? [n] : []),
      ...n.querySelectorAll(sel)]);
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  focus() {} select() {} setSelectionRange() {}
  remove() { this.parent.children = this.parent.children.filter(n => n !== this); }
  async click() {
    gesture = true;
    const pending = (this.listeners.click || []).map(f => f());
    gesture = false;
    await Promise.all(pending);
  }
}
const storage = new Map();
const context = {
  document: { createElement: tag => new El(tag), body: new El("body"), addEventListener() {},
    execCommand(cmd) { if (!gesture || cmd !== "copy") throw Error("copy outside click"); copies++; return copyOk; } },
  window: { isSecureContext: false }, navigator: {}, setTimeout() {},
  localStorage: { getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v) },
  fetch() { throw Error("unexpected network"); },
  alert() { throw Error("unexpected alert"); }, confirm() { throw Error("unexpected confirm"); },
};
// Expose private functions only in the VM, leaving the production API unchanged.
const code = fs.readFileSync(process.argv[1], "utf8").replace(
  "return { initIndex,", "return { postCard, postBadges, copyTitleButton, initIndex,");
vm.createContext(context);
vm.runInContext(code + "\nglobalThis.ui = AutoShort;", context);
const ui = context.ui, origin = process.argv[2];
const post = { clip_id: "k03", origin, text: "Bài đầy đủ", paragraphs: ["Đoạn bài."],
  chars: 11, image: "picture.png", image_missing: false, posted: false };
const card = ui.postCard({ id: "t11", view: { kind: "short" }, posts: [post] }, { clip_id: "k03" }, post);
const button = label => card.querySelectorAll(".btn").find(n => n.textContent === label);
const warning = card.querySelector(".post-copy-warning");
const state = () => ({ copies, warning: !!warning && !warning.hidden,
  marks: JSON.parse(storage.get("autoShort.postMarks") || "{}"),
  fallback: card.querySelectorAll(".copy-fallback").length });
(async () => {
  const badges = ui.postBadges(post).map(n => n.textContent);
  const out = { badges, initial: state() };
  await button("Sao chép bài").click(); out.first = state();
  if (origin === "ai" || origin === "raw") {
    out.message = warning.children[0].textContent;
    await button("Hủy").click(); out.cancelled = state();
    await button("Sao chép bài").click(); out.reopened = state();
    await button("Vẫn sao chép").click();
  }
  out.final = state();
  // Title copying still succeeds in one click, without a post warning.
  copyOk = true;
  const title = ui.copyTitleButton("Tiêu đề");
  await title.querySelector(".copy-btn").click();
  out.titleCopies = copies - out.final.copies;
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("origin", ["ai", "raw", "doc", "manual"])
@pytest.mark.parametrize("copy_ok", [True, False])
def test_post_copy_warning_and_mark_only_after_success(origin, copy_ok):
    result = subprocess.run([NODE, "-e", HARNESS, str(APP_JS), origin, json.dumps(copy_ok)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    ai_label = "Chữ AI từ phụ đề — đọc kỹ trước khi đăng"
    assert out["badges"].count(ai_label) == int(origin in {"ai", "raw"})
    if origin == "raw":
        assert "AI không chắc — kiểm lại" in out["badges"]
    if origin == "doc":
        assert "Văn bản gốc" in out["badges"]
    assert out["initial"] == {"copies": 0, "warning": False, "marks": {}, "fallback": 0}
    if origin in {"ai", "raw"}:
        assert out["first"] == {"copies": 0, "warning": True, "marks": {}, "fallback": 0}
        assert out["message"] == ("Bài này do AI chấm câu từ phụ đề tự động, có thể sai chữ. "
                                  "Đọc kỹ / sửa trước khi đăng.")
        assert out["cancelled"] == out["initial"]
        assert out["reopened"] == out["first"]
    else:
        assert out["first"]["copies"] == 1 and out["first"]["warning"] is False
    assert out["final"]["copies"] == 1  # exactly one clipboard attempt, inside a user click
    assert out["final"]["marks"] == ({"t11/k03": {"copy": "Bài đầy đủ"}} if copy_ok else {})
    assert out["final"]["fallback"] == int(not copy_ok)
    assert out["titleCopies"] == 1
