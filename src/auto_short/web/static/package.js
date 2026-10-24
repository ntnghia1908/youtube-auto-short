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
  const names = { A: "Kiểu A — nền tối, chữ vàng", B: "Kiểu B — khung vàng, chữ trắng", C: "Kiểu C — giấy, chữ nâu" };
  const shapes = { landscape: "Ngang 16:9", vertical: "Dọc 9:16" };
  const active = () => view && view.job && view.job.active;
  const selectedStyle = () => { const r = $("pkg-form").querySelector('input[name="style"]:checked'); return r ? r.value : "A"; };
  function styleControls() { $("pkg-style-a").hidden = selectedStyle() !== "A"; }
  function say(message, error = false) {
    $("pkg-msg").textContent = message;
    $("pkg-msg").className = "small" + (error ? " error" : "");
  }
  const request = (suffix, method, body) => api(base + suffix, { method,
    headers: { "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) });
  function lock() {
    const busy = pending || active();
    for (const c of $("pkg-form").querySelectorAll("input, select, button")) c.disabled = !!busy;
    for (const shape of Object.keys(shapes)) {
      const link = $("pkg-download-" + shape), urls = view && view.package.download_urls;
      link.hidden = !!busy || dirty || !urls;
      link.href = urls ? urls[shape] : "#";
    }
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
      const s = doc.settings;
      for (let i = 0; i < 3; i++) $("pkg-line-" + i).value = s.title_lines[i] || "";
      $("pkg-series").value = s.series;
      $("pkg-speaker").value = s.speaker;
      $("pkg-focus").value = s.focus_x;
      $("pkg-palette").value = s.palette;
      $("pkg-background").value = s.background;
      $("pkg-minutes").textContent = `Khung thời lượng: ${s.minutes} phút (theo video đã ghép).`;
      $("pkg-options").replaceChildren();
      doc.title_options.forEach((title, i) => {
        const b = el("button", { type: "button", class: "btn small",
          text: `${i === doc.title_options.length - 1 ? "Truyền thống" : "Gợi ý " + (i + 1)}: ${title}` });
        b.addEventListener("click", () => { $("pkg-title").value = title; edited(); });
        $("pkg-options").append(b);
      });
      const cards = doc.thumbnails.map((t) => {
        const radio = el("input", { type: "radio", name: "style", value: t.style });
        radio.checked = doc.selected === t.style;
        const label = el("label", { class: "inline" }, radio, document.createTextNode(" " + names[t.style]));
        const select = el("select", { "aria-label": "Ảnh " + names[t.style], "data-style": t.style },
          el("option", { value: "", text: "Không ảnh" }));
        for (const asset of view.assets) select.append(el("option", { value: asset.id,
          text: `${asset.tags.join(", ") || asset.id.slice(0, 12)} · ${asset.license}` }));
        select.value = t.asset_ids[0] || "";
        const box = el("article", { class: "tp-plan" }, label, select);
        const previews = el("div", { style: "display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap" });
        for (const [shape, text] of Object.entries(shapes)) {
          const url = t.preview_urls[shape];
          previews.append(url ? el("figure", { style: "margin:0" },
            el("img", { src: url, alt: `${names[t.style]} · ${text}`, loading: "lazy",
              style: shape === "landscape" ? "display:block;max-width:100%;width:480px;height:auto"
                : "display:block;max-width:100%;width:216px;height:auto" }),
            el("figcaption", { class: "small muted", text })) : el("p", { class: "small muted", text: `${text}: chưa dựng` }));
        }
        box.append(previews);
        return box;
      });
      $("pkg-thumbnails").replaceChildren(...cards);
      styleControls();
    }
    lock();
    drawVisual();
  }
  async function load() {
    clearTimeout(timer);
    try { view = await api(base); draw(); }
    catch (e) { say(e.message, true); }
    if (active() || visualActive()) timer = setTimeout(load, 2000);
  }
  async function save() {
    if (!dirty) return;
    const asset_ids = {};
    for (const select of $("pkg-thumbnails").querySelectorAll("select")) {
      asset_ids[select.dataset.style] = select.value ? [select.value] : [];
    }
    await request("", "PUT", { title: $("pkg-title").value, selected: selectedStyle(),
      title_lines: [0, 1, 2].map((i) => $("pkg-line-" + i).value), series: $("pkg-series").value,
      speaker: $("pkg-speaker").value, focus_x: Number($("pkg-focus").value),
      palette: $("pkg-palette").value, background: $("pkg-background").value, asset_ids });
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
  $("pkg-form").addEventListener("change", (e) => { if (e.target.name === "style") styleControls(); edited(); });
  $("pkg-refresh").addEventListener("click", load);
  $("pkg-save").addEventListener("click", () => perform(async () => { await save(); say("Đã lưu."); }));
  $("pkg-build").addEventListener("click", () => perform(async () => { await save(); await request("/thumbnails", "POST"); }));
  $("pkg-approve").addEventListener("click", () => perform(async () => { await save(); await request("/approve", "POST"); say("Đã duyệt."); }));
  for (const [id, value] of [["pkg-copy-title", () => $("pkg-title").value],
    ["pkg-copy-description", () => view.description]]) {
    $(id).addEventListener("click", async () => say(await copyText(value()) ? "Đã copy." : "Không copy được."));
  }
  let visualPending = false;
  const visualActive = () => view && ((view.preview.job && view.preview.job.active) ||
    view.variants.some((v) => v.job && v.job.active));
  const sourceLabel = (id) => {
    const source = view.visual_sources.find((s) => s.id === id);
    const presets = { "generated:warm": "Vàng ấm", "generated:dawn": "Bình minh", "generated:soft": "Ánh sáng mềm" };
    if (presets[id]) return `${presets[id]} · Nền tạo sẵn`;
    return source ? `${source.tags.join(", ") || id.slice(0, 12)} · ${source.license}` : id.slice(0, 12);
  };
  function visualSpec() {
    return { visual: { mode: "ambient", asset_id: $("visual-source").value, motion: $("visual-motion").value,
      fit: $("visual-fit").value, loop_seconds: Number($("visual-length").value), crossfade: Number($("visual-fade").value) } };
  }
  function motionOptions() {
    const source = view.visual_sources.find((s) => s.id === $("visual-source").value);
    $("visual-motion").disabled = !source || source.kind !== "image";
    if ($("visual-motion").disabled) $("visual-motion").value = "none";
  }
  function play(url) {
    if (!url) return;
    const player = $("visual-player");
    player.hidden = false;
    if (player.getAttribute("src") !== url) player.src = url;
  }
  function drawVisual() {
    $("visual-section").hidden = false;
    const select = $("visual-source"), chosen = select.value;
    select.replaceChildren(...view.visual_sources.map((s) => el("option", { value: s.id, text: sourceLabel(s.id) })));
    if (view.visual_sources.some((s) => s.id === chosen)) select.value = chosen;
    motionOptions();
    const musicSelect = $("music-source"), musicChosen = musicSelect.value;
    musicSelect.replaceChildren(el("option", { value: "", text: "Chỉ giọng giảng (mặc định)" }),
      ...view.music_sources.map((s) => el("option", { value: s.id, text: `${s.tags.join(", ") || s.id.slice(0, 12)} · ${s.license}` })));
    if (view.music_sources.some((s) => s.id === musicChosen)) musicSelect.value = musicChosen;
    $("music-empty").hidden = view.music_sources.length > 0;
    const videoSelect = $("music-visual"), videoChosen = videoSelect.value;
    const built = view.variants.filter((v) => !v.spec.music && v.state !== "stale" && v.inline_url);
    videoSelect.replaceChildren(el("option", { value: "", text: "Original (TC3)" }),
      ...built.map((v) => el("option", { value: v.key12, text: sourceLabel(v.spec.visual.asset_id) })));
    if (built.some((v) => v.key12 === videoChosen)) videoSelect.value = videoChosen;
    for (const id of ["music-preview", "music-build"]) $(id).disabled = visualPending;
    const urls = view.preview.audio_urls || [];
    if (JSON.stringify(urls) !== $("music-previews").dataset.urls) {
      $("music-previews").dataset.urls = JSON.stringify(urls);
      $("music-previews").replaceChildren(...urls.map((url, i) => el("label", { text: ["Đầu", "Giữa", "Cuối"][i] },
        el("audio", { src: url, controls: "", preload: "metadata" }))));
    }
    for (const id of ["visual-preview", "visual-build"]) $(id).disabled = visualPending;
    const previewJob = view.preview.job;
    $("visual-cancel-preview").hidden = !(previewJob && previewJob.active);
    if (previewJob && previewJob.error) $("visual-msg").textContent = previewJob.error;
    if (view.preview.url && (!$("visual-player").getAttribute("src") ||
        $("visual-player").getAttribute("src").includes("preview-"))) play(view.preview.url);
    if (!view.preview.url && $("visual-player").getAttribute("src")?.includes("preview-")) {
      $("visual-player").pause(); $("visual-player").removeAttribute("src"); $("visual-player").hidden = true;
    }
    const playing = $("visual-player").getAttribute("src");
    if (playing && playing.includes("variant-") && !view.variants.some((v) => v.inline_url === playing)) {
      $("visual-player").pause(); $("visual-player").removeAttribute("src"); $("visual-player").hidden = true;
    }
    const states = { draft: "Bản nháp", approved: "Đã duyệt", stale: "Cũ — dựng lại", building: "Đang dựng" };
    const seconds = (n) => {
      if (n == null) return "—";
      const rounded = Math.round(n);
      return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
    };
    $("visual-variants").replaceChildren(...view.variants.map((v) => {
      const actions = el("td");
      const button = (text, action) => {
        const b = el("button", { type: "button", class: "btn small", text });
        b.disabled = visualPending; b.addEventListener("click", action); actions.append(b);
      };
      const path = `/variants/r${v.revision}/${v.key12}`;
      if (v.inline_url) button("Xem", () => play(v.inline_url));
      if (v.state === "draft" && v.size != null) button("Duyệt", () => performVisual(() => request(path + "/approve", "POST")));
      if (v.download_url) actions.append(el("a", { href: v.download_url, class: "btn small", text: "Tải bản đăng", download: "" }));
      if (v.job && v.job.active) button("Hủy", () => performVisual(() => request(path + "/cancel", "POST")));
      else if (v.size == null) button("Dựng lại", () => performVisual(() => request("/variants", "POST", v.spec)));
      else button("Xóa", () => { if (confirm("Xóa variant này?")) performVisual(() => request(path, "DELETE")); });
      const size = v.size == null ? "—" : v.size >= 1e9 ? `${(v.size / 1e9).toFixed(2)} GB` : `${(v.size / 1e6).toFixed(1)} MB`;
      const row = el("tr", {}, ...[(v.spec.visual ? sourceLabel(v.spec.visual.asset_id) : "Original") +
          (v.spec.music ? ` · Nhạc ${v.spec.music.asset_id.slice(0, 12)} · ${v.spec.music.level_lu} LU` : " · Chỉ giọng giảng"), `r${v.revision} · ${states[v.state]}`, size, seconds(v.duration),
        seconds(v.build_seconds), v.method || "—"].map((text) => el("td", { text })), actions);
      if (v.job && v.job.error) row.firstChild.append(el("p", { class: "error small", text: v.job.error }));
      return row;
    }));
  }
  async function performVisual(action) {
    if (visualPending) return;
    visualPending = true; drawVisual(); $("visual-msg").textContent = "";
    try { await action(); }
    catch (e) { $("visual-msg").textContent = e.message; }
    finally { visualPending = false; await load(); }
  }
  $("visual-source").addEventListener("change", motionOptions);
  $("visual-preview").addEventListener("click", () => performVisual(() => request("/preview", "POST", visualSpec())));
  $("visual-build").addEventListener("click", () => performVisual(() => request("/variants", "POST", visualSpec())));
  $("visual-cancel-preview").addEventListener("click", () => performVisual(() => request(`/variants/r${view.preview.revision}/preview/cancel`, "POST")));
  function musicSpec() {
    const source = view.variants.find((v) => v.key12 === $("music-visual").value);
    return { visual: source ? source.spec.visual : null,
      music: $("music-source").value ? { asset_id: $("music-source").value, level_lu: Number($("music-level").value),
        fade_in: Number($("music-in").value), fade_out: Number($("music-out").value),
        loop_crossfade: Number($("music-crossfade").value) } : null };
  }
  $("music-level").addEventListener("input", () => { $("music-level-value").textContent = $("music-level").value + " LU"; });
  for (const [id, route] of [["music-preview", "/preview"], ["music-build", "/variants"]]) {
    $(id).addEventListener("click", () => performVisual(async () => {
      const spec = musicSpec();
      if (!spec.visual && !spec.music) { $("visual-msg").textContent = "Chỉ giọng giảng + Original: dùng video TC3 đã ghép."; return; }
      await request(route, "POST", spec);
    }));
  }
  load();
})();
