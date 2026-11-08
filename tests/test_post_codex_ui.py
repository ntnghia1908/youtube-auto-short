"""PCX1 AC5: execute the production card's click handler in the existing no-socket JS VM."""
import json
import subprocess

import pytest

from test_web_post_doc_gate import APP_JS, HARNESS, NODE


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("posted,confirm", [(False, False), (True, False), (True, True)])
def test_codex_button_requires_posted_confirmation(posted, confirm):
    script = HARNESS.split("(async () => {")[0].replace("posted: false", f"posted: {json.dumps(posted)}")
    script += f'''
let confirmations = 0;
context.window.confirm = text => {{
  if (!text.includes("Bài đã đăng, chỉ thay chữ trên web")) throw Error("missing warning");
  confirmations++;
  return {json.dumps(confirm)};
}};
button("Codex dịch").click();
console.log(JSON.stringify({{ confirmations, posted }}));
'''
    proc = subprocess.run([NODE, "-e", script, str(APP_JS), "ai", "true"],
                          capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["confirmations"] == int(posted)
    assert out["posted"] == ([] if posted and not confirm else [
        {"url": "/api/episodes/t11/posts/codex", "method": "POST",
         "body": {"clips": ["k03"], "include_posted": posted}}])
