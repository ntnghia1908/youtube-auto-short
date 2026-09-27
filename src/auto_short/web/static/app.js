/* Auto Short web UI (CP8.3; CP8.5 delete / restore, "Đã đăng", episode delete). Plain JS, no build step. */
"use strict";

const AutoShort = (() => {
  const STAGE_LABELS = {
    ingest: "Tải video",
    transcript: "Phụ đề",
    analysis: "Phân tích cảnh / khoảng lặng",
    selection: "Chọn clip (AI)",
    titling: "Đặt tiêu đề (AI)",
    render: "Dựng Short",
  };
  const STATUS_LABELS = {
    pending: "chờ", running: "đang chạy", done: "xong", failed: "lỗi", stale: "cần chạy lại",
    queued: "đang đợi", interrupted: "bị ngắt",
  };
  const TITLE_SOURCE_LABELS = { ai: "AI", manual: "sửa tay", alternative: "phương án AI khác" };
  const POLL_MS = 2500;

  const $ = (sel) => document.querySelector(sel);

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children) if (c !== null && c !== undefined) node.append(c);
    return node;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, { credentials: "same-origin", ...options });
    if (res.status === 401) {
      location.href = "/login?next=" + encodeURIComponent(location.pathname);
      throw new Error("chưa đăng nhập");
    }
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      let msg = data && data.detail;
      if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
      throw new Error(msg || `HTTP ${res.status}`);
    }
    return data;
  }

  function fmtSeconds(s) {
    if (s === null || s === undefined) return "";
    s = Math.round(s);
    const m = Math.floor(s / 60);
    return m ? `${m} ph ${String(s % 60).padStart(2, "0")} s` : `${s} s`;
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString("vi-VN");
  }

  function jobActive(job) { return job && (job.status === "queued" || job.status === "running"); }

  async function submitUrl(url, series, episode) {
    return api("/api/episodes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, series: series || null, episode: episode || null }),
    });
  }

  // --- index page -------------------------------------------------------------------------------

  function initIndex() {
    const form = $("#submit-form"), btn = $("#submit-btn"), err = $("#submit-error");
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      err.hidden = true;
      btn.disabled = true;
      btn.textContent = "Đang kiểm tra…";
      try {
        const data = await submitUrl($("#url").value, $("#series").value.trim(), $("#episode").value.trim());
        location.href = "/episodes/" + encodeURIComponent(data.episode_id);
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
      } finally {
        btn.disabled = false;
        btn.textContent = "Bắt đầu";
      }
    });
    document.querySelectorAll("#ep-filters [data-filter]").forEach((b) => b.addEventListener("click", () => {
      epFilter = b.dataset.filter;
      applyEpisodeFilter();
    }));
    loadEpisodes();
  }

  // Episode list filter (CP8.5 X4): publish_group from the API ("todo" | "done" | null).
  let epFilter = "all";
  let episodeItems = [];

  function applyEpisodeFilter() {
    const counts = { all: episodeItems.length, todo: 0, done: 0 };
    for (const e of episodeItems) if (e.publish_group) counts[e.publish_group] += 1;
    document.querySelectorAll("#ep-filters [data-filter]").forEach((b) => {
      b.classList.toggle("active", b.dataset.filter === epFilter);
      b.querySelector(".n").textContent = counts[b.dataset.filter];
    });
    $("#ep-filters").hidden = !episodeItems.length;
    document.querySelectorAll("#episodes li[data-group]").forEach((li) => {
      li.hidden = epFilter !== "all" && li.dataset.group !== epFilter;
    });
  }

  async function loadEpisodes() {
    const list = $("#episodes");
    let data;
    try { data = await api("/api/episodes"); } catch (e) {
      list.replaceChildren(el("li", { class: "error", text: e.message }));
      return;
    }
    episodeItems = data.episodes;
    if (!data.episodes.length) {
      list.replaceChildren(el("li", { class: "muted", text: "Chưa có video nào." }));
      applyEpisodeFilter();
      return;
    }
    let active = false;
    list.replaceChildren(...data.episodes.map((e) => {
      let state;
      if (jobActive(e.job)) {
        active = true;
        state = e.job.status === "queued" ? "đang đợi" : `đang chạy: ${STAGE_LABELS[e.job.stage] || e.job.stage || ""}`;
      } else if (e.failed) state = `lỗi ở ${STAGE_LABELS[e.failed] || e.failed}`;
      else if (e.running) state = `dừng giữa chừng ở ${STAGE_LABELS[e.running] || e.running}`;
      else if (e.stages_done === e.stages_total) state = `${e.shorts} Shorts · đã đăng ${e.published || 0}/${e.shorts}`;
      else state = `${e.stages_done}/${e.stages_total} bước`;
      return el("li", { "data-group": e.publish_group || "none" },
        el("a", { href: "/episodes/" + encodeURIComponent(e.id) },
          el("span", { class: "ep-name", text: e.title || e.id }),
          el("span", { class: "ep-state muted", text: `${e.id} · ${state}` })));
    }));
    applyEpisodeFilter();
    if (active) setTimeout(loadEpisodes, 5000);
  }

  // --- episode page -----------------------------------------------------------------------------

  let episodeId = null;
  let shortsKey = null;
  let pollTimer = null;

  function initEpisode() {
    episodeId = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
    $("#resubmit").addEventListener("click", resubmit);
    $("#delete-episode").addEventListener("click", deleteEpisode);
    document.querySelectorAll("#filters [data-filter]").forEach((b) => b.addEventListener("click", () => {
      filter = b.dataset.filter;
      applyFilter();
    }));
    $("#show-deleted").addEventListener("click", () => { showDeleted = !showDeleted; applyFilter(); });
    refreshEpisode();
  }

  let lastData = null;

  async function deleteEpisode() {
    const d = lastData || {};
    const name = d.title || episodeId;
    const ok = confirm(`Xóa toàn bộ tập "${name}" (${episodeId})?\n\n` +
      "Sẽ xóa video nguồn đã tải, mọi Short và dữ liệu xử lý của tập này. " +
      "KHÔNG khôi phục được. (Gửi lại link sau đó = chạy lại từ đầu, AI có thể chọn clip / tiêu đề khác.)");
    if (!ok) return;
    const btn = $("#delete-episode");
    btn.disabled = true;
    try {
      await api("/api/episodes/" + encodeURIComponent(episodeId), { method: "DELETE" });
      location.href = "/";
    } catch (e) {
      setJobStatus(`Không xóa được tập: ${e.message}`, "error");
      btn.disabled = false;
    }
  }

  async function resubmit() {
    const btn = $("#resubmit");
    btn.disabled = true;
    try {
      await submitUrl(btn.dataset.url);
      refreshEpisode();
    } catch (e) {
      setJobStatus(`Không chạy được: ${e.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  }

  function setJobStatus(text, cls) {
    const box = $("#job-status");
    box.className = "job-status " + (cls || "");
    box.textContent = text;
  }

  async function refreshEpisode() {
    clearTimeout(pollTimer);
    let data;
    try {
      data = await api("/api/episodes/" + encodeURIComponent(episodeId));
    } catch (e) {
      setJobStatus(e.message, "error");
      pollTimer = setTimeout(refreshEpisode, POLL_MS * 4);
      return;
    }
    renderEpisode(data);
    const running = jobActive(data.job) || data.stages.some((s) => s.status === "running");
    if (running) pollTimer = setTimeout(refreshEpisode, POLL_MS);
  }

  function renderEpisode(d) {
    document.title = `${d.title || d.id} — Auto Short`;
    $("#ep-title").textContent = d.title || d.id;
    const meta = [d.id];
    if (d.channel) meta.push(d.channel);
    if (d.duration) meta.push(fmtSeconds(d.duration));
    $("#ep-meta").textContent = meta.join(" · ");

    const job = d.job;
    const timings = {};
    if (job) for (const s of job.stages) timings[s.stage] = s;
    if (jobActive(job)) {
      if (job.status === "queued") setJobStatus(`Đang đợi trong hàng (vị trí ${job.queue_position || "?"})`, "busy");
      else setJobStatus(`Đang chạy: ${STAGE_LABELS[job.stage] || job.stage || "…"} (bắt đầu ${fmtTime(job.started_at)})`, "busy");
    } else if (job && job.status === "done") setJobStatus(`Xong: ${job.summary || ""} (${fmtTime(job.finished_at)})`, "ok");
    else if (job && job.status === "failed") setJobStatus(`Lỗi: ${job.error}`, "error");
    else if (job && job.status === "interrupted") setJobStatus(`Bị ngắt (${job.error}). Bấm chạy tiếp để tiếp tục.`, "error");
    else setJobStatus("", "");

    const stages = d.stages.length ? d.stages : Object.keys(STAGE_LABELS).map((s) => ({ stage: s, status: "pending" }));
    $("#stages").replaceChildren(...stages.map((s) => {
      let status = s.status;
      if (jobActive(job) && job.stage === s.stage && status !== "running") status = "running";
      const t = timings[s.stage];
      const extra = t ? (t.ran ? fmtSeconds(t.seconds) : "bỏ qua (đã có)") : "";
      return el("li", { class: "stage " + status },
        el("span", { class: "stage-name", text: STAGE_LABELS[s.stage] || s.stage }),
        el("span", { class: "stage-status", text: STATUS_LABELS[status] || status }),
        extra ? el("span", { class: "stage-time muted", text: extra }) : null,
        s.error && status === "failed" ? el("div", { class: "stage-error", text: s.error }) : null);
    }));

    const logs = (job && job.logs) || [];
    const pre = $("#log");
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
    pre.textContent = logs.length ? logs.join("\n") : "(chưa có nhật ký trong phiên server này)";
    if (atBottom) pre.scrollTop = pre.scrollHeight;
    if (jobActive(job) || (job && job.status === "failed")) $("#log-box").open = true;

    const rb = $("#resubmit");
    rb.hidden = !d.source_url || jobActive(job);
    rb.dataset.url = d.source_url || "";
    const del = $("#delete-episode");
    del.hidden = !d.stages.length;
    del.disabled = jobActive(job);
    $("#delete-note").hidden = !jobActive(job) || !d.stages.length;

    lastData = d;
    renderShorts(d);
    setEditsLocked(jobActive(job));
  }

  // Shorts grid: a card is rebuilt only when its own state changes, in place, so polling never stops a playing
  // video or wipes a title being typed in another card.
  const cards = new Map(); // clip_id -> {key, node}
  let editsLocked = false;
  let maxChars = 60;
  let filter = "all"; // all | todo | done ("Chưa đăng" / "Đã đăng")
  let showDeleted = false;

  function cardKey(s) {
    return JSON.stringify([s.status, s.sha256, s.title, s.pending_title, s.override, s.rendering, s.editable,
      s.alternatives.length, s.deleted, s.rejected, s.published, s.published_stale, s.download_name]);
  }

  // Filter + "Short đã xóa" toggle only hide / show cards (no rebuild: a playing video keeps playing).
  function applyFilter() {
    const shorts = (lastData && lastData.shorts) || [];
    const live = shorts.filter((s) => !s.deleted);
    const done = live.filter((s) => s.status === "rendered" && s.published).length;
    const rendered = live.filter((s) => s.status === "rendered").length;
    const counts = { all: live.length, todo: rendered - done, done };
    document.querySelectorAll("#filters [data-filter]").forEach((b) => {
      b.classList.toggle("active", b.dataset.filter === filter);
      b.querySelector(".n").textContent = counts[b.dataset.filter];
    });
    $("#filters").hidden = !shorts.length;
    $("#published-count").textContent = rendered ? `Đã đăng ${done}/${rendered}` : "";
    const deleted = shorts.filter((s) => s.deleted).length;
    const sd = $("#show-deleted");
    sd.hidden = !deleted;
    sd.textContent = showDeleted ? `Ẩn Short đã xóa (${deleted})` : `Hiện Short đã xóa (${deleted})`;
    for (const s of shorts) {
      const entry = cards.get(s.clip_id);
      if (!entry) continue;
      let visible;
      if (s.deleted) visible = showDeleted;
      else if (filter === "todo") visible = s.status === "rendered" && !s.published;
      else if (filter === "done") visible = s.status === "rendered" && s.published;
      else visible = true;
      entry.node.hidden = !visible;
    }
  }

  function renderShorts(d) {
    maxChars = d.max_title_chars || 60;
    const rendered = d.shorts.filter((s) => s.status === "rendered");
    $("#shorts-count").textContent = d.shorts.length ? `(${rendered.length})` : "";
    const zip = $("#zip");
    zip.hidden = !d.zip_url;
    if (d.zip_url) { zip.href = d.zip_url; zip.setAttribute("download", d.zip_name || ""); }
    $("#header-lines").textContent = d.header ? "Header: " + d.header.join(" / ") : "";
    const notes = [];
    if (d.shorts.length && d.render_status !== "done") {
      notes.push(`Đang hiển thị bản dựng trước (bước Dựng Short: ${STATUS_LABELS[d.render_status] || d.render_status}).`);
    }
    if (d.titles_error) notes.push(`Chưa sửa title được: ${d.titles_error}`);
    if (d.publish_error) notes.push(`Không đọc được trạng thái "Đã đăng": ${d.publish_error}`);
    for (const w of d.titles_ignored || []) notes.push(w);
    $("#shorts-note").textContent = notes.join(" ");
    $("#shorts-note").hidden = !notes.length;

    const grid = $("#shorts");
    if (!d.shorts.length) {
      cards.clear();
      grid.replaceChildren(el("p", { class: "muted", text: "Chưa có Short (bước Dựng Short chưa xong)." }));
      return;
    }
    const ids = d.shorts.map((s) => s.clip_id);
    const sameSet = ids.length === cards.size && ids.every((id, i) => cards.has(id) && grid.children[i] === cards.get(id).node);
    if (!sameSet) {
      cards.clear();
      for (const s of d.shorts) cards.set(s.clip_id, { key: cardKey(s), node: shortCard(s) });
      grid.replaceChildren(...ids.map((id) => cards.get(id).node));
      applyFilter();
      return;
    }
    for (const s of d.shorts) {
      const entry = cards.get(s.clip_id), key = cardKey(s);
      if (entry.key === key) continue;
      const node = shortCard(s);
      entry.node.replaceWith(node);
      cards.set(s.clip_id, { key, node });
    }
    applyFilter();
  }

  function setEditsLocked(locked) {
    editsLocked = locked;
    document.querySelectorAll(".short .needs-idle").forEach((b) => { b.disabled = locked || b.dataset.invalid === "1"; });
    document.querySelectorAll(".short .lock-note").forEach((n) => { n.hidden = !locked; });
  }

  // One card per Short; ``.title-edit`` holds the title editor (CP8.2 functions via the API).
  function shortCard(s) {
    const title = s.title || {};
    const card = el("article", { class: "short" + (s.rendering ? " rendering" : ""), "data-clip": s.clip_id });
    const media = el("div", { class: "short-media" });
    if (s.status === "rendered") {
      media.append(el("video", { controls: true, preload: "metadata", playsinline: true, src: s.video_url }));
    } else if (s.deleted) {
      card.classList.add("deleted");
      media.append(el("div", { class: "short-missing", text: "Đã xóa (file đã bỏ; khôi phục = dựng lại)" }));
    } else {
      media.append(el("div", { class: "short-missing", text: `Bỏ qua: ${s.skip_reason || s.status}` }));
    }
    if (s.rendering) {
      const busy = s.rejected && !s.deleted ? "đang xóa…" : (!s.rejected && s.deleted ? "đang khôi phục…" : "đang render…");
      media.append(el("div", { class: "rendering-badge", text: busy }));
    }
    card.append(media);
    const body = el("div", { class: "short-body" },
      el("div", { class: "short-head" },
        el("span", { class: "clip-id", text: s.clip_id }),
        title.origin ? el("span", { class: "badge " + title.origin, text: TITLE_SOURCE_LABELS[title.origin] || title.origin }) : null,
        el("span", { class: "muted small", text: fmtSeconds(s.duration) })),
      el("p", { class: "short-title", text: title.text || "(không có tiêu đề)" }),
      s.pending_title ? el("p", { class: "pending small", text: s.pending_title.text
        ? `Tiêu đề mới (${TITLE_SOURCE_LABELS[s.pending_title.origin] || s.pending_title.origin}), chưa render: ${s.pending_title.text}`
        : "Sẽ bỏ qua ở lần render tới (không có tiêu đề)" }) : null,
      s.status === "rendered" || s.published ? publishBox(s) : null,
      el("div", { class: "short-actions" },
        s.download_url ? el("a", { class: "btn", href: s.download_url, download: s.download_name || "", text: "Tải về" }) : null,
        s.editable ? deleteButton(s) : null),
      s.editable && !s.deleted ? titleEditor(s) : el("div", { class: "title-edit", hidden: true }));
    card.append(body);
    return card;
  }

  // "Đã đăng" (X4): user state only, no job, allowed while a job runs; updated in place (no card rebuild).
  function publishBox(s) {
    const box = el("div", { class: "publish" });
    const input = el("input", { type: "checkbox", checked: s.published });
    input.disabled = s.status !== "rendered" && !s.published;
    const label = el("label", { class: "publish-label" }, input, " Đã đăng");
    const stale = el("span", { class: "stale small", hidden: !s.published_stale }, "đã đăng bản cũ ");
    const renew = el("button", { class: "btn link-dark small", type: "button", text: "đánh dấu bản này" });
    stale.append(renew);
    const msg = el("span", { class: "error small", hidden: true });
    box.append(label, stale, msg);
    async function send(value) {
      input.disabled = renew.disabled = true;
      msg.hidden = true;
      try {
        const r = await api(`/api/episodes/${encodeURIComponent(episodeId)}/shorts/${encodeURIComponent(s.clip_id)}/published`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value }),
        });
        s.published = r.published; s.published_stale = r.stale; s.published_at = r.at;
        const entry = cards.get(s.clip_id);
        if (entry) entry.key = cardKey(s);
      } catch (e) {
        msg.textContent = e.message;
        msg.hidden = false;
      }
      input.checked = s.published;
      stale.hidden = !s.published_stale;
      input.disabled = s.status !== "rendered" && !s.published;
      renew.disabled = false;
      applyFilter();
    }
    input.addEventListener("change", () => send(input.checked));
    renew.addEventListener("click", () => send(true));
    return box;
  }

  // Delete (X2, soft: review.json + render job that removes the mp4) / restore (render job re-encodes it).
  function deleteButton(s) {
    const restore = s.deleted;
    const btn = el("button", { class: "btn small needs-idle" + (restore ? "" : " danger"), type: "button",
      text: restore ? "Khôi phục" : "Xóa Short" });
    btn.disabled = editsLocked;
    btn.addEventListener("click", async () => {
      const title = (s.title && s.title.text) || s.clip_id;
      if (!restore && !confirm(`Xóa Short ${s.clip_id} "${title}"?\n\nFile video bị xóa ngay để tiết kiệm bộ nhớ; ` +
        "có thể khôi phục sau (dựng lại khoảng 16–40 giây, giữ tiêu đề).")) return;
      btn.disabled = true;
      try {
        await api(`/api/episodes/${encodeURIComponent(episodeId)}/shorts/${encodeURIComponent(s.clip_id)}/${restore ? "restore" : "delete"}`,
          { method: "POST" });
        refreshEpisode();
      } catch (e) {
        alert(e.message);
        btn.disabled = editsLocked;
      }
    });
    return btn;
  }

  function titleEditor(s) {
    const current = (s.pending_title && s.pending_title.text) || (s.title && s.title.text) || s.ai_title || "";
    const box = el("div", { class: "title-edit" });
    const toggle = el("button", { class: "btn small", type: "button", text: "Sửa tiêu đề" });
    const panel = el("div", { class: "edit-panel", hidden: true });
    const input = el("input", { type: "text", value: current, autocomplete: "off", "aria-label": "Tiêu đề mới" });
    const counter = el("span", { class: "counter small" });
    const select = el("select", { "aria-label": "Chọn tiêu đề AI" },
      el("option", { value: "", text: s.alternatives.length ? "— Chọn phương án AI khác —" : "(không có phương án AI khác)" }),
      ...s.alternatives.map((a) => el("option", { value: String(a.n), text: `${a.n}. ${a.title}` })));
    select.disabled = !s.alternatives.length;
    const preview = el("div", { class: "title-preview" });
    const msg = el("p", { class: "preview-msg small" });
    const save = el("button", { class: "btn primary small needs-idle", type: "button", text: "Lưu & render lại" });
    const reset = s.override ? el("button", { class: "btn small needs-idle", type: "button", text: "Khôi phục title AI" }) : null;
    const lockNote = el("p", { class: "lock-note muted small", text: "Đang có job chạy — đợi xong để lưu.", hidden: !editsLocked });
    panel.append(el("label", {}, "Tiêu đề mới ", counter), input, select, preview, msg,
      el("div", { class: "edit-actions" }, save, reset), lockNote);
    box.append(toggle, panel);

    let alt = null, timer = null, seq = 0;
    const setValid = (ok) => { save.dataset.invalid = ok ? "0" : "1"; save.disabled = !ok || editsLocked; };
    const count = () => {
      const n = [...input.value.trim()].length;
      counter.textContent = `${n}/${maxChars}`;
      counter.classList.toggle("over", n > maxChars);
    };
    async function runPreview() {
      const my = ++seq;
      msg.textContent = "Đang kiểm tra…";
      msg.className = "preview-msg small muted";
      try {
        const p = await api(`/api/episodes/${encodeURIComponent(episodeId)}/shorts/${encodeURIComponent(s.clip_id)}/title/preview`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: input.value }),
        });
        if (my !== seq) return;
        preview.replaceChildren(...p.display_lines.map((l) => el("div", { text: l })));
        preview.hidden = false;
        msg.textContent = `${p.display_lines.length} dòng, chữ ${p.font_size} px`;
        msg.className = "preview-msg small muted";
        setValid(true);
      } catch (e) {
        if (my !== seq) return;
        preview.hidden = true;
        msg.textContent = e.message;
        msg.className = "preview-msg small error";
        setValid(false);
      }
    }
    const schedule = () => { count(); setValid(false); clearTimeout(timer); timer = setTimeout(runPreview, 350); };
    toggle.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      toggle.textContent = panel.hidden ? "Sửa tiêu đề" : "Đóng";
      if (!panel.hidden) { count(); runPreview(); input.focus(); }
    });
    input.addEventListener("input", () => {
      if (alt !== null && input.value !== s.alternatives.find((a) => a.n === alt).title) { alt = null; select.value = ""; }
      schedule();
    });
    select.addEventListener("change", () => {
      alt = select.value ? Number(select.value) : null;
      if (alt !== null) input.value = s.alternatives.find((a) => a.n === alt).title;
      schedule();
    });
    async function send(body) {
      save.disabled = true;
      if (reset) reset.disabled = true;
      try {
        await api(`/api/episodes/${encodeURIComponent(episodeId)}/shorts/${encodeURIComponent(s.clip_id)}/title`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        msg.textContent = "Đã lưu, đang render lại…";
        msg.className = "preview-msg small";
        refreshEpisode();
      } catch (e) {
        msg.textContent = e.message;
        msg.className = "preview-msg small error";
        save.disabled = editsLocked;
        if (reset) reset.disabled = editsLocked;
      }
    }
    save.addEventListener("click", () => send(alt !== null ? { alternative: alt } : { set: input.value }));
    if (reset) reset.addEventListener("click", () => send({ reset: true }));
    setValid(false);
    return box;
  }

  return { initIndex, initEpisode };
})();
