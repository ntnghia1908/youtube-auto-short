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
  let state = null, receivedAt = 0, sourceKey = null, loading = false, queueKey = "";
  let sending = Promise.resolve(), pending = 0, pollTimer;
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
    if (loading) return true;
    const mark = programmed.get(event);
    if (!mark) return false;
    const actual = event === "seeked" ? video.currentTime : event === "ratechange" ? video.playbackRate : video.paused;
    const matches = typeof actual === "number" ? Math.abs(actual - mark.value) < (event === "ratechange" ? .001 : 1) : actual === mark.value;
    programmed.delete(event);
    return performance.now() < mark.until && matches;
  }
  function targetPosition() {
    return state.position + (state.paused ? 0 : Math.max(0,
      state.server_time - state.updated_at + (performance.now() - receivedAt) / 1000) * state.rate);
  }
  function syncPlayback() {
    if (!state?.video_url || loading || !video.readyState) return;
    const target = Math.min(targetPosition(), Number.isFinite(video.duration) ? video.duration : Infinity);
    if (Math.abs(video.currentTime - target) > 1) {
      arm("seeked", target);
      video.currentTime = target;
    }
    if (video.playbackRate !== state.rate) {
      arm("ratechange", state.rate);
      video.playbackRate = state.rate;
    }
    if (state.paused) {
      if (!video.paused) { arm("pause", true); video.pause(); }
      $("watch-play").hidden = true;
    } else if (video.paused && !video.ended) {
      const playMark = arm("play", false);
      const key = sourceKey;
      video.play().then(() => { $("watch-play").hidden = true; }).catch(() => {
        if (programmed.get("play") === playMark) programmed.delete("play");
        if (key === sourceKey && state?.video_url && !state.paused) $("watch-play").hidden = false;
      });
    }
  }
  function renderRoom() {
    const active = !!state.video_url;
    $("watch-title").textContent = active ? state.title : "Chưa có phòng xem chung";
    $("watch-viewers").textContent = `Đang xem: ${Object.keys(state.viewers).length} người`;
    video.hidden = !active;
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
      programmed.clear();
      if (key === null) {
        loading = true; video.pause(); video.removeAttribute("src"); video.load();
        $("watch-play").hidden = true;
      } else {
        loading = true; video.src = data.video_url; video.load();
      }
    } else if (force || data.by !== client) syncPlayback();
  }
  async function poll() {
    try {
      const data = await request("GET", undefined, "/api/watch" + (inRoom ? `?client=${encodeURIComponent(client)}` : ""));
      if (!pending) { accept(data); message(""); }
      return data;
    } catch (error) { message(`Không thể cập nhật phòng: ${error.message}`); }
  }
  async function tick() {
    await poll();
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
  if (inRoom) {
    video.addEventListener("loadedmetadata", () => { loading = false; syncPlayback(); });
    for (const [event, action] of [["play", "play"], ["pause", "pause"], ["seeked", "seek"], ["ratechange", "rate"]]) {
      video.addEventListener(event, () => {
        if (isProgrammed(event) || !state?.video_url || (event === "pause" && video.ended)) return;
        command(action, { position: video.currentTime, ...(action === "rate" ? { rate: video.playbackRate } : {}) }).catch(() => {});
      });
    }
    video.addEventListener("ended", () => {
      if (!loading && state?.video_url) command("next", { expect_version: state.version }, true).catch(() => {});
    });
    $("watch-prev").addEventListener("click", () => { command("prev", { expect_version: state.version }, true).catch(() => {}); });
    $("watch-next").addEventListener("click", () => { command("next", { expect_version: state.version }, true).catch(() => {}); });
    $("watch-rate").addEventListener("change", () => {
      command("rate", { rate: Number($("watch-rate").value), position: video.currentTime }, true).catch(() => {});
    });
    $("watch-play").addEventListener("click", () => {
      video.play().then(() => { $("watch-play").hidden = true; }).catch(() => { message("Không phát được video. Hãy thử lại."); });
    });
    $("watch-end").addEventListener("click", async () => {
      try { await sending; accept(await request("DELETE", {}), true); } catch (error) { message(error.message); }
    });
    const leave = () => navigator.sendBeacon("/api/watch/leave", new Blob([JSON.stringify({ client })], { type: "application/json" }));
    window.addEventListener("pagehide", () => { clearTimeout(pollTimer); leave(); });
    window.addEventListener("pageshow", (event) => { if (event.persisted) tick(); });
  } else {
    let scheduled = false;
    new MutationObserver(() => {
      if (!scheduled) { scheduled = true; requestAnimationFrame(() => { scheduled = false; scan(); }); }
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "style", "class", "controls"] });
    scan();
  }
  tick();
})();
