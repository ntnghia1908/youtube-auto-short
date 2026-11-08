/* Room transport shared by every page: client id, commands, polling, invitation bar and "Xem chung"
   buttons. The room UI itself lives in listen.js (one interface, solo / room modes). */
(() => {
  "use strict";
  let client;
  try { client = sessionStorage.getItem("auto-short-watch-client"); } catch (_) { /* Storage disabled. */ }
  if (!client) {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    client = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    try { sessionStorage.setItem("auto-short-watch-client", client); } catch (_) { /* Keep it for this page. */ }
  }
  // listen.js sets active / handler / message / onVersion when its page is in room mode.
  const room = { active: false, handler: null, message: null, onVersion: null };
  let cached = { version: null, queue: [] };   // queue cache: the server omits `queue` while queue_version matches
  let state = null, sending = Promise.resolve(), pending = 0, pollTimer, pollGeneration = 0, pageHidden = false;

  async function request(method = "GET", body, path = "/api/watch") {
    const isRoom = path.startsWith("/api/watch") && !path.startsWith("/api/watch/log");
    if (isRoom && !body && cached.version !== null) path += `${path.includes("?") ? "&" : "?"}queue_version=${encodeURIComponent(cached.version)}`;
    const response = await fetch(path, {
      method, cache: "no-store", headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify({ ...body, client, ...(isRoom && cached.version !== null ? { queue_version: cached.version } : {}) }) : undefined,
    });
    const data = await response.json();
    if (response.ok && isRoom && data.queue_version !== undefined) {
      if (data.queue === undefined) data.queue = cached.queue;
      else cached = { version: data.queue_version, queue: data.queue };
    }
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : "Yêu cầu không hợp lệ");
      error.status = response.status;
      throw error;
    }
    return data;
  }
  const message = (text) => { if (room.active && room.message) room.message(text || ""); };
  function command(action, extra = {}, force = false) {
    pending++;
    // Serialize this client's controls; polling cannot overwrite an unacknowledged local gesture.
    const result = sending.then(async () => {
      try {
        const data = await request("POST", { action, ...extra });
        accept(data, force);
        message("");
        return data;
      } catch (error) {
        if (error.status === 409) await poll();
        else message(error.message);
        throw error;
      }
    });
    sending = result.catch(() => {}).finally(() => { pending--; });
    return result;
  }
  const invite = document.createElement("div");
  invite.className = "watch-invite"; invite.hidden = true; document.body.prepend(invite);
  function accept(data, force = false) {
    if (state && data.version < state.version) return;
    if (state && data.version !== state.version && room.onVersion) room.onVersion();
    state = data;
    if (room.active) { room.handler(data, force); return; }
    invite.hidden = !data.video_url || data.by === client;
    if (!invite.hidden) {
      const link = document.createElement("a"); link.href = "/watch"; link.textContent = "Vào xem";
      invite.replaceChildren(document.createTextNode(`Đang xem chung: ${data.title} — `), link);
    }
  }
  async function poll(force = false) {
    try {
      const data = await request("GET", undefined, "/api/watch" + (room.active ? `?client=${encodeURIComponent(client)}` : ""));
      if (!pending) { accept(data, force); message(""); }
      return data;
    } catch (error) { message(`Không thể cập nhật phòng: ${error.message}`); }
  }
  async function tick(force = false) {
    const generation = pollGeneration;
    await poll(force);
    if (pageHidden || generation !== pollGeneration) return;
    pollTimer = setTimeout(tick, room.active || state?.video_url ? 1000 : 10000);
  }

  function eligible(v) {
    return v.controls && v.id !== "dq-awake" && v.id !== "awake" && v.id !== "listen-video"
      && !v.closest("[hidden]") && v.getBoundingClientRect().width > 0 && v.getBoundingClientRect().height > 0
      && getComputedStyle(v).visibility !== "hidden" && getComputedStyle(v).visibility !== "collapse";
  }
  function entryFor(v) {
    const raw = v.currentSrc || v.getAttribute("src") || v.querySelector("source")?.getAttribute("src");
    if (!raw) throw new Error("Video chưa có đường dẫn");
    const url = new URL(raw, location.href);
    if (url.origin !== location.origin || !["http:", "https:"].includes(url.protocol)) {
      throw new Error("Chỉ xem chung video cùng trang web");
    }
    let title;
    for (let card = v.parentElement; card && card !== document.body; card = card.parentElement) {
      const heading = card.querySelector(".short-title, .fv-title, .fv-main strong, h1, h2, h3, h4");
      if (heading?.textContent.trim()) { title = heading.textContent.trim(); break; }
    }
    if (!title) {
      try { title = decodeURIComponent(url.pathname.split("/").pop()); } catch (_) { title = url.pathname.split("/").pop(); }
    }
    return { url: url.pathname + url.search, title: Array.from(title || "Video").slice(0, 200).join("") };
  }

  const buttons = new Map();
  function scan() {
    for (const [v, b] of buttons) {
      if (!v.isConnected) { b.remove(); buttons.delete(v); }
      else {
        const hidden = !eligible(v);
        if (b.hidden !== hidden) b.hidden = hidden;
      }
    }
    document.querySelectorAll("video[controls]").forEach((v) => {
      if (!eligible(v) || buttons.has(v)) return;
      const button = document.createElement("button");
      button.className = "btn small watch-start"; button.type = "button"; button.textContent = "Xem chung";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const videos = Array.from(document.querySelectorAll("video[controls]")).filter(eligible);
          if (videos.length > 300) throw new Error("Danh sách tối đa 300 video; hãy lọc bớt trước khi xem chung");
          const queue = videos.map(entryFor), index = videos.indexOf(v);
          if (index < 0) return;
          await command("set", { queue, index, position: Number.isFinite(v.currentTime) ? v.currentTime : 0 });
          location.assign("/watch");
        } catch (error) { button.textContent = error.message; }
        finally { button.disabled = false; }
      });
      v.insertAdjacentElement("afterend", button); buttons.set(v, button);
    });
  }
  window.AutoShortWatch = {
    client, room, request, command, poll,
    sent: () => sending,
    stopPolling() { pageHidden = true; pollGeneration++; clearTimeout(pollTimer); },
    resume() { pageHidden = false; tick(true); },
    leave() { navigator.sendBeacon("/api/watch/leave", new Blob([JSON.stringify({ client })], { type: "application/json" })); },
    async end() { await sending; accept(await request("DELETE", {}), true); },
  };
  let scheduled = false;
  new MutationObserver(() => {
    if (!scheduled) { scheduled = true; requestAnimationFrame(() => { scheduled = false; scan(); }); }
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "style", "class", "controls"] });
  scan();
  tick();
})();
