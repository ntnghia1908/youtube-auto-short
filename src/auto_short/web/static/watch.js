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
  const video = $("watch-video"), audio = $("watch-audio");
  let background = false;
  try { background = inRoom && localStorage.getItem("auto-short-watch-background") === "true"; } catch (_) { /* Private mode. */ }
  const media = () => background ? audio : video;
  let handoff = null, pauseTimer = null, lastHiddenAt = -Infinity, pageHidden = false, favoriteBusy = false;
  function cancelPause() { clearTimeout(pauseTimer); pauseTimer = null; }
  function hiddenPause() {
    return pageHidden || document.visibilityState === "hidden" || performance.now() - lastHiddenAt < 1500;
  }
  let state = null, receivedAt = 0, sourceKey = null, loading = false, queueKey = "";
  let sending = Promise.resolve(), pending = 0, pollTimer, pollGeneration = 0;
  const programmed = new Map();

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
  function message(text) { if (inRoom) $("watch-message").textContent = text; }
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
  function arm(event, value) {
    const mark = { value, until: performance.now() + 5000 };
    programmed.set(event, mark);
    return mark;
  }
  function isProgrammed(event) {
    const current = media();
    if (loading) { programmed.delete(event); return true; }
    const mark = programmed.get(event);
    if (!mark) return false;
    const actual = event === "seeked" ? current.currentTime : event === "ratechange" ? current.playbackRate : current.paused;
    const matches = typeof actual === "number" ? Math.abs(actual - mark.value) < (event === "ratechange" ? .001 : 1) : actual === mark.value;
    programmed.delete(event);
    return performance.now() < mark.until && matches;
  }
  function targetPosition() {
    return state.position + (state.paused ? 0 : Math.max(0,
      state.server_time - state.updated_at + (performance.now() - receivedAt) / 1000) * state.rate);
  }
  function playMedia(current) {
    const playMark = arm("play", false), key = sourceKey;
    current.play().then(() => {
      if (current === media() && key === sourceKey) $("watch-play").hidden = true;
    }).catch(() => {
      if (programmed.get("play") === playMark) programmed.delete("play");
      if (current === media() && key === sourceKey && state?.video_url && !state.paused) $("watch-play").hidden = false;
    });
  }
  function syncPlayback(transfer = null) {
    const current = media();
    if (!state?.video_url || loading || !current.readyState || pauseTimer !== null) return;
    const position = transfer ? transfer.position + (transfer.paused ? 0 : (performance.now() - transfer.at) / 1000 * transfer.rate) : targetPosition();
    const target = Math.min(position, Number.isFinite(current.duration) ? current.duration : Infinity);
    const rate = transfer ? transfer.rate : state.rate, paused = transfer ? transfer.paused : state.paused;
    if (Math.abs(current.currentTime - target) > (transfer ? .05 : 1)) {
      arm("seeked", target); current.currentTime = target;
    }
    if (current.playbackRate !== rate) { arm("ratechange", rate); current.playbackRate = rate; }
    if (paused) {
      if (!current.paused) { arm("pause", true); current.pause(); }
      $("watch-play").hidden = true;
    } else if (current.paused && !current.ended) playMedia(current);
  }
  function loadMedia(transfer = null) {
    loading = true; programmed.clear(); handoff = transfer;
    const current = media();
    current.src = state.video_url; current.load();
    // Calling play during the checkbox gesture preserves mobile playback permission.
    if (transfer && !transfer.paused) playMedia(current);
  }
  function updateSession() {
    if (!("mediaSession" in navigator)) return;
    if (typeof MediaMetadata === "function") navigator.mediaSession.metadata = state.video_url
      ? new MediaMetadata({ title: state.title || "Video", artist: "Auto Short" }) : null;
    navigator.mediaSession.playbackState = state.video_url ? (state.paused ? "paused" : "playing") : "none";
  }
  function renderRoom() {
    const active = !!state.video_url;
    $("watch-title").textContent = active ? state.title : "Chưa có phòng xem chung";
    $("watch-viewers").textContent = `Đang xem: ${Object.keys(state.viewers).length} người`;
    video.hidden = !active || background;
    audio.hidden = !active || !background;
    const fav = state.queue[state.index]?.fav, heart = $("watch-favorite");
    heart.hidden = !fav; heart.disabled = favoriteBusy;
    heart.textContent = fav?.favorite ? "♥" : "♡";
    heart.classList.toggle("on", !!fav?.favorite);
    heart.setAttribute("aria-pressed", fav?.favorite ? "true" : "false");
    heart.title = fav?.favorite ? "Bỏ yêu thích" : "Yêu thích";
    heart.setAttribute("aria-label", heart.title);
    updateSession();
    $("watch-prev").disabled = !active || state.index === 0;
    $("watch-next").disabled = !active;
    $("watch-end").disabled = !active;
    $("watch-rate").disabled = !active;
    // Keep custom native playback rates visible as well.
    if (active && !Array.from($("watch-rate").options).some((o) => Number(o.value) === state.rate)) {
      const option = document.createElement("option");
      option.value = String(state.rate); option.textContent = `${state.rate}×`;
      $("watch-rate").append(option);
    }
    $("watch-rate").value = String(state.rate);
    const signature = JSON.stringify([state.queue, state.index]);
    if (queueKey !== signature) {
      queueKey = signature;
      $("watch-queue").replaceChildren(...state.queue.map((entry, index) => {
        const li = document.createElement("li"), button = document.createElement("button");
        button.type = "button"; button.className = "btn"; button.textContent = entry.title || entry.url;
        if (index === state.index) button.setAttribute("aria-current", "true");
        button.addEventListener("click", () => { command("goto", { index }, true).catch(() => {}); });
        li.append(button); return li;
      }));
    }
  }
  const invite = document.createElement("div");
  if (!inRoom) { invite.className = "watch-invite"; invite.hidden = true; document.body.prepend(invite); }
  function accept(data, force = false) {
    if (state && data.version < state.version) return;
    if (state && data.version !== state.version) cancelPause();
    state = data; receivedAt = performance.now();
    if (!inRoom) {
      invite.hidden = !data.video_url || data.by === client;
      if (!invite.hidden) {
        const link = document.createElement("a"); link.href = "/watch"; link.textContent = "Vào xem";
        invite.replaceChildren(document.createTextNode(`Đang xem chung: ${data.title} — `), link);
      }
      return;
    }
    renderRoom();
    const key = data.video_url ? JSON.stringify([data.index, data.video_url]) : null;
    if (key !== sourceKey) {
      sourceKey = key;
      programmed.clear(); handoff = null;
      if (key === null) {
        loading = true;
        for (const current of [video, audio]) { current.pause(); current.removeAttribute("src"); current.load(); }
        $("watch-play").hidden = true;
      } else loadMedia();
    } else if (force || data.by !== client) syncPlayback();
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
    return v.controls && v.id !== "dq-awake" && v.id !== "awake" && v !== video
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
    const entry = { url: url.pathname + url.search, title: Array.from(title || "Video").slice(0, 200).join("") };
    try {
      const fav = JSON.parse(v.dataset.watchFav);
      if (fav && ["playlist_id", "episode_id", "clip"].every((key) => typeof fav[key] === "string") && typeof fav.favorite === "boolean") {
        entry.fav = { playlist_id: fav.playlist_id, episode_id: fav.episode_id, clip: fav.clip, favorite: fav.favorite };
      }
    } catch (_) { /* Missing or malformed metadata does not prevent sharing the video. */ }
    return entry;
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
  if (inRoom) {
    $("watch-background").checked = background;
    for (const current of [video, audio]) {
      current.addEventListener("loadedmetadata", () => {
        if (current !== media() || !state?.video_url) return;
        loading = false;
        const transfer = handoff?.version === state.version ? handoff : null;
        handoff = null; syncPlayback(transfer);
      });
      for (const [event, action] of [["play", "play"], ["pause", "pause"], ["seeked", "seek"], ["ratechange", "rate"]]) {
        current.addEventListener(event, () => {
          if (current !== media() || isProgrammed(event) || !state?.video_url || (event === "pause" && current.ended)) return;
          if (event === "pause") {
            if (hiddenPause()) return;
            cancelPause();
            const version = state.version, position = current.currentTime;
            // Wait through the transition window: some phones pause BEFORE visibilitychange/pagehide.
            pauseTimer = setTimeout(() => {
              pauseTimer = null;
              if (!hiddenPause() && current === media() && current.paused && state?.version === version) {
                command("pause", { position }).catch(() => {});
              }
            }, 1500);
            return;
          }
          cancelPause();
          command(action, { position: current.currentTime, ...(action === "rate" ? { rate: current.playbackRate } : {}) }).catch(() => {});
        });
      }
      current.addEventListener("ended", () => {
        if (current === media() && !loading && state?.video_url) {
          cancelPause(); command("next", { expect_version: state.version }, true).catch(() => {});
        }
      });
    }
    $("watch-background").addEventListener("change", () => {
      const previous = media();
      const transfer = state?.video_url ? { position: loading ? targetPosition() : previous.currentTime,
        paused: loading ? state.paused : previous.paused, rate: loading ? state.rate : previous.playbackRate,
        version: state.version, at: performance.now() } : null;
      background = $("watch-background").checked;
      try { localStorage.setItem("auto-short-watch-background", String(background)); } catch (_) { /* Private mode. */ }
      cancelPause();
      previous.pause(); previous.removeAttribute("src"); previous.load();
      if (state) renderRoom();
      if (transfer) loadMedia(transfer);
    });
    $("watch-favorite").addEventListener("click", async () => {
      const index = state?.index, fav = state?.queue[index]?.fav;
      if (!fav || favoriteBusy) return;
      favoriteBusy = true; renderRoom();
      try {
        const saved = await request("POST", { episode_id: fav.episode_id, clip: fav.clip, favorite: !fav.favorite },
          `/api/playlists/${encodeURIComponent(fav.playlist_id)}/favorites`);
        const latest = state?.queue[index]?.fav;
        if (latest && ["playlist_id", "episode_id", "clip"].every((key) => latest[key] === fav[key])) {
          await command("favorite", { index, favorite: saved.favorite });
        }
      } catch (error) { message(error.message); }
      finally { favoriteBusy = false; renderRoom(); }
    });
    const navigate = (action) => {
      if (state?.video_url) { cancelPause(); return command(action, { expect_version: state.version }, true).catch(() => {}); }
    };
    $("watch-prev").addEventListener("click", () => navigate("prev"));
    $("watch-next").addEventListener("click", () => navigate("next"));
    $("watch-rate").addEventListener("change", () => {
      command("rate", { rate: Number($("watch-rate").value), position: media().currentTime }, true).catch(() => {});
    });
    $("watch-play").addEventListener("click", () => {
      media().play().then(() => { $("watch-play").hidden = true; }).catch(() => { message("Không phát được video. Hãy thử lại."); });
    });
    $("watch-end").addEventListener("click", async () => {
      try { cancelPause(); await sending; accept(await request("DELETE", {}), true); } catch (error) { message(error.message); }
    });
    if ("mediaSession" in navigator) {
      for (const [name, action] of [["play", "play"], ["pause", "pause"], ["previoustrack", "prev"], ["nexttrack", "next"]]) {
        try {
          navigator.mediaSession.setActionHandler(name, () => {
            if (!state?.video_url) return;
            cancelPause();
            if (action === "prev" || action === "next") navigate(action);
            else command(action, { position: loading ? targetPosition() : media().currentTime }, true).catch(() => {});
          });
        } catch (_) { /* Some browsers expose only a subset of Media Session actions. */ }
      }
    }
    const leave = () => navigator.sendBeacon("/api/watch/leave", new Blob([JSON.stringify({ client })], { type: "application/json" }));
    document.addEventListener("visibilitychange", () => {
      lastHiddenAt = performance.now(); cancelPause();
      if (document.visibilityState !== "hidden") sending.then(() => poll(true));
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
