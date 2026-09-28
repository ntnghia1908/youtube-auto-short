/* Auto Short web UI (CP8.3; CP8.5 delete / restore, "Đã đăng", episode delete; CP8.6 storage tab, archived
   episodes, low-disk banner). Plain JS, no build step. */
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

  // CP8.10 queue lanes: "đang tải trước" (prepare lane running), "đợi GPU" / "đợi render" (waiting between lanes).
  function laneLabel(job) {
    if (!job || job.status !== "running" || !job.lane) return null;
    const pos = job.queue_position ? ` (vị trí ${job.queue_position})` : "";
    if (job.waiting && job.lane === "ai") return "đợi GPU" + pos;
    if (job.waiting && job.lane === "render") return "đợi render" + pos;
    if (!job.waiting && job.lane === "prepare") return "đang tải trước";
    return null;
  }

  // Human-readable size, binary units like the OS (648 MB = 678 949 583 bytes); GB with 1 decimal.
  function fmtBytes(n) {
    if (n === null || n === undefined) return "";
    const KB = 1024, MB = KB * 1024, GB = MB * 1024;
    if (n >= GB) return `${(n / GB).toFixed(1).replace(".", ",")} GB`;
    if (n >= MB) return `${Math.round(n / MB)} MB`;
    if (n >= KB) return `${Math.round(n / KB)} kB`;
    return `${n} B`;
  }

  // S4: red banner on every page when the disk is low (and new URLs are refused below 3 GB).
  async function checkDisk() {
    const box = $("#disk-banner");
    if (!box) return;
    let st;
    try { st = await api("/api/storage/status"); } catch (_) { return; }
    box.hidden = !st.warn;
    if (!st.warn) return;
    box.replaceChildren(
      document.createTextNode(`Ổ đĩa server sắp đầy: còn ${fmtBytes(st.free)} trống. ` +
        (st.block ? "Đang CHẶN gửi video mới (dưới 3 GB). " : "") + "Xem gợi ý dọn ở "),
      el("a", { href: "/storage", text: "tab Bộ nhớ" }), document.createTextNode("."));
  }

  // ``opts`` (CP8.9 A1.1): {kinds: ["short", "khaithi"] (absent = both), min, max (khai thị minutes)}.
  async function submitUrl(url, series, episode, mode, opts) {
    const body = { url, series: series || null, episode: episode || null, mode: mode || null };
    if (opts && opts.kinds) body.kinds = opts.kinds;
    if (opts && opts.min !== undefined) Object.assign(body, { min_minutes: opts.min, max_minutes: opts.max });
    return api("/api/episodes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  // --- CP8.9 khai thị -----------------------------------------------------------------------------

  // Video id of a single-video YouTube URL (mirror of the server's parser, only to look up <id>.kt first).
  function videoIdOf(url) {
    const m = String(url || "").match(/(?:youtu\.be\/|[?&]v=|\/(?:shorts|embed|live|v)\/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])/);
    return m ? m[1] : null;
  }

  function ktLabel(d) {
    return d.min_minutes && d.max_minutes ? `Khai thị ${d.min_minutes}–${d.max_minutes} phút` : "Khai thị";
  }

  // Minutes typed in two number inputs (the server re-checks: whole numbers, 1 ≤ min < max ≤ 15).
  function ktMinutes(minSel, maxSel) {
    const read = (sel) => { const v = $(sel).value.trim(); return /^\d+$/.test(v) ? Number(v) : v; };
    return { min: read(minSel), max: read(maxSel) };
  }

  // K7: an existing khai thị episode with other minutes is replaced (re-run from analysis): ask first.
  async function confirmKhaithi(videoId, kt) {
    if (!videoId) return true;
    let cur;
    try { cur = await api("/api/episodes/" + encodeURIComponent(videoId + ".kt")); } catch (_) { return true; }
    if (cur.kind !== "khaithi" || (cur.min_minutes === kt.min && cur.max_minutes === kt.max)) return true;
    return confirm(`Video này đã có video khai thị ${cur.min_minutes}–${cur.max_minutes} phút.\n\n` +
      `Chạy lại với ${kt.min}–${kt.max} phút sẽ THAY TOÀN BỘ video khai thị cũ (AI chọn lại đoạn, đặt lại tiêu đề); ` +
      "các tick \"Đã đăng\" cũ thành \"đã đăng bản cũ\". Tiếp tục?");
  }

  function gotoResult(data) {
    if (data.kind === "playlist") location.href = "/playlists/" + encodeURIComponent(data.playlist_id);
    else location.href = "/episodes/" + encodeURIComponent(data.episode_id);
  }

  // --- index page -------------------------------------------------------------------------------

  function initIndex() {
    const form = $("#submit-form"), btn = $("#submit-btn"), err = $("#submit-error");
    // A1.3: two boxes "Short" / "Khai thị", both ticked by default; khai thị minutes 4–7
    const kindsOf = () => [...document.querySelectorAll('input[name="kind"]:checked')].map((b) => b.value);
    document.querySelectorAll('input[name="kind"]').forEach((r) => r.addEventListener("change", () => {
      $("#kt-minutes").hidden = !kindsOf().includes("khaithi");
    }));
    async function send(mode) {
      err.hidden = true;
      const url = $("#url").value;
      const isPlaylist = mode === "playlist" || /\/playlist\?/.test(url);
      const kinds = kindsOf();
      if (!isPlaylist && !kinds.length) {
        err.textContent = "Chọn ít nhất một loại: Short hoặc Khai thị.";
        err.hidden = false;
        return;
      }
      const opts = { kinds };
      if (kinds.includes("khaithi")) Object.assign(opts, ktMinutes("#kt-min", "#kt-max"));
      const maybeAsk = mode === null && /[?&]list=/.test(url); // the server first asks "tập lẻ / cả bộ kinh"
      if (!isPlaylist && !maybeAsk && kinds.includes("khaithi") && !(await confirmKhaithi(videoIdOf(url), opts))) return;
      btn.disabled = true;
      btn.textContent = isPlaylist || /[?&]list=/.test(url) ? "Đang lấy danh sách…" : "Đang kiểm tra…";
      try {
        const data = await submitUrl(url, $("#series").value.trim(), $("#episode").value.trim(), mode,
          isPlaylist ? null : opts);
        if (data.kind === "ask") { $("#ask-box").hidden = false; return; }
        gotoResult(data);
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
      } finally {
        btn.disabled = false;
        btn.textContent = "Bắt đầu";
      }
    }
    form.addEventListener("submit", (ev) => { ev.preventDefault(); $("#ask-box").hidden = true; send(null); });
    $("#ask-video").addEventListener("click", () => { $("#ask-box").hidden = true; send("video"); });
    $("#ask-playlist").addEventListener("click", () => { $("#ask-box").hidden = true; send("playlist"); });
    document.querySelectorAll("#ep-filters [data-filter]").forEach((b) => b.addEventListener("click", () => {
      epFilter = b.dataset.filter;
      applyEpisodeFilter();
    }));
    loadEpisodes();
    loadPlaylists();
    loadDeleted();
    checkDisk();
  }

  // Deleted single episodes (tombstones, bổ sung HUMAN LEAD 2026-09-27): collapsed, "Xóa khỏi lịch sử".
  async function loadDeleted() {
    const box = $("#deleted-box");
    let data;
    try { data = await api("/api/deleted"); } catch (_) { return; }
    box.hidden = !data.episodes.length;
    $("#deleted-count").textContent = data.episodes.length;
    $("#deleted").replaceChildren(...data.episodes.map((t) => {
      const btn = el("button", { class: "btn small", type: "button", text: "Xóa khỏi lịch sử" });
      btn.addEventListener("click", async () => {
        if (!confirm(`Xóa "${t.title || t.episode_id}" khỏi lịch sử? (Chỉ xóa dòng ghi nhớ này.)`)) return;
        btn.disabled = true;
        try { await api(`/api/deleted/${encodeURIComponent(t.episode_id)}`, { method: "DELETE" }); loadDeleted(); }
        catch (e) { btn.disabled = false; alert(e.message); }
      });
      return el("li", { class: "deleted-item" },
        el("span", { class: "ep-name clamp2", text: t.title || t.episode_id }),
        el("span", { class: "ep-state muted", text: `${t.episode_id} · ${t.complete ? "✔ Xong · " : "chưa xong · "}` +
          `${t.shorts} Short, đã đăng ${t.published}/${t.shorts} · xóa lúc ${fmtTime(t.deleted_at)}` }),
        btn);
    }));
  }

  async function loadPlaylists() {
    const list = $("#playlists");
    let data;
    try { data = await api("/api/playlists"); } catch (e) {
      list.replaceChildren(el("li", { class: "error", text: e.message }));
      return;
    }
    if (!data.playlists.length) {
      list.replaceChildren(el("li", { class: "muted", text: "Chưa có bộ kinh nào — dán link playlist ở trên." }));
      return;
    }
    list.replaceChildren(...data.playlists.map((p) => el("li", {},
      el("a", { href: "/playlists/" + encodeURIComponent(p.id) },
        el("span", { class: "ep-name", text: p.title || p.id }),
        el("span", { class: "ep-state muted", text: `${p.count} tập · đã xử lý ${p.processed} · Xong ${p.complete}` +
          (p.doing ? ` · đang làm ${p.doing}` : "") })))));
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
    const single = data.episodes.filter((e) => !e.in_playlist); // CP8.7: episodes of a bộ kinh are on its page
    // CP8.9 A1.5: a khai thị episode whose Short episode is listed is shown under it, not as its own row
    const ids = new Set(single.map((e) => e.id));
    episodeItems = single.filter((e) => !(e.kind === "khaithi" && e.base_episode_id && ids.has(e.base_episode_id)));
    const ktOf = new Map(single.filter((e) => e.kind === "khaithi" && e.base_episode_id).map((e) => [e.base_episode_id, e]));
    if (!episodeItems.length) {
      list.replaceChildren(el("li", { class: "muted", text: "Chưa có tập lẻ nào." }));
      applyEpisodeFilter();
      return;
    }
    let active = false;
    const stateText = (e) => {
      const unit = e.kind === "khaithi" ? "video khai thị" : "Shorts";
      if (jobActive(e.job)) {
        active = true;
        if (e.job.status === "queued") return "đang đợi";
        const lane = laneLabel(e.job);
        if (lane && e.job.waiting) return lane;
        return `${lane || "đang chạy"}: ${STAGE_LABELS[e.job.stage] || e.job.stage || ""}`;
      }
      if (e.failed) return `lỗi ở ${STAGE_LABELS[e.failed] || e.failed}`;
      if (e.running) return `dừng giữa chừng ở ${STAGE_LABELS[e.running] || e.running}`;
      if (e.stages_done === e.stages_total) return (e.complete ? "Xong · " : "") + `${e.shorts} ${unit} · đã đăng ${e.published || 0}/${e.shorts}` + (e.archived ? " · đã dọn video nguồn" : "");
      return `${e.stages_done}/${e.stages_total} bước`;
    };
    list.replaceChildren(...episodeItems.map((e) => {
      const kt = e.kind !== "khaithi" ? ktOf.get(e.id) : null;
      return el("li", { "data-group": e.publish_group || "none" },
        el("a", { href: "/episodes/" + encodeURIComponent(e.id) },
          el("span", { class: "ep-name", text: e.title || e.id }),
          e.kind === "khaithi" ? el("span", { class: "kind-label", text: ktLabel(e) }) : null,
          el("span", { class: "ep-state muted", text: `${e.id} · ${stateText(e)}` })),
        kt ? el("a", { class: "sub-episode", href: "/episodes/" + encodeURIComponent(kt.id) },
          el("span", { class: "kind-label", text: ktLabel(kt) }),
          el("span", { class: "muted small", text: ` ${stateText(kt)}` })) : null);
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
    $("#kt-create").addEventListener("click", createKhaithi);
    document.querySelectorAll("#filters [data-filter]").forEach((b) => b.addEventListener("click", () => {
      filter = b.dataset.filter;
      applyFilter();
    }));
    $("#show-deleted").addEventListener("click", () => { showDeleted = !showDeleted; applyFilter(); });
    refreshEpisode();
    checkDisk();
  }

  let lastData = null;

  // CP8.9 A2.3: a khai thị episode says "video" where a Short episode says "Short".
  function noun() { return lastData && lastData.kind === "khaithi" ? "video" : "Short"; }
  function stageLabel(stage) {
    if (stage === "render" && lastData && lastData.kind === "khaithi") return "Dựng video khai thị";
    return STAGE_LABELS[stage] || stage || "";
  }

  async function deleteEpisode() {
    const d = lastData || {};
    const name = d.title || episodeId;
    const ok = confirm(`Xóa toàn bộ tập "${name}" (${episodeId})?\n\n` +
      `Sẽ xóa video nguồn đã tải, mọi ${noun()} và dữ liệu xử lý của tập này. ` +
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

  // CP8.9 K7: "Tạo video khai thị" on a Short episode page (same API as the home page form).
  async function createKhaithi() {
    const d = lastData || {};
    const err = $("#kt-error"), btn = $("#kt-create");
    err.hidden = true;
    const kt = ktMinutes("#kt-min", "#kt-max");
    if (!(await confirmKhaithi(videoIdOf(d.source_url), kt))) return;
    btn.disabled = true;
    try {
      const data = await submitUrl(d.source_url, null, null, "video", { kinds: ["khaithi"], ...kt });
      location.href = "/episodes/" + encodeURIComponent(data.episode_id);
    } catch (e) {
      err.textContent = e.message;
      err.hidden = false;
      btn.disabled = false;
    }
  }

  async function resubmit() {
    const btn = $("#resubmit");
    const d = lastData || {};
    btn.disabled = true;
    try {
      // only this episode's kind; a khai thị episode resumes with its own minutes (nothing up to date re-runs)
      await submitUrl(btn.dataset.url, null, null, null, d.kind === "khaithi"
        ? { kinds: ["khaithi"], ...(d.min_minutes ? { min: d.min_minutes, max: d.max_minutes } : {}) }
        : { kinds: ["short"] });
      refreshEpisode();
    } catch (e) {
      setJobStatus(`Không chạy được: ${e.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  }

  // CP8.9 K7: link between the Short page and the khai thị page of the same video; "Tạo video khai thị" box.
  function renderKindLinks(d) {
    const box = $("#kind-links");
    const isKt = d.kind === "khaithi";
    const other = isKt ? d.base_episode_id : d.khaithi_episode_id;
    box.hidden = !other;
    if (other) {
      box.replaceChildren(el("a", { href: "/episodes/" + encodeURIComponent(other),
        text: isKt ? "→ Trang Short của video này" : "→ Trang video khai thị của video này" }));
    }
    $("#shorts-label").textContent = isKt ? "Video khai thị" : "Shorts";
    const kb = $("#kt-box");
    kb.hidden = isKt || !d.source_url;
    $("#kt-summary").textContent = d.khaithi_episode_id ? "Tạo lại video khai thị (đổi số phút)" : "Tạo video khai thị từ video này";
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
    lastData = d; // noun() / stageLabel() read the kind
    document.title = `${d.title || d.id} — Auto Short`;
    $("#ep-title").textContent = d.title || d.id;
    const meta = [d.id];
    if (d.complete) meta.unshift("✔ Xong (đã đăng hết)");
    if (d.channel) meta.push(d.channel);
    if (d.duration) meta.push(fmtSeconds(d.duration));
    if (d.kind === "khaithi") meta.unshift(ktLabel(d));
    $("#ep-meta").textContent = meta.join(" · ");
    renderKindLinks(d);

    const job = d.job;
    const timings = {};
    if (job) for (const s of job.stages) timings[s.stage] = s;
    if (jobActive(job)) {
      if (job.status === "queued") setJobStatus(`Đang đợi trong hàng (vị trí ${job.queue_position || "?"})`, "busy");
      else if (job.waiting) {
        const lane = laneLabel(job);
        setJobStatus(`${lane ? lane[0].toUpperCase() + lane.slice(1) : "Đang đợi"}: tiếp theo ${stageLabel(job.stage) || "…"} (bắt đầu ${fmtTime(job.started_at)})`, "busy");
      } else {
        const lane = laneLabel(job);
        setJobStatus(`${lane ? lane[0].toUpperCase() + lane.slice(1) : "Đang chạy"}: ${stageLabel(job.stage) || "…"} (bắt đầu ${fmtTime(job.started_at)})`, "busy");
      }
    } else if (job && job.status === "done") setJobStatus(`Xong: ${job.summary || ""} (${fmtTime(job.finished_at)})`, "ok");
    else if (job && job.status === "failed") setJobStatus(`Lỗi: ${job.error}`, "error");
    else if (job && job.status === "interrupted") setJobStatus(`Bị ngắt (${job.error}). Bấm chạy tiếp để tiếp tục.`, "error");
    else setJobStatus("", "");

    const stages = d.stages.length ? d.stages : Object.keys(STAGE_LABELS).map((s) => ({ stage: s, status: "pending" }));
    $("#stages").replaceChildren(...stages.map((s) => {
      let status = s.status;
      if (jobActive(job) && job.stage === s.stage && status !== "running") status = job.waiting ? "queued" : "running";
      const t = timings[s.stage];
      const extra = t ? (t.ran ? fmtSeconds(t.seconds) : "bỏ qua (đã có)") : "";
      return el("li", { class: "stage " + status },
        el("span", { class: "stage-name", text: stageLabel(s.stage) }),
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

    archived = !!d.archived;
    const an = $("#archived-note");
    an.hidden = !archived;
    if (archived) {
      an.textContent = `Đã dọn video nguồn${d.archived.freed ? ` (giải phóng ${fmtBytes(d.archived.freed)})` : ""}` +
        `${d.archived.at ? `, ${fmtTime(d.archived.at)}` : ""}: chỉ xem / tải / đánh dấu đã đăng / xóa ${noun()}. ` +
        `Muốn sửa tiêu đề hay khôi phục ${noun()} thì xóa tập rồi chạy lại.`;
    }
    const rb = $("#resubmit");
    rb.hidden = !d.source_url || jobActive(job) || archived;
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
  let archived = false; // CP8.6: source video cleaned up
  let showDeleted = false;

  function cardKey(s) {
    return JSON.stringify([s.status, s.sha256, s.title, s.pending_title, s.override, s.rendering, s.editable,
      s.alternatives.length, s.deleted, s.rejected, s.published, s.published_stale, s.download_name, archived]);
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
    sd.textContent = showDeleted ? `Ẩn ${noun()} đã xóa (${deleted})` : `Hiện ${noun()} đã xóa (${deleted})`;
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
    if (!zip.dataset.bound) { zip.dataset.bound = "1"; zip.addEventListener("click", () => setTimeout(refreshEpisode, 2000)); }
    $("#header-lines").textContent = d.header ? "Header: " + d.header.join(" / ") : "";
    const notes = [];
    if (d.shorts.length && d.render_status !== "done") {
      notes.push(`Đang hiển thị bản dựng trước (bước ${stageLabel("render")}: ${STATUS_LABELS[d.render_status] || d.render_status}).`);
    }
    if (d.titles_error) notes.push(`Chưa sửa title được: ${d.titles_error}`);
    if (d.publish_error) notes.push(`Không đọc được trạng thái "Đã đăng": ${d.publish_error}`);
    for (const w of d.titles_ignored || []) notes.push(w);
    $("#shorts-note").textContent = notes.join(" ");
    $("#shorts-note").hidden = !notes.length;

    const grid = $("#shorts");
    if (!d.shorts.length) {
      cards.clear();
      grid.replaceChildren(el("p", { class: "muted", text: `Chưa có ${noun()} (bước ${stageLabel("render")} chưa xong).` }));
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
      el("div", { class: "title-row" },
        el("p", { class: "short-title", text: title.text || "(không có tiêu đề)" }),
        s.copy_text ? copyTitleButton(s.copy_text) : null),
      s.hashtags && s.hashtags.length ? el("p", { class: "hashtags small muted", text: s.hashtags.join(" ") }) : null,
      s.pending_title ? el("p", { class: "pending small", text: s.pending_title.text
        ? `Tiêu đề mới (${TITLE_SOURCE_LABELS[s.pending_title.origin] || s.pending_title.origin}), chưa render: ${s.pending_title.text}`
        : "Sẽ bỏ qua ở lần render tới (không có tiêu đề)" }) : null,
      s.status === "rendered" || s.published ? publishBox(s) : null,
      el("div", { class: "short-actions" },
        s.download_url ? downloadLink(s) : null,
        s.editable && !(archived && s.deleted) ? deleteButton(s) : null),
      s.editable && !s.deleted && !archived ? titleEditor(s) : el("div", { class: "title-edit", hidden: true }));
    card.append(body);
    return card;
  }

  // CP8.7 (bổ sung HUMAN LEAD): copy the title in the file, to paste into the YouTube app. The site is plain HTTP
  // on the LAN (no secure context -> no navigator.clipboard on most phones): fall back to a selected textarea +
  // execCommand("copy") inside the click (user gesture); if that fails too, show the title selected to long-press.
  function legacyCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.contentEditable = "true"; // iOS Safari only selects editable content
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.left = "-9999px";
    ta.style.fontSize = "16px"; // no zoom on iOS
    document.body.append(ta);
    let ok = false;
    try {
      ta.focus();
      ta.select();
      ta.setSelectionRange(0, text.length);
      ok = document.execCommand("copy");
    } catch (_) { ok = false; }
    ta.remove();
    return ok;
  }

  async function copyText(text) {
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
      try { await navigator.clipboard.writeText(text); return true; } catch (_) { /* fall back */ }
    }
    return legacyCopy(text);
  }

  function copyTitleButton(text) {
    const wrap = el("span", { class: "copy-wrap" });
    const btn = el("button", { class: "btn small copy-btn", type: "button", text: "Copy", title: "Copy tiêu đề" });
    const note = el("span", { class: "copy-note small", hidden: true });
    btn.addEventListener("click", async () => {
      const ok = await copyText(text);
      wrap.querySelectorAll(".copy-fallback").forEach((n) => n.remove());
      if (ok) {
        note.textContent = "Đã copy";
        note.hidden = false;
        setTimeout(() => { note.hidden = true; }, 1500);
        return;
      }
      // Could not copy: show the title selected so the user can long-press -> Copy.
      const box = el("input", { class: "copy-fallback", type: "text", value: text, readonly: true,
        "aria-label": "Tiêu đề (giữ để copy)" });
      wrap.append(box);
      box.focus();
      box.select();
      box.setSelectionRange(0, text.length);
      note.textContent = "Giữ vào ô để copy";
      note.hidden = false;
    });
    wrap.append(btn, note);
    return wrap;
  }

  // CP8.7: a download ticks "Đã đăng" server-side; show it on the next refresh.
  function downloadLink(s) {
    const a = el("a", { class: "btn", href: s.download_url, download: s.download_name || "", text: "Tải về" });
    a.addEventListener("click", () => setTimeout(refreshEpisode, 1500));
    return a;
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
      text: restore ? "Khôi phục" : `Xóa ${noun()}` });
    btn.disabled = editsLocked;
    btn.addEventListener("click", async () => {
      const title = (s.title && s.title.text) || s.clip_id;
      if (!restore && !confirm(`Xóa ${noun()} ${s.clip_id} "${title}"?\n\nFile video bị xóa ngay để tiết kiệm bộ nhớ; ` +
        (archived ? "tập đã dọn video nguồn nên KHÔNG khôi phục được." :
          "có thể khôi phục sau (dựng lại khoảng 16–40 giây, giữ tiêu đề)."))) return;
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

  // --- storage page (CP8.6) ---------------------------------------------------------------------

  const STATE_LABELS = {
    processing: "đang xử lý", done: "xong", failed: "lỗi", incomplete: "dở dang", archived: "đã dọn nguồn",
    orphan: "chỉ còn Short (không có workspace)",
  };
  const ACTION_LABELS = { archive: "Dọn video nguồn", delete: "Xóa cả tập" };

  function initStorage() {
    loadStorage();
    checkDisk();
  }

  function recReason(r) {
    if (r.rule === "all_published") return "Đã đăng hết Short.";
    if (r.rule === "old_source") return `Dựng Short xong ${r.age_days} ngày trước, còn video nguồn.`;
    return `Lỗi / dở dang, không hoạt động ${r.age_days} ngày.`;
  }

  async function runAction(r, a, btn) {
    const name = r.title || r.episode_id;
    const msg = a.action === "archive"
      ? `Dọn video nguồn của "${name}" (${r.episode_id})? Giải phóng ${fmtBytes(a.frees)}.\n\n` +
        "Short vẫn xem / tải được. Sau đó KHÔNG sửa tiêu đề, khôi phục Short hay chạy lại được nữa " +
        "(muốn sửa thì xóa tập rồi chạy lại từ đầu)."
      : `Xóa toàn bộ tập "${name}" (${r.episode_id})? Giải phóng ${fmtBytes(a.frees)}.\n\n` +
        "Sẽ xóa video nguồn đã tải, mọi Short và dữ liệu xử lý. KHÔNG khôi phục được.";
    if (!confirm(msg)) return;
    btn.disabled = true;
    const out = $("#rec-msg");
    try {
      if (a.action === "archive") {
        const res = await api(`/api/episodes/${encodeURIComponent(r.episode_id)}/archive`, { method: "POST" });
        out.textContent = `Đã dọn video nguồn "${name}": giải phóng ${fmtBytes(res.freed)}.`;
      } else {
        await api(`/api/episodes/${encodeURIComponent(r.episode_id)}`, { method: "DELETE" });
        out.textContent = `Đã xóa tập "${name}".`;
      }
      out.className = "small ok";
    } catch (e) {
      out.textContent = e.message;
      out.className = "small error";
      btn.disabled = false;
    }
    out.hidden = false;
    loadStorage();
    checkDisk();
  }

  function recButtons(r) {
    return el("div", { class: "rec-actions" }, ...r.actions.map((a) => {
      const btn = el("button", { class: "btn small" + (a.action === "delete" ? " danger" : ""), type: "button",
        text: `Làm: ${ACTION_LABELS[a.action]} (giải phóng ${fmtBytes(a.frees)})` });
      btn.addEventListener("click", () => runAction(r, a, btn));
      return btn;
    }));
  }

  async function loadStorage() {
    let d;
    try { d = await api("/api/storage"); } catch (e) {
      $("#disks").replaceChildren(el("p", { class: "error", text: e.message }));
      return;
    }
    $("#disks").replaceChildren(...d.disks.map((k) => {
      const pct = k.total ? Math.round((k.used / k.total) * 100) : 0;
      return el("div", { class: "disk" + (d.warn ? " low" : "") },
        el("div", { class: "disk-line", text: `Ổ chứa ${k.label === "work" ? "work/" : "output/"}` }),
        el("div", { class: "bar" }, el("div", { class: "bar-used", style: `width:${pct}%` })),
        el("div", { class: "disk-nums small", text: `Đã dùng ${fmtBytes(k.used)} / ${fmtBytes(k.total)} (${pct} %) · còn trống ${fmtBytes(k.free)}` }));
    }));
    const t = d.totals;
    $("#storage-meta").textContent = `Các tập: ${fmtBytes(t.episodes)} (video nguồn ${fmtBytes(t.source)}, Short ${fmtBytes(t.shorts)}, khác ${fmtBytes(t.other)}). ` +
      `Tính lúc ${fmtTime(d.computed_at)} (làm mới tối đa 30 giây một lần).`;

    const recs = $("#recs");
    if (!d.recommendations.length) {
      recs.replaceChildren(el("li", { class: "muted", text: "Không có gợi ý nào." }));
    } else {
      recs.replaceChildren(...d.recommendations.map((r) => el("li", { class: "rec" },
        el("a", { href: "/episodes/" + encodeURIComponent(r.episode_id), class: "ep-name clamp2", text: r.title || r.episode_id }),
        el("span", { class: "muted small", text: `${r.episode_id} · ${recReason(r)}` }),
        recButtons(r))));
    }
    const recOf = {};
    for (const r of d.recommendations) recOf[r.episode_id] = r;
    const epLink = (e) => (e.state === "orphan" ? el("span", { class: "clamp2", text: e.id })
      : el("a", { class: "clamp2", href: "/episodes/" + encodeURIComponent(e.id), text: e.title || e.id }));
    const src = (e) => (e.source_kind === "local" ? "(file local)" : fmtBytes(e.source));
    // Desktop: table; ≤ 640 px: one card per episode (CSS shows one of the two).
    $("#ep-rows").replaceChildren(...d.episodes.map((e) => el("tr", {},
      el("td", {}, epLink(e)),
      el("td", { text: STATE_LABELS[e.state] || e.state }),
      el("td", { class: "num", text: src(e) }),
      el("td", { class: "num", text: fmtBytes(e.shorts_bytes) }),
      el("td", { class: "num", text: fmtBytes(e.other) }),
      el("td", { class: "num", text: fmtBytes(e.total) }),
      el("td", { class: "num", text: e.shorts ? `${e.published}/${e.shorts}` : "–" }),
      el("td", {}, recOf[e.id] ? recButtons(recOf[e.id]) : null))));
    $("#ep-cards").replaceChildren(...d.episodes.map((e) => el("li", { class: "ep-card" },
      el("div", { class: "ep-card-head" }, epLink(e), el("span", { class: "badge state-" + e.state, text: STATE_LABELS[e.state] || e.state })),
      el("div", { class: "ep-card-total", text: fmtBytes(e.total) }),
      el("div", { class: "small muted", text: `Nguồn ${src(e)} · Short ${fmtBytes(e.shorts_bytes)} · Khác ${fmtBytes(e.other)}` }),
      el("div", { class: "small", text: e.shorts ? `Đã đăng ${e.published}/${e.shorts}` + (e.complete ? " · Xong" : "") : "Chưa có Short" }),
      recOf[e.id] ? recButtons(recOf[e.id]) : null)));
    $("#caches").replaceChildren(...d.caches.map((c) => el("li", { text: `${c.name} (${c.path}): ` +
      (c.exists ? fmtBytes(c.bytes) : "chưa có thư mục (đặt [transcript.whisper] models_dir tuyệt đối nếu model nằm chỗ khác)") })));
  }

  // --- playlist page (CP8.7) --------------------------------------------------------------------

  const PL_STATE = {
    new: "chưa xử lý", queued: "đang chờ", processing: "đang xử lý", failed: "lỗi", rendered: "đã dựng Short",
    incomplete: "dở dang", complete: "Xong", unavailable: "không khả dụng", deleted: "Đã xóa dữ liệu",
  };
  let playlistId = null;
  let plFilter = "doing"; // CP8.9 A2.1: "Đang làm" by default; the user's choice is remembered
  let plTimer = null;
  let plDefaultsApplied = false;

  // localStorage wrapped: private mode / disabled storage must never break the page.
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (_) { /* ignore */ }
    return null;
  }

  // CP8.9 A2.2: what "Xử lý" / "Xử lý lại" create (Short / khai thị + minutes), remembered by the browser.
  function plKinds() {
    const kinds = [...document.querySelectorAll('#pl-kinds input[name="pl-kind"]:checked')].map((b) => b.value);
    const opts = { kinds };
    if (kinds.includes("khaithi")) Object.assign(opts, ktMinutes("#pl-kt-min", "#pl-kt-max"));
    return opts;
  }

  function initPlKinds() {
    let saved = null;
    try { saved = JSON.parse(store("autoShort.plKinds") || "null"); } catch (_) { saved = null; }
    if (saved && Array.isArray(saved.kinds)) {
      document.querySelectorAll('#pl-kinds input[name="pl-kind"]').forEach((b) => { b.checked = saved.kinds.includes(b.value); });
      if (saved.min) $("#pl-kt-min").value = saved.min;
      if (saved.max) $("#pl-kt-max").value = saved.max;
    }
    const changed = (ev) => {
      const o = plKinds();
      if (ev) store("autoShort.plKinds", JSON.stringify({ kinds: o.kinds, min: $("#pl-kt-min").value, max: $("#pl-kt-max").value }));
      $("#pl-kt-minutes").hidden = !o.kinds.includes("khaithi");
      $("#pl-kinds-note").hidden = o.kinds.length > 0;
      document.querySelectorAll("#pl-entries button[data-action='process'], #pl-entries button[data-action='reprocess']")
        .forEach((b) => { b.disabled = !o.kinds.length; });
    };
    document.querySelectorAll("#pl-kinds input").forEach((i) => i.addEventListener("change", changed));
    changed();
  }

  function initPlaylist() {
    playlistId = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
    const savedFilter = store("autoShort.plFilter");
    if (["all", "todo", "doing", "done"].includes(savedFilter)) plFilter = savedFilter;
    document.querySelectorAll("#pl-filters [data-filter]").forEach((b) => b.addEventListener("click", () => {
      plFilter = b.dataset.filter;
      store("autoShort.plFilter", plFilter);
      applyPlFilter();
    }));
    initPlKinds();
    $("#pl-refresh").addEventListener("click", refreshPlaylist);
    initHashtags();
    initSeries();
    $("#pl-delete").addEventListener("click", deletePlaylist);
    loadPlaylist();
    checkDisk();
  }

  function plMessage(text, cls) {
    const m = $("#pl-msg");
    m.textContent = text;
    m.className = "small " + (cls || "");
    m.hidden = !text;
  }

  async function refreshPlaylist() {
    const b = $("#pl-refresh");
    b.disabled = true;
    plMessage("Đang lấy lại danh sách từ YouTube…", "muted");
    try {
      const r = await api(`/api/playlists/${encodeURIComponent(playlistId)}/refresh`, { method: "POST" });
      plMessage(r.added.length ? `Thêm ${r.added.length} tập mới (tổng ${r.count}).` : `Không có tập mới (tổng ${r.count}).`, "ok");
      loadPlaylist();
    } catch (e) { plMessage(e.message, "error"); }
    b.disabled = false;
  }

  async function deletePlaylist() {
    if (!confirm("Xóa bộ kinh này khỏi danh sách?\n\nChỉ xóa danh sách tập; các tập đã xử lý (Short, video) vẫn giữ nguyên ở mục Tập lẻ.")) return;
    try {
      await api(`/api/playlists/${encodeURIComponent(playlistId)}`, { method: "DELETE" });
      location.href = "/";
    } catch (e) { plMessage(e.message, "error"); }
  }

  function applyPlFilter() {
    document.querySelectorAll("#pl-filters [data-filter]").forEach((b) => b.classList.toggle("active", b.dataset.filter === plFilter));
    document.querySelectorAll("#pl-entries li[data-group]").forEach((li) => {
      li.hidden = plFilter !== "all" && li.dataset.group !== plFilter;
    });
  }

  // Per-bộ kinh hashtags (bổ sung HUMAN LEAD 2026-09-27): chips in order, add / remove / move, preview.
  let htTags = null; // working list, without "#"
  let htTimer = null;

  function htMessage(text, cls) {
    const m = $("#ht-msg");
    m.textContent = text;
    m.className = "small " + (cls || "");
    m.hidden = !text;
  }

  function htNormalize(text) { // mirror of review.names.hashtag (the server re-checks)
    const body = [...(text || "").normalize("NFC")].filter((c) => /[\p{L}\p{N}]/u.test(c)).join("");
    return body || null;
  }

  function htRender() {
    const ul = $("#ht-chips");
    ul.replaceChildren(...htTags.map((t, i) => {
      const up = el("button", { class: "btn small", type: "button", text: "↑", "aria-label": "Lên", disabled: i === 0 });
      const down = el("button", { class: "btn small", type: "button", text: "↓", "aria-label": "Xuống", disabled: i === htTags.length - 1 });
      const rm = el("button", { class: "btn small danger", type: "button", text: "✕", "aria-label": `Bỏ #${t}` });
      up.addEventListener("click", () => { [htTags[i - 1], htTags[i]] = [htTags[i], htTags[i - 1]]; htChanged(); });
      down.addEventListener("click", () => { [htTags[i + 1], htTags[i]] = [htTags[i], htTags[i + 1]]; htChanged(); });
      rm.addEventListener("click", () => { htTags.splice(i, 1); htChanged(); });
      return el("li", { class: "ht-chip" }, el("span", { class: "ht-tag", text: `#${t}` }), up, down, rm);
    }));
    if (!htTags.length) ul.replaceChildren(el("li", { class: "muted small", text: "(không có hashtag)" }));
  }

  function htChanged() {
    htRender();
    clearTimeout(htTimer);
    htTimer = setTimeout(htPreview, 250);
  }

  async function htPreview() {
    try {
      const p = await api(`/api/playlists/${encodeURIComponent(playlistId)}/hashtags/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hashtags: htTags }) });
      $("#ht-preview-label").textContent = p.title_is_real ? `Xem trước (tiêu đề dài nhất của bộ kinh, ${p.chars}/${p.max_chars} ký tự):`
        : `Xem trước (tiêu đề mẫu 60 ký tự, ${p.chars}/${p.max_chars} ký tự):`;
      $("#ht-preview").textContent = p.copy_text;
      const dr = $("#ht-dropped");
      dr.hidden = !p.dropped.length;
      dr.textContent = p.dropped.length ? `Bị bỏ vì quá 100 ký tự: ${p.dropped.join(" ")}` : "";
    } catch (e) { $("#ht-preview").textContent = e.message; }
  }

  function initHashtags() {
    const input = $("#ht-input");
    input.addEventListener("input", () => {
      const n = htNormalize(input.value);
      $("#ht-norm").hidden = !input.value.trim();
      $("#ht-norm").textContent = n ? `Sẽ thêm: #${n}` : "Không có chữ / số nào";
    });
    const add = () => {
      const n = htNormalize(input.value);
      if (!n) { htMessage("Hashtag rỗng", "error"); return; }
      if (htTags.some((t) => t.toLowerCase() === n.toLowerCase())) { htMessage(`#${n} đã có`, "error"); return; }
      if (htTags.length >= 15) { htMessage("Tối đa 15 hashtag", "error"); return; }
      htTags.push(n);
      input.value = "";
      $("#ht-norm").hidden = true;
      htMessage("", "");
      htChanged();
    };
    $("#ht-add").addEventListener("click", add);
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); add(); } });
    $("#ht-save").addEventListener("click", async () => {
      try {
        const r = await api(`/api/playlists/${encodeURIComponent(playlistId)}/hashtags`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hashtags: htTags }) });
        htLoad(r);
        htMessage("Đã lưu", "ok");
      } catch (e) { htMessage(e.message, "error"); }
    });
    $("#ht-reset").addEventListener("click", async () => {
      if (!confirm("Khôi phục hashtag mặc định (#bộ kinh + danh sách chung)?")) return;
      try {
        const r = await api(`/api/playlists/${encodeURIComponent(playlistId)}/hashtags`, { method: "DELETE" });
        htLoad(r);
        htMessage("Đã khôi phục mặc định", "ok");
      } catch (e) { htMessage(e.message, "error"); }
    });
  }

  function htLoad(d) {
    htTags = d.hashtags.map((t) => t.replace(/^#/, ""));
    $("#ht-state").textContent = d.hashtags_custom ? "riêng bộ kinh này" : "mặc định";
    htChanged();
  }

  // "Tên bộ kinh" (CP8.11 D5, D7): header fallback for episodes whose video title no pattern recognizes.
  let srEditing = false; // the input differs from the saved name: the poll must not overwrite it
  let srLoaded = false;

  function srMessage(text, cls) {
    const m = $("#sr-msg");
    m.textContent = text;
    m.className = "small " + (cls || "");
    m.hidden = !text;
  }

  function srLoad(d, force) {
    const input = $("#sr-input");
    $("#sr-state").textContent = d.series ? "đã đặt" : "tự nhận từ tiêu đề";
    if (d.series_suggested !== undefined) input.placeholder = d.series_suggested || "Tên bộ kinh";
    if (d.unrecognized !== undefined) {
      $("#sr-unrecognized").textContent = d.unrecognized;
      if (!srLoaded && d.unrecognized > 0 && !d.series) $("#sr-box").open = true;
    }
    $("#sr-reset").disabled = !d.series;
    if (force || !srEditing) {
      input.value = d.series || "";
      input.dataset.saved = d.series || "";
      srEditing = false;
    }
    srLoaded = true;
  }

  function initSeries() {
    const input = $("#sr-input");
    input.addEventListener("input", () => { srEditing = input.value !== (input.dataset.saved || ""); });
    const save = async () => {
      const value = input.value.normalize("NFC").split(/\s+/).filter(Boolean).join(" ");
      if (!value) { srMessage("Tên bộ kinh rỗng — dùng \"Bỏ tên\" để bỏ", "error"); return; }
      try {
        const r = await api(`/api/playlists/${encodeURIComponent(playlistId)}/series`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ series: value }) });
        srLoad(r, true);
        srMessage("Đã lưu", "ok");
      } catch (e) { srMessage(e.message, "error"); }
    };
    $("#sr-save").addEventListener("click", save);
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); save(); } });
    $("#sr-reset").addEventListener("click", async () => {
      if (!confirm("Bỏ tên bộ kinh?\n\nTập mà tiêu đề video không nhận ra tên bộ kinh sẽ không tạo được tiêu đề; " +
        "tập đã xử lý bằng tên này sẽ tạo lại tiêu đề AI ở lần chạy sau.")) return;
      try {
        const r = await api(`/api/playlists/${encodeURIComponent(playlistId)}/series`, { method: "DELETE" });
        srLoad(r, true);
        srMessage("Đã bỏ tên", "ok");
      } catch (e) { srMessage(e.message, "error"); }
    });
  }

  async function processEntry(e, btn) {
    if (e.action === "reprocess" && !confirm(`Xử lý lại "${e.title || e.video_id}"?\n\n` +
      "Dữ liệu tập này đã bị xóa: sẽ tải lại video (≈ 700 MB) và chạy lại từ đầu (≈ 25 phút); " +
      "AI có thể chọn đoạn / tiêu đề khác lần trước.")) return;
    // CP8.9 A2.2: "Xử lý" / "Xử lý lại" follow the kind bar; A1.2: "Chạy tiếp" -> only the unfinished ones
    const opts = e.action === "resume" ? (e.resume_kinds ? { kinds: e.resume_kinds } : null) : plKinds();
    if (opts && !opts.kinds.length) return;
    btn.disabled = true;
    try {
      await submitUrl(`https://youtu.be/${e.video_id}`, null, null, "video", opts);
      loadPlaylist();
    } catch (err) {
      btn.disabled = false;
      alert(err.message);
    }
  }

  function entryState(e) {
    if (e.state === "deleted") {
      const base = e.complete ? "✔ Xong (đã xóa dữ liệu)" : "Đã xóa dữ liệu (chưa xong)";
      return `${base} · ${e.shorts} Short, đã đăng ${e.published}/${e.shorts}`;
    }
    let text = PL_STATE[e.state] || e.state;
    if ((e.state === "processing" || e.state === "failed") && e.stage) text += `: ${STAGE_LABELS[e.stage] || e.stage}`;
    if (e.state === "queued" && e.job && e.job.status === "queued") text = "đang chờ trong hàng";
    if (e.state === "processing") { // CP8.10: lane of the running job (Short first, then khai thị)
      const job = [e.job, e.khaithi_job].find((j) => laneLabel(j));
      if (job) {
        const who = job === e.khaithi_job ? "khai thị " : "";
        text = job.waiting ? who + laneLabel(job) : `${who}${laneLabel(job)}: ${STAGE_LABELS[job.stage] || job.stage || ""}`;
      }
    }
    if (e.shorts || e.state === "rendered" || e.state === "complete") text += ` · ${e.shorts} Short, đã đăng ${e.published}/${e.shorts}`;
    if (e.khaithi_state) { // CP8.9 A1.4: the khai thị videos of the same video, counted separately
      text += e.khaithi_videos || e.khaithi_state === "rendered" || e.khaithi_state === "complete"
        ? ` · ${e.khaithi_videos} video khai thị, đã đăng ${e.khaithi_published}/${e.khaithi_videos}`
        : ` · khai thị: ${PL_STATE[e.khaithi_state] || e.khaithi_state}`;
    }
    if (e.archived) text += " · đã dọn nguồn";
    return text;
  }

  async function loadPlaylist() {
    clearTimeout(plTimer);
    let d;
    try { d = await api(`/api/playlists/${encodeURIComponent(playlistId)}`); } catch (e) {
      $("#pl-title").textContent = e.message;
      return;
    }
    document.title = `${d.title || d.id} — Auto Short`;
    $("#pl-title").textContent = d.title || d.id;
    if (htTags === null) htLoad(d); // not while the user edits
    srLoad(d);
    const kd = d.khaithi_defaults; // A2.2: server defaults unless the browser remembers the user's minutes
    if (kd && !plDefaultsApplied) {
      plDefaultsApplied = true;
      let saved = null;
      try { saved = JSON.parse(store("autoShort.plKinds") || "null"); } catch (_) { saved = null; }
      for (const [sel, v] of [["#pl-kt-min", kd.min_minutes], ["#pl-kt-max", kd.max_minutes]]) {
        $(sel).max = kd.max_minutes_limit;
        if (!saved || !saved.min) $(sel).value = v;
      }
    }
    $("#pl-meta").replaceChildren(document.createTextNode(`${d.count} tập · lấy danh sách lúc ${fmtTime(d.fetched_at)} · `),
      el("a", { href: d.url, target: "_blank", rel: "noopener", text: "mở trên YouTube" }));
    document.querySelectorAll("#pl-filters [data-filter]").forEach((b) => { b.querySelector(".n").textContent = d.counts[b.dataset.filter]; });
    let busy = false;
    $("#pl-entries").replaceChildren(...d.entries.map((e) => {
      if (e.state === "queued" || e.state === "processing") busy = true;
      const title = e.title || e.video_id || "(không rõ)";
      const head = e.state === "new" || e.state === "unavailable" || e.state === "deleted" || !e.video_id ? el("span", { class: "ep-name", text: title })
        : el("a", { class: "ep-name", href: "/episodes/" + encodeURIComponent(e.video_id), text: title });
      const actions = el("div", { class: "rec-actions" });
      if (e.action) {
        const b = el("button", { class: "btn small" + (e.action === "process" ? " primary" : ""), type: "button",
          "data-action": e.action, text: { process: "Xử lý", resume: "Chạy tiếp", reprocess: "Xử lý lại" }[e.action] });
        if (e.action !== "resume" && !plKinds().kinds.length) b.disabled = true;
        b.addEventListener("click", () => processEntry(e, b));
        actions.append(b);
      }
      return el("li", { class: "pl-entry " + e.state, "data-group": e.group || "none" },
        el("span", { class: "pl-index muted", text: `${e.index}.` }),
        el("div", { class: "pl-body" }, head,
          el("span", { class: "muted small", text: [e.episode ? `tập ${e.episode}` : null, e.duration ? fmtSeconds(e.duration) : null].filter(Boolean).join(" · ") }),
          e.khaithi_episode_id ? el("a", { class: "kind-label", href: "/episodes/" + encodeURIComponent(e.khaithi_episode_id), text: "Khai thị" }) : null,
          el("span", { class: "pl-state small", text: entryState(e) }),
          e.state === "failed" && e.error ? el("span", { class: "error small", text: e.error }) : null),
        actions);
    }));
    applyPlFilter();
    if (busy) plTimer = setTimeout(loadPlaylist, POLL_MS * 2);
  }

  return { initIndex, initEpisode, initStorage, initPlaylist };
})();
