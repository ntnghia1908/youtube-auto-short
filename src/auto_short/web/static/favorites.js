/* CP8.33: trang Yêu thích của bộ kinh (khai thị yêu thích, ghép / lặp / tự ghép). Plain JS, no build step. */
"use strict";

const Favorites = (() => {
  const { el, api, copyText } = AutoShort;
  const POLL_MS = 3000;
  const STATE = { queued: "đang chờ", running: "đang ghép", done: "xong", failed: "lỗi" };
  const MODE = { concat: "ghép", loop: "lặp", auto: "tự ghép" };
  const $ = (sel) => document.querySelector(sel);
  let pid = "", data = null, timer = null;
  const ticked = new Set(); // "episode_id|clip"
  let openLoop = null; // key of the row whose "Lặp" box is open
  const KINDS = ["all", "short", "khaithi"];
  let kindFilter = "all"; // Amendment 2: Tất cả | Short | Khai thị (remembered per browser)
  const players = new Map(), idleCallbacks = new Set();
  const videoCounts = { plans: 0, comps: 0 };
  let compsDeferred = false, showTab = () => {};
  function busy() {
    return [...players.values()].some((video) => (!video.paused && !video.ended) || document.fullscreenElement === video);
  }
  function flush() {
    if (!busy()) for (const fn of idleCallbacks) fn();
  }
  function onIdle(fn) { idleCallbacks.add(fn); }
  function pauseAll() {
    for (const video of players.values()) video.pause();
  }
  function player(src, cls = "") {
    let video = players.get(src);
    if (!video) {
      video = el("video", { src, controls: "", playsinline: "", preload: "metadata" });
      players.set(src, video);
      video.addEventListener("play", () => {
        for (const other of players.values()) if (other !== video) other.pause();
      });
      video.addEventListener("pause", flush);
      video.addEventListener("ended", flush);
    }
    video.className = cls;
    return video;
  }
  function setVideoCount(source, n) {
    videoCounts[source] = n;
    $("#fv-videos-count").textContent = videoCounts.plans + videoCounts.comps;
    // Run after the synchronous render: cached elements may have moved to new cards.
    Promise.resolve().then(() => {
      for (const [src, video] of players) if (!video.isConnected) players.delete(src);
    });
  }
  function scrollToVideo(id) {
    document.getElementById("vd-plan-" + id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function store(key, value) {
    try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (_) { /* private mode */ }
    return null;
  }

  const post = (path, obj) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(obj) });

  // User state only, like the Short publishBox: update controls without rebuilding a playing card.
  function publishBox(item, kind, id, onUpdate) {
    const input = el("input", { type: "checkbox" });
    const stale = el("span", { class: "stale small" }, "đã đăng bản cũ ");
    const renew = el("button", { class: "btn link-dark small", type: "button", text: "đánh dấu bản này" });
    const msg = el("span", { class: "error small", hidden: true });
    stale.append(renew);
    function update() {
      input.checked = !!item.published;
      stale.hidden = !item.published_stale;
    }
    async function send(value) {
      input.disabled = renew.disabled = true;
      msg.hidden = true;
      try {
        const result = await post(`/api/playlists/${encodeURIComponent(pid)}/videos/published`, { kind, id, published: value });
        Object.assign(item, result);
        onUpdate(result); // polling may have replaced data while this request was pending
      } catch (e) {
        msg.textContent = e.message;
        msg.hidden = false;
      }
      update();
      input.disabled = renew.disabled = false;
    }
    input.addEventListener("change", () => send(input.checked));
    renew.addEventListener("click", () => send(true));
    update();
    return el("div", { class: "publish" }, el("label", { class: "publish-label" }, input, " Đã đăng"), stale, msg);
  }

  function say(text, cls) {
    const m = $("#fv-msg");
    m.textContent = text || "";
    m.className = "small" + (cls ? " " + cls : "");
    m.hidden = !text;
  }

  function fmtDur(s) {
    s = Math.round(s || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return h ? `${h} giờ ${String(m).padStart(2, "0")} ph` : (m ? `${m} ph ${String(sec).padStart(2, "0")} s` : `${sec} s`);
  }
  const keyOf = (f) => f.episode_id + "|" + f.clip;
  const shown = (f) => kindFilter === "all" || f.kind === kindFilter;
  const usable = () => (data ? data.favorites.filter((f) => f.usable && shown(f)) : []);
  const kindsOfFilter = () => (kindFilter === "all" ? ["short", "khaithi"] : [kindFilter]);

  // G10 preview (same rule as the server): usable favourites in order, wrap around, stop at >= T.
  function autoPreview(minutes) {
    const list = usable();
    if (!list.length || !(minutes >= 1)) return null;
    let total = 0, n = 0;
    while (total < minutes * 60 && n < 100000) {
      for (const f of list) { total += f.duration; n += 1; if (total >= minutes * 60) break; }
    }
    return { n, rounds: Math.ceil(n / list.length), total };
  }

  async function unheart(f) {
    try {
      await post(`/api/playlists/${encodeURIComponent(pid)}/favorites`, { episode_id: f.episode_id, clip: f.clip, favorite: false });
      ticked.delete(keyOf(f));
      await load();
      window.dispatchEvent(new Event("favorites-changed"));
    } catch (e) { say(e.message, "error"); }
  }

  async function create(body, btn) {
    if (btn) btn.disabled = true;
    say("");
    try {
      const r = await post(`/api/playlists/${encodeURIComponent(pid)}/compilations`, body);
      say(r.created ? "Đã xếp vào hàng đợi ghép." : "Video này đã có sẵn, không ghép lại.", "ok");
      await load();
    } catch (e) { say(e.message, "error"); }
    if (btn) btn.disabled = false;
  }

  function loopBox(f) {
    const input = el("input", { type: "number", min: "1", max: String(data.max_minutes), step: "1", value: "30", inputmode: "numeric", "aria-label": "Tổng thời lượng (phút)" });
    const prev = el("span", { class: "small muted" });
    const go = el("button", { class: "btn small primary", type: "button", text: "Tạo" });
    function update() {
      const t = parseInt(input.value, 10);
      if (!(t >= 1) || !f.duration) { prev.textContent = ""; return; }
      const n = Math.max(1, Math.ceil((60 * t) / f.duration - 1e-9));
      prev.textContent = `${n} lần ≈ ${fmtDur(n * f.duration)}`;
    }
    input.addEventListener("input", update);
    go.addEventListener("click", () => create({ mode: "loop", item: { episode_id: f.episode_id, clip: f.clip }, minutes: parseInt(input.value, 10) }, go));
    update();
    return el("div", { class: "fv-loop" }, input, " phút ", prev, " ", go);
  }

  function row(f) {
    const k = keyOf(f);
    const box = el("input", { type: "checkbox", "aria-label": `Chọn ${f.code}` });
    box.checked = ticked.has(k);
    box.disabled = !f.usable;
    box.addEventListener("change", () => { if (box.checked) ticked.add(k); else ticked.delete(k); updateConcat(); });
    const heartBtn = el("button", { class: "btn icon-btn heart on", type: "button", title: "Bỏ yêu thích", "aria-label": "Bỏ yêu thích", text: "♥" });
    heartBtn.addEventListener("click", () => {
      if (f.kept && !confirm("Khai thị này đã bị xóa khỏi tập, bỏ tim sẽ xóa hẳn.")) return;
      unheart(f);
    });
    const loopBtn = el("button", { class: "btn small", type: "button", text: "Lặp" });
    loopBtn.disabled = !f.usable;
    loopBtn.addEventListener("click", () => { openLoop = openLoop === k ? null : k; render(); });
    const li = el("li", { class: "fv-row" + (f.usable ? "" : " dim") },
      el("label", { class: "fv-main" }, box, " ",
        el("strong", { text: f.code }), " ",
        el("span", { text: f.title || (f.usable ? "" : "(không còn dùng được)") }), " ",
        el("span", { class: "muted small", text: f.duration ? fmtDur(f.duration) : "" }), " ",
        f.kept ? el("span", { class: "kept-note", text: "đã lưu" }) : null),
      el("span", { class: "fv-actions" },
        f.video_url && f.usable ? el("a", { class: "btn small", href: f.video_url, target: "_blank", rel: "noopener", text: "Xem" }) : null,
        loopBtn, heartBtn));
    if (openLoop === k && f.usable) li.append(loopBox(f));
    return li;
  }

  function updateConcat() {
    const picked = usable().filter((f) => ticked.has(keyOf(f)));
    const total = picked.reduce((a, f) => a + f.duration, 0);
    const btn = $("#fv-concat");
    btn.textContent = picked.length ? `Ghép (${picked.length} đoạn, ${fmtDur(total)})` : "Ghép";
    btn.disabled = picked.length < 2;
    btn.title = picked.length < 2 ? "Chọn ít nhất 2 khai thị" : "";
    $("#fv-all").checked = picked.length > 0 && picked.length === usable().length;
  }

  function updateAuto() {
    const t = parseInt($("#fv-auto-min").value, 10);
    const p = autoPreview(t);
    $("#fv-auto-preview").textContent = p ? `${p.n} đoạn (${p.rounds} vòng) ≈ ${fmtDur(p.total)}` : (usable().length ? "" : "Chưa có mục yêu thích dùng được.");
    $("#fv-auto").disabled = !p;
  }

  function compRow(c) {
    const info = `${MODE[c.mode] || c.mode} · ${c.mode === "loop" ? `${c.repeat} lần` : `${c.segments} đoạn`} · ${fmtDur(c.duration)}`;
    const actions = el("span", { class: "fv-actions" });
    if (c.download_url) {
      actions.append(el("a", { class: "btn small", href: c.download_url, download: c.download_name || "", text: "Tải video" }));
      for (const [label, text] of [["Copy tiêu đề", c.title || (c.download_name || "").replace(/\.mp4$/, "")], ["Copy mô tả", c.description || ""]]) {
        const copy = el("button", { class: "btn small", type: "button", text: label });
        copy.addEventListener("click", async () => {
          copy.textContent = await copyText(text) ? "Đã copy" : "Không copy được";
          setTimeout(() => { copy.textContent = label; }, 1500);
        });
        actions.append(copy);
      }
    }
    const del = el("button", { class: "btn small danger", type: "button", text: "Xóa" });
    del.disabled = c.state === "queued" || c.state === "running";
    del.addEventListener("click", async () => {
      if (!confirm(`Xóa video ghép "${c.download_name || c.cid}"? File bị xóa khỏi đĩa.`)) return;
      pauseAll();
      try { await api(`/api/playlists/${encodeURIComponent(pid)}/compilations/${c.cid}`, { method: "DELETE" }); await load(); }
      catch (e) { say(e.message, "error"); }
    });
    actions.append(del);
    const card = el("li", { class: "vd-card" },
      c.download_url ? player(c.download_url + "?inline=1", "vd-vertical") : null,
      el("div", { class: "fv-main" }, el("strong", { text: c.download_name || c.cid }), " ",
        el("span", { class: "badge", text: STATE[c.state] || c.state }), " ",
        el("span", { class: "muted small", text: info }),
        c.error ? el("div", { class: "error small", text: c.error }) : null),
      actions, c.download_url || c.published ? publishBox(c, "compilation", c.cid, (result) => {
        const current = data.compilations.find((item) => item.cid === c.cid);
        if (current) Object.assign(current, result);
      }) : null);
    if (String(c.error || "").includes("Bộ kinh chưa có ảnh bìa khai thị")) card.append(
      el("a", { href: `/playlists/${encodeURIComponent(pid)}/thumbs`, text: "Thiết kế bìa khai thị" }));
    if (c.download_url) card.append(el("details", { class: "tp-details" },
      el("summary", { text: "Sửa video & thumbnail" }),
      thumbnailBlock(`/api/playlists/${encodeURIComponent(pid)}/compilations/${c.cid}/thumbs`)));
    return card;
  }

  // Both types of video card share the same server-audited two-shape thumbnail controls.
  function thumbnailBlock(endpoint, introState = null, onIntroChanged = null) {
    const block = el("div", { class: "fv-thumbnails", "aria-label": "Thumbnail video ghép" });
    async function refresh() {
      if (!block.isConnected) return;
      try {
        const view = await api(endpoint);
        if (!block.isConnected) return;
        const busy = !!(view.job && view.job.active);
        const status = el("p", { class: "small", role: "status", text: busy ? "Đang dựng thumbnail…" : view.reason || (view.state === "ready" ? "Thumbnail" : "Chưa có thumbnail") });
        const build = el("button", { class: "btn small", type: "button", text: view.state === "empty" ? "Dựng thumbnail" : "Dựng lại" });
        build.disabled = busy;
        build.addEventListener("click", async () => {
          build.disabled = true;
          try { await post(endpoint, {}); await refresh(); }
          catch (e) { status.textContent = e.message; build.disabled = false; }
        });
        block.replaceChildren(status, build);
        if (introState && view.files?.[introState.shape]?.sha256 !== introState.intro.sha256) {
          block.append(el("p", { class: "small error", role: "status", text: "Thumbnail intro đã đổi — bấm Ghép lại video." }));
          const details = block.closest?.("details");
          if (details) details.open = true;
          if (onIntroChanged) onIntroChanged();
        }
        if (view.job && view.job.error && !busy) block.append(el("p", { class: "small error", text: view.job.error }));
        if (view.reason && view.reason.includes("chưa có ảnh bìa khai thị")) {
          build.disabled = true;
          block.append(el("a", { class: "btn small", href: view.cover_url, text: "Cài ảnh bìa khai thị của bộ" }));
        }
        const images = el("div", { class: "fv-thumb-images" });
        for (const [shape, file] of Object.entries(view.files || {})) {
          const label = shape === "vertical" ? "dọc" : "ngang";
          images.append(el("figure", {}, el("a", { href: file.preview_url, target: "_blank", rel: "noopener" },
            el("img", { src: file.preview_url, alt: "Thumbnail " + label, loading: "lazy" })),
            el("figcaption", {}, el("a", { class: "btn small", href: file.download_url, download: "", text: "Tải ảnh " + label }))));
        }
        block.append(images);
        if (busy) setTimeout(refresh, POLL_MS);
      } catch (e) {
        if (block.isConnected) block.replaceChildren(el("p", { class: "small error", role: "status", text: e.message }));
      }
    }
    setTimeout(refresh, 0); // the caller attaches the card before the first request
    return block;
  }

  function render() {
    $("#fv-title").textContent = `Yêu thích — ${data.series || data.title || pid}`;
    document.title = `Yêu thích — ${data.series || data.title || pid} — Auto Short`;
    $("#fv-max").textContent = data.max_minutes;
    $("#fv-auto-min").max = data.max_minutes;
    $("#fv-count").textContent = data.favorites.length;
    document.querySelectorAll("#fv-filters [data-kind]").forEach((b) => b.classList.toggle("active", b.dataset.kind === kindFilter));
    const rows = data.favorites.filter(shown);
    $("#fv-list").replaceChildren(...(rows.length ? rows.map(row)
      : [el("li", { class: "muted", text: "Chưa có mục yêu thích. Bấm ♥ ở trang một tập (Short hoặc khai thị)." })]));
    renderComps();
    updateConcat();
    updateAuto();
  }

  function renderComps() {
    setVideoCount("comps", data.compilations.length);
    compsDeferred = busy();
    if (compsDeferred) return;
    $("#fv-comps").replaceChildren(...(data.compilations.length ? data.compilations.map(compRow)
      : [el("li", { class: "muted", text: "Chưa có." })]));
  }
  onIdle(() => { if (compsDeferred && data) renderComps(); });

  async function load() {
    clearTimeout(timer);
    try {
      data = await api(`/api/playlists/${encodeURIComponent(pid)}/compilations`);
      const keys = new Set(data.favorites.map(keyOf));
      for (const k of [...ticked]) if (!keys.has(k)) ticked.delete(k);
      if (!document.activeElement || document.activeElement.tagName !== "INPUT" || document.activeElement.type === "checkbox") render();
      else renderComps();
    } catch (e) { say(e.message, "error"); }
    if (data && data.compilations.some((c) => c.state === "queued" || c.state === "running")) timer = setTimeout(load, POLL_MS);
  }

  function initTabs() {
    const tabs = [...document.querySelectorAll("[data-fv-tab]")];
    function show(name, focus = false) {
      if (name !== "videos") pauseAll();
      for (const tab of tabs) {
        const selected = tab.dataset.fvTab === name;
        tab.classList.toggle("active", selected);
        tab.setAttribute("aria-selected", String(selected));
        tab.setAttribute("tabindex", selected ? "0" : "-1");
        document.getElementById("fv-pane-" + tab.dataset.fvTab).hidden = !selected;
        if (selected && focus) tab.focus();
      }
      store("autoShort.fvTab", name);
    }
    for (const [i, tab] of tabs.entries()) {
      tab.addEventListener("click", () => show(tab.dataset.fvTab));
      tab.addEventListener("keydown", (event) => {
        const keys = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1 };
        if (keys[event.key] === undefined) return;
        event.preventDefault();
        show(tabs[keys[event.key]].dataset.fvTab, true);
      });
    }
    showTab = show;
    const saved = store("autoShort.fvTab");
    show(["manual", "videos"].includes(saved) ? saved : "ai");
    document.addEventListener("fullscreenchange", flush);
  }

  function init() {
    initTabs();
    pid = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
    const saved = store("autoShort.fvKind");
    if (KINDS.includes(saved)) kindFilter = saved;
    document.querySelectorAll("#fv-filters [data-kind]").forEach((b) => b.addEventListener("click", () => {
      kindFilter = b.dataset.kind;
      store("autoShort.fvKind", kindFilter);
      render();
    }));
    $("#fv-back").href = "/playlists/" + encodeURIComponent(pid);
    $("#fv-all").addEventListener("change", (ev) => {
      for (const f of usable()) { if (ev.target.checked) ticked.add(keyOf(f)); else ticked.delete(keyOf(f)); }
      render();
    });
    $("#fv-concat").addEventListener("click", (ev) => {
      const items = usable().filter((f) => ticked.has(keyOf(f))).map((f) => ({ episode_id: f.episode_id, clip: f.clip }));
      create({ mode: "concat", items }, ev.target);
    });
    $("#fv-auto-min").addEventListener("input", updateAuto);
    $("#fv-auto").addEventListener("click", (ev) => create({ mode: "auto", minutes: parseInt($("#fv-auto-min").value, 10), kinds: kindsOfFilter() }, ev.target));
    load();
  }

  return { init, el, api, fmtDur, copyText, thumbnailBlock, publishBox, player, busy, onIdle, pauseAll,
    showTab: (name) => showTab(name), scrollToVideo, setVideoCount };
})();
