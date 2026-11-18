/* SCH1: render local channel snapshots. No YouTube API calls. */
(() => {
  "use strict";
  const { el, api } = AutoShort;
  const kinds = { vertical: "Bản dọc", kt: "Khai thị", short: "Short", post: "Bài post" };
  const clock = new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    hourCycle: "h23",
  });
  function date(value) {
    const stamp = new Date(value);
    return value && Number.isFinite(stamp.getTime()) ? clock.format(stamp) : "—";
  }
  function cell(group) {
    const last = group.last_scheduled, pub = group.last_public;
    return el("td", { class: group.warning ? "note" : "" },
      el("strong", { text: last ? last.key : "Chưa có lịch" }),
      el("div", { class: "schedule-date", text: last ? date(last.publish_at) : "—" }),
      el("div", { text: group.days_remaining > 0 ? `Còn ${group.days_remaining} ngày` : "hết lịch" }),
      el("div", { class: "muted small", text: `${group.scheduled_count || 0} mục còn lịch` }),
      el("div", { class: "muted small", text: "Công khai gần nhất: " +
        (pub ? `${pub.key} · ${date(pub.published_at)}` : "chưa có số liệu") }));
  }
  function limited(label, items, render, suffix = "") {
    if (!items.length) return null;
    const line = el("div", { class: "small note" }, el("strong", { text: label }));
    const list = (entries) => {
      const span = el("span");
      entries.forEach((item, index) => { if (index) span.append("; "); span.append(render(item)); });
      return span;
    };
    line.append(list(items.slice(0, 10)), suffix);
    if (items.length > 10) line.append(el("details", {},
      el("summary", { text: `và ${items.length - 10} mã khác` }), list(items.slice(10))));
    return line;
  }
  function warnings(channel) {
    const box = el("div", { class: "schedule-warnings" });
    const missing = Object.entries(channel.missing || {}).flatMap(([kind, keys]) =>
      keys.map(key => ({ key, kind })));
    const duplicates = channel.duplicates || [];
    const absent = limited("⚠ Thiếu: ", missing,
      row => `${row.key} (${kinds[row.kind] || row.kind})`, " — upload bổ sung");
    const repeated = limited("⚠ Trùng: ", duplicates, row => {
      const span = el("span", { text: `${row.key} — ` });
      row.copies.forEach((copy, index) => {
        if (index) span.append(", ");
        span.append(copy.keep ? "giữ bản " : "xóa bản ", el("a", {
          href: `https://studio.youtube.com/video/${encodeURIComponent(copy.youtube_id)}/edit`,
          target: "_blank", rel: "noopener noreferrer", text: copy.youtube_id,
        }));
      });
      return span;
    });
    if (absent) box.append(absent);
    if (repeated) box.append(repeated);
    if (channel.unrecognized_count) box.append(el("p", { class: "small note",
      text: `⚠ Không nhận ra loại: ${channel.unrecognized_count} video` }));
    for (const [kind, pending] of Object.entries(channel.pending || {})) {
      const episodes = pending.episodes || [];
      if (pending.count && episodes.length) box.append(el("p", { class: "small muted",
        text: `${kinds[kind]}: chưa đăng T${episodes[0]}–T${episodes[episodes.length - 1]} (${pending.count} mục)` }));
    }
    return box.childNodes.length ? box : null;
  }
  function render(channel) {
    const table = el("table", { class: "storage-table schedule-table" },
      el("thead", {}, el("tr", {}, ...Object.values(kinds).map(text => el("th", { scope: "col", text })))),
      el("tbody", {}, el("tr", {}, ...Object.keys(kinds).map(kind => cell(channel.kinds[kind] || {})))));
    return el("section", { class: "card" }, el("h2", { text: channel.channel_title }),
      el("p", { class: channel.stale ? "small note" : "small muted",
        text: `${channel.stale ? "Số liệu cũ (cập nhật " : "Cập nhật "}${date(channel.updated_at)}${channel.stale ? ")" : ""}` }),
      el("div", { class: "table-wrap" }, table), warnings(channel),
      channel.post_error ? el("p", { class: "error small", text: channel.post_error }) : null);
  }
  async function load() {
    const message = document.querySelector("#schedule-message");
    const button = document.querySelector("#schedule-refresh");
    button.disabled = true;
    try {
      const data = await api("/api/schedule-overview");
      document.querySelector("#schedule-channels").replaceChildren(...data.channels.map(render));
      message.className = "muted";
      message.textContent = data.channels.length ? "" : "Chưa có số liệu";
    } catch (err) {
      message.className = "error";
      message.textContent = err.message;
    } finally { button.disabled = false; }
  }
  document.querySelector("#schedule-refresh").addEventListener("click", load);
  load();
})();
