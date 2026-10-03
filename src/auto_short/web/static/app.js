/* Auto Short web UI (CP8.3; CP8.5 delete / restore, "Đã đăng", episode delete; CP8.6 storage tab, archived
   episodes, low-disk banner; CP9 "Thêm Short" + "Sửa đầu/cuối"). Plain JS, no build step. */
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

  // CP8.21 D5: UI flags from the server (``[web] show_advanced``): "Sửa đầu/cuối" and "Từ điển sửa lỗi" are hidden
  // by default (code and API stay).
  let uiFlags = { advanced: false };
  async function loadUi() {
    try { uiFlags = await fetch("/api/ui", { credentials: "same-origin" }).then((r) => (r.ok ? r.json() : uiFlags)); }
    catch (_) { /* keep the default: hidden */ }
  }

  // CP8.21 D6: inline SVG icons (no dependency); the button carries ``title`` + ``aria-label``.
  const ICONS = {
    download: ["M12 3v12", "M7 10l5 5 5-5", "M5 20h14"],
    trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13", "M10 11v6", "M14 11v6"],
    loop: ["M4 11V9a3 3 0 0 1 3-3h11", "M15 3l3 3-3 3", "M20 13v2a3 3 0 0 1-3 3H6", "M9 21l-3-3 3-3"],
  };
  function icon(name) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: "22", height: "22", fill: "none",
      stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round",
      "aria-hidden": "true", focusable: "false" })) svg.setAttribute(k, v);
    for (const d of ICONS[name]) {
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      svg.append(path);
    }
    return svg;
  }

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
      const err = new Error(msg || `HTTP ${res.status}`);
      err.status = res.status; // CP8.12 U4: the episode page tells a missing episode (404) from other errors
      throw err;
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
    if (job && job.status === "running" && job.hd_wait) return "đợi HD"; // CP13.1b: parked after titling, holds no lane
    if (!job || job.status !== "running" || !job.lane) return null;
    const pos = job.queue_position ? ` (vị trí ${job.queue_position})` : "";
    if (job.waiting && job.lane === "ai") return (job.gpu_wait ? "đợi GPU (mất kết nối)" : "đợi GPU") + pos;
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

  // FIX-ollama-wait O7: warning strip under the disk banner while the ai lane cannot reach Ollama (``gpu`` of the
  // list / episode / bộ kinh API; the pages poll while a job is active, so it also disappears by itself).
  function showGpu(gpu) {
    const anchor = $("#disk-banner");
    if (!anchor) return;
    let box = $("#gpu-banner");
    if (!gpu || gpu.state !== "down") { if (box) box.hidden = true; return; }
    if (!box) {
      box = el("div", { id: "gpu-banner", class: "disk-banner gpu-banner" });
      anchor.after(box);
    }
    const t = gpu.since ? new Date(gpu.since) : null;
    const hhmm = t && !isNaN(t) ? t.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }) : "?";
    box.textContent = `Mất kết nối GPU (Ollama) từ ${hhmm} — tập vẫn được tải / chuẩn bị, phần AI tự chạy tiếp khi GPU có lại (kiểm lại mỗi 60 s).`;
    box.hidden = false;
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
        el("span", { class: "ep-state muted", text: playlistSummary(p) })))));
  }

  // CP8.13 G3: "… · đang xử lý a · lỗi / dở dang b · đang làm c" (a part equal to 0 is left out).
  function playlistSummary(p) {
    return `${p.count} tập · đã xử lý ${p.processed} · Xong ${p.complete}` +
      [["đang xử lý", p.running], ["lỗi / dở dang", p.failed], ["đang làm", p.doing]]
        .filter(([, n]) => n).map(([label, n]) => ` · ${label} ${n}`).join("");
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
    showGpu(data.gpu);
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
    initAddDialog(); // CP9 C7
    loadUi().then(refreshEpisode);
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

  // CP8.12 U1 (replaces the CP8.9 K7 text link): sticky [Shorts | Khai thị] bar. The current page's button is
  // highlighted (aria-current, not a link); the other one links to the other episode of the same video, or is dimmed.
  const KT_GONE_NOTE = "Tập Short của video này đã bị xóa. Muốn có lại Short: gửi lại link video ở trang chủ (chọn Short).";
  let kindBarKey = null;
  let baseCheck = null; // CP8.12 U4: {id, state: "pending" | "ok" | "gone" | "error"}, checked once per page

  function checkBaseEpisode(id) {
    if (baseCheck && baseCheck.id === id) return;
    baseCheck = { id, state: "pending" };
    api("/api/episodes/" + encodeURIComponent(id))
      .then(() => { baseCheck.state = "ok"; })
      .catch((e) => { baseCheck.state = e.status === 404 ? "gone" : "error"; }) // temporary error: keep the link
      .finally(() => { if (lastData) renderKindBar(lastData); });
  }

  function openKtBox() {
    const kb = $("#kt-box");
    kb.open = true;
    kb.scrollIntoView({ block: "center", behavior: "smooth" });
    $("#kt-min").focus({ preventScroll: true });
  }

  function showKindNote(text) {
    const note = $("#kind-note");
    note.textContent = text;
    note.hidden = !text;
  }

  function kindButton(label, spec) {
    if (spec.current) return el("span", { class: "kind-btn current", "aria-current": "page", text: label });
    if (spec.href) return el("a", { class: "kind-btn", href: spec.href, text: label });
    const b = el("button", { class: "kind-btn dim", type: "button", disabled: !!spec.disabled, title: spec.title,
      text: label });
    if (spec.onClick) b.addEventListener("click", spec.onClick);
    return b;
  }

  // CP8.16 R1: the third button "Bài đăng" links to ``/episodes/<id>/posts`` (the same page for both episodes).
  function postsButton(id, current) {
    return current ? kindButton("Bài đăng", { current: true })
      : kindButton("Bài đăng", { href: "/episodes/" + encodeURIComponent(id) + "/posts" });
  }

  function renderKindBar(d) {
    const isKt = d.kind === "khaithi";
    const ktBoxShown = !isKt && !!d.source_url;
    let shorts, kt, key;
    if (isKt) {
      kt = { current: true };
      const base = d.base_episode_id;
      if (base) checkBaseEpisode(base);
      const state = base ? baseCheck.state : null;
      if (!base) shorts = { disabled: true, title: "Không rõ tập Short của video này" };
      else if (state === "gone") shorts = { title: "Tập Short đã bị xóa", onClick: () => showKindNote(KT_GONE_NOTE) };
      else shorts = { href: "/episodes/" + encodeURIComponent(base) };
      key = `kt|${base}|${state === "gone"}`;
    } else {
      shorts = { current: true };
      const other = d.khaithi_episode_id;
      if (other) kt = { href: "/episodes/" + encodeURIComponent(other) };
      else if (ktBoxShown) kt = { title: "Chưa có video khai thị — bấm để tạo", onClick: openKtBox };
      else kt = { disabled: true, title: "Không có link video nguồn" };
      key = `short|${other}|${ktBoxShown}`;
    }
    if (key !== kindBarKey) { // rebuilt only when it changes: polling keeps focus / hover on the buttons
      kindBarKey = key;
      $("#kind-bar").replaceChildren(kindButton("Shorts", shorts), kindButton("Khai thị", kt), postsButton(d.id, false));
      if (!(isKt && baseCheck && baseCheck.state === "gone")) showKindNote("");
    }
    $("#shorts-label").textContent = isKt ? "Video khai thị" : "Shorts";
    $("#kt-box").hidden = !ktBoxShown;
    $("#kt-summary").textContent = d.khaithi_episode_id ? "Tạo lại video khai thị (đổi số phút)" : "Tạo video khai thị từ video này";
  }

  // CP8.12 U2: the stages box is closed when every stage is done and no job is active, open otherwise.
  function stagesShouldOpen(d) {
    const job = d.job;
    if (jobActive(job)) return true;
    if (job && (job.status === "failed" || job.status === "interrupted")) return true;
    const stages = d.stages || [];
    return !stages.length || !stages.every((s) => s.status === "done");
  }

  // Applied on edges only (first render, or the wanted state changed): a poll never undoes the user's own toggle.
  let stagesOpenApplied = null;
  function applyStagesOpen(d) {
    const want = stagesShouldOpen(d);
    if (want === stagesOpenApplied) return;
    stagesOpenApplied = want;
    $("#stages-box").open = want;
  }

  function stagesDoneText(d) {
    const stages = (d && d.stages) || [];
    const total = stages.length || Object.keys(STAGE_LABELS).length;
    return `Các bước xử lý: ${stages.filter((s) => s.status === "done").length}/${total} xong`;
  }

  // The job line is the summary of the stages box; with no job line it falls back to "x/6 xong" (never empty).
  function setJobStatus(text, cls) {
    const box = $("#job-status");
    box.className = "job-status " + (text ? cls || "" : "");
    box.textContent = text || stagesDoneText(lastData);
  }

  // CP8.12 U4: the episode is gone (API 404) → a message + link home instead of the page; polling stops.
  function showEpisodeGone() {
    clearTimeout(pollTimer);
    document.title = "Tập không còn — Auto Short";
    $("main").replaceChildren(el("section", { class: "card gone" },
      el("h2", { text: "Tập này không còn (đã bị xóa hoặc chưa từng xử lý)." }),
      el("p", {}, el("a", { class: "btn", href: "/", text: "← Về trang chủ" }))));
  }

  async function refreshEpisode() {
    clearTimeout(pollTimer);
    let data;
    try {
      data = await api("/api/episodes/" + encodeURIComponent(episodeId));
    } catch (e) {
      if (e.status === 404) { showEpisodeGone(); return; }
      setJobStatus(e.message, "error");
      pollTimer = setTimeout(refreshEpisode, POLL_MS * 4);
      return;
    }
    showGpu(data.gpu);
    renderEpisode(data);
    const running = jobActive(data.job) || data.stages.some((s) => s.status === "running");
    if (running) pollTimer = setTimeout(refreshEpisode, POLL_MS);
    else if (enhanceBusy(data.enhance)) pollTimer = setTimeout(refreshEpisode, POLL_MS * 2);
  }

  // --- CP13.1b enhance (E10): status line + buttons on the episode page ---------------------------------

  const ENHANCE_BUSY = ["queued", "running", "assembling"];
  function enhanceBusy(e) { return !!(e && e.exists && ENHANCE_BUSY.includes(e.state)); }

  function enhanceText(e) {
    const base = e.follows ? ` (chung với video ${e.follows})` : "";
    const wait = e.waiting_hd ? " · đợi HD rồi render" : "";
    if (e.state === "off") return (e.override ? "Enhance đang tắt (bạn đã chọn)." : `Không cần enhance (${e.reason || "nguồn đủ nét"}).`) + base;
    if (e.state === "queued") return "Cần enhance · đợi máy GPU" + wait + base;
    if (e.state === "running") {
      const who = e.gpu || e.worker || "máy GPU";
      return `Đang enhance trên ${who}: ${e.segments_done}/${e.segments_total} đoạn` + wait + base;
    }
    if (e.state === "assembling") return "Đang ghép bản HD…" + wait + base;
    if (e.state === "failed") return `Lỗi ghép bản HD: ${e.error || "?"} (bấm "Bật enhance" để thử lại).` + base;
    if (e.state === "done") {
      const dr = e.rendered_from_hd ? "Short đã dựng từ bản HD." : (e.rendered ? "Short chưa dựng từ bản HD." : "");
      return `Đã enhance${e.finished_at ? ` (${fmtTime(e.finished_at)})` : ""}. ${dr}`.trim() + base;
    }
    return "";
  }

  async function enhancePost(path, body, btn, confirmText) {
    if (confirmText && !confirm(confirmText)) return;
    btn.disabled = true;
    try {
      await api("/api/episodes/" + encodeURIComponent(episodeId) + path, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    } catch (e) { alert(e.message); }
    refreshEpisode();
  }

  function renderEnhance(d) {
    const box = $("#enhance-box");
    const e = d.enhance;
    if (!box) return;
    if (!e || (!e.exists && !e.can_enable)) { box.hidden = true; return; }
    box.hidden = false;
    const busy = jobActive(d.job) && !(d.job && d.job.hd_wait);
    $("#enhance-status").textContent = e.exists ? enhanceText(e) : "Chưa enhance (nguồn này không tự vào hàng đợi).";
    const toggle = $("#enhance-toggle");
    toggle.hidden = !(e.wanted || e.can_enable);
    toggle.textContent = e.wanted ? "Tắt enhance" : "Bật enhance";
    toggle.onclick = () => enhancePost("/enhance", { enabled: !e.wanted }, toggle,
      e.wanted ? "Tắt enhance cho video này (cả Short và khai thị)? Phần đã enhance được giữ." : null);
    const orig = $("#enhance-original");
    orig.hidden = !(e.exists && e.waiting_hd);
    orig.onclick = () => enhancePost("/enhance/render-original", null, orig,
      "Render ngay bằng bản gốc (không đợi HD) và tắt enhance cho video này?");
    const again = $("#enhance-rerender");
    again.hidden = !e.can_rerender;
    again.disabled = busy;
    again.onclick = () => enhancePost("/enhance/rerender", null, again,
      "Render lại từ bản HD? Short đã đăng sẽ thành \"đã đăng bản cũ\".");
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
    renderKindBar(d);

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
    applyStagesOpen(d);

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
      an.textContent = `${d.archived.auto ? "Đã tự dọn video nguồn" : "Đã dọn video nguồn"}${d.archived.freed ? ` (giải phóng ${fmtBytes(d.archived.freed)})` : ""}` +
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
    renderEnhance(d);
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
  // CP8.13 G5: "Lặp lại" per video (clip_id -> on), kept while the page is open (a card rebuilt by a poll reads it
  // back); off by default, never stored.
  const loops = new Map();

  function cardKey(s) {
    return JSON.stringify([s.status, s.sha256, s.title, s.pending_title, s.override, s.rendering, s.editable,
      s.alternatives.length, s.deleted, s.rejected, s.published, s.published_stale, s.watched, s.watched_stale, s.download_name, archived, uiFlags.advanced,
      s.origin, s.cut]);
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
    // CP8.17 D3/D4: a zip no longer ticks "Đã đăng" (nothing to refresh); the label says what the zip holds
    zip.textContent = d.kind === "khaithi" ? "Tải tất cả khai thị (.zip)" : "Tải tất cả Short (.zip)";
    const zipAll = $("#zip-all"); // CP8.17 D5: Shorts/ + KhaiThị/ in one zip (hidden when either kind is missing)
    zipAll.hidden = !d.zip_all_url;
    if (d.zip_all_url) { zipAll.href = d.zip_all_url; zipAll.setAttribute("download", d.zip_all_name || ""); }
    $("#header-lines").textContent = d.header ? "Header: " + d.header.join(" / ") : "";
    // CP9 C7: "Thêm Short" once the episode has a render and titles (not on an archived episode)
    const addBtn = $("#add-short");
    addBtn.hidden = !d.shorts.length || !!d.titles_error || archived;
    addBtn.textContent = d.kind === "khaithi" ? "+ Thêm video khai thị" : "+ Thêm Short";
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
    $("#add-short").disabled = locked;
    document.querySelectorAll("#add-dialog .needs-idle").forEach((b) => { b.disabled = locked || b.dataset.invalid === "1"; });
    document.querySelectorAll("#add-dialog .lock-note").forEach((n) => { n.hidden = !locked; });
    document.querySelectorAll(".short .needs-idle").forEach((b) => { b.disabled = locked || b.dataset.invalid === "1"; });
    document.querySelectorAll(".short .lock-note").forEach((n) => { n.hidden = !locked; });
  }

  // One card per Short; ``.title-edit`` holds the title editor (CP8.2 functions via the API).
  function shortCard(s) {
    const title = s.title || {};
    const card = el("article", { class: "short" + (s.rendering ? " rendering" : ""), "data-clip": s.clip_id });
    const media = el("div", { class: "short-media" });
    let video = null;
    if (s.status === "rendered") {
      video = el("video", { controls: true, preload: "metadata", playsinline: true, src: s.video_url });
      media.append(video);
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
        s.origin === "added" ? el("span", { class: "badge added", text: "thêm tay" }) : null,
        s.cut ? el("span", { class: "badge cut", text: "đã sửa đầu/cuối" }) : null,
        el("span", { class: "muted small", text: fmtSeconds(s.duration) })),
      el("div", { class: "title-row" },
        el("p", { class: "short-title", text: title.text || "(không có tiêu đề)" }),
        s.copy_text ? copyTitleButton(s.copy_text) : null),
      s.hashtags && s.hashtags.length ? el("p", { class: "hashtags small muted", text: s.hashtags.join(" ") }) : null,
      s.pending_title ? el("p", { class: "pending small", text: s.pending_title.text
        ? `Tiêu đề mới (${TITLE_SOURCE_LABELS[s.pending_title.origin] || s.pending_title.origin}), chưa render: ${s.pending_title.text}`
        : "Sẽ bỏ qua ở lần render tới (không có tiêu đề)" }) : null,
      s.status === "rendered" || s.published ? publishBox(s, video) : null,
      el("div", { class: "short-actions" },
        s.download_url ? downloadLink(s) : null,
        video ? loopButton(s.clip_id, video) : null,
        s.editable && !(archived && s.deleted) ? deleteButton(s) : null),
      s.editable && !s.deleted && !archived ? titleEditor(s) : el("div", { class: "title-edit", hidden: true }),
      s.editable && !s.deleted && !archived && uiFlags.advanced ? cutEditor(s) : null);
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

  // ``onCopied`` (CP8.17 D1) runs only when the copy really succeeded (not in the "Giữ vào ô để copy" fallback).
  function copyTitleButton(text, onCopied) {
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
        if (onCopied) onCopied();
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

  // CP8.13 G5: toggle ``video.loop`` of this card (only playback: no request, no card rebuild).
  function loopButton(clipId, video) {
    const on = loops.get(clipId) === true;
    video.loop = on;
    const b = el("button", { class: "btn icon-btn loop-btn", type: "button", "aria-pressed": on ? "true" : "false",
      title: "Lặp lại", "aria-label": "Lặp lại" }, icon("loop"));
    b.addEventListener("click", () => {
      const next = loops.get(clipId) !== true;
      loops.set(clipId, next);
      video.loop = next;
      b.setAttribute("aria-pressed", next ? "true" : "false");
    });
    return b;
  }

  // CP8.7: a download ticks "Đã đăng" server-side; show it on the next refresh.
  function downloadLink(s) {
    const a = el("a", { class: "btn icon-btn", href: s.download_url, download: s.download_name || "", title: "Tải về",
      "aria-label": "Tải về" }, icon("download"));
    a.addEventListener("click", () => setTimeout(refreshEpisode, 1500));
    return a;
  }

  // "Đã đăng" (X4): user state only, no job, allowed while a job runs; updated in place (no card rebuild).
  function publishBox(s, video) {
    const box = el("div", { class: "publish" });
    const input = el("input", { type: "checkbox", checked: s.published });
    input.disabled = s.status !== "rendered" && !s.published;
    const label = el("label", { class: "publish-label" }, input, " Đã đăng");
    const stale = el("span", { class: "stale small", hidden: !s.published_stale }, "đã đăng bản cũ ");
    const renew = el("button", { class: "btn link-dark small", type: "button", text: "đánh dấu bản này" });
    stale.append(renew);
    const msg = el("span", { class: "error small", hidden: true });
    box.append(label, stale, msg);
    if (video) box.append(watchedControl(s, video));
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

  // CP8.21 D4 "Đã xem": user state (``watched.json``), no job; ticked by hand or when the video plays to its end
  // for the first time. ``ended`` does not fire while "Lặp lại" is on (loop), so a wrap from the end back to the
  // start counts as well.
  function watchedControl(s, video) {
    const wrap = el("span", { class: "watched" });
    const input = el("input", { type: "checkbox", checked: s.watched });
    const label = el("label", { class: "publish-label" }, input, " Đã xem");
    const stale = el("span", { class: "stale small", hidden: !s.watched_stale }, "đã xem bản cũ ");
    const renew = el("button", { class: "btn link-dark small", type: "button", text: "đánh dấu bản này" });
    stale.append(renew);
    const msg = el("span", { class: "error small", hidden: true });
    wrap.append(label, stale, msg);
    let busy = false;
    async function send(value) {
      busy = true;
      input.disabled = renew.disabled = true;
      msg.hidden = true;
      try {
        const r = await api(`/api/episodes/${encodeURIComponent(episodeId)}/shorts/${encodeURIComponent(s.clip_id)}/watched`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value }),
        });
        s.watched = r.watched; s.watched_stale = r.stale; s.watched_at = r.at;
        const entry = cards.get(s.clip_id);
        if (entry) entry.key = cardKey(s);
      } catch (e) {
        msg.textContent = e.message;
        msg.hidden = false;
      }
      input.checked = s.watched;
      stale.hidden = !s.watched_stale;
      input.disabled = renew.disabled = false;
      busy = false;
    }
    input.addEventListener("change", () => send(input.checked));
    renew.addEventListener("click", () => send(true));
    const finished = () => { if (!busy && (!s.watched || s.watched_stale)) send(true); };
    let prev = 0;
    video.addEventListener("ended", finished);
    video.addEventListener("timeupdate", () => {
      const t = video.currentTime, d = video.duration;
      if (video.loop && d > 0 && prev >= d * 0.85 && t < prev * 0.5) finished();
      prev = t;
    });
    return wrap;
  }

  // Delete (X2, soft: review.json + render job that removes the mp4) / restore (render job re-encodes it).
  function deleteButton(s) {
    const restore = s.deleted;
    const btn = restore
      ? el("button", { class: "btn small needs-idle", type: "button", text: "Khôi phục" })
      : el("button", { class: "btn icon-btn needs-idle danger", type: "button", title: `Xóa ${noun()}`,
        "aria-label": `Xóa ${noun()}` }, icon("trash")); // CP8.21 D6
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

  // --- CP9: "Sửa đầu/cuối" + "Thêm Short" -------------------------------------------------------------

  function fmtClock(t) {
    const neg = t < 0;
    t = Math.abs(t);
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
    const ss = sec.toFixed(1).padStart(4, "0");
    return (neg ? "−" : "") + (h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`);
  }
  function fmtNudge(n) { return n ? ` (${n > 0 ? "+" : "−"}${Math.abs(n).toFixed(1)} s)` : ""; }

  // "Nghe thử": the source video (Range) between a and b via a media fragment (#t=a,b stops at b), in a small
  // floating player shared by the cut editors and the "Thêm Short" dialog. play() runs inside the click (phones).
  function playSource(a, b, label) {
    const box = $("#source-float"), v = $("#source-video");
    const t0 = Math.max(0, a), t1 = Math.max(t0 + 0.5, b);
    $("#source-label").textContent = `${label}: ${fmtClock(t0)} → ${fmtClock(t1)}`;
    box.hidden = false;
    v.src = `/files/${encodeURIComponent(episodeId)}/source.mp4#t=${t0.toFixed(2)},${t1.toFixed(2)}`;
    const p = v.play();
    if (p && p.catch) p.catch(() => { /* the user presses play on the player */ });
  }
  function listenButtons(get) { // get() -> {start, end} | null
    const bs = el("button", { class: "btn small", type: "button", text: "▶ Nghe 5 s đầu" });
    const be = el("button", { class: "btn small", type: "button", text: "▶ Nghe 5 s cuối" });
    bs.addEventListener("click", () => { const r = get(); if (r) playSource(r.start, Math.min(r.start + 5, r.end), "5 s đầu"); });
    be.addEventListener("click", () => { const r = get(); if (r) playSource(Math.max(r.end - 5, r.start), r.end, "5 s cuối"); });
    return [bs, be];
  }

  async function loadTranscript() {
    return api("/api/episodes/" + encodeURIComponent(episodeId) + "/transcript");
  }
  async function previewCut(body) {
    return api("/api/episodes/" + encodeURIComponent(episodeId) + "/cut/preview", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  }
  function speechStep(segs, i, dir) {
    let j = i + dir;
    while (j >= 0 && j < segs.length && segs[j].kind !== "speech") j += dir;
    return j >= 0 && j < segs.length ? j : i;
  }
  function rangeInfo(p, limits) {
    const nodes = [el("span", { text: `Thời lượng: ${fmtSeconds(p.duration)} (${p.duration.toFixed(1)} s)` +
      (limits ? `, cần ${limits}` : "") })];
    if (p.error) nodes.push(el("div", { class: "error", text: "Không lưu được: " + p.error }));
    for (const w of p.warnings || []) nodes.push(el("div", { class: "warn", text: "Lưu ý: " + w }));
    return nodes;
  }
  function limitsText(tr) { return tr && tr.min_duration ? `${fmtSeconds(tr.min_duration)}–${fmtSeconds(tr.max_duration)}` : ""; }

  // One Short: first / last caption line with [+ dòng] [− dòng] [−0.2 s] [+0.2 s], new duration, "Nghe thử",
  // "Lưu + render lại", "Về như AI chọn" (C7). The server computes every range (preview), the page only steps.
  function cutEditor(s) {
    const box = el("div", { class: "cut-edit" });
    const toggle = el("button", { class: "btn small", type: "button", text: "Sửa đầu/cuối" });
    const panel = el("div", { class: "cut-panel", hidden: true });
    box.append(toggle, panel);
    let st = null;
    toggle.addEventListener("click", async () => {
      if (!panel.hidden) { panel.hidden = true; toggle.textContent = "Sửa đầu/cuối"; return; }
      panel.hidden = false;
      toggle.textContent = "Đóng sửa đầu/cuối";
      panel.replaceChildren(el("p", { class: "muted small", text: "Đang tải phụ đề…" }));
      try { open(await loadTranscript()); } catch (e) { panel.replaceChildren(el("p", { class: "error small", text: e.message })); }
    });

    function edgeRow(label, which) {
      const text = el("div", { class: "cut-text" });
      const time = el("span", { class: "muted small" });
      const more = el("button", { class: "btn small", type: "button", text: "+ dòng", title: which === "a" ? "Thêm dòng phía trước" : "Thêm dòng phía sau" });
      const less = el("button", { class: "btn small", type: "button", text: "− dòng", title: "Bớt một dòng" });
      const minus = el("button", { class: "btn small", type: "button", text: "−0.2 s" });
      const plus = el("button", { class: "btn small", type: "button", text: "+0.2 s" });
      more.addEventListener("click", () => step(which, which === "a" ? -1 : 1));
      less.addEventListener("click", () => step(which, which === "a" ? 1 : -1));
      minus.addEventListener("click", () => nudge(which, -1));
      plus.addEventListener("click", () => nudge(which, 1));
      const row = el("div", { class: "cut-row" }, el("div", { class: "cut-label" }, el("b", { text: label }), " ", time), text,
        el("div", { class: "cut-buttons" }, more, less, minus, plus));
      return { row, text, time, more, less, minus, plus };
    }

    function open(tr) {
      const me = tr.shorts.find((x) => x.clip_id === s.clip_id);
      if (!me || !me.start_segment) {
        panel.replaceChildren(el("p", { class: "error small", text: "Không tìm thấy dòng phụ đề của Short này." }));
        return;
      }
      const idx = new Map(tr.segments.map((g, i) => [g.id, i]));
      st = { tr, me, a: idx.get(me.start_segment), b: idx.get(me.end_segment), dn0: 0, dn1: 0, seq: 0, p: null };
      st.ra = edgeRow("Đầu", "a");
      st.rb = edgeRow("Cuối", "b");
      st.info = el("div", { class: "cut-info small" });
      const [ls, le] = listenButtons(() => st.p);
      st.save = el("button", { class: "btn primary small needs-idle", type: "button", text: "Lưu + render lại" });
      st.save.addEventListener("click", () => send(false));
      st.reset = me.cut ? el("button", { class: "btn small needs-idle", type: "button", text: "Về như AI chọn" }) : null;
      if (st.reset) st.reset.addEventListener("click", () => send(true));
      const lockNote = el("p", { class: "lock-note muted small", text: "Đang có job chạy — đợi xong để lưu.", hidden: !editsLocked });
      panel.replaceChildren(st.ra.row, st.rb.row, st.info, el("div", { class: "edit-actions" }, ls, le),
        el("div", { class: "edit-actions" }, st.save, st.reset), lockNote);
      update();
    }
    function step(which, dir) {
      const segs = st.tr.segments;
      if (which === "a") { const j = speechStep(segs, st.a, dir); if (j <= st.b) { st.a = j; st.dn0 = 0; } }
      else { const j = speechStep(segs, st.b, dir); if (j >= st.a) { st.b = j; st.dn1 = 0; } }
      update();
    }
    function nudge(which, dir) {
      const key = which === "a" ? "dn0" : "dn1";
      st[key] = Math.max(-10, Math.min(10, st[key] + dir)); // steps of 0.2 s, at most ±2.0 s (C3)
      update();
    }
    function body() {
      return { start_segment: st.tr.segments[st.a].id, end_segment: st.tr.segments[st.b].id,
        start_nudge: +(st.dn0 * 0.2).toFixed(1), end_nudge: +(st.dn1 * 0.2).toFixed(1) };
    }
    function setSave(ok) { st.save.dataset.invalid = ok ? "0" : "1"; st.save.disabled = !ok || editsLocked; }
    async function update() {
      const segs = st.tr.segments;
      st.ra.text.textContent = segs[st.a].text;
      st.rb.text.textContent = segs[st.b].text;
      st.ra.minus.disabled = st.dn0 <= -10; st.ra.plus.disabled = st.dn0 >= 10;
      st.rb.minus.disabled = st.dn1 <= -10; st.rb.plus.disabled = st.dn1 >= 10;
      setSave(false);
      const my = ++st.seq;
      st.info.replaceChildren(el("span", { class: "muted", text: "Đang tính…" }));
      try {
        const p = await previewCut({ clip_id: s.clip_id, ...body() });
        if (my !== st.seq) return;
        st.p = p;
        st.ra.time.textContent = fmtClock(p.start) + fmtNudge(st.dn0 * 0.2);
        st.rb.time.textContent = fmtClock(p.end) + fmtNudge(st.dn1 * 0.2);
        const nodes = rangeInfo(p, limitsText(st.tr));
        if (!p.changed) nodes.push(el("div", { class: "muted", text: "Chưa đổi gì so với bản hiện tại." }));
        else if (p.original) nodes.push(el("div", { class: "muted", text: "Trở về đúng đoạn AI chọn." }));
        st.info.replaceChildren(...nodes);
        setSave(!p.error && p.changed);
      } catch (e) {
        if (my !== st.seq) return;
        st.p = null;
        st.info.replaceChildren(el("div", { class: "error", text: e.message }));
      }
    }
    async function send(reset) {
      st.save.disabled = true;
      if (st.reset) st.reset.disabled = true;
      try {
        await api(`/api/episodes/${encodeURIComponent(episodeId)}/shorts/${encodeURIComponent(s.clip_id)}/cut`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reset ? { reset: true } : body()),
        });
        st.info.replaceChildren(el("div", { text: "Đã lưu, đang render lại…" }));
        refreshEpisode();
      } catch (e) {
        st.info.replaceChildren(el("div", { class: "error", text: e.message }));
        setSave(!!st.p && !st.p.error && st.p.changed);
        if (st.reset) st.reset.disabled = editsLocked;
      }
    }
    return box;
  }

  // --- CP8.15 / CP8.16: tab "Bài đăng" (community post text of every Short + khai thị of one video) ------------

  function postsUrlFor(id, suffix) { return `/api/episodes/${encodeURIComponent(id)}/posts${suffix || ""}`; }

  function jsonBody(method, obj) {
    return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(obj) };
  }

  function postBadges(p) {
    const nodes = [];
    if (p.origin === "doc") nodes.push(el("span", { class: "badge", text: "Văn bản gốc" }));
    if (p.origin === "raw") nodes.push(el("span", { class: "badge stale-badge", text: "AI không chắc — kiểm lại" }));
    if (p.low_punctuation) nodes.push(el("span", { class: "badge stale-badge", text: "Ít dấu câu — kiểm lại" }));
    if (p.stale) {
      nodes.push(el("span", { class: "badge stale-badge", text: p.posted
        ? "Text nguồn đã đổi (bài đã đăng, giữ nguyên)" : "Text nguồn đã đổi — soạn lại" }));
    }
    if (p.image_missing) nodes.push(el("span", { class: "badge stale-badge", text: "Thiếu ảnh" }));
    return nodes;
  }

  const postsPage = { vid: null, groups: [], autoTried: false, timer: null, nodes: new Map(), loaded: false };

  function renderedOf(g) { return g.view.shorts.filter((s) => s.status === "rendered"); }

  // Decides only whether the page *asks* the server to compose (R2b); which Shorts get composed is the server's
  // canonical ``clips: "auto"`` set (CP8.16 R4), so over-asking is harmless (the job composes nothing).
  function needsCompose(g) {
    const byClip = new Map(g.posts.map((p) => [p.clip_id, p]));
    return renderedOf(g).some((s) => {
      const p = byClip.get(s.clip_id);
      return !p || (p.stale && !p.posted && p.origin !== "manual");
    });
  }

  function pipelineActive(g) { return jobActive(g.view.job) && g.view.job.kind === "pipeline"; }

  async function fetchPostGroup(id, label) {
    let view;
    try { view = await api("/api/episodes/" + encodeURIComponent(id)); } catch (e) {
      if (e.status === 404) return null;
      throw e;
    }
    const g = { id, label, view, posts: [], postError: null };
    if (view.shorts.some((s) => s.status === "rendered")) {
      const d = await api(postsUrlFor(id));
      g.posts = d.posts;
      g.postError = d.post_error;
    }
    return g;
  }

  function postsMsg(text, cls) {
    const m = $("#posts-msg");
    m.textContent = text || "";
    m.className = "small " + (cls || "");
    m.hidden = !text;
  }

  function postJobLine(g) {
    const j = g.view.post_job;
    if (!j) return null;
    if (j.status === "queued") return { text: `${g.label}: đang đợi soạn bài (vị trí ${j.queue_position || "?"})`, cls: "busy" };
    if (j.status === "running" && j.waiting) return { text: `${g.label}: soạn bài — ${laneLabel(j) || "đợi GPU"}`, cls: "busy" };
    if (j.status === "running") return { text: `${g.label}: đang soạn bài…`, cls: "busy" };
    if (j.status === "failed") return { text: `${g.label}: soạn bài lỗi — ${j.error}. Bấm "Soạn bài còn thiếu" hoặc "Soạn lại" để thử lại.`, cls: "error" };
    return null;
  }

  function anyPostWork() {
    return postsPage.groups.some((g) => jobActive(g.view.post_job) || jobActive(g.view.job));
  }

  function updatePostsHead() {
    const groups = postsPage.groups;
    const total = groups.reduce((n, g) => n + renderedOf(g).length, 0);
    const posted = groups.reduce((n, g) => n + g.posts.filter((p) => p.posted).length, 0);
    $("#posts-count").textContent = total ? `Đã đăng ${posted} / ${total}` : "";
    const btn = $("#posts-compose-missing");
    btn.hidden = !total;
    btn.disabled = groups.some((g) => jobActive(g.view.post_job));
    const lines = groups.map(postJobLine).filter(Boolean);
    $("#posts-jobs").replaceChildren(...lines.map((l) => el("p", { class: l.cls, text: l.text })));
    const titles = groups.map((g) => g.view.title).filter(Boolean);
    $("#posts-meta").textContent = titles.length ? titles[0] : postsPage.vid;
  }

  function postsKindBar() {
    const groups = postsPage.groups;
    const shortG = groups.find((g) => g.id === postsPage.vid);
    const ktG = groups.find((g) => g.id !== postsPage.vid);
    const shorts = shortG ? { href: "/episodes/" + encodeURIComponent(postsPage.vid) }
      : { disabled: true, title: "Không có tập Short của video này" };
    const kt = ktG ? { href: "/episodes/" + encodeURIComponent(ktG.id) }
      : { disabled: true, title: "Chưa có video khai thị" };
    $("#kind-bar").replaceChildren(kindButton("Shorts", shorts), kindButton("Khai thị", kt), postsButton(episodeId, true));
  }

  function renderPostsPage() {
    postsKindBar();
    updatePostsHead();
    const root = $("#post-groups");
    const groups = postsPage.groups.filter((g) => renderedOf(g).length);
    if (!groups.length) {
      postsPage.nodes.clear();
      root.replaceChildren(el("section", { class: "card" }, el("p", { class: "muted",
        text: "Chưa có Short nào dựng xong để soạn bài đăng." })));
      return;
    }
    const seen = new Set();
    const sections = groups.map((g) => {
      const byClip = new Map(g.posts.map((p) => [p.clip_id, p]));
      const cards = renderedOf(g).map((s) => {
        const cur = byClip.get(s.clip_id) || null;
        const id = g.id + "|" + s.clip_id;
        seen.add(id);
        const key = JSON.stringify([cur, s.title && s.title.text, s.video_url, jobActive(g.view.post_job)]);
        const old = postsPage.nodes.get(id);
        if (old && old.key === key) return old.node;
        const node = postCard(g, s, cur);
        postsPage.nodes.set(id, { key, node });
        return node;
      });
      const head = el("div", { class: "shorts-head" }, el("h2", { text: g.label }),
        g.postError ? el("p", { class: "error small", text: "Lỗi đọc bài đăng: " + g.postError }) : null);
      return el("section", { class: "card" }, head, el("div", { class: "posts-list" }, ...cards));
    });
    for (const id of [...postsPage.nodes.keys()]) if (!seen.has(id)) postsPage.nodes.delete(id);
    root.replaceChildren(...sections);
  }

  async function loadPostsPage() {
    clearTimeout(postsPage.timer);
    let groups;
    try {
      groups = (await Promise.all([fetchPostGroup(postsPage.vid, "Shorts"),
        fetchPostGroup(postsPage.vid + ".kt", "Khai thị")])).filter(Boolean);
    } catch (e) {
      postsMsg(e.message, "error");
      postsPage.timer = setTimeout(loadPostsPage, POLL_MS * 4);
      return;
    }
    postsPage.groups = groups;
    postsPage.loaded = true;
    showGpu((groups[0] && groups[0].view || {}).gpu);
    renderPostsPage();
    if (!postsPage.autoTried) { // R2b: once per page load, for each episode that lacks / needs posts
      postsPage.autoTried = true;
      if (await autoCompose(groups, false)) return;
    }
    if (anyPostWork()) postsPage.timer = setTimeout(loadPostsPage, POLL_MS);
  }

  // Sends ``clips: "auto"`` for every episode that needs it and has no active compose job (nor a running pipeline,
  // which would answer 409 and triggers the compose itself when it ends). Returns true when it queued a job (the
  // page was reloaded).
  async function autoCompose(groups, report) {
    let queued = false;
    const errors = [];
    for (const g of groups) {
      if (!renderedOf(g).length || jobActive(g.view.post_job) || pipelineActive(g) || !needsCompose(g)) continue;
      try {
        await api(postsUrlFor(g.id), jsonBody("POST", { clips: "auto" }));
        queued = true;
      } catch (e) { errors.push(`${g.label}: ${e.message}`); }
    }
    if (errors.length) postsMsg("Không soạn được bài: " + errors.join("; "), "error");
    else if (report) postsMsg(queued ? "Đã xếp soạn bài." : "Không có bài nào cần soạn.", "");
    if (queued) await loadPostsPage();
    return queued;
  }

  async function composeMissing() {
    const btn = $("#posts-compose-missing");
    btn.disabled = true;
    postsMsg("");
    try { await autoCompose(postsPage.groups, true); } finally { updatePostsHead(); }
  }

  function initPosts() {
    episodeId = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
    postsPage.vid = episodeId.endsWith(".kt") ? episodeId.slice(0, -3) : episodeId;
    initImageDialog();
    $("#posts-compose-missing").addEventListener("click", composeMissing);
    initCorrections();
    loadUi().then(() => { $("#corr-open").hidden = !uiFlags.advanced; }); // CP8.21 D5
    checkDisk();
    loadPostsPage();
  }

  // --- CP8.18 D7: correction dictionary dialog ---------------------------------------------------------------

  function corrMsg(text, cls) {
    const m = $("#corr-msg");
    m.textContent = text || "";
    m.className = "small " + (cls || "");
    m.hidden = !text;
  }

  function setCorrectionsButton(proposed) {
    $("#corr-open").textContent = proposed ? `Từ điển sửa lỗi (${proposed} đề xuất)` : "Từ điển sửa lỗi";
  }

  async function refreshCorrectionsCount() {
    try {
      const d = await api("/api/post-corrections");
      setCorrectionsButton(d.rules.filter((r) => r.status === "proposed").length);
      return d;
    } catch (_) { return null; }
  }

  function closeCorrections() {
    $("#corr-dialog").hidden = true;
    document.body.classList.remove("modal-open");
  }

  function initCorrections() {
    $("#corr-open").addEventListener("click", openCorrections);
    $("#corr-close").addEventListener("click", closeCorrections);
    $("#corr-add-btn").addEventListener("click", async () => {
      const body = { from: $("#corr-add-from").value, to: $("#corr-add-to").value };
      try {
        const d = await api("/api/post-corrections", jsonBody("POST", body));
        $("#corr-add-from").value = "";
        $("#corr-add-to").value = "";
        await corrApplied(d.applied);
      } catch (e) { corrMsg(e.message, "error"); }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !$("#corr-dialog").hidden) closeCorrections();
    });
    refreshCorrectionsCount();
  }

  async function openCorrections() {
    $("#corr-dialog").hidden = false;
    document.body.classList.add("modal-open");
    corrMsg("");
    await loadCorrections();
  }

  async function corrApplied(applied) {
    if (applied) {
      corrMsg(`Đã sửa ${applied.places} chỗ trong ${applied.posts} bài chưa đăng`, "");
      loadPostsPage();
    } else corrMsg("");
    await loadCorrections();
  }

  async function corrUpdate(id, body) {
    try {
      const d = await api("/api/post-corrections/" + encodeURIComponent(id), jsonBody("PUT", body));
      await corrApplied(d.applied);
    } catch (e) { corrMsg(e.message, "error"); }
  }

  async function corrDelete(id) {
    if (!confirm("Xóa luật này? Các bài đã sửa không bị hoàn tác.")) return;
    try {
      await api("/api/post-corrections/" + encodeURIComponent(id), { method: "DELETE" });
      corrMsg("");
      await loadCorrections();
    } catch (e) { corrMsg(e.message, "error"); }
  }

  function corrButton(label, cls, fn) {
    const b = el("button", { class: "btn small " + cls, type: "button", text: label });
    b.addEventListener("click", fn);
    return b;
  }

  function corrExamples(r) {
    const ex = (r.examples || []).map((e) => `${e.episode_id}/${e.clip_id}`);
    return `${r.count} lần` + (ex.length ? " · " + ex.join(", ") : "");
  }

  function proposedRow(r) {
    const from = el("input", { type: "text", value: r.from, "aria-label": "Cụm sai" });
    const to = el("input", { type: "text", value: r.to, "aria-label": "Cụm đúng" });
    from.value = r.from;
    to.value = r.to;
    return el("div", { class: "corr-row" },
      el("div", { class: "corr-pair", text: `${r.from} → ${r.to}` }),
      el("div", { class: "muted small", text: corrExamples(r) }),
      el("div", { class: "edit-actions" }, from, to),
      el("div", { class: "edit-actions" },
        corrButton("Duyệt", "primary", () => {
          const body = { status: "approved" };
          if (from.value !== r.from) body.from = from.value;
          if (to.value !== r.to) body.to = to.value;
          corrUpdate(r.id, body);
        }),
        corrButton("Bỏ qua", "", () => corrUpdate(r.id, { status: "rejected" }))));
  }

  function approvedRow(r) {
    return el("div", { class: "corr-row" },
      el("div", { class: "corr-pair", text: `${r.from} → ${r.to}` }),
      el("div", { class: "muted small", text: corrExamples(r) }),
      el("div", { class: "edit-actions" },
        corrButton("Bỏ duyệt", "", () => corrUpdate(r.id, { status: "proposed" })),
        corrButton("Xóa", "danger", () => corrDelete(r.id))));
  }

  async function loadCorrections() {
    let d;
    try { d = await api("/api/post-corrections"); } catch (e) { corrMsg(e.message, "error"); return; }
    if (d.error) corrMsg(d.error, "error");
    const proposed = d.rules.filter((r) => r.status === "proposed");
    const approved = d.rules.filter((r) => r.status === "approved");
    setCorrectionsButton(proposed.length);
    const none = (t) => el("p", { class: "muted small", text: t });
    $("#corr-proposed").replaceChildren(...(proposed.length ? proposed.map(proposedRow) : [none("Chưa có đề xuất.")]));
    $("#corr-approved").replaceChildren(...(approved.length ? approved.map(approvedRow) : [none("Chưa có luật nào được duyệt.")]));
    const st = d.stats || {};
    $("#corr-stats").textContent = st.avg_changed_pct === null || st.avg_changed_pct === undefined
      ? "Chưa có số đo (chưa lưu đoạn nào)."
      : `Trung bình bạn sửa ${st.avg_changed_pct}% từ mỗi bài (${Math.min(st.saves, 20)} lần lưu gần nhất).`;
  }

  // --- CP8.17 D1/D2: "Đã đăng bài" ticks itself once the post text was copied AND its image downloaded -----------
  // Marks live in the browser (localStorage, memory fallback): per post ``{copy: <text copied>, image: <image
  // downloaded>}``; a mark only counts while the post still has that text / image. No image to download -> the
  // copy alone is enough (D2 = a). The marks of a post are cleared once it ticks, so an un-tick by hand sticks.
  const POST_MARKS_KEY = "autoShort.postMarks";
  let postMarksMem = {};

  function readPostMarks() {
    try {
      const raw = localStorage.getItem(POST_MARKS_KEY);
      const v = raw ? JSON.parse(raw) : {};
      if (v && typeof v === "object" && !Array.isArray(v)) postMarksMem = v;
    } catch (_) { /* keep the in-memory marks */ }
    return postMarksMem;
  }

  function writePostMarks(marks) {
    postMarksMem = marks;
    try { localStorage.setItem(POST_MARKS_KEY, JSON.stringify(marks)); } catch (_) { /* memory only */ }
  }

  function setPostMark(key, kind, value) {
    const marks = readPostMarks();
    marks[key] = { ...(marks[key] || {}), [kind]: value };
    writePostMarks(marks);
  }

  function clearPostMark(key) {
    const marks = readPostMarks();
    if (key in marks) { delete marks[key]; writePostMarks(marks); }
  }

  // True when the marks of ``key`` cover ``post`` (the stored post: text, image, image_missing).
  function postMarksDone(key, post) {
    const mark = readPostMarks()[key] || {};
    if (!post || typeof post.text !== "string" || mark.copy !== post.text) return false;
    const hasImage = !!post.image && !post.image_missing;
    return !hasImage || mark.image === post.image;
  }

  // One Short's post card: title + "Xem Short" + the editor (paragraphs, image, link, copy, "Soạn lại", "Đã đăng bài"),
  // always open. ``cur`` = the stored post (view of ``GET …/posts``) or null (not composed yet).
  function postCard(g, s, cur) {
    const url = (suffix) => `${postsUrlFor(g.id)}/${encodeURIComponent(s.clip_id)}${suffix || ""}`;
    const card = el("article", { class: "post-card", "data-clip": s.clip_id });
    const head = el("div", { class: "short-head" },
      el("span", { class: "clip-id", text: s.clip_id }),
      s.video_url ? el("a", { class: "btn small", href: s.video_url, target: "_blank", rel: "noopener",
        text: g.view.kind === "khaithi" ? "Xem Khai thị" : "Xem Short" }) : null);
    card.append(head, el("p", { class: "short-title", text: (s.title && s.title.text) || "(không có tiêu đề)" }));
    const panel = el("div", { class: "post-panel" });
    card.append(panel);

    function changed(next) { // keep the page state (count, next poll) in step with an edit
      cur = next;
      const i = g.posts.findIndex((p) => p.clip_id === s.clip_id);
      if (i >= 0) g.posts[i] = next; else g.posts.push(next);
      updatePostsHead();
    }

    function render() {
      if (!cur) {
        const busy = jobActive(g.view.post_job);
        const btn = el("button", { class: "btn primary small", type: "button", text: "Soạn bài" });
        btn.disabled = busy;
        const msg = el("p", { class: "error small", hidden: true });
        btn.addEventListener("click", () => compose(btn, msg));
        panel.replaceChildren(...[el("p", { class: "muted small", text: busy ? "Đang đợi / đang soạn bài…" : "Chưa có bài đăng cho Short này." }),
          busy ? null : btn, msg].filter(Boolean));
        return;
      }
      const textarea = el("textarea", { class: "post-textarea", "aria-label": "Các đoạn của bài đăng" });
      textarea.value = cur.paragraphs.join("\n\n");
      const save = el("button", { class: "btn small", type: "button", text: "Lưu đoạn" });
      const saveMsg = el("span", { class: "small", hidden: true });
      save.addEventListener("click", () => saveParagraphs(textarea, save, saveMsg));

      const img = el("div", { class: "post-image" });
      if (cur.image && !cur.image_missing) {
        img.append(el("img", { src: `/files/post-images/${encodeURIComponent(cur.image)}`, alt: "" }));
      } else {
        img.append(el("span", { class: "muted small",
          text: cur.image_missing ? "Ảnh đã bị xóa khỏi thư viện" : "Chưa có ảnh trong thư viện" }));
      }
      const changeImg = el("button", { class: "btn small", type: "button", text: "Đổi ảnh" });
      changeImg.addEventListener("click", () => openImageDialog((name) => setImage(name)));
      const download = cur.image && !cur.image_missing
        ? el("a", { class: "btn small", href: `/files/post-images/${encodeURIComponent(cur.image)}?download=1`,
          text: "Tải ảnh" }) : null;
      if (download) download.addEventListener("click", () => markPostStep("image", cur.image));

      const link = el("input", { type: "url", value: cur.link || "", placeholder: "Dán link Short (tùy chọn)",
        "aria-label": "Link Short" });
      const linkSave = el("button", { class: "btn small", type: "button", text: "Lưu link" });
      const linkMsg = el("span", { class: "small", hidden: true });
      linkSave.addEventListener("click", () => saveLink(link, linkSave, linkMsg));

      const copyBtn = copyTitleButton(cur.text, () => markPostStep("copy", cur.text));
      copyBtn.querySelector(".copy-btn").textContent = "Sao chép bài";
      const composeAgain = el("button", { class: "btn small", type: "button", text: "Soạn lại" });
      const composeMsg = el("p", { class: "error small", hidden: true });
      composeAgain.addEventListener("click", () => compose(composeAgain, composeMsg));

      const postedInput = el("input", { type: "checkbox", checked: cur.posted });
      const postedLabel = el("label", { class: "publish-label" }, postedInput, " Đã đăng bài");
      postedInput.addEventListener("change", () => togglePosted(postedInput));

      const badges = postBadges(cur);
      panel.replaceChildren(...[
        badges.length ? el("div", { class: "post-badges" }, ...badges) : null,
        el("label", { class: "small" }, "Các đoạn (một dòng trống giữa hai đoạn)"),
        textarea, el("div", { class: "edit-actions" }, save, saveMsg),
        el("div", { class: "post-image-row" }, img, changeImg, download),
        el("div", { class: "edit-actions" }, link, linkSave, linkMsg),
        el("p", { class: "muted small", text: `${cur.chars} ký tự (bài đầy đủ, kể cả tiêu đề / link / hashtag)` }),
        el("div", { class: "edit-actions" }, copyBtn, composeAgain, postedLabel),
        composeMsg].filter(Boolean));
    }

    async function compose(btn, msg) {
      btn.disabled = true;
      msg.hidden = true;
      try {
        await api(postsUrlFor(g.id), jsonBody("POST", { clips: [s.clip_id] }));
        await loadPostsPage();
      } catch (e) {
        msg.textContent = e.message;
        msg.hidden = false;
        btn.disabled = false;
      }
    }

    async function saveParagraphs(textarea, btn, msg) {
      const paragraphs = textarea.value.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
      btn.disabled = true;
      try {
        const saved = await api(url(), jsonBody("PUT", { paragraphs }));
        changed(saved);
        render();
        if (saved.proposed > 0) { // CP8.18 D7
          postsMsg(`Đã ghi ${saved.proposed} đề xuất sửa từ`, "");
          refreshCorrectionsCount();
        }
        return;
      } catch (e) {
        msg.textContent = e.message;
        msg.className = "small error";
        msg.hidden = false;
      }
      btn.disabled = false;
    }

    async function setImage(name) {
      try {
        changed(await api(url(), jsonBody("PUT", { image: name })));
        render();
      } catch (e) { alert(e.message); }
    }

    async function saveLink(input, btn, msg) {
      btn.disabled = true;
      try {
        changed(await api(url(), jsonBody("PUT", { link: input.value })));
        render();
        return;
      } catch (e) {
        msg.textContent = e.message;
        msg.className = "small error";
        msg.hidden = false;
      }
      btn.disabled = false;
    }

    // CP8.17 D1: remember a step of this post (copy / image download); tick "Đã đăng bài" once both are done.
    async function markPostStep(kind, value) {
      if (!cur || cur.posted) return; // a ticked post is left alone
      const key = `${g.id}/${s.clip_id}`;
      setPostMark(key, kind, value);
      if (!postMarksDone(key, cur)) return;
      clearPostMark(key);
      try {
        const r = await api(url("/posted"), jsonBody("POST", { value: true }));
        changed({ ...cur, posted: r.posted, posted_at: r.posted_at });
        render();
      } catch (e) { alert(e.message); }
    }

    async function togglePosted(input) {
      input.disabled = true;
      try {
        const r = await api(url("/posted"), jsonBody("POST", { value: input.checked }));
        changed({ ...cur, posted: r.posted, posted_at: r.posted_at });
        render();
        return;
      } catch (e) {
        input.checked = !input.checked;
        alert(e.message);
      }
      input.disabled = false;
    }

    render();
    return card;
  }

  // --- image library (P5, P5a, P5b): a modal shared by every "Đổi ảnh" button --------------------------------

  let imagePickCallback = null;

  function initImageDialog() {
    $("#image-close").addEventListener("click", closeImageDialog);
    $("#image-upload-input").addEventListener("change", (e) => {
      const f = e.target.files[0];
      if (f) uploadImageFile(f);
      e.target.value = "";
    });
    $("#image-search-btn").addEventListener("click", () => runImageSearch($("#image-search-url").value));
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !$("#image-dialog").hidden) closeImageDialog();
    });
  }

  function closeImageDialog() {
    $("#image-dialog").hidden = true;
    document.body.classList.remove("modal-open");
    imagePickCallback = null;
  }

  async function openImageDialog(onPick) {
    imagePickCallback = onPick || null;
    $("#image-dialog").hidden = false;
    document.body.classList.add("modal-open");
    $("#image-msg").hidden = true;
    await loadImageGrid();
  }

  function imgMsg(text, cls) {
    const m = $("#image-msg");
    m.textContent = text || "";
    m.className = "small " + (cls || "");
    m.hidden = !text;
  }

  async function loadImageGrid() {
    const grid = $("#image-grid");
    grid.replaceChildren(el("p", { class: "muted small", text: "Đang tải…" }));
    try {
      const d = await api("/api/post-images");
      renderImageGrid(d.images);
      renderQuickLinks(d.image_sources || []);
    } catch (e) {
      grid.replaceChildren(el("p", { class: "error small", text: e.message }));
    }
  }

  function renderQuickLinks(sources) {
    const box = $("#image-quick-links");
    box.hidden = !sources.length;
    box.replaceChildren(...sources.map((url) => {
      const short = url.length > 36 ? url.slice(0, 33) + "…" : url;
      const b = el("button", { class: "btn small", type: "button", title: url, text: short });
      b.addEventListener("click", () => { $("#image-search-url").value = url; runImageSearch(url); });
      return b;
    }));
  }

  function renderImageGrid(images) {
    const grid = $("#image-grid");
    if (!images.length) {
      grid.replaceChildren(el("p", { class: "muted small", text: "Thư viện chưa có ảnh." }));
      return;
    }
    grid.replaceChildren(...images.map((img) => imageCard(img)));
  }

  function imageCard(img) {
    const card = el("div", { class: "img-card" });
    card.append(el("img", { src: `/files/post-images/${encodeURIComponent(img.name)}`, alt: "", loading: "lazy" }));
    if (imagePickCallback) {
      const pick = el("button", { class: "btn primary small", type: "button", text: "Chọn" });
      pick.addEventListener("click", () => { imagePickCallback(img.name); closeImageDialog(); });
      card.append(pick);
    }
    card.append(el("p", { class: "muted small", text: `${img.width}×${img.height} · dùng ${img.used} bài` }));
    const del = el("button", { class: "btn danger small", type: "button", text: "Xóa khỏi thư viện" });
    del.addEventListener("click", () => deleteImageFromLibrary(img));
    card.append(del);
    return card;
  }

  async function deleteImageFromLibrary(img) {
    if (img.used && !confirm(`Ảnh này đang dùng ở ${img.used} bài đăng. Xóa khỏi thư viện? ` +
      'Các bài đó sẽ hiện "thiếu ảnh" (vẫn giữ text / link / tick).')) return;
    try {
      await api(`/api/post-images/${encodeURIComponent(img.name)}`, { method: "DELETE" });
      await loadImageGrid();
    } catch (e) { alert(e.message); }
  }

  async function uploadImageFile(file) {
    imgMsg("Đang tải lên…");
    try {
      const buf = await file.arrayBuffer();
      const r = await api(`/api/post-images?name=${encodeURIComponent(file.name)}`, {
        method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: buf,
      });
      imgMsg(r.duplicate ? "Ảnh đã có trong thư viện." : "Đã tải ảnh lên.");
      await loadImageGrid();
    } catch (e) { imgMsg(e.message, "error"); }
  }

  async function runImageSearch(url) {
    if (!url || !url.trim()) { imgMsg("Dán một link trước.", "error"); return; }
    const btn = $("#image-search-btn");
    btn.disabled = true;
    imgMsg("Đang tìm ảnh…");
    try {
      const r = await api("/api/post-images/search", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
      });
      await pollImageSearch(r.job.id);
    } catch (e) {
      imgMsg(e.message, "error");
    }
    btn.disabled = false;
  }

  async function pollImageSearch(jobId) {
    for (let i = 0; i < 60; i++) {
      const r = await api(`/api/post-images/search/${encodeURIComponent(jobId)}`);
      if (r.status !== "queued" && r.status !== "running") {
        if (r.status === "done") {
          const skippedN = Object.values(r.skipped || {}).reduce((a, b) => a + b, 0);
          imgMsg(`Đã thêm ${r.added.length} ảnh` + (r.duplicate.length ? `, ${r.duplicate.length} đã có` : "") +
            (skippedN ? `, bỏ qua ${skippedN}` : "") + ".");
        } else {
          imgMsg("Tìm ảnh lỗi.", "error");
        }
        await loadImageGrid();
        return;
      }
      await new Promise((res) => setTimeout(res, 600));
    }
    imgMsg("Đang tìm ảnh lâu hơn dự kiến — mở lại thư viện sau.", "error");
  }

  // "Thêm Short" dialog: tab "Đề xuất AI (n)" (remaining proposals) and tab "Chọn trên transcript".
  const add = { tr: null, props: null, a: null, b: null, seq: 0, p: null };

  function initAddDialog() {
    $("#add-short").addEventListener("click", openAdd);
    $("#add-close").addEventListener("click", closeAdd);
    $("#tab-proposals").addEventListener("click", () => showTab("proposals"));
    $("#tab-transcript").addEventListener("click", () => showTab("transcript"));
    $("#tr-search").addEventListener("input", filterLines);
    $("#source-close").addEventListener("click", () => { const v = $("#source-video"); v.pause(); $("#source-float").hidden = true; });
    $("#tr-clear").addEventListener("click", () => { add.a = add.b = null; paintSelection(); updateBar(); });
    $("#tr-add").addEventListener("click", () => submitAdd({ start_segment: add.tr.segments[add.a].id, end_segment: add.tr.segments[add.b].id }, $("#tr-add")));
    const [ls, le] = listenButtons(() => add.p);
    $("#tr-listen").replaceChildren(ls, le);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#add-dialog").hidden) closeAdd(); });
  }
  function showTab(name) {
    $("#tab-proposals").classList.toggle("active", name === "proposals");
    $("#tab-transcript").classList.toggle("active", name === "transcript");
    $("#tab-proposals").setAttribute("aria-selected", name === "proposals" ? "true" : "false");
    $("#tab-transcript").setAttribute("aria-selected", name === "transcript" ? "true" : "false");
    $("#pane-proposals").hidden = name !== "proposals";
    $("#pane-transcript").hidden = name !== "transcript";
    $("#tr-bar").hidden = name !== "transcript";
  }
  function closeAdd() {
    $("#add-dialog").hidden = true;
    document.body.classList.remove("modal-open");
  }
  async function openAdd() {
    const kt = lastData && lastData.kind === "khaithi";
    $("#add-title").textContent = kt ? "Thêm video khai thị" : "Thêm Short";
    $("#add-dialog").hidden = false;
    document.body.classList.add("modal-open");
    $("#add-error").hidden = true;
    add.a = add.b = null; add.p = null;
    $("#n-proposals").textContent = "…";
    $("#pane-proposals").replaceChildren(el("p", { class: "muted", text: "Đang tải…" }));
    $("#tr-lines").replaceChildren(el("li", { class: "muted", text: "Đang tải phụ đề…" }));
    showTab("proposals");
    updateBar();
    try {
      const [props, tr] = await Promise.all([
        api("/api/episodes/" + encodeURIComponent(episodeId) + "/proposals"), loadTranscript()]);
      add.props = props.proposals; add.tr = tr;
      renderProposals();
      renderLines();
      if (!add.props.length) showTab("transcript");
    } catch (e) {
      $("#pane-proposals").replaceChildren(el("p", { class: "error", text: e.message }));
      $("#tr-lines").replaceChildren(el("li", { class: "error", text: e.message }));
    }
    setEditsLocked(editsLocked);
  }
  const PROPOSAL_STATUS = { overlapped: "trùng một Short đã chọn", over_limit: "vượt số Short tối đa", ineligible: "AI không chọn" };
  function renderProposals() {
    $("#n-proposals").textContent = String(add.props.length);
    const pane = $("#pane-proposals");
    if (!add.props.length) {
      pane.replaceChildren(el("p", { class: "muted", text: "Không còn đề xuất AI nào (mọi đề xuất đã thành Short). Chọn trên transcript." }));
      return;
    }
    pane.replaceChildren(...add.props.map((p) => {
      const btn = el("button", { class: "btn primary small needs-idle", type: "button", text: "Thêm đoạn này" });
      btn.dataset.invalid = p.error ? "1" : "0";
      btn.disabled = !!p.error || editsLocked;
      btn.addEventListener("click", () => submitAdd({ candidate_id: p.candidate_id }, btn));
      const [ls, le] = listenButtons(() => p);
      return el("article", { class: "proposal" },
        el("div", { class: "proposal-head" },
          el("b", { text: p.topic || p.candidate_id }),
          el("span", { class: "muted small", text: ` · điểm ${p.score ?? "?"}/10 · ${PROPOSAL_STATUS[p.status] || p.status}` })),
        p.reason ? el("p", { class: "small", text: p.reason }) : null,
        el("p", { class: "small muted", text: `${fmtClock(p.start)} → ${fmtClock(p.end)} · ${fmtSeconds(p.duration)} (${p.duration.toFixed(1)} s)` +
          (p.reject_reason ? ` · ${p.reject_reason}` : "") }),
        el("p", { class: "small quote", text: `“${p.start_text || ""} … ${p.end_text || ""}”` }),
        p.added_as.length ? el("p", { class: "small warn", text: `Đã thêm thành ${p.added_as.join(", ")}` }) : null,
        ...rangeInfo(p, limitsText(add.tr)).slice(1).map((n) => { n.classList.add("small"); return n; }),
        el("div", { class: "edit-actions" }, ls, le, btn));
    }));
  }
  function renderLines() {
    const tr = add.tr;
    const owner = new Array(tr.segments.length).fill(null);
    const firsts = new Map();
    const pos = new Map(tr.segments.map((g, i) => [g.id, i]));
    for (const sh of tr.shorts) { // lines of a Short = its first .. last line as the server computes them (T8)
      if (sh.rejected || !sh.start_segment) continue;
      for (let i = pos.get(sh.start_segment); i <= pos.get(sh.end_segment); i++) {
        if (tr.segments[i].kind === "speech") owner[i] = owner[i] ? owner[i] + "," + sh.clip_id : sh.clip_id;
      }
      if (sh.start_segment) firsts.set(sh.start_segment, (firsts.get(sh.start_segment) || []).concat(sh.clip_id));
    }
    const out = [];
    const c0 = tr.content.start, c1 = tr.content.end;
    tr.segments.forEach((g, i) => {
      const outside = g.end <= c0 || g.start >= c1;
      const li = el("li", { class: "tr-line" + (g.kind !== "speech" ? " ns" : "") + (owner[i] ? " in-short" : "") + (outside ? " outside" : ""),
        "data-i": String(i) },
        el("span", { class: "tr-time", text: fmtClock(g.start) }),
        firsts.has(g.id) ? el("span", { class: "tr-tag", text: firsts.get(g.id).join(",") }) : null,
        el("span", { class: "tr-text", text: g.text }));
      if (g.kind === "speech" && !outside) li.addEventListener("click", () => pickLine(i));
      out.push(li);
    });
    $("#tr-lines").replaceChildren(...out);
    $("#tr-hint").textContent = `Bấm dòng đầu rồi dòng cuối. Dòng tô vàng thuộc ${noun()} đã có (chồng lấn được, chỉ cảnh báo). ` +
      `Thời lượng cần ${limitsText(tr)} sau khi rút khoảng lặng.`;
    filterLines();
  }
  function strip(t) { return t.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase(); }
  function filterLines() {
    const q = strip($("#tr-search").value.trim());
    document.querySelectorAll("#tr-lines .tr-line").forEach((li) => {
      li.hidden = !!q && !strip(li.querySelector(".tr-text").textContent).includes(q);
    });
  }
  function pickLine(i) {
    if (add.a === null || add.b !== null) { add.a = i; add.b = null; }
    else if (i < add.a) { add.b = add.a; add.a = i; }
    else add.b = i;
    paintSelection();
    updateBar();
  }
  function paintSelection() {
    const lo = add.a, hi = add.b === null ? add.a : add.b;
    document.querySelectorAll("#tr-lines .tr-line").forEach((li) => {
      const i = Number(li.dataset.i);
      li.classList.toggle("sel", lo !== null && i >= lo && i <= hi);
      li.classList.toggle("sel-edge", i === add.a || i === add.b);
    });
  }
  async function updateBar() {
    const info = $("#tr-info"), btn = $("#tr-add");
    btn.dataset.invalid = "1";
    btn.disabled = true;
    add.p = null;
    $("#tr-clear").hidden = add.a === null;
    if (!add.tr || add.a === null) { info.replaceChildren(el("span", { class: "muted", text: "Chưa chọn dòng nào." })); return; }
    const segs = add.tr.segments;
    if (add.b === null) {
      info.replaceChildren(el("div", {}, el("b", { text: "Đầu: " }), segs[add.a].text), el("span", { class: "muted", text: "Bấm dòng cuối." }));
      return;
    }
    const my = ++add.seq;
    info.replaceChildren(el("span", { class: "muted", text: "Đang tính…" }));
    try {
      const p = await previewCut({ start_segment: segs[add.a].id, end_segment: segs[add.b].id });
      if (my !== add.seq) return;
      add.p = p;
      info.replaceChildren(
        el("div", {}, el("b", { text: `Đầu ${fmtClock(p.start)}: ` }), segs[add.a].text),
        el("div", {}, el("b", { text: `Cuối ${fmtClock(p.end)}: ` }), segs[add.b].text),
        ...rangeInfo(p, limitsText(add.tr)));
      btn.dataset.invalid = p.error ? "1" : "0";
      btn.disabled = !!p.error || editsLocked;
    } catch (e) {
      if (my !== add.seq) return;
      info.replaceChildren(el("div", { class: "error", text: e.message }));
    }
  }
  async function submitAdd(body, btn) {
    const err = $("#add-error");
    err.hidden = true;
    btn.disabled = true;
    try {
      const r = await api("/api/episodes/" + encodeURIComponent(episodeId) + "/shorts", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      closeAdd();
      setJobStatus(`Đã thêm ${r.clip_id}: AI đang đặt tiêu đề, rồi dựng ${noun()}…`, "busy");
      refreshEpisode();
    } catch (e) {
      err.textContent = e.message;
      err.hidden = false;
      btn.disabled = btn.dataset.invalid === "1" || editsLocked;
    }
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
    loadEnhance();
  }

  // CP13.1b E10: one place for the enhance workers + the global "Tạm dừng enhance" (read from /api/enhance/status).
  async function loadEnhance() {
    const card = $("#enhance-card");
    if (!card) return;
    let d;
    try { d = await api("/api/enhance/status"); } catch (_) { setTimeout(loadEnhance, POLL_MS * 4); return; }
    card.hidden = !d.enabled && !d.workers.length && !d.items.length;
    const c = d.counts;
    $("#enhance-summary").textContent = (d.enabled ? "" : "Enhance đang tắt ([enhance] enabled = false). ") +
      (d.paused ? "ĐANG TẠM DỪNG. " : "") +
      `Hàng đợi: ${c.queued || 0} đợi máy GPU, ${c.running || 0} đang enhance, ${c.assembling || 0} đang ghép` +
      (c.failed ? `, ${c.failed} lỗi` : "") + (c.waiting_hd ? `; ${c.waiting_hd} đang đợi HD để render` : "") + ".";
    const pause = $("#enhance-pause");
    pause.textContent = d.paused ? "Chạy tiếp enhance" : "Tạm dừng enhance";
    pause.onclick = async () => {
      pause.disabled = true;
      try { await api("/api/enhance-pause", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused: !d.paused }) }); } catch (e) { alert(e.message); }
      pause.disabled = false;
      loadEnhance();
    };
    $("#enhance-workers").replaceChildren(...(d.workers.length ? d.workers.map((w) => el("li", {},
      el("b", { text: w.label || w.name }), el("span", { class: "muted small",
        text: ` · ${w.gpu || "GPU ?"}${w.yield ? " · nhường Ollama" : ""} · liên lạc ${fmtTime(w.last_seen)}` +
          (w.episode_id ? ` · đang làm ` : " · rảnh") }),
      w.episode_id ? el("a", { href: "/episodes/" + encodeURIComponent(w.episode_id), text: w.episode_id }) : null,
      w.progress && w.progress.segments_total ? el("span", { class: "muted small",
        text: ` (${w.progress.segments_uploaded || 0}/${w.progress.segments_total} đoạn)` }) : null))
      : [el("li", { class: "muted", text: "Chưa có worker nào liên lạc (từ lúc khởi động server)." })]));
    clearTimeout(enhTimer);
    enhTimer = setTimeout(loadEnhance, POLL_MS * 2);
  }
  let enhTimer = null;

  function recReason(r) {
    if (r.rule === "all_published") return (r.episodes || []).length > 1 ? "Đã đăng hết Short và khai thị." : "Đã đăng hết.";
    if (r.rule === "old_source") return `Dựng Short xong ${r.age_days} ngày trước, còn video nguồn.`;
    return `Lỗi / dở dang, không hoạt động ${r.age_days} ngày.`;
  }

  async function runAction(r, a, btn) {
    const name = r.title || r.episode_id;
    const ids = a.episodes || [r.episode_id];
    const parts = ids.length > 1 ? ` (${ids.length} phần: Short + khai thị)` : "";
    const postWarn = r.post_unticked ? `\n\nCòn ${r.post_unticked} bài đăng chưa đăng — xóa cả tập sẽ mất bài đã soạn.` : "";
    const msg = a.action === "archive"
      ? `Dọn video nguồn của "${name}" (${r.episode_id})${parts}? Giải phóng ${fmtBytes(a.frees)}.\n\n` +
        "Short vẫn xem / tải được. Sau đó KHÔNG sửa tiêu đề, khôi phục Short hay chạy lại được nữa " +
        "(muốn sửa thì xóa tập rồi chạy lại từ đầu)."
      : `Xóa toàn bộ tập "${name}" (${r.episode_id})${parts}? Giải phóng ${fmtBytes(a.frees)}.\n\n` +
        "Sẽ xóa video nguồn đã tải, mọi Short và dữ liệu xử lý. KHÔNG khôi phục được." + postWarn;
    if (!confirm(msg)) return;
    btn.disabled = true;
    const out = $("#rec-msg");
    try {
      let freed = 0;
      for (const id of ids) {
        if (a.action === "archive") {
          const res = await api(`/api/episodes/${encodeURIComponent(id)}/archive`, { method: "POST" });
          freed += res.freed || 0;
        } else {
          await api(`/api/episodes/${encodeURIComponent(id)}`, { method: "DELETE" });
        }
      }
      out.textContent = a.action === "archive" ? `Đã dọn video nguồn "${name}": giải phóng ${fmtBytes(freed)}.`
        : `Đã xóa tập "${name}".`;
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
    $("#storage-meta").textContent = `Các tập: ${fmtBytes(t.episodes)} (video nguồn ${fmtBytes(t.source)}, Short ${fmtBytes(t.shorts)}, khác ${fmtBytes(t.other)}` +
      (t.hd || t.enhance_tmp ? `; trong đó bản HD ${fmtBytes(t.hd || 0)}, đoạn enhance tạm ${fmtBytes(t.enhance_tmp || 0)}` : "") + `). ` +
      `Tính lúc ${fmtTime(d.computed_at)} (làm mới tối đa 30 giây một lần).`;

    const recs = $("#recs");
    if (!d.recommendations.length) {
      recs.replaceChildren(el("li", { class: "muted", text: "Không có gợi ý nào." }));
    } else {
      recs.replaceChildren(...d.recommendations.map((r) => el("li", { class: "rec" },
        el("a", { href: "/episodes/" + encodeURIComponent(r.episode_id), class: "ep-name clamp2", text: r.title || r.episode_id }),
        el("span", { class: "muted small", text: `${r.episode_id} · ${recReason(r)}` }),
        r.post_unticked ? el("span", { class: "small error", text: `Còn ${r.post_unticked} bài đăng chưa đăng — xóa cả tập sẽ mất bài đã soạn.` }) : null,
        recButtons(r))));
    }
    const recOf = {};
    for (const r of d.recommendations) recOf[r.episode_id] = r; // video-level: buttons on the first part's row
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
  const PL_FILTERS = ["all", "todo", "running", "failed", "doing", "done"]; // CP8.13 G2
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
    if (PL_FILTERS.includes(savedFilter)) plFilter = savedFilter;
    document.querySelectorAll("#pl-filters [data-filter]").forEach((b) => b.addEventListener("click", () => {
      plFilter = b.dataset.filter;
      store("autoShort.plFilter", plFilter);
      applyPlFilter();
    }));
    initPlKinds();
    $("#pl-refresh").addEventListener("click", refreshPlaylist);
    initHashtags();
    initSeries();
    initDoc();
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

  // CP8.13 G1/G2: every tab filters on the server ``group`` (CP8.12 A1 "Đang xử lý" included: the combined state
  // is queued / processing when a job of the Short or of the khai thị episode is). A job running keeps polling.
  const RUNNING_STATES = ["queued", "processing"];

  function applyPlFilter() {
    document.querySelectorAll("#pl-filters [data-filter]").forEach((b) => b.classList.toggle("active", b.dataset.filter === plFilter));
    let shown = 0;
    document.querySelectorAll("#pl-entries li[data-group]").forEach((li) => {
      li.hidden = plFilter !== "all" && li.dataset.group !== plFilter;
      if (!li.hidden) shown += 1;
    });
    $("#pl-running-empty").hidden = !(plFilter === "running" && shown === 0);
    $("#pl-failed-empty").hidden = !(plFilter === "failed" && shown === 0);
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

  // "Văn bản gốc" (CP8.19 D1): link of the lecture document of the bộ kinh.
  let dcEditing = false;

  function dcMessage(text, cls) {
    const m = $("#dc-msg");
    m.textContent = text;
    m.className = "small " + (cls || "");
    m.hidden = !text;
  }

  function dcLoad(d, force) {
    const input = $("#dc-input");
    $("#dc-state").textContent = d.doc_url ? "đã gắn" : "chưa gắn";
    $("#dc-reset").disabled = !d.doc_url;
    if (force || !dcEditing) {
      input.value = d.doc_url || "";
      input.dataset.saved = d.doc_url || "";
      dcEditing = false;
    }
  }

  function dcCheckText(r) {
    const c = r.check;
    const queued = r.queued ? ` Đã xếp soạn lại bài của ${r.queued} tập.` : "";
    if (!c) return ["Đã lưu. Chưa có tập nào có transcript để kiểm." + queued, "ok"];
    if (c.match === null || c.match === undefined) {
      return [`Đã lưu, nhưng không tải được văn bản tập ${c.episode}: ${c.error || "lỗi"}.` + queued, "error"];
    }
    const pct = Math.round(c.match * 100);
    return c.ok
      ? [`Khớp ${pct}% — đúng bản giảng (tập ${c.episode}).` + queued, "ok"]
      : [`Khớp ${pct}% — có thể sai bản giảng (tập ${c.episode}); tập khớp kém dùng cách cũ.` + queued, "error"];
  }

  function initDoc() {
    const input = $("#dc-input");
    input.addEventListener("input", () => { dcEditing = input.value.trim() !== (input.dataset.saved || ""); });
    const put = async (url, busy) => {
      dcMessage(busy, "muted");
      try {
        const r = await api(`/api/playlists/${encodeURIComponent(playlistId)}/doc`, jsonBody("PUT", { url }));
        dcLoad(r, true);
        if (url === null) dcMessage("Đã xóa", "ok");
        else { const [t, cls] = dcCheckText(r); dcMessage(t, cls); }
        loadPlaylist();
      } catch (e) { dcMessage(e.message, "error"); }
    };
    $("#dc-save").addEventListener("click", () => {
      const value = input.value.trim();
      if (!value) { dcMessage("Link rỗng — dùng \"Xóa\" để bỏ", "error"); return; }
      put(value, "Đang tải văn bản để kiểm…");
    });
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); $("#dc-save").click(); } });
    $("#dc-reset").addEventListener("click", () => {
      if (!confirm("Xóa văn bản gốc của bộ kinh?\n\nBài đã soạn từ văn bản giữ nguyên; lần soạn sau dùng cách cũ (AI).")) return;
      put(null, "…");
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
    showGpu(d.gpu);
    document.title = `${d.title || d.id} — Auto Short`;
    $("#pl-title").textContent = d.title || d.id;
    if (htTags === null) htLoad(d); // not while the user edits
    srLoad(d);
    dcLoad(d);
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
    document.querySelectorAll("#pl-filters [data-filter]").forEach((b) => { b.querySelector(".n").textContent = d.counts[b.dataset.filter] || 0; });
    let busy = false;
    $("#pl-entries").replaceChildren(...d.entries.map((e) => {
      if (RUNNING_STATES.includes(e.state)) busy = true;
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
          el("span", { class: "pl-state small", text: entryState(e) }),
          e.state === "failed" && e.error ? el("span", { class: "error small", text: e.error }) : null),
        actions);
    }));
    applyPlFilter();
    if (busy) plTimer = setTimeout(loadPlaylist, POLL_MS * 2);
  }

  // --- CP8.22 queue bar (every page except login): "Hàng đợi đang tạm ngưng — n việc chờ · Chạy tiếp" -----------

  function initQueueBar() {
    const header = $("header.topbar");
    if (!header) return;
    const bar = el("div", { id: "queue-bar", class: "queue-bar", hidden: true });
    header.after(bar);
    const note = el("span", { class: "queue-note" });
    const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined }).then(render, (e) => { note.textContent = e.message; });
    const btn = (text, fn) => { const b = el("button", { class: "btn small", type: "button", text }); b.addEventListener("click", fn); return b; };
    const resume = btn("Chạy tiếp", () => post("/api/queue/resume"));
    const after = btn("Tạm ngưng sau bước hiện tại", () => post("/api/queue/pause", { mode: "after" }));
    const now = btn("Tạm ngưng ngay", () => {
      if (confirm("Tạm ngưng ngay: bước đang chạy bị ngắt và sẽ làm lại từ đầu bước khi Chạy tiếp. Tiếp tục?")) post("/api/queue/pause", { mode: "now" });
    });
    bar.append(note, resume, after, now);
    function render(q) {
      if (!q) return;
      const busy = q.running + q.pending > 0;
      bar.hidden = !(q.paused || busy);
      bar.classList.toggle("paused", q.paused);
      resume.hidden = !q.paused;
      after.hidden = q.paused;
      now.hidden = q.paused && q.running === 0;
      if (q.paused) {
        note.textContent = "Hàng đợi đang tạm ngưng — " + q.pending + " việc chờ" +
          (q.running ? ` (đang đợi ${q.running} bước chạy xong)` : "") + " · ";
      } else {
        note.textContent = `Hàng đợi: ${q.running} đang chạy, ${q.pending} chờ · `;
      }
    }
    async function poll() {
      try { render(await api("/api/queue")); } catch (_) { /* keep the last state */ }
      setTimeout(poll, POLL_MS * 2);
    }
    poll();
  }
  document.addEventListener("DOMContentLoaded", initQueueBar);

  return { initIndex, initEpisode, initStorage, initPlaylist, initPosts };
})();
