(() => {
  "use strict";
  const $ = (name) => document.getElementById(`listen-${name}`);
  if (!$("queue")) return;
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
  const player = new AutoShortPlayer("listen", {
    client: AutoShortWatch.client, request, message, onNavigate: (action) => navigate(action), getNext: () => items[index + 1],
    onAuto(value) {
      auto = value; write("auto-short-listen-auto", auto);
      if (state) { state = { ...state, auto }; player.setState(state, false); }
    },
    onAction(action, extra, force) {
      if (!state) return;
      if (action === "play") started = true;
      state = { ...state, ...extra, paused: action === "pause" ? true : action === "play" ? false : state.paused,
        server_time: 0, updated_at: 0 };
      player.setState(state, !!force);
      save();
    },
    onFavorite(fav, favorite) {
      fav.favorite = favorite;
      player.render();
    },
  });
  let all = [], items = [], index = -1, currentItem = null, state = null, version = 0, started = false;
  let storageKey, lastSave = 0;
  let groups = new Map();
  const manuallyOpen = new Set();
  let auto = read("auto-short-listen-auto", true) !== false;
  let filter = read("auto-short-listen-filter", "both");
  if (!["both", "short", "khaithi"].includes(filter)) filter = "both";
  renderFilter();
  if (document.getElementById("episode-listen").hidden) player.suspend();
  const same = (a, b) => a?.episode_id === b?.episode_id && a?.clip_id === b?.clip_id;
  const epLabel = (item) => `Tập ${item.ep_label || item.ep_index || "—"}`;
  const kindLabel = (item) => item.kind === "khaithi" ? "Khai thị" : "Short";
  function save() {
    // Keep the media identity separate from a filter's changing list/index.
    const item = currentItem;
    if (!storageKey || !item || !started || player.loading) return;
    write(storageKey, { episode_id: item.episode_id, clip_id: item.clip_id,
      position: Number.isFinite(player.media().currentTime) ? player.media().currentTime : 0 });
  }
  function renderCurrent(scrollItem = true) {
    const item = items[index];
    $("lecture").textContent = item?.ep_title || "";
    $("meta").textContent = item ? `${epLabel(item)} · ${kindLabel(item)} ${item.number || "—"} / ${item.total || "—"}` : "";
    $("title").textContent = AutoShortPlayer.heading(item);
    $("count").textContent = item ? `${index + 1} / ${items.length}` : "0 / 0";
    $("watch").disabled = !item;
    $("next").disabled = !item || index === items.length - 1;
    if (item) $("jump").value = item.base_episode_id;
    for (const [base, group] of groups) {
      const open = base === item?.base_episode_id || manuallyOpen.has(base);
      if (group.details.open !== open) {
        group.expectedToggle = open; group.details.open = open;
      }
    }
    $("queue").querySelectorAll("button[data-index]").forEach((button) => {
      if (Number(button.dataset.index) === index) {
        button.setAttribute("aria-current", "true");
        if (scrollItem && document.visibilityState === "visible" && player.active) button.scrollIntoView({ block: "nearest" });
      } else button.removeAttribute("aria-current");
    });
  }
  function choose(next, autoplay = false, position = 0, scroll = false) {
    save(); index = next; started = autoplay;
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
  function buildList() {
    groups = new Map();
    $("queue").replaceChildren(); $("jump").replaceChildren();
    items.forEach((item, n) => {
      if (!groups.has(item.base_episode_id)) {
        const details = document.createElement("details"), summary = document.createElement("summary"), list = document.createElement("ol");
        const group = { details, summary, list, item, count: 0, userToggle: false };
        details.append(summary, list); $("queue").append(details);
        // Native toggle events are asynchronous and also fire for .open changes.
        summary.addEventListener("click", () => { group.userToggle = true; });
        details.addEventListener("toggle", () => {
          const automatic = !group.userToggle && group.expectedToggle === details.open;
          group.expectedToggle = undefined; group.userToggle = false;
          if (automatic) return;
          if (details.open) manuallyOpen.add(item.base_episode_id);
          else manuallyOpen.delete(item.base_episode_id);
        });
        const option = document.createElement("option"); option.value = item.base_episode_id; option.textContent = epLabel(item);
        $("jump").append(option); groups.set(item.base_episode_id, group);
      }
      const li = document.createElement("li"), button = AutoShortPlayer.queueButton(item, () => choose(n, true, 0, true));
      button.dataset.index = n; li.append(button);
      const group = groups.get(item.base_episode_id); group.list.append(li); group.count++;
    });
    for (const group of groups.values()) group.summary.textContent = `${epLabel(group.item)} · ${group.count} bài`;
    $("jump").disabled = !items.length;
  }
  function renderFilter() {
    $("filter").querySelectorAll("[data-kind]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.kind === filter)));
  }
  $("filter").querySelectorAll("[data-kind]").forEach((button) => button.addEventListener("click", () => {
    const previous = items[index], position = player.media().currentTime;
    const playing = player.active && !!state && !player.media().paused;
    save(); filter = button.dataset.kind; write("auto-short-listen-filter", filter); renderFilter();
    items = all.filter((item) => filter === "both" || item.kind === filter);
    const retained = items.findIndex((item) => same(item, previous));
    buildList(); choose(retained < 0 ? startingIndex() : retained, playing, retained < 0 ? 0 : position);
  }));
  $("jump").addEventListener("change", () => choose(items.findIndex((item) => item.base_episode_id === $("jump").value), true, 0, true));
  $("watch").addEventListener("click", async () => {
    if (!items[index]) return;
    $("watch").disabled = true;
    try {
      const queue = items.slice(index, index + 300).map((item) => ({ url: item.video_url,
        title: Array.from(item.title || "Video").slice(0, 200).join("") }));
      save(); await AutoShortWatch.start(queue, player.loading ? state.position : player.media().currentTime);
    } catch (error) { message(error.message); }
    finally { $("watch").disabled = false; }
  });
  player.video.addEventListener("timeupdate", () => {
    if (performance.now() - lastSave > 3000) { lastSave = performance.now(); save(); }
  });
  document.addEventListener("episode-tab", (event) => {
    if (event.detail === "listen") { player.activate(); renderCurrent(); }
    else {
      save();
      if (state) {
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
      const current = await episode(episodeId), base = current.base_episode_id || current.id;
      let data;
      if (current.favorites?.playlist_id) {
        data = await request("GET", null, `/api/playlists/${encodeURIComponent(current.favorites.playlist_id)}/listen`);
      } else {
        const baseView = current.id === base ? current : await episode(base).catch((error) => { if (error.status !== 404) throw error; return null; });
        const ktId = baseView?.khaithi_episode_id;
        const kt = current.kind === "khaithi" ? current : ktId ? await episode(ktId).catch((error) => { if (error.status !== 404) throw error; return null; }) : null;
        data = { title: baseView?.title || current.title || base, items: standalone([baseView, kt], base) };
      }
      all = data.items; storageKey = `auto-short-listen-position:${data.playlist_id || base}`;
      $("series").textContent = data.title;
      items = all.filter((item) => filter === "both" || item.kind === filter);
      buildList(); choose(startingIndex());
      const saved = read(storageKey);
      const resume = all.find((item) => same(item, saved));
      if (resume && Number.isFinite(saved.position) && saved.position >= 0) {
        const seconds = Math.floor(saved.position);
        $("resume").textContent = `Nghe tiếp từ ${epLabel(resume)} · ${kindLabel(resume)} · ${resume.title || resume.clip_id} (${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")})`;
        $("resume").hidden = false;
        $("resume").addEventListener("click", () => {
          if (!items.some((item) => same(item, resume))) {
            filter = "both"; renderFilter(); write("auto-short-listen-filter", filter);
            items = [...all]; buildList();
          }
          choose(items.findIndex((item) => same(item, resume)), true, saved.position, true);
          $("resume").hidden = true;
        });
      }
    } catch (error) { message(error.message); }
  }
  load();
})();
