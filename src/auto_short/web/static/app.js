/* Auto Short web UI (CP8.3). Plain JS, no build step. */
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
  const TITLE_SOURCE_LABELS = { ai: "AI", manual: "sửa tay", alternative: "phương án khác" };
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
    loadEpisodes();
  }

  async function loadEpisodes() {
    const list = $("#episodes");
    let data;
    try { data = await api("/api/episodes"); } catch (e) {
      list.replaceChildren(el("li", { class: "error", text: e.message }));
      return;
    }
    if (!data.episodes.length) {
      list.replaceChildren(el("li", { class: "muted", text: "Chưa có video nào." }));
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
      else if (e.stages_done === e.stages_total) state = `${e.shorts} Shorts`;
      else state = `${e.stages_done}/${e.stages_total} bước`;
      return el("li", {},
        el("a", { href: "/episodes/" + encodeURIComponent(e.id) },
          el("span", { class: "ep-name", text: e.title || e.id }),
          el("span", { class: "ep-state muted", text: `${e.id} · ${state}` })));
    }));
    if (active) setTimeout(loadEpisodes, 5000);
  }

  // --- episode page -----------------------------------------------------------------------------

  let episodeId = null;
  let shortsKey = null;
  let pollTimer = null;

  function initEpisode() {
    episodeId = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
    $("#resubmit").addEventListener("click", resubmit);
    refreshEpisode();
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

    renderShorts(d);
  }

  function renderShorts(d) {
    const key = JSON.stringify(d.shorts.map((s) => [s.clip_id, s.sha256, s.title && s.title.text]));
    if (key === shortsKey) return; // keep playing videos untouched while polling
    shortsKey = key;
    const rendered = d.shorts.filter((s) => s.status === "rendered");
    $("#shorts-count").textContent = d.shorts.length ? `(${rendered.length})` : "";
    const zip = $("#zip");
    zip.hidden = !d.zip_url;
    if (d.zip_url) { zip.href = d.zip_url; zip.setAttribute("download", ""); }
    $("#header-lines").textContent = d.header ? "Header: " + d.header.join(" / ") : "";
    const grid = $("#shorts");
    if (!d.shorts.length) {
      grid.replaceChildren(el("p", { class: "muted", text: "Chưa có Short (bước Dựng Short chưa xong)." }));
      return;
    }
    grid.replaceChildren(...d.shorts.map(shortCard));
  }

  // One card per Short. The ``.title-edit`` slot is where CP8.2 title editing plugs in.
  function shortCard(s) {
    const title = s.title || {};
    const card = el("article", { class: "short", "data-clip": s.clip_id });
    if (s.status === "rendered") {
      card.append(el("video", { controls: true, preload: "metadata", playsinline: true, src: s.video_url }));
    } else {
      card.append(el("div", { class: "short-missing", text: `Bỏ qua: ${s.skip_reason || s.status}` }));
    }
    const body = el("div", { class: "short-body" },
      el("div", { class: "short-head" },
        el("span", { class: "clip-id", text: s.clip_id }),
        el("span", { class: "badge", text: TITLE_SOURCE_LABELS[title.source] || title.source || "" }),
        el("span", { class: "muted small", text: fmtSeconds(s.duration) })),
      el("p", { class: "short-title", text: title.text || "(không có tiêu đề)" }),
      el("div", { class: "short-actions" },
        s.download_url ? el("a", { class: "btn", href: s.download_url, download: `${episodeId}_${s.clip_id}.mp4`, text: "Tải về" }) : null),
      el("div", { class: "title-edit", hidden: true }));
    card.append(body);
    return card;
  }

  return { initIndex, initEpisode };
})();
