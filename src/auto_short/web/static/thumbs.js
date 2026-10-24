/* PKG2: one playlist render job, deterministic images with per-episode overrides. */
"use strict";
(() => {
  const { el, api } = AutoShort;
  const $ = (id) => document.getElementById(id);
  const pid = encodeURIComponent(decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || ""));
  const base = `/api/playlists/${pid}/thumbs`;
  let pending = false, timer = null;
  $("thumbs-back").href = `/playlists/${pid}`;
  function say(text) { $("thumbs-msg").textContent = text; }
  async function load() {
    clearTimeout(timer);
    try {
      const view = await api(base);
      const busy = pending || !!(view.job && view.job.active);
      $("thumbs-title").textContent = `Thumbnail — ${view.series}`;
      $("thumbs-build").disabled = busy;
      $("thumbs-zip").href = view.zip_url;
      $("thumbs-zip").hidden = !view.episodes.some((row) => Object.keys(row.files).length);
      $("thumbs-status").textContent = view.job
        ? (view.job.active ? "Đang dựng… " : "") + (view.job.summary || view.job.status) + (view.job.error ? ": " + view.job.error : "") : "Chưa chạy";
      $("thumbs-grid").replaceChildren(...view.episodes.map((row) => {
        const select = el("select", { "aria-label": `Ảnh tập ${row.episode || row.video_id}` },
          el("option", { value: "", text: "Tự chọn theo số tập" }));
        for (const asset of view.assets) select.append(el("option", { value: asset.id,
          text: `${asset.tags.join(", ") || asset.id.slice(0, 12)} · ${asset.license}` }));
        select.value = row.override || "";
        select.disabled = busy;
        select.addEventListener("change", () => mutate("/" + encodeURIComponent(row.video_id), "PUT", { asset_id: select.value || null }));
        const card = el("article", { class: "card" },
          el("h3", { text: `Tập ${row.episode || row.video_id}` }), select);
        if (row.skipped_reason) card.append(el("p", { class: "small muted", text: row.skipped_reason }));
        const images = el("div", { class: "actions", style: "align-items:flex-start;margin-top:12px" });
        for (const [shape, file] of Object.entries(row.files)) {
          images.append(el("a", { href: file.download_url, download: "", title: "Tải thumbnail " + (shape === "landscape" ? "ngang" : "dọc") },
            el("img", { src: file.preview_url, alt: `Tập ${row.episode} — ${shape === "landscape" ? "ngang" : "dọc"}`,
              loading: "lazy", width: shape === "landscape" ? "288" : "135", height: shape === "landscape" ? "162" : "240",
              style: "max-width:100%;object-fit:contain" })));
        }
        card.append(images);
        return card;
      }));
      if (busy) timer = setTimeout(load, 2000);
    } catch (e) { say(e.message); }
  }
  async function mutate(suffix, method, body) {
    pending = true;
    $("thumbs-build").disabled = true;
    document.querySelectorAll("#thumbs-grid select").forEach((s) => { s.disabled = true; });
    try {
      await api(base + suffix, { method, headers: { "Content-Type": "application/json" },
        ...(body ? { body: JSON.stringify(body) } : {}) });
      say("");
    } catch (e) { say(e.message); }
    pending = false;
    await load();
  }
  $("thumbs-build").addEventListener("click", () => mutate("", "POST"));
  $("thumbs-refresh").addEventListener("click", load);
  load();
})();
