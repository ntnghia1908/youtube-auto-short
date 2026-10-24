/* PKG2.1: one design for the whole playlist, optional own look for the 9:16 shape; temporary previews before publication. */
"use strict";
(() => {
  const { el, api } = AutoShort;
  const $ = (id) => document.getElementById(id);
  const pid = encodeURIComponent(decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || ""));
  const base = `/api/playlists/${pid}/thumbs`;
  let pending = false, dirty = false, timer = null, view = null;
  const cards = new Map();
  // Two image pickers share the same code: the compact "selected image" line + a closed <details> holding the gallery.
  const looks = {
    main: { picked: $("thumbs-picked"), details: $("thumbs-details"), grid: $("thumbs-assets"), id: null, key: null },
    vertical: { picked: $("thumbs-vpicked"), details: $("thumbs-vdetails"), grid: $("thumbs-vassets"), id: null, key: null },
  };
  $("thumbs-back").href = `/playlists/${pid}`;
  function say(text) { $("thumbs-msg").textContent = text; }
  function draft() {
    return { style: $("thumbs-style").value, asset_id: looks.main.id, focus_x: Number($("thumbs-focus").value),
      title_lines: $("thumbs-lines").value.split("\n").filter((line) => line.trim()), credit: $("thumbs-credit").value,
      vertical: $("thumbs-vsep").checked ? { style: $("thumbs-vstyle").value, asset_id: looks.vertical.id,
        focus_x: Number($("thumbs-vfocus").value) } : null };
  }
  function showPicked(look) {
    const asset = look.id && view ? view.assets.find((a) => a.id === look.id) : null;
    look.picked.replaceChildren(...(asset
      ? [el("img", { src: asset.preview_url, alt: "Ảnh " + asset.number }), el("span", { text: "Ảnh " + asset.number })]
      : [el("span", { text: look.id ? "Ảnh không còn dùng được" : "Không ảnh" })]));
    look.grid.querySelectorAll("button").forEach((button) => {
      const selected = (button.dataset.asset || null) === look.id;
      button.setAttribute("aria-pressed", String(selected));
      button.style.outline = selected ? "3px solid #b58a44" : "none";
    });
  }
  function fillGallery(look) {
    const key = JSON.stringify(view.assets);
    if (look.key === key) return;
    look.key = key;
    look.grid.replaceChildren(...[{ id: "", number: "Không ảnh" }, ...view.assets].map((asset) => {
      const button = el("button", { class: "btn", type: "button", "data-asset": asset.id,
        "aria-label": "Ảnh " + asset.number, style: "padding:6px" });
      if (asset.preview_url) button.append(el("img", { src: asset.preview_url, alt: "Ảnh " + asset.number,
        loading: "lazy", width: "96", height: "90", style: "max-width:100%;object-fit:contain;display:block" }));
      button.append(document.createTextNode(String(asset.number)));
      button.addEventListener("click", () => { look.id = asset.id || null; look.details.open = false; edited(); });
      return button;
    }));
  }
  function lock() {
    const busy = pending || !!(view && view.job && view.job.active);
    $("thumbs-settings").querySelectorAll("input, textarea, select, button").forEach((c) => { c.disabled = busy && !("keep" in c.dataset); });
    $("thumbs-zip").hidden = dirty || busy || !view || !view.episodes.some((row) => Object.keys(row.files).length);
    $("thumbs-focus-value").textContent = Number($("thumbs-focus").value).toFixed(2);
    $("thumbs-vfocus-value").textContent = Number($("thumbs-vfocus").value).toFixed(2);
    $("thumbs-vgroup").hidden = !$("thumbs-vsep").checked;
    showPicked(looks.main);
    showPicked(looks.vertical);
  }
  function edited() {
    dirty = true;
    $("thumbs-preview-images").replaceChildren();
    lock();
  }
  function picture(shape, url) {
    return el("img", { src: url, alt: "Thumbnail " + (shape === "landscape" ? "ngang" : "dọc"),
      loading: "lazy", width: shape === "landscape" ? "288" : "135", height: shape === "landscape" ? "162" : "240",
      style: "max-width:100%;object-fit:contain" });
  }
  function drawProgress() {
    const p = view.progress, active = !!(view.job && view.job.active);
    $("thumbs-progress").textContent = `Đã có thumbnail ${p.with_any}/${p.total} tập — ngang ${p.landscape}, dọc ${p.vertical}`
      + (p.skipped ? ` · ${p.skipped} tập bỏ qua` : "");
    $("thumbs-reasons").replaceChildren(...Object.entries(p.skipped_by_reason).map(([reason, n]) => el("li", { text: `${n} tập: ${reason}` })));
    const bar = $("thumbs-bar");
    bar.hidden = !active;
    bar.max = Math.max(p.total, 1);
    bar.value = p.with_any;
  }
  function drawEpisodes() {
    const box = $("thumbs-grid");
    if (!$("thumbs-episodes").open) { box.replaceChildren(); return; }  // DOM only while the list is open
    box.replaceChildren(...view.episodes.map((row) => {
      const key = JSON.stringify(row);
      const cached = cards.get(row.video_id);
      if (cached && cached.key === key) return cached.card;
      const card = el("article", { class: "card" }, el("h3", { text: `Tập ${row.episode || row.video_id}` }));
      if (row.skipped_reason) card.append(el("p", { class: "small muted", text: row.skipped_reason }));
      const images = el("div", { class: "actions", style: "align-items:flex-start;margin-top:12px" });
      for (const [shape, file] of Object.entries(row.files)) {
        images.append(el("a", { href: file.download_url, download: "", title: "Tải thumbnail" }, picture(shape, file.preview_url)));
      }
      card.append(images);
      cards.set(row.video_id, { key, card });
      return card;
    }));
  }
  function draw() {
    $("thumbs-title").textContent = `Thumbnail — ${view.series}`;
    $("thumbs-zip").href = view.zip_url;
    $("thumbs-status").textContent = view.job
      ? (view.job.active ? "Đang dựng… " : "") + (view.job.summary || view.job.status) + (view.job.error ? ": " + view.job.error : "") : "Chưa chạy";
    if (!dirty && !pending) {
      const s = view.settings, v = s.vertical;
      looks.main.id = s.asset_id;
      $("thumbs-style").value = s.style;
      $("thumbs-lines").value = s.title_lines.join("\n");
      $("thumbs-credit").value = s.credit;
      $("thumbs-focus").value = s.focus_x;
      $("thumbs-vsep").checked = !!v;
      looks.vertical.id = (v || s).asset_id;
      $("thumbs-vstyle").value = (v || s).style;
      $("thumbs-vfocus").value = (v || s).focus_x;
    }
    fillGallery(looks.main);
    fillGallery(looks.vertical);
    drawProgress();
    drawEpisodes();
    lock();
  }
  async function load() {
    clearTimeout(timer);
    try {
      view = await api(base);
      draw();
      if (view.job && view.job.active) timer = setTimeout(load, 2000);
    } catch (e) { say(e.message); }
  }
  const request = (suffix, method, body) => api(base + suffix, { method, headers: { "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  async function act(preview) {
    if (pending) return;
    pending = true;
    clearTimeout(timer);
    lock();
    try {
      if (preview) {
        const result = await request("/preview", "POST", draft());
        $("thumbs-preview-images").replaceChildren(...Object.entries(result.files).map(([shape, file]) => picture(shape, file.preview_url)));
        say("Xem trước — chưa dựng vào các tập.");
      } else {
        await request("/settings", "PUT", draft());
        dirty = false;
        await request("", "POST");
        say("");
      }
    } catch (e) { say(e.message); }
    pending = false;
    if (preview) lock(); else await load();
  }
  $("thumbs-settings").addEventListener("submit", (e) => { e.preventDefault(); act(false); });
  for (const id of ["thumbs-style", "thumbs-lines", "thumbs-credit", "thumbs-focus", "thumbs-vstyle", "thumbs-vfocus"]) $(id).addEventListener("input", edited);
  $("thumbs-vsep").addEventListener("change", () => {
    if ($("thumbs-vsep").checked) {  // start from the shared look, then let the user change it
      looks.vertical.id = looks.main.id;
      $("thumbs-vstyle").value = $("thumbs-style").value;
      $("thumbs-vfocus").value = $("thumbs-focus").value;
    }
    edited();
  });
  $("thumbs-episodes").addEventListener("toggle", () => { if (view) drawEpisodes(); });
  $("thumbs-preview").addEventListener("click", () => act(true));
  $("thumbs-refresh").addEventListener("click", load);
  load();
})();
