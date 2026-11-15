/* Shared title editor for management cards and the playing solo track. */
(() => {
  "use strict";
  const { el, api } = window.AutoShort;
  function titleEditor(s, { episodeId, locked = false, maxChars = 60, onSaved, open = false, onToggle }) {
    let sending = false;
    const isLocked = () => sending || (typeof locked === "function" ? locked() : locked);
    const current = (s.pending_title && s.pending_title.text) || (s.title && s.title.text) || s.ai_title || "";
    const box = el("div", { class: "title-edit" });
    const toggle = el("button", { class: "btn small", type: "button", text: open ? "Đóng" : "Sửa tiêu đề" });
    const panel = el("div", { class: "edit-panel", hidden: !open });
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
    const lockNote = el("p", { class: "lock-note muted small", text: "Đang có job chạy — đợi xong để lưu.", hidden: !isLocked() });
    panel.append(el("label", {}, "Tiêu đề mới ", counter), input, select, preview, msg,
      el("div", { class: "edit-actions" }, save, reset), lockNote);
    box.append(toggle, panel);

    let alt = null, timer = null, seq = 0, disposed = false;
    box.dispose = () => { disposed = true; ++seq; clearTimeout(timer); };
    const setValid = (ok) => { save.dataset.invalid = ok ? "0" : "1"; save.disabled = !ok || isLocked(); };
    const count = () => {
      const n = [...input.value.trim()].length;
      counter.textContent = `${n}/${maxChars}`;
      counter.classList.toggle("over", n > maxChars);
    };
    async function runPreview() {
      if (disposed) return;
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
      onToggle?.(!panel.hidden);
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
      if (disposed || isLocked()) return;
      const submitted = body.reset ? s.ai_title : body.alternative != null
        ? s.alternatives.find((a) => a.n === body.alternative).title : body.set.trim();
      sending = true; save.disabled = true;
      if (reset) reset.disabled = true;
      try {
        const result = await api(`/api/episodes/${encodeURIComponent(episodeId)}/shorts/${encodeURIComponent(s.clip_id)}/title`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        msg.textContent = result.queued === "restore" ? "Đang lấy lại nguồn từ 3090…" : "Đã lưu, đang render lại…";
        msg.className = "preview-msg small";
        onSaved?.(result, result.preview?.title ?? submitted);
        sending = false; lockNote.hidden = !isLocked();
      } catch (e) {
        sending = false;
        msg.textContent = e.message;
        msg.className = "preview-msg small error";
        save.disabled = isLocked();
        if (reset) reset.disabled = isLocked();
      }
    }
    save.addEventListener("click", () => send(alt !== null ? { alternative: alt } : { set: input.value }));
    if (reset) reset.disabled = isLocked();
    if (reset) reset.addEventListener("click", () => send({ reset: true }));
    setValid(false);
    if (open) { count(); runPreview(); }
    return box;
  }

  window.AutoShort.titleEditor = titleEditor;
})();
