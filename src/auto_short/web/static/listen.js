/* One listening interface, two modes: solo (local queue) and room (shared watch party). */
(() => {
  "use strict";
  const $ = (name) => document.getElementById(`listen-${name}`);
  if (!$("queue")) return;
  const W = window.AutoShortWatch;
  const shell = location.pathname === "/watch";
  // Favorites use parts; ordinary listening uses episodes through the same group interface.
  const favPid = decodeURIComponent((location.pathname.match(/^\/playlists\/([^/]+)\/favorites$/) || [])[1] || "");   // /watch only loads the same interface in room mode
  const ROOM_MAX = 1000;                           // = MAX_QUEUE of WatchRoom
  const read = (key, fallback = null) => {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (_) { return fallback; }
  };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* Private mode. */ } };
  const episodeId = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
  const message = (text) => { $("message").textContent = text || ""; };
  async function request(method = "GET", body, path) {
    const response = await fetch(path, { method, cache: "no-store", headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : "Không tải được danh sách");
      error.status = response.status; throw error;
    }
    return data;
  }
  const episode = (id) => request("GET", null, `/api/episodes/${encodeURIComponent(id)}`);
  let all = [], items = [], index = -1, currentItem = null, state = null, version = 0, started = false;
  let storageKey, lastSave = 0;
  let inRoom = false, rstate = null, lastRoomIndex = -1;
  let pauseTimer = null, lastHiddenAt = -Infinity, roomHidden = false;
  let auto = read("auto-short-listen-auto", true) !== false;
  let filter = read("auto-short-listen-filter", "both");
  if (!["both", "short", "khaithi"].includes(filter)) filter = "both";
  // In Yêu thích an un-hearted item stays until the playing item changes (it finishes first).
  const same = (a, b) => !!a && !!b && a.episode_id === b.episode_id && a.clip_id === b.clip_id;
  const visible = (item) => (filter === "both" || item.kind === filter) && (!favPid || item.fav?.favorite || same(item, currentItem));
  function rebuildItems() {
    items = all.filter(visible);
    if (favPid) items = AutoShortPlayer.groupFavorites(items, filter);
  }
  const curItems = () => inRoom ? (rstate?.queue || []) : items;
  const curIndex = () => inRoom ? (rstate?.index ?? -1) : index;

  const cancelPause = () => { clearTimeout(pauseTimer); pauseTimer = null; player.syncBlocked = false; };
  const hiddenPause = () => player.inPiP() ? false : roomHidden || player.isHidden() || performance.now() - lastHiddenAt < 1500;
  const roomCommand = (action, extra = {}, force = false) => W.command(action, extra, force);

  const player = new AutoShortPlayer("listen", {
    client: W.client, request, message,
    getItems: curItems,
    getNext: () => curItems()[curIndex() + 1],
    onNavigate: (action) => inRoom ? roomNavigate(action) : navigate(action),
    onGroup(id) {
      if (inRoom) {
        const explicit = curItems().some((item) => item.group?.id === id);
        player.hideNotice(); roomCommand(explicit ? "group" : "episode", explicit ? { group: id } : { episode: id }, true)
          .then(() => player.scrollToVideo()).catch(() => {}); return;
      }
      const n = items.findIndex((item) => player.group(item)?.id === id);
      if (n >= 0) choose(n, true, 0, true);
    },
    onAuto(value) {
      if (inRoom) { roomCommand("auto", { auto: value }).catch(() => W.poll(true)); return; }
      auto = value; write("auto-short-listen-auto", auto);
      if (state) { state = { ...state, auto }; player.setState(state, false); }
    },
    onAction(action, extra, force) { inRoom ? roomAction(action, extra, force) : soloAction(action, extra, force); },
    onFavorite(fav, favorite) {
      if (favPid) for (const name of ["listen-favorite-changed", "favorites-changed"]) window.dispatchEvent(new Event(name));
      if (inRoom) { W.poll(true); return; }
      fav.favorite = favorite;
      player.render();
    },
  });
  const roomEnded = (position) => { cancelPause(); roomCommand("ended", { expect_version: rstate.version, position }, true).catch(() => {}); };
  const roomAdvance = () => roomCommand("advance_now", { expect_version: rstate.version }, true).catch(() => {});
  const roomCancel = () => roomCommand("cancel_advance", { expect_version: rstate.version }, true).catch(() => {});
  function roomNavigate(action) {
    if (rstate?.video_url) { cancelPause(); return roomCommand(action, { expect_version: rstate.version }, true).catch(() => {}); }
  }
  function roomAction(action, extra, force = false) {
    if (action === "pause" && !force) {
      if (hiddenPause()) return;
      cancelPause();
      const version = rstate.version;
      player.syncBlocked = true;
      // Some phones pause before visibilitychange/pagehide: preserve WATCH1's transition window.
      pauseTimer = setTimeout(() => {
        pauseTimer = null; player.syncBlocked = false;
        if (!hiddenPause() && player.media().paused && rstate?.version === version) roomCommand("pause", extra).catch(() => {});
      }, 1500);
      return;
    }
    cancelPause(); roomCommand(action, extra, force).catch(() => {});
  }
  function soloAction(action, extra, force) {
    if (!state) return;
    if (action === "play") started = true;
    state = { ...state, ...extra, paused: action === "pause" ? true : action === "play" ? false : state.paused,
      server_time: 0, updated_at: 0 };
    player.setState(state, !!force);
    save();
  }
  renderFilter();
  if (document.getElementById("episode-listen").hidden) player.suspend();
  const epLabel = (item) => `Tập ${item.ep_label || item.ep_index || "—"}`;
  const kindLabel = (item) => item.kind === "khaithi" ? "Khai thị" : "Short";
  function save() {
    // Keep the media identity separate from a filter's changing list/index.
    const item = currentItem;
    if (inRoom || !storageKey || !item || !started || player.loading) return;
    write(storageKey, { episode_id: item.episode_id, clip_id: item.clip_id,
      position: Number.isFinite(player.media().currentTime) ? player.media().currentTime : 0 });
  }
  function renderJump() {
    const eps = player.groups(), signature = JSON.stringify(eps);
    if ($("jump").dataset.signature !== signature) {
      $("jump").dataset.signature = signature;
      $("jump").replaceChildren(...eps.map((e) => {
        const option = document.createElement("option"); option.value = e.id; option.textContent = e.choice || e.label; return option;
      }));
    }
    const here = player.group(curItems()[curIndex()]);
    const noun = here?.kind === "part" ? "phần" : "tập";
    $("jump").setAttribute("aria-label", `Nhảy tới ${noun}`);
    $("jump").parentElement.firstChild.textContent = `Tới ${noun} `;
    $("queue").setAttribute("aria-label", `Danh sách theo ${noun}`);
    if (here) $("jump").value = here.id;
    $("jump").disabled = !eps.length;
  }
  function renderCurrent(scrollItem = true) {
    const list = curItems(), i = curIndex(), item = list[i];
    $("lecture").textContent = item?.ep_title || "";
    $("meta").textContent = item && (item.ep_label || item.ep_index) ? `${epLabel(item)} · ${kindLabel(item)} ${item.number || "—"} / ${item.total || "—"}` : "";
    $("title").textContent = item ? AutoShortPlayer.heading(item) : inRoom ? "Chưa có phòng xem chung" : "";
    $("count").textContent = item ? `${i + 1} / ${list.length}` : "0 / 0";
    if (inRoom) {
      $("viewers").textContent = `Đang xem: ${Object.keys(rstate?.viewers || {}).length} người`;
      $("end").disabled = !rstate?.video_url;
    } else {
      $("watch").disabled = !item;
      $("next").disabled = !item || index === items.length - 1;
    }
    renderJump();
    player.renderGroupList($("queue"), list, i, (n) => {
      if (inRoom) { player.hideNotice(); roomCommand("goto", { index: n }, true).then(() => player.scrollToVideo()).catch(() => {}); }
      else choose(n, true, 0, true);
    }, scrollItem);
  }
  function choose(next, autoplay = false, position = 0, scroll = false) {
    save(); player.hideNotice();
    const target = items[next];
    if (favPid && target) { currentItem = target; rebuildItems(); next = items.findIndex((item) => same(item, target)); }
    index = next; started = autoplay;
    const item = currentItem = items[index];
    state = { ...item, video_url: item?.video_url || null, auto,
      title: item?.title || "",
      fav: item?.fav || null, index, version: ++version, paused: !autoplay,
      position, rate: 1, server_time: 0, updated_at: 0 };
    player.setState(state); renderCurrent(!scroll);
    if (autoplay) player.playMedia(player.media());
    message(item ? "" : "Chưa có mục đã render trong lựa chọn này.");
    if (scroll) player.scrollToVideo();
  }
  function navigate(action) {
    if (index < 0) return;
    const next = index + (action === "prev" ? -1 : 1);
    if (next >= 0 && next < items.length) choose(next, true);
    else if (action === "next") {
      save();
      state = { ...state, paused: true, position: player.media().currentTime, server_time: 0, updated_at: 0 };
      player.setState(state); renderCurrent();
    }
  }
  function startingIndex() {
    let start = items.findIndex((item) => item.episode_id === episodeId);
    if (start < 0) start = items.findIndex((item) => item.base_episode_id === episodeId.replace(/\.kt$/, ""));
    return start < 0 ? (items.length ? 0 : -1) : start;
  }
  function renderFilter() {
    $("filter").querySelectorAll("[data-kind]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.kind === filter)));
  }

  // --- mode switching -------------------------------------------------------------------------
  function showInvite() {
    const link = document.createElement("a"), copy = document.createElement("button");
    link.href = "/watch"; link.textContent = `${location.origin}/watch`;
    copy.type = "button"; copy.className = "btn small"; copy.textContent = "Sao chép";
    copy.addEventListener("click", () => { navigator.clipboard?.writeText(link.textContent).then(() => { copy.textContent = "Đã chép"; }).catch(() => {}); });
    $("invite").replaceChildren(document.createTextNode("Mời người khác xem cùng, gửi link: "), link, document.createTextNode(" "), copy);
  }
  function setRoomMode(on) {
    inRoom = on; W.room.active = on;
    W.room.handler = roomHandler; W.room.message = message; W.room.onVersion = cancelPause;
    player.onEnded = on ? roomEnded : undefined;
    player.onAdvance = on ? roomAdvance : undefined;
    player.onCancelAdvance = on ? roomCancel : undefined;
    $("filter").hidden = on; $("watch").hidden = on; $("resume").hidden = on || $("resume").hidden;
    $("end").hidden = !on; $("viewers").hidden = !on; $("invite").hidden = !on;
    if (on) showInvite(); else { cancelPause(); rstate = null; lastRoomIndex = -1; }
    $("queue").dataset.signature = ""; $("jump").dataset.signature = "";
  }
  function roomHandler(data, force) {
    if (!data.video_url && !shell && items.length) { exitRoom(); return; }
    const scroll = data.index !== lastRoomIndex; lastRoomIndex = data.index;
    rstate = data;
    player.setState(data, force || data.by !== W.client, pauseTimer !== null, data.by !== W.client);
    renderCurrent(scroll);
  }
  // Back to solo at the item / position the room was on.
  function exitRoom() {
    const last = rstate, playing = !player.media().paused;
    const position = player.loading || !Number.isFinite(player.media().currentTime) ? (last?.position || 0) : player.media().currentTime;
    setRoomMode(false);
    let found = last ? items.findIndex((item) => item.video_url === last.video_url) : -1;
    if (found < 0) found = index >= 0 ? index : startingIndex();
    choose(found, playing, position);
  }
  async function startRoom() {
    if (inRoom || !items[index]) return;
    $("watch").disabled = true;
    try {
      save();
      // The whole list (AC 35); above the room cap send a window that still holds the playing item.
      const from = items.length > ROOM_MAX ? Math.max(0, Math.min(index - ROOM_MAX / 2, items.length - ROOM_MAX)) : 0;
      const queue = items.slice(from, from + ROOM_MAX).map((item) => ({ url: item.video_url,
        title: Array.from(item.title || "Video").slice(0, 200).join(""), ep_label: String(item.ep_label || "").slice(0, 40) || undefined, group: item.group }));
      const position = player.loading ? state.position : player.media().currentTime;
      setRoomMode(true);
      await roomCommand("set", { queue, index: index - from, position, paused: state.paused }, true);
      if (!auto) await roomCommand("auto", { auto: false }, true);
    } catch (error) {
      if (inRoom) { setRoomMode(false); renderCurrent(false); }
      message(error.message);
    } finally { $("watch").disabled = false; }
  }
  $("watch").addEventListener("click", startRoom);
  $("end").addEventListener("click", async () => {
    try { cancelPause(); await W.end(); } catch (error) { message(error.message); }
  });
  document.addEventListener("visibilitychange", () => {
    if (!inRoom) return;
    lastHiddenAt = performance.now(); cancelPause();
    if (!player.isHidden()) W.sent().then(() => W.poll(true));
  });
  window.addEventListener("pagehide", () => {
    if (!inRoom) return;
    roomHidden = true; lastHiddenAt = performance.now(); cancelPause(); W.stopPolling(); W.leave();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && inRoom) { roomHidden = false; lastHiddenAt = performance.now(); W.resume(); }
  });

  $("filter").querySelectorAll("[data-kind]").forEach((button) => button.addEventListener("click", () => {
    const previous = items[index], position = player.media().currentTime;
    const playing = player.active && !!state && !player.media().paused;
    save(); filter = button.dataset.kind; write("auto-short-listen-filter", filter); renderFilter();
    rebuildItems();
    const retained = items.findIndex((item) => same(item, previous));
    choose(retained < 0 ? startingIndex() : retained, playing, retained < 0 ? 0 : position);
  }));
  $("jump").addEventListener("change", () => player.onGroup($("jump").value));
  player.video.addEventListener("timeupdate", () => {
    if (performance.now() - lastSave > 3000) { lastSave = performance.now(); save(); }
  });
  document.addEventListener("episode-tab", (event) => {
    if (event.detail === "listen") { player.activate(); renderCurrent(); if (inRoom) player.sync(); }
    else {
      save();
      if (state && !inRoom) {
        state = { ...state, paused: true, position: player.loading ? state.position : player.media().currentTime,
          server_time: 0, updated_at: 0 };
        player.setState(state, false);
      }
      player.suspend();
    }
  });
  document.addEventListener("visibilitychange", () => {
    save();
    if (document.visibilityState === "visible" && player.active) renderCurrent();
  });
  window.addEventListener("pagehide", save);

  // An unbound episode needs only the existing episode API (at most its two kinds).
  function standalone(views, base) {
    return views.filter(Boolean).flatMap((view) => (view.shorts || [])
      .filter((short) => short.status === "rendered" && !short.deleted && !short.rejected && short.video_url)
      .map((short) => {
        // The existing download name already owns the canonical label/number/width.
        const match = short.download_name?.match(/^(T(.*?)_(?:KT|S)(\d+))(?:_|\.mp4$)/);
        return { code: match?.[1] || null, ep_label: match?.[2], number: match ? Number(match[3]) : null,
          total: view.shorts.length, kind: view.kind, episode_id: view.id, base_episode_id: base,
          ep_index: null, ep_title: views.find((v) => v?.id === base)?.title || view.title,
          clip_id: short.clip_id, title: short.title?.text, duration: short.duration, video_url: short.video_url,
          fav: null };
      }));
  }

  async function load() {
    try {
      const current = favPid ? null : await episode(episodeId), base = favPid || current.base_episode_id || current.id;
      let data;
      if (favPid) {
        data = await request("GET", null, `/api/playlists/${encodeURIComponent(favPid)}/listen?favorites=1`);
      } else if (current.favorites?.playlist_id) {
        data = await request("GET", null, `/api/playlists/${encodeURIComponent(current.favorites.playlist_id)}/listen`);
      } else {
        const baseView = current.id === base ? current : await episode(base).catch((error) => { if (error.status !== 404) throw error; return null; });
        const ktId = baseView?.khaithi_episode_id;
        const kt = current.kind === "khaithi" ? current : ktId ? await episode(ktId).catch((error) => { if (error.status !== 404) throw error; return null; }) : null;
        data = { title: baseView?.title || current.title || base, items: standalone([baseView, kt], base) };
      }
      all = data.items; storageKey = `auto-short-listen-position:${data.playlist_id || base}${favPid ? ":fav" : ""}`;
      $("series").textContent = favPid ? `Yêu thích — ${data.title}` : data.title;
      rebuildItems();
      const saved = read(storageKey);
      const resume = all.find((item) => same(item, saved));
      const validResume = resume && Number.isFinite(saved.position) && saved.position >= 0;
      // Favorites reopen at the saved identity/part, paused; ordinary episode pages keep the resume button.
      if (favPid && validResume) {
        if (!items.some((item) => same(item, resume))) {
          filter = "both"; renderFilter(); write("auto-short-listen-filter", filter); rebuildItems();
        }
        choose(items.findIndex((item) => same(item, resume)), false, saved.position);
      } else choose(startingIndex());
      if (validResume) {
        const seconds = Math.floor(saved.position);
        $("resume").textContent = `Nghe tiếp từ ${epLabel(resume)} · ${kindLabel(resume)} · ${resume.title || resume.clip_id} (${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")})`;
        $("resume").hidden = false;
        $("resume").addEventListener("click", () => {
          if (!items.some((item) => same(item, resume))) {
            filter = "both"; renderFilter(); write("auto-short-listen-filter", filter);
            rebuildItems();
          }
          choose(items.findIndex((item) => same(item, resume)), true, saved.position, true);
          $("resume").hidden = true;
        });
      }
    } catch (error) { message(error.message); }
  }
  if (shell) { setRoomMode(true); renderCurrent(false); }
  else load();
})();
