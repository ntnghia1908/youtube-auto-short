"""FIX-post-scroll-return: tick wiring and one scroll retry on returning to Posts."""

import shutil
import subprocess
from pathlib import Path

import pytest


APP_JS = Path(__file__).resolve().parents[1] / "src/auto_short/web/static/app.js"
NODE = shutil.which("node")


@pytest.mark.parametrize("handler,next_marker", [
    ("async function tickPostedAfterCopy()", "async function togglePosted(input)"),
    ("async function togglePosted(input)", "\n    render();\n    return card;"),
])
def test_successful_posted_handlers_request_scroll_after_reload(handler, next_marker):
    js = APP_JS.read_text(encoding="utf-8")
    body = js.split(handler, 1)[1].split(next_marker, 1)[0]
    assert 'await api(url("/posted")' in body
    assert "await loadPostsPage();\n        if (r.posted) requestPostScroll();" in body
    assert body.index("await api(") < body.index("await loadPostsPage();")
    assert "requestPostScroll" not in body.split("catch (e)", 1)[1]
    assert "scrollToNextPost" not in body


def test_return_listener_is_only_registered_in_posts_init():
    js = APP_JS.read_text(encoding="utf-8")
    registration = 'document.addEventListener("visibilitychange", resumePostScroll);'
    assert js.count(registration) == 1
    assert registration in js.split("function initPosts() {", 1)[1].split("\n  }", 1)[0]
    assert "initialScrolled: false, scrollOnReturn: false" in js


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("scenario", ["hidden", "visible", "no-tick", "hidden-before-frame"])
def test_return_scroll_lifecycle(scenario):
    # Execute the production helpers with only visibility, frame queue and scrolling faked.
    js = APP_JS.read_text(encoding="utf-8")
    helpers = "function requestPostScroll() {" + js.split("function requestPostScroll() {", 1)[1]
    helpers = helpers.split("  function postsKindBar()", 1)[0]
    script = r"""
const assert = require("node:assert/strict");
const postsPage = { scrollOnReturn: false }, document = { hidden: false }, frames = [];
let scrolls = 0;
function scrollToNextPost() { scrolls++; }
function requestAnimationFrame(fn) { frames.push(fn); }
function frame() { while (frames.length) frames.shift()(); }
""" + helpers + r"""
const scenario = process.argv[1];
if (scenario !== "no-tick") {
  document.hidden = scenario === "hidden";
  requestPostScroll();
}
const immediate = Number(scenario === "visible" || scenario === "hidden-before-frame");
assert.equal(scrolls, immediate);
document.hidden = true;
resumePostScroll();
assert.equal(frames.length, 0);
document.hidden = false;
resumePostScroll();
assert.equal(scrolls, immediate); // wait for layout before retrying
if (scenario === "hidden-before-frame") {
  document.hidden = true;
  frame();
  assert.equal(postsPage.scrollOnReturn, true); // another app switch must retain the retry
  assert.equal(scrolls, immediate);
  document.hidden = false;
  resumePostScroll();
}
frame();
const expected = immediate + Number(scenario !== "no-tick");
assert.equal(scrolls, expected);
assert.equal(postsPage.scrollOnReturn, false);
document.hidden = true;
resumePostScroll();
document.hidden = false;
resumePostScroll();
frame();
assert.equal(scrolls, expected); // the retry is consumed exactly once
"""
    result = subprocess.run([NODE, "-e", script, scenario], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
