/* TC2.3: one-click thematic compilations on Yêu thích. */
"use strict";
const ThemePlan = (() => {
  const { el, api, fmtDur, copyText, player, busy: playing, onIdle, setVideoCount } = Favorites;
  const $ = (id) => document.getElementById(id);
  const jobs = { queued: "đang chờ", running: "đang ghép", done: "xong", failed: "lỗi", interrupted: "bị ngắt" };
  const REASONS = {
    "not a khai thi episode": "Short thường, không phải khai thị",
    "kept source unreconstructable": "khai thị đã lưu không dựng lại được nguồn",
    "rejected": "clip đã bị loại khi duyệt",
    "episode outside selected playlist": "tập không thuộc bộ kinh này",
  };
  const drafts = new Map(), choices = new Map(), opened = new Map(), inputs = new Set();
  let base = "", data = null, timer = null, loading = false, pending = false, refreshAgain = false, plansDeferred = false;
  const active = (job) => !!(job && job.active);
  const jobText = (job) => job ? `${job.yt_wait ? "đang chờ YouTube" : job.gpu_wait ? "đang chờ GPU / Ollama" : jobs[job.status] || job.status}${job.summary ? " · " + job.summary : ""}${job.error ? ": " + job.error : ""}` : "";
  function sourceStatus(plan) {
    const s = plan && plan.sources;
    return el("p", { class: "small muted", text: s ? `Video gốc: ${s.ready} / ${s.total} sẵn sàng${s.store ? " (3090: " + s.store + ")" : ""}${s.youtube ? " · " + s.youtube + " cần tải YouTube" : ""}` : "" });
  }
  function say(text, error = false) {
    $("tp-msg").textContent = text;
    $("tp-msg").className = "small" + (error ? " error" : "");
  }
  const minutes = (seconds) => `${(seconds / 60).toFixed(1).replace(".", ",")} phút`;
  const duration = (total) => minutes(total) + (total < 1800 ? " — ngắn hơn 30 phút" : total > 2400 ? " — dài hơn 40 phút" : "");
  function control(node) { inputs.add(node); return node; }
  function button(text, fn, disabled = false) {
    const b = control(el("button", { class: "btn small", type: "button", text }));
    b.disabled = disabled;
    b.addEventListener("click", () => { if (!pending && !b.disabled) return fn(); });
    return b;
  }
  function details(key, label, ...children) {
    const node = el("details", { class: "tp-details" }, el("summary", { text: label }), ...children);
    node.open = !!opened.get(key);
    node.addEventListener("toggle", () => opened.set(key, node.open));
    return node;
  }
  const request = (path, method, body) => api(base + path, { method, headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  async function perform(work) {
    if (pending) return;
    pending = true;
    clearTimeout(timer);
    const locked = new Map([...inputs, $("tp-generate")].map((node) => [node, node.disabled]));
    for (const node of locked.keys()) node.disabled = true;
    say("");
    let step = "Tải trạng thái";
    const at = (name) => { step = name; say(name + "…"); };
    try { await work(at); }
    catch (e) { say(`${step}: ${e.status === 409 ? "đã có thay đổi khác, tải lại. " : ""}${e.message}`, true); }
    finally {
      // Refresh partial successes too, so retries resume the saved plan/revision.
      await load();
      for (const [node, disabled] of locked) node.disabled = disabled;
      pending = false;
      if (data) renderData();
    }
  }
  function clipLabel(clip) {
    const found = (data.clips_available || []).find((c) => c.id === clip.id);
    return `${found ? found.label : (clip.episode_id || clip.id) + " · " + (clip.clip || "")} · ${fmtDur(clip.duration)}`;
  }
  function remember(plan) {
    const i = data.plans.findIndex((p) => p.plan_id === plan.plan_id);
    if (i < 0) data.plans.push(plan);
    else data.plans[i] = plan;
    return plan;
  }
  function merge(proposed, chosenTitle, planId = null, edit = null) {
    return perform(async (at) => {
      // Read persisted provenance before creating: repeat clicks and reloads reuse the plan.
      at("Tải trạng thái");
      data = await api(base + "/theme-plan");
      let plan = planId ? data.plans.find((p) => p.plan_id === planId)
        : data.plans.find((p) => p.proposal && p.proposal.proposal_id === proposed.proposal_id);
      if (planId && !plan) throw new Error("Video này đã bị xóa. Tải lại trạng thái.");
      if (plan && ["stale", "invalid"].includes((plan.check || {}).state)) {
        throw new Error("Nội dung clip đã đổi hoặc không dùng được. Bấm Gợi ý lại rồi chọn chủ đề mới.");
      }
      if (plan && active(plan.render_job)) { say("Video đang trong hàng đợi ghép."); return; }
      if (!plan) {
        at("Tạo video từ chủ đề");
        plan = remember(await request("/theme-plans", "POST", { proposal_id: proposed.proposal_id }));
      }
      const path = "/theme-plans/" + encodeURIComponent(plan.plan_id);
      const title = edit ? edit.title : (planId ? plan.title : chosenTitle);
      const clips = edit ? edit.clips : plan.clips;
      if (edit && edit.revision !== plan.revision) throw new Error("đã có thay đổi khác, tải lại bản đã lưu trước khi ghép.");
      const changed = title !== plan.title || clips.map((c) => c.id).join("|") !== plan.clips.map((c) => c.id).join("|");
      if (changed) {
        at("Lưu tiêu đề và danh sách clip");
        plan = remember(await request(path, "PUT", { revision: plan.revision, title, clip_ids: clips.map((c) => c.id) }));
        if (edit) Object.assign(edit, { revision: plan.revision, title: plan.title,
          clips: plan.clips.map((c) => ({ ...c })), dirty: false });
      }
      if (changed || !plan.check || plan.check.state !== "approved") {
        at("Duyệt video");
        plan = remember(await request(path + "/approve", "POST", { revision: plan.revision, duration_override: true }));
      }
      at("Xếp hàng ghép video");
      await request(path + "/render", "POST");
      drafts.delete(plan.plan_id);
      say("Đã xếp vào hàng đợi ghép. Xem tiến độ ở tab Video đã ghép.");
    });
  }
  function proposal(p) {
    const existing = data.plans.find((plan) => plan.proposal && plan.proposal.proposal_id === p.proposal_id);
    let choice = choices.get(p.proposal_id);
    if (!choice) { choice = { title: existing ? existing.title : (p.titles || [])[0] || p.label }; choices.set(p.proposal_id, choice); }
    const title = control(el("input", { type: "text", maxlength: "120", value: choice.title, "aria-label": "Sửa tiêu đề video" }));
    const options = el("div", { class: "tp-titles", role: "group", "aria-label": "Chọn tiêu đề video" });
    const radios = [];
    for (const [i, text] of (p.titles || []).entries()) {
      const radio = control(el("input", { type: "radio", name: "tp-title-" + p.proposal_id, value: text }));
      radio.checked = choice.title === text;
      radios.push(radio);
      radio.addEventListener("change", () => { choice.title = text; title.value = text; drawActions(); });
      options.append(el("label", { class: "tp-title-option" }, radio, el("span", { text: (i === 0 ? "★ " : "") + text })));
    }
    title.addEventListener("input", () => { choice.title = title.value; for (const radio of radios) radio.checked = radio.value === title.value; drawActions(); });
    const clips = el("ol", { class: "tp-clip-preview" });
    for (const c of p.clips) clips.append(el("li", { text: clipLabel(c) }));
    const actions = el("div", { class: "actions" });
    function drawActions() {
      for (const node of actions.children) inputs.delete(node);
      actions.replaceChildren();
      const job = existing && existing.render_job;
      const busy = active(job);
      const failed = job && ["failed", "interrupted"].includes(job.status);
      const done = existing && existing.check && existing.check.state === "approved" && existing.output && existing.output.download_url;
      if (done && !busy && !failed) {
        actions.append(el("span", { class: "small", role: "status", text: "✓ Đã ghép · " + minutes(existing.total_duration) }));
        actions.append(button("Xem video", () => {
          Favorites.showTab("videos");
          Favorites.scrollToVideo(existing.plan_id);
        }));
        if (choice.title === existing.title) return;
      }
      if (failed && !busy) actions.append(el("span", { class: "small error", role: "status", text: jobText(job) }));
      const go = button(busy ? "Đang ghép…" : failed ? "Ghép lại" : done ? "Ghép lại với tiêu đề này" : "Ghép video", () => {
        go.textContent = "Đang ghép…";
        return merge(p, choice.title);
      }, busy);
      go.className += " primary";
      actions.append(go);
    }
    drawActions();
    return el("article", { class: "tp-plan" }, el("h4", { text: (p.titles || [])[0] || p.label }), options, title,
      el("p", { class: "small muted", text: `${p.clips.length} clip · ${duration(p.total_duration)} · ${p.label} · ${p.rationale}${p.dropped_for_length ? " · đã bớt " + p.dropped_for_length + " clip cho vừa thời lượng" : ""}` }),
      sourceStatus(existing),
      details("proposal-" + p.proposal_id, `Xem ${p.clips.length} khai thị`, clips), actions);
  }
  function planRow(plan) {
    const check = plan.check || { state: "invalid", problems: [] };
    const busy = active(plan.render_job), broken = ["stale", "invalid"].includes(check.state);
    const path = "/theme-plans/" + encodeURIComponent(plan.plan_id);
    const output = plan.output && plan.output.download_url ? plan.output : null;
    const failed = plan.render_job && ["failed", "interrupted"].includes(plan.render_job.status);
    const box = el("article", { class: "tp-plan vd-card", id: "vd-plan-" + plan.plan_id },
      output ? player(output.download_url + "?inline=1", "vd-landscape") : null,
      el("h4", { text: plan.title || plan.plan_id }));
    const editDetails = details("plan-" + plan.plan_id, "Sửa video & thumbnail");
    const status = broken ? "Nội dung clip đã đổi hoặc không dùng được — hãy Gợi ý lại."
      : jobText(plan.render_job) || (plan.output ? "xong" : "Chưa ghép — bấm Ghép lại để tiếp tục.");
    box.append(el("p", { class: "small" + (broken || (plan.render_job && plan.render_job.error) ? " error" : ""), role: "status", text: status }));
    if (String(plan.render_job?.error || "").includes("Bộ kinh chưa có ảnh bìa khai thị")) box.append(
      el("a", { href: base.replace(/^\/api/, "") + "/thumbs", text: "Thiết kế bìa khai thị" }));
    box.append(sourceStatus(plan));
    for (const why of check.problems || []) box.append(el("p", { class: "error small", text: why }));
    const actions = el("div", { class: "actions" });
    if (output) {
      actions.append(el("a", { class: "btn small", href: output.download_url, download: output.download_name || "", text: "Tải video" }),
        button("Copy tiêu đề", async () => say(await copyText((output.download_name || "").replace(/\.mp4$/, "")) ? "Đã copy tiêu đề." : "Không copy được.")),
        button("Copy mô tả", async () => say(await copyText(output.description || "") ? "Đã copy mô tả." : "Không copy được.")));
      if (Favorites.thumbnailBlock) editDetails.append(Favorites.thumbnailBlock(base + path + "/thumbs",
        output.intro ? { shape: "landscape", intro: output.intro } : null,
        () => opened.set("plan-" + plan.plan_id, true)));
    }
    if (broken) actions.append(button("Gợi ý lại", generate, busy || active(data.generate_job)));
    else {
      let draft = drafts.get(plan.plan_id);
      if (!draft || (!draft.dirty && draft.revision !== plan.revision)) {
        draft = { revision: plan.revision, title: plan.title, clips: plan.clips.map((c) => ({ ...c })), dirty: false };
        drafts.set(plan.plan_id, draft);
      }
      const title = control(el("input", { type: "text", maxlength: "120", value: draft.title, "aria-label": "Tiêu đề video đã ghép" }));
      title.disabled = busy;
      const rows = el("ol", { class: "fv-list" }), total = el("p", { class: "small" });
      const select = control(el("select", { "aria-label": "Thêm clip đã index" }));
      select.disabled = busy;
      const retry = button("Ghép lại", () => merge(null, null, plan.plan_id, draft), busy);
      function update() {
        total.textContent = `${draft.clips.length} clip · ${duration(draft.clips.reduce((a, c) => a + c.duration, 0))}${draft.dirty ? " · chưa lưu" : ""}${draft.revision !== plan.revision ? " · đã có thay đổi khác, tải lại bản đã lưu" : ""}`;
        retry.disabled = busy || !draft.clips.length || !draft.title.trim() || draft.revision !== plan.revision;
      }
      function edit() { draft.dirty = true; update(); }
      function drawClips() {
        rows.replaceChildren();
        draft.clips.forEach((c, i) => {
          const row = el("li", { class: "fv-row" }, el("span", { class: "fv-main", text: clipLabel(c) }));
          const moves = el("span", { class: "fv-actions" });
          for (const [text, label, offset] of [["↑", "Đưa clip lên", -1], ["↓", "Đưa clip xuống", 1], ["✕", "Bỏ clip", 0]]) {
            const b = button(text, () => {
              if (offset) [draft.clips[i], draft.clips[i + offset]] = [draft.clips[i + offset], draft.clips[i]];
              else draft.clips.splice(i, 1);
              edit(); drawClips();
            }, busy || (offset < 0 && i === 0) || (offset > 0 && i === draft.clips.length - 1));
            b.setAttribute("aria-label", label + " " + (i + 1));
            moves.append(b);
          }
          row.append(moves); rows.append(row);
        });
        select.replaceChildren(el("option", { value: "", text: "Chọn clip đã index…" }));
        for (const c of data.clips_available || []) if (!draft.clips.some((x) => x.id === c.id)) {
          select.append(el("option", { value: c.id, text: `${c.label} · ${fmtDur(c.duration)}` }));
        }
        update();
      }
      title.addEventListener("input", () => { draft.title = title.value; edit(); });
      const add = button("Thêm clip", () => {
        const clip = (data.clips_available || []).find((c) => c.id === select.value);
        if (clip) { draft.clips.push({ ...clip }); edit(); drawClips(); }
      }, busy);
      const reset = button("Tải lại bản đã lưu", () => { drafts.delete(plan.plan_id); renderData(); }, busy);
      editDetails.append(title, rows, el("div", { class: "actions" }, select, add), total,
        el("div", { class: "actions" }, reset));
      if (!output || failed) actions.append(retry);
      else editDetails.append(el("div", { class: "actions" }, retry));
      drawClips();
    }
    actions.append(button("Xóa", () => {
      if (!confirm("Xóa video ghép này?")) return;
      return perform(async (at) => { at("Xóa video"); Favorites.pauseAll(); await request(path, "DELETE"); drafts.delete(plan.plan_id); say("Đã xóa."); });
    }, busy));
    box.append(actions);
    if (output || plan.published) box.append(Favorites.publishBox(plan, "theme", plan.plan_id, (result) => {
      const current = data.plans.find((item) => item.plan_id === plan.plan_id);
      if (current) Object.assign(current, result);
    }));
    if (!broken || output) box.append(editDetails);
    return box;
  }
  function renderData() {
    const s = data.index_summary;
    const parts = [`${s.usable} clip sẵn sàng`];
    if (s.pending) parts.push(`${s.pending} clip khai thị chờ AI đọc nội dung (bấm "AI gợi ý chủ đề")`);
    if (s.unusable) {
      const why = s.common_reasons.map((r) => `${r.count} × ${REASONS[r.reason] || r.reason}`).join("; ");
      parts.push(`${s.unusable} không dùng cho ghép chủ đề${why ? ` (${why})` : ""}`);
    }
    if (s.source_missing) parts.push(`${s.source_missing} clip phải tải lại nguồn khi ghép`);
    $("tp-summary").textContent = parts.join(" · ");
    $("tp-job").textContent = jobText(data.generate_job);
    $("tp-generate").disabled = active(data.generate_job);
    setVideoCount("plans", data.plans.length);
    // Preserve focus/caret independently in each pane. Keep controls in a deferred pane registered.
    const focused = document.activeElement;
    const editing = (root) => focused && focused.tagName === "INPUT" && focused.type === "text" && root.contains(focused);
    if (!editing($("tp-proposals"))) renderProposals();
    plansDeferred = playing() || editing($("tp-plans"));
    if (!plansDeferred) renderPlans();
  }
  function forgetControls(root) {
    for (const node of inputs) if (root.contains(node)) inputs.delete(node);
  }
  function renderProposals() {
    forgetControls($("tp-proposals"));
    $("tp-proposals").replaceChildren();
    const doc = data.proposals;
    if (doc) {
      for (const key of ["ai_error", "shortfall"]) if (doc[key]) $("tp-proposals").append(el("p", { class: "error small", text: doc[key] }));
      for (const p of doc.proposals || []) $("tp-proposals").append(proposal(p));
      if ((doc.rejected_themes || []).length) {
        const rejected = details("rejected", `Chủ đề bị loại (${doc.rejected_themes.length})`);
        for (const r of doc.rejected_themes) rejected.append(el("p", { class: "small", text: `#${r.position + 1}: ${r.reason}` }));
        $("tp-proposals").append(rejected);
      }
    }
  }
  function renderPlans() {
    forgetControls($("tp-plans"));
    $("tp-plans").replaceChildren(...(data.plans.length ? data.plans.map(planRow) : [el("p", { class: "muted small", text: "Chưa có video ghép theo chủ đề." })]));
  }
  async function load() {
    if (loading) { refreshAgain = true; return; }
    loading = true;
    clearTimeout(timer);
    try {
      data = await api(base + "/theme-plan");
      if (!pending) renderData();
    } catch (e) {
      if (!pending) say(e.message, true);
      $("tp-summary").textContent = "Không tải được trạng thái mới. Bấm Tải lại trạng thái.";
      $("tp-generate").disabled = false;
    } finally {
      loading = false;
      if (refreshAgain) { refreshAgain = false; load(); }
      else if (data && (active(data.generate_job) || data.plans.some((p) => active(p.render_job)))) timer = setTimeout(load, 5000);
    }
  }
  function generate() {
    return perform(async (at) => { at("AI gợi ý chủ đề"); await request("/theme-plan/generate", "POST"); say("Đã yêu cầu AI gợi ý chủ đề."); });
  }
  function init() {
    const pid = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
    base = "/api/playlists/" + encodeURIComponent(pid);
    $("tp-generate").addEventListener("click", generate);
    $("tp-refresh").addEventListener("click", load);
    for (const id of ["tp-plans", "tp-proposals"]) $(id).addEventListener("focusout", () => setTimeout(() => { if (data && !pending) renderData(); }, 0));
    onIdle(() => { if (plansDeferred && data && !pending) renderData(); });
    window.addEventListener("favorites-changed", load);
    load();
  }
  return { init };
})();
