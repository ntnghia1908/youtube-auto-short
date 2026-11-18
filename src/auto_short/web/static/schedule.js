/* SCH1: local snapshots; explicit token renewal uses server-side OAuth device flow. */
(() => {
  "use strict";
  const { el, api } = AutoShort;
  const kinds = { vertical: "Bản dọc", kt: "Khai thị", short: "Short", post: "Bài post" };
  const authSessions = new Map();
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
  function tokenControl(stem, token) {
    if (!stem || !token) return null;
    const state = authSessions.get(stem) || {};
    authSessions.set(stem, state);
    const label = token.days_left == null ? "Token không rõ hạn" : token.expired ?
      "Token hết hạn — lấy lại token" : `Token còn ${token.days_left} ngày (hết ${date(token.expires_at * 1000)})`;
    const button = el("button", { class: "btn small", type: "button", text: "Lấy lại token" });
    const box = el("div", { role: "status", "aria-live": "polite" });
    state.update = () => {
      const data = state.data || {};
      button.disabled = data.status === "waiting";
      box.replaceChildren(...(data.status === "waiting" ? [
        el("p", { text: "Mở trang Google và nhập mã để lấy lại token:" }),
        el("strong", { class: "device-code", text: data.user_code }),
        el("a", { href: "https://www.google.com/device", target: "_blank", rel: "noopener noreferrer",
          text: "https://www.google.com/device" }),
      ] : [el("p", { class: data.status === "error" ? "error small" : "small", text: data.message || "" })]));
    };
    const endpoint = `/api/youtube-tokens/${encodeURIComponent(stem)}/auth`;
    async function poll() {
      try {
        state.data = await api(endpoint);
        state.update();
        if (state.data.status === "waiting") state.timer = setTimeout(poll, 5000);
        else if (state.data.status === "done") load();
      } catch (err) {
        state.data = { status: "error", message: err.message };
        state.update();
      }
    }
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        state.data = await api(endpoint, { method: "POST" });
        state.update();
        if (state.data.status === "waiting") {
          clearTimeout(state.timer);
          state.timer = setTimeout(poll, 5000);
        }
      } catch (err) {
        state.data = { status: "error", message: err.message };
        state.update();
      }
    });
    state.update();
    return el("div", {}, el("p", { class: token.expired ? "error small" : token.warning ? "note small" : "muted small",
      text: label }), button, box);
  }
  function checkError(error) {
    return el("p", { class: "error small", text:
      `Lần đọc ${date(error.at)} lỗi: ${error.message} — tự thử lại 15:30` });
  }
  function render(channel, tokens, errors) {
    const table = el("table", { class: "storage-table schedule-table" },
      el("thead", {}, el("tr", {}, ...Object.values(kinds).map(text => el("th", { scope: "col", text })))),
      el("tbody", {}, el("tr", {}, ...Object.keys(kinds).map(kind => cell(channel.kinds[kind] || {})))));
    return el("section", { class: "card" }, el("h2", { text: channel.channel_title }),
      el("p", { class: channel.stale ? "small note" : "small muted",
        text: `${channel.stale ? "Số liệu cũ (cập nhật " : "Cập nhật "}${date(channel.updated_at)}${channel.stale ? ")" : ""}` }),
      el("div", { class: "table-wrap" }, table), warnings(channel),
      ...errors.filter(error => error.token === channel.token).map(checkError),
      tokenControl(channel.token, tokens[channel.token]),
      channel.post_error ? el("p", { class: "error small", text: channel.post_error }) : null);
  }
  async function load() {
    const message = document.querySelector("#schedule-message");
    const button = document.querySelector("#schedule-refresh");
    button.disabled = true;
    try {
      const data = await api("/api/schedule-overview");
      const tokens = data.tokens || {}, errors = data.errors || [];
      const known = new Set(data.channels.map(channel => channel.token));
      const extra = Object.keys(tokens).filter(stem => !known.has(stem));
      document.querySelector("#schedule-channels").replaceChildren(
        ...(!data.channels.length ? [el("p", { class: "card note", text:
          "Chưa có số liệu. Số liệu cập nhật tự động lúc 15:30 giờ VN mỗi ngày (sau khi hạn mức YouTube mở lại lúc 15:00)." })] : []),
        ...data.channels.map(channel => render(channel, tokens, errors)),
        ...extra.map(stem => el("section", { class: "card" }, el("h2", { text: stem }),
          ...errors.filter(error => error.token === stem).map(checkError), tokenControl(stem, tokens[stem]))),
        ...errors.filter(error => !known.has(error.token) && !tokens[error.token]).map(checkError));
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
