/* THUMB1: suggest four covers, choose, review variants, install, build the playlist. */
"use strict";
(() => {
  const { el, api } = AutoShort;
  const $ = (id) => document.getElementById(id);
  const pid = encodeURIComponent(decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || ""));
  const base = `/api/playlists/${pid}/thumbs`;
  const labels = { vertical: "Tập · dọc", landscape: "Tập · ngang", kt_vertical: "Khai thị · dọc", kt_landscape: "Khai thị · ngang" };
  let view = null, pending = false, timer = null, galleryKey = "";
  $("thumbs-back").href = `/playlists/${pid}`;
  function picture(url, label) {
    const image = el("img", { src: url, alt: label, loading: "lazy", tabindex: "0", role: "button", "aria-label": `Phóng to ${label}` });
    function zoom() { $("thumbs-zoom").querySelector("img").src = url; $("thumbs-zoom").showModal(); }
    image.addEventListener("click", zoom);
    image.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); zoom(); } });
    return el("div", {}, el("p", { text: label }), image);
  }
  function drawEpisodes() {
    if (!view || !$("thumbs-episodes").open) return;
    const key = JSON.stringify(view.episodes);
    if (galleryKey === key) return;
    galleryKey = key;
    $("thumbs-grid").replaceChildren(...view.episodes.map((row) => {
      const card = el("article", {}, el("h3", { text: `Tập ${row.episode || "?"}` }));
      for (const [shape, file] of Object.entries(row.files)) {
        card.append(picture(file.preview_url, labels[shape]), el("a", { class: "btn small", href: file.download_url, download: "", text: "Tải " + labels[shape] }));
      }
      if (row.skipped_reason) card.append(el("p", { text: row.skipped_reason }));
      return card;
    }));
  }
  function draw() {
    const s = view.suggestion, running = s && s.status === "running";
    const job = view.job, active = job && job.active;
    $("thumbs-title").textContent = "Thumbnail cả bộ — " + view.series;
    $("thumbs-suggest").disabled = pending || running || active || Boolean(view.codex_unavailable);
    $("thumbs-build").disabled = pending || active;
    $("thumbs-cancel").hidden = !running;
    $("thumbs-cancel").disabled = pending;
    $("thumbs-bar").hidden = !active && !running;
    const progress = view.progress;
    $("thumbs-progress").textContent = `Đã có ${progress.landscape}/${progress.total} bản ngang, ${progress.vertical}/${progress.total} bản dọc; bỏ qua ${progress.skipped} tập.`;
    $("thumbs-status").textContent = job ? (job.error || job.summary || job.status) : "";
    $("thumbs-zip").href = view.zip_url;
    $("thumbs-suggest-status").textContent = view.codex_unavailable || (s ?
      (running ? `Đang vẽ ${s.phase === "options" ? "4 mẫu" : "3 ảnh cùng phong cách"}… Có thể mất vài phút.` :
        s.error || (s.installed ? "Đã dùng bộ ảnh này. Bấm Dựng cả bộ để cập nhật thumbnail." : "Đã vẽ xong. Hãy kiểm tra dấu tiếng Việt.")) +
      (s.tokens ? ` (${s.tokens} tokens)` : "") : "");
    const covers = $("thumbs-covers");
    if (covers.dataset.key !== JSON.stringify(view.covers)) {
      covers.dataset.key = JSON.stringify(view.covers);
      covers.replaceChildren(...Object.keys(labels).map((shape) => view.covers[shape]
        ? picture(view.covers[shape].preview_url + "?v=" + Date.now(), labels[shape])
        : el("p", { text: labels[shape] + ": chưa có ảnh bìa" })));
    }
    const options = $("thumbs-options"), previews = $("thumbs-previews");
    const key = JSON.stringify(s);
    if (options.dataset.key !== key) {
      options.dataset.key = key;
      options.replaceChildren(); previews.replaceChildren();
      if (s) {
        for (const [name, entry] of Object.entries(s.options)) {
          const card = picture(`${base}/suggest/${s.run_id}/images/${name.replace(".png", "-preview.jpg")}?v=${encodeURIComponent(s.updated_at)}`, "Mẫu " + name.match(/[1-4]/)[0]);
          const button = el("button", { type: "button", class: "btn", text: name === s.selected ? "Đã chọn · Vẽ lại 3 ảnh" : "Chọn mẫu này" });
          button.disabled = pending || running || Boolean(view.codex_unavailable);
          button.addEventListener("click", () => select(name)); card.append(button); options.append(card);
        }
        for (const entry of s.previews || []) previews.append(picture(entry.preview_url + "?v=" + encodeURIComponent(s.updated_at), entry.label));
        for (const [name, reason] of Object.entries(s.errors || {})) options.append(el("p", { class: "small", text: `${name}: ${reason}` }));
      }
    }
    $("thumbs-accept").hidden = !(s && s.phase === "variants" && s.selected && !running);
    $("thumbs-install").disabled = pending || active || !s || s.status !== "done";
    $("thumbs-redraw").disabled = pending || Boolean(view.codex_unavailable);
    drawEpisodes();
  }
  async function load() {
    clearTimeout(timer);
    try { view = await api(base); draw(); }
    catch (e) { $("thumbs-msg").textContent = e.message; }
    if (view && ((view.job && view.job.active) || (view.suggestion && view.suggestion.status === "running"))) timer = setTimeout(load, 1800);
  }
  async function action(path, body) {
    if (pending) return;
    pending = true; $("thumbs-msg").textContent = "";
    if (view) draw();
    try { await api(base + path, { method: "POST", headers: { "Content-Type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) }); }
    catch (e) { $("thumbs-msg").textContent = e.message; }
    finally { pending = false; if (view) $("thumbs-options").dataset.key = ""; await load(); }
  }
  function suggest() { return action("/suggest", { notes: $("thumbs-notes").value }); }
  function select(name) { return action(`/suggest/${view.suggestion.run_id}/select`, { name }); }
  $("thumbs-suggest").addEventListener("click", suggest);
  $("thumbs-again").addEventListener("click", suggest);
  $("thumbs-redraw").addEventListener("click", () => select(view.suggestion.selected));
  $("thumbs-cancel").addEventListener("click", () => action(`/suggest/${view.suggestion.run_id}/cancel`));
  $("thumbs-install").addEventListener("click", async () => { $("thumbs-covers").dataset.key = ""; await action(`/suggest/${view.suggestion.run_id}/install`); });
  $("thumbs-build").addEventListener("click", () => action(""));
  $("thumbs-refresh").addEventListener("click", load);
  $("thumbs-episodes").addEventListener("toggle", drawEpisodes);
  $("thumbs-close").addEventListener("click", () => $("thumbs-zoom").close());
  load();
})();
