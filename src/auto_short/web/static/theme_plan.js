/* TC2 phase C: the thematic planner card on Yêu thích. */
"use strict";
const ThemePlan = (() => {
  const { el, api, fmtDur, copyText } = Favorites;
  const $ = (id) => document.getElementById(id);
  const states = { draft: "nháp", approved: "đã duyệt", stale: "cần xem lại", invalid: "hỏng" };
  const jobs = { queued: "đang chờ", running: "đang chạy", done: "xong", failed: "lỗi", interrupted: "bị ngắt" };
  const drafts = new Map();
  let base = "", data = null, timer = null, loading = false, pending = false, refreshAgain = false;
  const active = (job) => !!(job && job.active);
  const jobText = (job) => job ? `${job.gpu_wait ? "đang chờ GPU / Ollama" : jobs[job.status] || job.status}${job.error ? ": " + job.error : ""}` : "";
  function say(text, error = false) {
    $("tp-msg").textContent = text;
    $("tp-msg").className = "small" + (error ? " error" : "");
  }
  const minutes = (seconds) => `${(seconds / 60).toFixed(1)} phút`;
  const outside = (total) => total < 1800 || total > 2400;
  function warning(total) {
    return outside(total) ? ` · ngoài 30–40 phút${total < 1800 ? ", thiếu " + minutes(1800 - total) : ""}` : "";
  }
  function button(text, fn, disabled = false) {
    const b = el("button", { class: "btn small", type: "button", text });
    b.disabled = disabled;
    b.addEventListener("click", fn);
    return b;
  }
  async function change(path, method, body, done) {
    if (pending) return;
    pending = true;
    say("");
    try {
      await api(base + path, { method, headers: { "Content-Type": "application/json" },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (done) done();
      say("Đã cập nhật.");
      await load();
    } catch (e) {
      say(e.status === 409 ? "đã có thay đổi khác, tải lại. " + e.message : e.message, true);
    } finally { pending = false; }
  }
  function clipLabel(clip) {
    const found = (data.clips_available || []).find((c) => c.id === clip.id);
    return `${found ? found.label : (clip.episode_id || clip.id) + " · " + (clip.clip || "")} · ${fmtDur(clip.duration)}`;
  }
  function proposal(p) {
    const clips = el("ol");
    for (const c of p.clips) clips.append(el("li", { text: clipLabel(c) }));
    return el("article", { class: "tp-plan" }, el("h4", { text: p.label }), el("p", { text: p.rationale }), clips,
      el("p", { class: "small", text: `${minutes(p.total_duration)}${p.shortfall_seconds ? " · thiếu " + minutes(p.shortfall_seconds) : ""}${p.dropped_for_length ? " · đã cắt bớt " + p.dropped_for_length + " clip" : ""}` }),
      button("Dùng chủ đề này", () => change("/theme-plans", "POST", { proposal_id: p.proposal_id })));
  }
  function planRow(plan) {
    const check = plan.check || { state: "invalid", problems: [] };
    const box = el("article", { class: "tp-plan" });
    const busy = active(plan.render_job);
    box.append(el("h4", { text: `${plan.title || plan.plan_id} · ${states[check.state] || check.state}` }));
    for (const why of check.problems || []) box.append(el("p", { class: "error small", text: why }));
    const path = "/theme-plans/" + encodeURIComponent(plan.plan_id);
    const remove = button("Xóa kế hoạch", () => {
      if (confirm("Xóa kế hoạch này?")) change(path, "DELETE", undefined, () => drafts.delete(plan.plan_id));
    }, busy);
    if (check.state === "invalid") { box.append(remove); return box; }

    let draft = drafts.get(plan.plan_id);
    if (!draft || (!draft.dirty && draft.revision !== plan.revision)) {
      draft = { revision: plan.revision, title: plan.title, clips: plan.clips.map((c) => ({ ...c })), dirty: false };
      drafts.set(plan.plan_id, draft);
    }
    if (draft.revision !== plan.revision) box.append(el("p", { class: "error small", text: "đã có thay đổi khác, tải lại trước khi lưu" }));
    const title = el("input", { type: "text", maxlength: "120", value: draft.title, "aria-label": "Tiêu đề kế hoạch" });
    title.disabled = busy;
    const rows = el("ol", { class: "fv-list" });
    const totalText = el("p", { class: "small" });
    const override = el("input", { type: "checkbox" });
    const overrideLabel = el("label", { class: "inline small" }, override, " Tôi xác nhận thời lượng ngoài 30–40 phút");
    const select = el("select", { "aria-label": "Thêm clip đã index" });
    const save = button("Lưu sửa", () => change(path, "PUT", {
      revision: draft.revision, title: draft.title, clip_ids: draft.clips.map((c) => c.id)
    }, () => drafts.delete(plan.plan_id)), busy);
    const approve = button("Duyệt", () => change(path + "/approve", "POST", {
      revision: plan.revision, duration_override: override.checked
    }, () => drafts.delete(plan.plan_id)));
    const render = button("Xuất video ngang", () => change(path + "/render", "POST"));
    function controls() {
      const total = draft.clips.reduce((a, c) => a + c.duration, 0);
      totalText.textContent = `${minutes(total)}${warning(total)}${draft.dirty ? " · chưa lưu" : ""}`;
      overrideLabel.hidden = !outside(total);
      approve.disabled = busy || draft.dirty || check.state !== "draft" || (outside(total) && !override.checked);
      render.disabled = busy || draft.dirty || check.state !== "approved";
      save.disabled = busy || !draft.clips.length;
    }
    function edit() { draft.dirty = true; override.checked = false; controls(); }
    function drawClips() {
      rows.replaceChildren();
      draft.clips.forEach((c, i) => {
        const row = el("li", { class: "fv-row" }, el("span", { class: "fv-main", text: `${i + 1}. ${clipLabel(c)}` }));
        const actions = el("span", { class: "fv-actions" });
        for (const [text, label, offset] of [["↑", "Đưa clip lên", -1], ["↓", "Đưa clip xuống", 1], ["✕", "Bỏ clip", 0]]) {
          const b = button(text, () => {
            if (offset) [draft.clips[i], draft.clips[i + offset]] = [draft.clips[i + offset], draft.clips[i]];
            else draft.clips.splice(i, 1);
            edit(); drawClips();
          }, busy || (offset < 0 && i === 0) || (offset > 0 && i === draft.clips.length - 1));
          b.setAttribute("aria-label", label + " " + (i + 1));
          actions.append(b);
        }
        row.append(actions); rows.append(row);
      });
      select.replaceChildren(el("option", { value: "", text: "Chọn clip đã index…" }));
      for (const c of data.clips_available || []) if (!draft.clips.some((x) => x.id === c.id)) {
        select.append(el("option", { value: c.id, text: `${c.label} · ${fmtDur(c.duration)}` }));
      }
      controls();
    }
    title.addEventListener("input", () => { draft.title = title.value; edit(); });
    override.addEventListener("change", controls);
    const add = button("Thêm clip", () => {
      const clip = (data.clips_available || []).find((c) => c.id === select.value);
      if (clip) { draft.clips.push({ ...clip }); edit(); drawClips(); }
    }, busy);
    select.disabled = busy;
    const reset = button("Tải lại bản đã lưu", () => { drafts.delete(plan.plan_id); renderPlans(); });
    box.append(title, rows, el("div", { class: "actions" }, select, add), totalText, overrideLabel,
      el("div", { class: "actions" }, save, reset, approve, render, remove),
      el("p", { class: "small" + (plan.render_job && plan.render_job.error ? " error" : ""), text: jobText(plan.render_job) }));
    if (plan.output) {
      const output = plan.output;
      const copy = button("Copy mô tả", async () => say(await copyText(output.description) ? "Đã copy mô tả." : "Không copy được.", false));
      box.append(el("div", { class: "actions" },
        el("a", { class: "btn small", href: output.download_url, download: output.download_name, text: "Tải về" }), copy,
        el("span", { class: "small", text: fmtDur(output.duration) })));
    }
    drawClips();
    return box;
  }
  function renderPlans() {
    // Keep focus/caret and the current editor while a status request finishes.
    const focused = document.activeElement;
    if ($("tp-plans").contains(focused) && focused.tagName === "INPUT" && focused.type === "text") return;
    $("tp-plans").replaceChildren(...data.plans.map(planRow));
  }
  function renderData() {
    const s = data.index_summary;
    $("tp-summary").textContent = `${s.usable} clip khai thị dùng được / ${s.unusable} không dùng được · ${s.source_missing} clip phải tải lại nguồn${s.common_reasons.length ? ". Lý do: " + s.common_reasons.map((r) => `${r.count} × ${r.reason}`).join("; ") : ""}`;
    $("tp-job").textContent = jobText(data.generate_job);
    $("tp-generate").disabled = active(data.generate_job);
    $("tp-proposals").replaceChildren();
    const doc = data.proposals;
    if (doc) {
      for (const key of ["ai_error", "shortfall"]) if (doc[key]) $("tp-proposals").append(el("p", { class: "error small", text: doc[key] }));
      for (const p of doc.proposals || []) $("tp-proposals").append(proposal(p));
      if ((doc.rejected_themes || []).length) {
        const details = el("details", {}, el("summary", { text: `Chủ đề bị loại (${doc.rejected_themes.length})` }));
        for (const r of doc.rejected_themes) details.append(el("p", { class: "small", text: `#${r.position + 1}: ${r.reason}` }));
        $("tp-proposals").append(details);
      }
    }
    renderPlans();
  }
  async function load() {
    if (loading) { refreshAgain = true; return; }
    loading = true;
    clearTimeout(timer);
    try {
      data = await api(base + "/theme-plan");
      renderData();
    } catch (e) {
      say(e.message, true);
      $("tp-summary").textContent = "Không tải được trạng thái mới. Bấm Tải lại trạng thái.";
      $("tp-generate").disabled = false;
    } finally {
      loading = false;
      if (refreshAgain) { refreshAgain = false; load(); }
      else if (data && (active(data.generate_job) || data.plans.some((p) => active(p.render_job)))) timer = setTimeout(load, 5000);
    }
  }
  function init() {
    const pid = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
    base = "/api/playlists/" + encodeURIComponent(pid);
    $("tp-generate").addEventListener("click", () => change("/theme-plan/generate", "POST"));
    $("tp-refresh").addEventListener("click", load);
    $("tp-plans").addEventListener("focusout", () => setTimeout(() => { if (data) renderPlans(); }, 0));
    window.addEventListener("favorites-changed", load);
    load();
  }
  return { init };
})();
