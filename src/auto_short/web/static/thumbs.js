/* PKG2 v2: one design and portrait for the whole playlist; temporary previews before publication. */
"use strict";
(() => {
  const { el, api } = AutoShort;
  const $ = (id) => document.getElementById(id);
  const pid = encodeURIComponent(decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || ""));
  const base = `/api/playlists/${pid}/thumbs`;
  let pending = false, dirty = false, timer = null, view = null, assetId = null, assetKey = null;
  const cards = new Map();
  $("thumbs-back").href = `/playlists/${pid}`;
  function say(text) { $("thumbs-msg").textContent = text; }
  function draft() {
    return { style: $("thumbs-style").value, asset_id: assetId, focus_x: Number($("thumbs-focus").value),
      title_lines: $("thumbs-lines").value.split("\n").filter((line) => line.trim()), credit: $("thumbs-credit").value };
  }
  function lock() {
    const busy = pending || !!(view && view.job && view.job.active);
    $("thumbs-settings").querySelectorAll("input, textarea, select, button").forEach((c) => { c.disabled = busy; });
    $("thumbs-zip").hidden = dirty || busy || !view || !view.episodes.some((row) => Object.keys(row.files).length);
    $("thumbs-focus-value").textContent = Number($("thumbs-focus").value).toFixed(2);
    document.querySelectorAll("#thumbs-assets button").forEach((button) => {
      const selected = (button.dataset.asset || null) === assetId;
      button.setAttribute("aria-pressed", String(selected));
      button.style.outline = selected ? "3px solid #b58a44" : "none";
    });
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
  function draw() {
    $("thumbs-title").textContent = `Thumbnail — ${view.series}`;
    $("thumbs-zip").href = view.zip_url;
    $("thumbs-status").textContent = view.job
      ? (view.job.active ? "Đang dựng… " : "") + (view.job.summary || view.job.status) + (view.job.error ? ": " + view.job.error : "") : "Chưa chạy";
    if (!dirty && !pending) {
      assetId = view.settings.asset_id;
      $("thumbs-style").value = view.settings.style;
      $("thumbs-lines").value = view.settings.title_lines.join("\n");
      $("thumbs-credit").value = view.settings.credit;
      $("thumbs-focus").value = view.settings.focus_x;
    }
    const choices = [{ id: "", number: "Không ảnh" }, ...view.assets];
    const nextAssetKey = JSON.stringify(view.assets);
    if (assetKey !== nextAssetKey) {
      assetKey = nextAssetKey;
      $("thumbs-assets").replaceChildren(...choices.map((asset) => {
      const button = el("button", { class: "btn", type: "button", "data-asset": asset.id,
        "aria-label": "Ảnh " + asset.number, style: "padding:6px" });
      if (asset.preview_url) button.append(el("img", { src: asset.preview_url, alt: "Ảnh " + asset.number,
        loading: "lazy", width: "96", height: "90", style: "max-width:100%;object-fit:contain;display:block" }));
      button.append(document.createTextNode(String(asset.number)));
      button.addEventListener("click", () => { assetId = asset.id || null; edited(); });
      return button;
      }));
    }
    $("thumbs-grid").replaceChildren(...view.episodes.map((row) => {
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
  for (const id of ["thumbs-style", "thumbs-lines", "thumbs-credit", "thumbs-focus"]) $(id).addEventListener("input", edited);
  $("thumbs-preview").addEventListener("click", () => act(true));
  $("thumbs-refresh").addEventListener("click", load);
  load();
})();
