/* Shared media controls for the local listening queue and the watch room. */
(() => {
  "use strict";
  window.AutoShortPlayer = class {
    constructor(prefix, { request, onAction, onNavigate, onFavorite, message, onInteraction = () => {} }) {
      const $ = (name) => document.getElementById(`${prefix}-${name}`);
      this.$ = $; this.request = request; this.onAction = onAction;
      this.onNavigate = onNavigate; this.onFavorite = onFavorite; this.message = message;
      this.video = $("video"); this.audio = $("audio");
      this.storageKey = "auto-short-watch-background";
      try { this.background = localStorage.getItem(this.storageKey) === "true"; } catch (_) { /* Private mode. */ }
      this.programmed = new Map(); this.sourceKey = null; this.active = true;
      this.receivedAt = 0; this.loading = false; this.state = null;
      $("background").checked = !!this.background;
      for (const current of [this.video, this.audio]) {
        current.addEventListener("loadedmetadata", () => {
          if (current !== this.media() || !this.state?.video_url) return;
          this.loading = false;
          const transfer = this.handoff?.version === this.state.version ? this.handoff : null;
          this.handoff = null; this.sync(transfer);
        });
        for (const [event, action] of [["play", "play"], ["pause", "pause"], ["seeked", "seek"], ["ratechange", "rate"]]) {
          current.addEventListener(event, () => {
            if (current === this.media() && (event === "play" || event === "pause")) this.updatePlaybackState();
            if (!this.active || current !== this.media() || this.isProgrammed(event) || !this.state?.video_url
                || (event === "pause" && current.ended)) return;
            this.onAction(action, { position: current.currentTime, ...(action === "rate" ? { rate: current.playbackRate } : {}) });
          });
        }
        current.addEventListener("ended", () => {
          if (this.active && current === this.media() && !this.loading && this.state?.video_url) this.onNavigate("next");
        });
      }
      $("background").addEventListener("change", () => {
        const previous = this.media(), transfer = this.transfer();
        onInteraction();
        this.background = $("background").checked;
        try { localStorage.setItem(this.storageKey, String(this.background)); } catch (_) { /* Private mode. */ }
        // Switch active elements before pausing, so this pause never becomes a user command.
        previous.pause(); previous.removeAttribute("src"); previous.load();
        this.render(); this.message("");
        if (transfer) this.load(transfer);
      });
      this.audio.addEventListener("error", () => {
        if (this.audio !== this.media() || !this.state?.video_url) return;
        if (!this.audioFallback && this.audioUrl()) {
          const transfer = this.handoff || { position: this.audio.currentTime || this.targetPosition(),
            paused: this.state.paused, rate: this.state.rate, version: this.state.version, at: performance.now() };
          this.audioFallback = true;
          this.audioWarning = "Không tải được file tiếng; đang dùng âm thanh từ video MP4.";
          this.message(this.audioWarning); this.load(transfer);
        } else this.message("Không phát được tiếng. Hãy thử lại khi nguồn / kho sẵn sàng.");
      });
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
    media() { return this.background ? this.audio : this.video; }
    audioUrl() {
      if (this.state?.audio_url) return this.state.audio_url;
      const match = this.state?.video_url?.split("?")[0].match(/^\/files\/([^/]+)\/([^/]+)\.mp4$/);
      return match ? `/api/watch/audio/${encodeURIComponent(match[1])}/${encodeURIComponent(match[2])}` : null;
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
    sync(transfer = null) {
      const current = this.media(), s = this.state;
      if (!this.active || !s?.video_url || this.loading || !current.readyState || this.syncBlocked) return;
      const position = transfer ? transfer.position + (transfer.paused ? 0 : (performance.now() - transfer.at) / 1000 * transfer.rate) : this.targetPosition();
      const target = Math.min(position, Number.isFinite(current.duration) ? current.duration : Infinity);
      const rate = transfer ? transfer.rate : s.rate, paused = transfer ? transfer.paused : s.paused;
      if (Math.abs(current.currentTime - target) > (transfer ? .05 : 1)) {
        this.arm("seeked", target); current.currentTime = target;
      }
      if (current.playbackRate !== rate) { this.arm("ratechange", rate); current.playbackRate = rate; }
      if (paused) {
        if (!current.paused) { this.arm("pause", true); current.pause(); }
        this.$("play").hidden = !current.paused;
      } else if (current.paused && !current.ended) this.playMedia(current);
    }
    transfer() {
      if (!this.state?.video_url) return null;
      const current = this.media();
      return { position: this.loading ? this.targetPosition() : current.currentTime,
        paused: this.loading ? this.state.paused : current.paused,
        rate: this.loading ? this.state.rate : current.playbackRate, version: this.state.version, at: performance.now() };
    }
    load(transfer = null) {
      this.loading = true; this.programmed.clear(); this.handoff = transfer; this.playPending = null;
      const current = this.media();
      current.src = this.background && !this.audioFallback ? (this.audioUrl() || this.state.video_url) : this.state.video_url;
      current.load();
      if (transfer && !transfer.paused) this.playMedia(current);
    }
    resetRetry() { this.hiddenPlayBlocked = false; this.playPending = null; }
    setState(state, sync = true, blocked = false) {
      if (this.state?.version !== state.version) this.resetRetry();
      this.state = state; this.receivedAt = performance.now(); this.syncBlocked = blocked;
      const key = state.video_url ? JSON.stringify([state.index, state.video_url]) : null;
      if (key !== this.sourceKey) {
        this.sourceKey = key; this.handoff = null; this.playPending = null;
        this.audioFallback = false; this.audioWarning = "";
        if (key === null) {
          this.loading = true;
          for (const current of [this.video, this.audio]) { current.pause(); current.removeAttribute("src"); current.load(); }
        } else this.load();
      } else if (sync) this.sync();
      this.render();
    }
    render() {
      const s = this.state, active = !!s?.video_url;
      this.video.hidden = !active || !!this.background; this.audio.hidden = !active || !this.background;
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
      for (const current of [this.video, this.audio]) current.pause();
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
