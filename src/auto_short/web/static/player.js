/* Shared media controls for the local listening queue and the watch room. */
(() => {
  "use strict";
  window.AutoShortPlayer = class {
    constructor(prefix, { request, onAction, onNavigate, onFavorite, message, onAuto, getNext = () => this.state?.queue?.[this.state.index + 1] }) {
      const $ = (name) => document.getElementById(`${prefix}-${name}`);
      this.$ = $; this.request = request; this.onAction = onAction;
      this.onNavigate = onNavigate; this.onFavorite = onFavorite; this.message = message;
      this.video = $("video"); this.getNext = getNext;
      this.programmed = new Map(); this.sourceKey = null; this.active = true;
      this.receivedAt = 0; this.loading = false; this.state = null;
      const current = this.video;
      current.addEventListener("loadedmetadata", () => {
        if (!this.state?.video_url) return;
        this.loading = false;
        this.sync();
      });
      for (const [event, action] of [["play", "play"], ["pause", "pause"], ["seeked", "seek"], ["ratechange", "rate"]]) {
        current.addEventListener(event, () => {
          if (event === "play" || event === "pause") this.updatePlaybackState();
          if (!this.active || this.isProgrammed(event) || !this.state?.video_url
              || (event === "pause" && current.ended)) return;
          this.onAction(action, { position: current.currentTime, ...(action === "rate" ? { rate: current.playbackRate } : {}) });
        });
      }
      current.addEventListener("ended", () => {
        if (!this.active || this.loading || !this.state?.video_url) return;
        this.notifyEpisodeEnd(this.getNext());
        if ($("auto").checked) this.onNavigate("next");
        else this.onAction("pause", { position: current.currentTime }, true);
      });
      $("auto").addEventListener("change", () => onAuto($("auto").checked));
      $("notice").addEventListener("click", () => this.hideNotice());
      $("favorite").addEventListener("click", async () => {
        const fav = this.state?.fav;
        if (!fav || this.favoriteBusy) return;
        this.favoriteBusy = true; this.render();
        try {
          await this.request("POST", { episode_id: fav.episode_id, clip: fav.clip, favorite: !fav.favorite },
            `/api/playlists/${encodeURIComponent(fav.playlist_id)}/favorites`);
          await this.onFavorite(fav, !fav.favorite);
        } catch (error) { this.message(error.message); }
        finally { this.favoriteBusy = false; this.render(); }
      });
      $("prev").addEventListener("click", () => this.onNavigate("prev"));
      $("next").addEventListener("click", () => this.onNavigate("next"));
      $("play").addEventListener("click", () => {
        if (!this.active || !this.state?.video_url) return;
        this.onAction("play", { position: this.loading ? this.targetPosition() : this.media().currentTime }, true);
        this.resetRetry(); this.playMedia(this.media());
      });
    }
    media() { return this.video; }
    episode(entry) {
      if (!entry) return null;
      const match = (entry.video_url || entry.url || "").split("?")[0].match(/^\/files\/([^/]+)\/[^/]+\.mp4$/);
      const id = entry.base_episode_id || entry.episode_id || match?.[1];
      if (!id) return null;
      const base = id.replace(/\.kt$/, "");
      const label = entry.ep_index != null ? `Tập ${entry.ep_index} — ${entry.ep_title || base}`
        : entry.title?.match(/^(Tập [^·]+)\s·/)?.[1]?.trim() || `Tập ${base}`;
      return { id: base, label };
    }
    hideNotice() { clearTimeout(this.noticeTimer); this.$("notice").hidden = true; }
    notifyEpisodeEnd(next) {
      const current = this.episode(this.state), upcoming = this.episode(next);
      if (!current || (next && (!upcoming || current.id === upcoming.id))) return;
      const notice = this.$("notice"), text = document.createElement("span");
      text.textContent = `Đã hết ${current.label}.`;
      notice.replaceChildren(text);
      if (!next) {
        const done = document.createElement("span"); done.textContent = " Đã hết danh sách."; notice.append(done);
      } else if (this.$("auto").checked) {
        const following = document.createElement("span"); following.textContent = ` Tiếp theo: ${upcoming.label}`; notice.append(following);
      } else {
        const button = document.createElement("button"), source = this.sourceKey;
        button.type = "button"; button.className = "btn small"; button.textContent = `Nghe ${upcoming.label}`;
        button.addEventListener("click", () => { if (this.sourceKey === source) this.onNavigate("next"); });
        notice.append(button);
      }
      clearTimeout(this.noticeTimer); notice.hidden = false;
      this.noticeTimer = setTimeout(() => this.hideNotice(), 8000);
    }
    arm(event, value) {
      const mark = { value, until: performance.now() + 5000 };
      this.programmed.set(event, mark); return mark;
    }
    isProgrammed(event) {
      if (this.loading) {
        const marked = this.programmed.has(event);
        this.programmed.delete(event);
        // Native controls can emit a user play before metadata has arrived.
        return event !== "play" || marked;
      }
      const mark = this.programmed.get(event);
      if (!mark) return false;
      const current = this.media();
      const actual = event === "seeked" ? current.currentTime : event === "ratechange" ? current.playbackRate : current.paused;
      const matches = typeof actual === "number" ? Math.abs(actual - mark.value) < (event === "ratechange" ? .001 : 1) : actual === mark.value;
      this.programmed.delete(event);
      return performance.now() < mark.until && matches;
    }
    targetPosition() {
      const s = this.state;
      return s.position + (s.paused ? 0 : Math.max(0,
        s.server_time - s.updated_at + (performance.now() - this.receivedAt) / 1000) * s.rate);
    }
    playMedia(current) {
      if (!this.active || this.playPending || (document.visibilityState === "hidden" && this.hiddenPlayBlocked)) return;
      const playMark = this.arm("play", false), attempt = { current, key: this.sourceKey, version: this.state.version };
      this.playPending = attempt;
      const stillCurrent = () => this.playPending === attempt && current === this.media() && attempt.key === this.sourceKey;
      current.play().then(() => {
        if (stillCurrent()) this.$("play").hidden = true;
      }).catch(() => {
        if (this.programmed.get("play") === playMark) this.programmed.delete("play");
        if (!stillCurrent()) return;
        if (document.visibilityState === "hidden" && attempt.version === this.state?.version) this.hiddenPlayBlocked = true;
        if (this.state?.video_url && !this.state.paused) this.$("play").hidden = false;
      }).finally(() => { if (this.playPending === attempt) this.playPending = null; });
    }
    sync() {
      const current = this.media(), s = this.state;
      if (!this.active || !s?.video_url || this.loading || !current.readyState || this.syncBlocked) return;
      const position = this.targetPosition();
      const target = Math.min(position, Number.isFinite(current.duration) ? current.duration : Infinity);
      const rate = s.rate, paused = s.paused;
      if (Math.abs(current.currentTime - target) > 1) {
        this.arm("seeked", target); current.currentTime = target;
      }
      if (current.playbackRate !== rate) { this.arm("ratechange", rate); current.playbackRate = rate; }
      if (paused) {
        if (!current.paused) { this.arm("pause", true); current.pause(); }
        this.$("play").hidden = !current.paused;
      } else if (current.paused && !current.ended) this.playMedia(current);
    }
    load() {
      this.loading = true; this.programmed.clear(); this.playPending = null;
      this.video.src = this.state.video_url;
      this.video.load();
    }
    resetRetry() { this.hiddenPlayBlocked = false; this.playPending = null; }
    setState(state, sync = true, blocked = false) {
      if (this.state?.version !== state.version) this.resetRetry();
      // A peer may advance the room just before this browser emits its own ended.
      if (this.state && state.index === this.state.index + 1 && this.video.readyState
          && Number.isFinite(this.video.duration) && this.video.currentTime >= this.video.duration - 1) {
        this.notifyEpisodeEnd({ ...state, url: state.video_url });
      }
      this.state = state; this.receivedAt = performance.now(); this.syncBlocked = blocked;
      const key = state.video_url ? JSON.stringify([state.index, state.video_url]) : null;
      if (key !== this.sourceKey) {
        this.sourceKey = key; this.playPending = null;
        if (key === null) {
          this.loading = true;
          this.video.pause(); this.video.removeAttribute("src"); this.video.load();
          this.hideNotice();
        } else this.load();
      } else if (sync) this.sync();
      this.render();
    }
    render() {
      const s = this.state, active = !!s?.video_url;
      this.video.hidden = !active;
      this.$("auto").checked = s?.auto !== false; this.$("auto").disabled = !active;
      const fav = s?.fav, heart = this.$("favorite");
      heart.hidden = !fav; heart.disabled = !!this.favoriteBusy;
      heart.textContent = fav?.favorite ? "♥" : "♡"; heart.classList.toggle("on", !!fav?.favorite);
      heart.setAttribute("aria-pressed", fav?.favorite ? "true" : "false");
      heart.title = fav?.favorite ? "Bỏ yêu thích" : "Yêu thích"; heart.setAttribute("aria-label", heart.title);
      this.$("prev").disabled = !active || s.index === 0;
      this.$("next").disabled = !active;
      this.$("play").hidden = !active || !this.media().paused;
      if (this.active) this.updateSession();
    }
    updatePlaybackState() {
      if (this.active && "mediaSession" in navigator) navigator.mediaSession.playbackState = this.state?.video_url
        ? (this.media().paused ? "paused" : "playing") : "none";
    }
    updateSession() {
      if (!("mediaSession" in navigator)) return;
      if (typeof MediaMetadata === "function") navigator.mediaSession.metadata = this.state?.video_url
        ? new MediaMetadata({ title: this.state.title || "Video", artist: "Auto Short" }) : null;
      this.updatePlaybackState();
      for (const [name, action] of [["play", "play"], ["pause", "pause"], ["previoustrack", "prev"], ["nexttrack", "next"]]) {
        try {
          navigator.mediaSession.setActionHandler(name, () => {
            if (!this.active || !this.state?.video_url) return;
            if (action === "prev" || action === "next") this.onNavigate(action);
            else this.onAction(action, { position: this.loading ? this.targetPosition() : this.media().currentTime }, true);
          });
        } catch (_) { /* Unsupported action. */ }
      }
    }
    suspend() {
      this.active = false;
      this.video.pause();
      this.hideNotice();
      if ("mediaSession" in navigator) {
        navigator.mediaSession.playbackState = "none";
        for (const action of ["play", "pause", "previoustrack", "nexttrack"]) {
          try { navigator.mediaSession.setActionHandler(action, null); } catch (_) { /* Unsupported action. */ }
        }
      }
    }
    activate() { this.active = true; this.resetRetry(); this.render(); }
  };
})();
