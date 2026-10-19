/* CP8.33: trang Yêu thích của bộ kinh (khai thị yêu thích, ghép / lặp / tự ghép). Plain JS, no build step. */
"use strict";

const Favorites = (() => {
  const POLL_MS = 3000;
  const STATE = { queued: "đang chờ", running: "đang ghép", done: "xong", failed: "lỗi" };
  const MODE = { concat: "ghép", loop: "lặp", auto: "tự ghép" };
  const $ = (sel) => document.querySelector(sel);
  let pid = "", data = null, timer = null;
  const ticked = new Set(); // "episode_id|clip"
  let openLoop = null; // key of the row whose "Lặp" box is open
  const KINDS = ["all", "short", "khaithi"];
  let kindFilter = "all"; // Amendment 2: Tất cả | Short | Khai thị (remembered per browser)
  function store(key, value) {
    try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (_) { /* private mode */ }
    return null;
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
    if (res.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); throw new Error("chưa đăng nhập"); }
    let body = null;
    try { body = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) {
      let msg = body && body.detail;
      if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
      const error = new Error(msg || `HTTP ${res.status}`);
      error.status = res.status;
      throw error;
    }
    return body;
  }
  const post = (path, obj) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(obj) });

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

  function legacyCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.contentEditable = "true";
    ta.style.cssText = "position:fixed;top:0;left:-9999px;font-size:16px";
    document.body.append(ta);
    let ok = false;
    try { ta.focus(); ta.select(); ta.setSelectionRange(0, text.length); ok = document.execCommand("copy"); } catch (_) { ok = false; }
    ta.remove();
    return ok;
  }
  async function copyText(text) {
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
      try { await navigator.clipboard.writeText(text); return true; } catch (_) { /* fall back */ }
    }
    return legacyCopy(text);
  }

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
      actions.append(el("a", { class: "btn small", href: c.download_url, download: c.download_name || "", text: "Tải" }));
      const copy = el("button", { class: "btn small", type: "button", text: "Copy mô tả" });
      copy.addEventListener("click", async () => {
        const ok = await copyText(c.description || "");
        copy.textContent = ok ? "Đã copy" : "Không copy được";
        setTimeout(() => { copy.textContent = "Copy mô tả"; }, 1500);
      });
      actions.append(copy);
    }
    const del = el("button", { class: "btn small danger", type: "button", text: "Xóa" });
    del.disabled = c.state === "queued" || c.state === "running";
    del.addEventListener("click", async () => {
      if (!confirm(`Xóa video ghép "${c.download_name || c.cid}"? File bị xóa khỏi đĩa.`)) return;
      try { await api(`/api/playlists/${encodeURIComponent(pid)}/compilations/${c.cid}`, { method: "DELETE" }); await load(); }
      catch (e) { say(e.message, "error"); }
    });
    actions.append(del);
    return el("li", { class: "fv-row" },
      el("div", { class: "fv-main" }, el("strong", { text: c.download_name || c.cid }), " ",
        el("span", { class: "badge", text: STATE[c.state] || c.state }), " ",
        el("span", { class: "muted small", text: info }),
        c.error ? el("div", { class: "error small", text: c.error }) : null),
      actions);
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
    $("#fv-comps").replaceChildren(...(data.compilations.length ? data.compilations.map(compRow)
      : [el("li", { class: "muted", text: "Chưa có." })]));
    updateConcat();
    updateAuto();
  }

  async function load() {
    clearTimeout(timer);
    try {
      data = await api(`/api/playlists/${encodeURIComponent(pid)}/compilations`);
      const keys = new Set(data.favorites.map(keyOf));
      for (const k of [...ticked]) if (!keys.has(k)) ticked.delete(k);
      if (!document.activeElement || document.activeElement.tagName !== "INPUT" || document.activeElement.type === "checkbox") render();
      else { $("#fv-comps").replaceChildren(...(data.compilations.length ? data.compilations.map(compRow) : [])); }
    } catch (e) { say(e.message, "error"); }
    if (data && data.compilations.some((c) => c.state === "queued" || c.state === "running")) timer = setTimeout(load, POLL_MS);
  }

  function initTabs() {
    const tabs = [...document.querySelectorAll("[data-fv-tab]")];
    function show(name, focus = false) {
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
    show(store("autoShort.fvTab") === "manual" ? "manual" : "ai");
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

  return { init, el, api, fmtDur, copyText };
})();
