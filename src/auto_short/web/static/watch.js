(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let client;
  try { client = sessionStorage.getItem("auto-short-watch-client"); } catch (_) { /* Storage disabled. */ }
  if (!client) {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    client = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    try { sessionStorage.setItem("auto-short-watch-client", client); } catch (_) { /* Keep it for this page. */ }
  }
  const inRoom = !!$("watch-room");
  const video = $("watch-video");
  let pauseTimer = null, lastHiddenAt = -Infinity, pageHidden = false;
  let player;
  function cancelPause() { clearTimeout(pauseTimer); pauseTimer = null; if (player) player.syncBlocked = false; }
  function hiddenPause() {
    if (player?.inPiP()) return false;
    return pageHidden || (player ? player.isHidden() : document.visibilityState === "hidden") || performance.now() - lastHiddenAt < 1500;
  }
  let state = null;
  let sending = Promise.resolve(), pending = 0, pollTimer, pollGeneration = 0;

  async function request(method = "GET", body, path = "/api/watch") {
    const response = await fetch(path, {
      method, cache: "no-store", headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify({ ...body, client }) : undefined,
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : "Yêu cầu không hợp lệ");
      error.status = response.status;
      throw error;
    }
    return data;
  }
  function message(text) { if (inRoom) $("watch-message").textContent = text || ""; }
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
  function renderRoom() {
    const active = !!state.video_url;
    $("watch-title").textContent = active ? AutoShortPlayer.heading(state) : "Chưa có phòng xem chung";
    $("watch-meta").textContent = active && state.ep_label ? `Tập ${state.ep_label} · ${state.kind === "khaithi" ? "Khai thị" : "Short"} ${state.number} / ${state.total}` : "";
    $("watch-viewers").textContent = `Đang xem: ${Object.keys(state.viewers).length} người`;
    $("watch-end").disabled = !active;
    player.renderEpisodeList($("watch-queue"), state.queue, state.index, (index) => {
      player.hideNotice();
      command("goto", { index }, true).then(() => player.scrollToVideo()).catch(() => {});
    }, false);
  }
  const invite = document.createElement("div");
  if (!inRoom) { invite.className = "watch-invite"; invite.hidden = true; document.body.prepend(invite); }
  function accept(data, force = false) {
    if (state && data.version < state.version) return;
    if (state && data.version !== state.version) {
      cancelPause();
    }
    state = data;
    if (!inRoom) {
      invite.hidden = !data.video_url || data.by === client;
      if (!invite.hidden) {
        const link = document.createElement("a"); link.href = "/watch"; link.textContent = "Vào xem";
        invite.replaceChildren(document.createTextNode(`Đang xem chung: ${data.title} — `), link);
      }
      return;
    }
    renderRoom();
    player.setState(data, force || data.by !== client, pauseTimer !== null, data.by !== client);
  }

  async function poll(force = false) {
    try {
      const data = await request("GET", undefined, "/api/watch" + (inRoom ? `?client=${encodeURIComponent(client)}` : ""));
      if (!pending) { accept(data, force); message(""); }
      return data;
    } catch (error) { message(`Không thể cập nhật phòng: ${error.message}`); }
  }
  async function tick(force = false) {
    const generation = pollGeneration;
    await poll(force);
    if (pageHidden || generation !== pollGeneration) return;
    pollTimer = setTimeout(tick, inRoom || state?.video_url ? 1000 : 10000);
  }

  function eligible(v) {
    return v.controls && v.id !== "dq-awake" && v.id !== "awake" && v !== video && v.id !== "listen-video"
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
    client,
    async start(queue, position = 0) {
      await command("set", { queue, index: 0, position });
      location.assign("/watch");
    },
  };
  if (inRoom) {
    const navigate = (action) => {
      if (state?.video_url) { cancelPause(); return command(action, { expect_version: state.version }, true).catch(() => {}); }
    };
    player = new AutoShortPlayer("watch", {
      client, request, message, onNavigate: navigate,
      onEnded: (position) => { cancelPause(); command("ended", { expect_version: state.version, position }, true).catch(() => {}); },
      onAdvance: () => command("advance_now", { expect_version: state.version }, true).catch(() => {}),
      onCancelAdvance: () => command("cancel_advance", { expect_version: state.version }, true).catch(() => {}),
      onEpisode: (episode) => { player.hideNotice(); command("episode", { episode }, true).then(() => player.scrollToVideo()).catch(() => {}); },
      onFavorite: () => poll(true),
      onAuto: (auto) => { command("auto", { auto }).catch(() => poll(true)); },
      onAction(action, extra, force = false) {
        if (action === "pause" && !force) {
          if (hiddenPause()) return;
          cancelPause();
          const version = state.version;
          player.syncBlocked = true;
          // Some phones pause before visibilitychange/pagehide: preserve WATCH1's transition window.
          pauseTimer = setTimeout(() => {
            pauseTimer = null; player.syncBlocked = false;
            if (!hiddenPause() && player.media().paused && state?.version === version) {
              command("pause", extra).catch(() => {});
            }
          }, 1500);
          return;
        }
        cancelPause(); command(action, extra, force).catch(() => {});
      },
    });
    $("watch-end").addEventListener("click", async () => {
      try { cancelPause(); await sending; accept(await request("DELETE", {}), true); } catch (error) { message(error.message); }
    });
    const leave = () => navigator.sendBeacon("/api/watch/leave", new Blob([JSON.stringify({ client })], { type: "application/json" }));
    document.addEventListener("visibilitychange", () => {
      lastHiddenAt = performance.now(); cancelPause();
      if (!player.isHidden()) {
        sending.then(() => poll(true));
      }
    });
    window.addEventListener("pagehide", () => {
      pageHidden = true; pollGeneration++; lastHiddenAt = performance.now(); cancelPause(); clearTimeout(pollTimer); leave();
    });
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) { pageHidden = false; lastHiddenAt = performance.now(); tick(true); }
    });
  } else {
    let scheduled = false;
    new MutationObserver(() => {
      if (!scheduled) { scheduled = true; requestAnimationFrame(() => { scheduled = false; scan(); }); }
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "style", "class", "controls"] });
    scan();
  }
  tick();
})();
