/* PKG1: explicit edits, background rendering and manual publication approval. */
"use strict";
(() => {
  const { el, api, copyText } = AutoShort;
  const $ = (id) => document.getElementById(id);
  const parts = location.pathname.split("/").filter(Boolean);
  const pid = encodeURIComponent(decodeURIComponent(parts[1] || ""));
  const plan = encodeURIComponent(decodeURIComponent(parts[3] || ""));
  const base = `/api/playlists/${pid}/theme-plans/${plan}/package`;
  let view = null, dirty = false, pending = false, timer = null;
  const names = { classic: "Cổ điển", minimal: "Tối giản", scenic: "Phong cảnh" };
  const active = () => view && view.job && view.job.active;
  function say(message, error = false) {
    $("pkg-msg").textContent = message;
    $("pkg-msg").className = "small" + (error ? " error" : "");
  }
  const request = (suffix, method, body) => api(base + suffix, { method,
    headers: { "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) });
  function lock() {
    const busy = pending || active();
    for (const c of $("pkg-form").querySelectorAll("input, select, button")) c.disabled = !!busy;
    $("pkg-download").hidden = !!busy || dirty || !view || !view.package.download_url;
  }
  function edited() { dirty = true; lock(); }
  function draw() {
    const doc = view.package;
    $("pkg-form").hidden = false;
    $("pkg-status").textContent = (doc.state === "stale" ? "Cũ — dựng lại. Video hoặc kế hoạch đã đổi."
      : doc.state === "approved" ? "Đã duyệt bản đăng." : "Bản nháp — chọn thumbnail rồi duyệt.") +
      (view.job ? ` · ${view.job.active ? "Đang dựng thumbnail…" : view.job.status}${view.job.error ? ": " + view.job.error : ""}` : "");
    if (!dirty) {
      $("pkg-title").value = doc.title;
      $("pkg-headline").value = doc.headline;
      $("pkg-options").replaceChildren();
      doc.title_options.forEach((title, i) => {
        const b = el("button", { type: "button", class: "btn small",
          text: `${i === doc.title_options.length - 1 ? "Truyền thống" : "Gợi ý " + (i + 1)}: ${title}` });
        b.addEventListener("click", () => { $("pkg-title").value = title; edited(); });
        $("pkg-options").append(b);
      });
      const cards = doc.thumbnails.map((t) => {
        const radio = el("input", { type: "radio", name: "template", value: t.template });
        radio.checked = doc.selected === t.template;
        const label = el("label", { class: "inline" }, radio, document.createTextNode(" " + names[t.template]));
        const select = el("select", { "aria-label": "Ảnh " + names[t.template], "data-template": t.template },
          el("option", { value: "", text: "Nền có sẵn" }));
        for (const asset of view.assets) select.append(el("option", { value: asset.id,
          text: `${asset.tags.join(", ") || asset.id.slice(0, 12)} · ${asset.license}` }));
        select.value = t.asset_ids[0] || "";
        const box = el("article", { class: "tp-plan" }, label, select);
        if (t.preview_url) box.append(el("img", { src: t.preview_url, alt: "Thumbnail " + names[t.template],
          width: "1280", height: "720", style: "display:block;max-width:100%;height:auto" }));
        return box;
      });
      $("pkg-thumbnails").replaceChildren(...cards);
    }
    $("pkg-download").href = doc.download_url || "#";
    lock();
  }
  async function load() {
    clearTimeout(timer);
    try { view = await api(base); draw(); }
    catch (e) { say(e.message, true); }
    if (active()) timer = setTimeout(load, 2000);
  }
  async function save() {
    if (!dirty) return;
    const asset_ids = {};
    for (const select of $("pkg-thumbnails").querySelectorAll("select")) {
      asset_ids[select.dataset.template] = select.value ? [select.value] : [];
    }
    await request("", "PUT", { title: $("pkg-title").value, headline: $("pkg-headline").value,
      selected: $("pkg-form").querySelector('input[name="template"]:checked').value, asset_ids });
    dirty = false;
  }
  async function perform(action) {
    if (pending || active()) return;
    pending = true; clearTimeout(timer); lock(); say("");
    try { await action(); }
    catch (e) { say(e.message, true); }
    finally { pending = false; await load(); }
  }
  $("pkg-back").href = `/playlists/${pid}/favorites`;
  $("pkg-form").addEventListener("submit", (e) => e.preventDefault());
  $("pkg-form").addEventListener("input", edited);
  $("pkg-form").addEventListener("change", edited);
  $("pkg-refresh").addEventListener("click", load);
  $("pkg-save").addEventListener("click", () => perform(async () => { await save(); say("Đã lưu."); }));
  $("pkg-build").addEventListener("click", () => perform(async () => { await save(); await request("/thumbnails", "POST"); }));
  $("pkg-approve").addEventListener("click", () => perform(async () => { await save(); await request("/approve", "POST"); say("Đã duyệt."); }));
  for (const [id, value] of [["pkg-copy-title", () => $("pkg-title").value],
    ["pkg-copy-description", () => view.description]]) {
    $(id).addEventListener("click", async () => say(await copyText(value()) ? "Đã copy." : "Không copy được."));
  }
  load();
})();
