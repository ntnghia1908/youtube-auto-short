/* Shared media controls for the local listening queue and the watch room. */
(() => {
  "use strict";
  const AUDIO_PAD = 1.5; // Content-clock offset of the padded /files/*.m4a rendition.
  window.AutoShortPlayer = class AutoShortPlayer {
    constructor(prefix, { client, request, onAction, onNavigate, onFavorite, message, onAuto, onEnded, onHiddenAdvance, onAdvance, onCancelAdvance, onGroup, getItems = () => this.state?.queue || [], getNext = () => this.state?.queue?.[this.state.index + 1] }) {
      const $ = (name) => document.getElementById(`${prefix}-${name}`);
      this.$ = $; this.request = request; this.onAction = onAction;
      this.onNavigate = action => { this.cancelEarly(this.adopting); return onNavigate(action); };
      this.onFavorite = onFavorite; this.message = message;
      this.video = $("video"); this.getNext = getNext; this.getItems = getItems; this.onGroup = onGroup;
      this.audios = [document.createElement("audio"), document.createElement("audio")];
      this.audio = this.audios[0];
      for (const audio of this.audios) { audio.hidden = true; audio.preload = "auto"; audio.volume = 1; }
      $("controls").append(...this.audios);
      this.video.muted = true;
      this.onEnded = onEnded; this.onAdvance = onAdvance; this.onCancelAdvance = onCancelAdvance;
      this.onHiddenAdvance = onHiddenAdvance;
      this.client = client; this.page = prefix; this.events = []; this.lastLogAt = -Infinity; this.logMarks = new Map();
      this.programmed = new Map(); this.sourceKey = null; this.active = true;
      this.receivedAt = 0; this.loading = false; this.state = null;
      this.pipActive = document.pictureInPictureElement === this.video;
      this.hiddenRun = this.isHidden() ? { attempts: 0, since: null, position: null, gaveUp: false, skipped: false } : null;
      this.progressChecks = new Set();
      this.setupPiP();
      for (const current of this.audios) {
        current.addEventListener("loadedmetadata", () => {
          if (current !== this.media() || !this.state?.video_url) return;
          this.loading = false;
          // A fallback reload keeps the audio clock; a newer room state still wins.
          const resume = this.fallbackResume;
          this.fallbackResume = null;
          if (resume?.state === this.state && !resume.raw) {
            this.arm("seeked", resume.position); this.seek(resume.position, current);
          }
          this.sync(resume?.state === this.state);
        });
        current.addEventListener("error", () => {
          if (current !== this.media()) {
            if (current.error && this.prepared?.media === current) this.earlyFailed(this.prepared, current.error);
            return;
          }
          if (!this.active || !this.state?.video_url || !current.error || this.audioFallback
              || current.getAttribute("src") !== this.audioUrl(this.state.video_url)
              || current.getAttribute("src") === this.state.video_url) return;
          const position = this.loading ? this.targetPosition() : this.position(current);
          this.record("audio_fallback", { err: String(current.error.code) });
          this.fallbackResume = { state: this.state, position };
          this.audioFallback = true; this.loading = true; this.playPending = null;
          this.loadMedia(current, this.state.video_url, position, this.state.rate);
          if (this.wantsPlay()) this.playMedia(current);
        });
        for (const [event, action] of [["play", "play"], ["pause", "pause"], ["seeked", "seek"], ["ratechange", "rate"]]) {
          current.addEventListener(event, () => {
            if (current !== this.media()) return;
            this.syncVideo();
            if (event === "play" || event === "pause") this.updatePlaybackState();
            if (event === "play") {
              clearTimeout(this.videoPauseTimer); this.videoPauseTimer = null;
              if (!this.isHidden()) this.cancelRecovery();
              this.prepareNext();
            }
            if (this.isProgrammed(event) || !this.active || !this.state?.video_url
                || (event === "pause" && current.ended)) return;
            if (event === "pause" && this.isHidden() && this.wantsPlay()) {
              this.record("pause_hidden");
              this.recover();
              return;
            }
            if (action === "seek") this.cancelEarly();
            if (action === "play" || action === "seek") this.hideNotice();
            this.onAction(action, { position: this.position(current), ...(action === "rate" ? { rate: current.playbackRate } : {}) });
          });
        }
        current.addEventListener("ended", () => {
          if (current !== this.media() || !this.active || !current.ended || this.loading || !this.state?.video_url || this.finishedKey === this.sourceKey) return;
          this.syncVideo();
          this.finishedKey = this.endedKey = this.sourceKey;
          this.cancelRecovery(); this.clearProgressChecks();
          const next = this.getNext();
          if (this.isHidden() && this.state.auto && this.$("auto").checked && next) {
            if (this.prepared?.pending) { this.prepared.ended = true; return; }
            if (this.prepared && !this.prepared.failed) this.adopting = this.prepared;
            this.advanceHidden();
            return;
          }
          this.finishEnded();
        });
        for (const event of ["stalled", "waiting"]) current.addEventListener(event, () => {
          if (current === this.media() && this.active && this.isHidden()) this.record(event);
        });
        current.addEventListener("timeupdate", () => {
          if (current !== this.media()) return;
          this.syncVideo();
          if (this.hiddenRun?.since != null && this.position() > this.hiddenRun.position) this.resetRetry();
          if (this.isHidden() && this.wantsPlay() && !this.loading && !current.ended
              && Number.isFinite(current.duration) && current.duration - current.currentTime <= .5) this.startEarly();
        });
      }
      for (const event of ["freeze", "resume"]) document.addEventListener(event, () => {
        if (this.active) this.record(event);
        if (event === "freeze") this.flushLog(true);
      });
      this.video.addEventListener("loadedmetadata", () => this.syncVideo(true));
      this.video.addEventListener("volumechange", () => { this.video.muted = true; });
      for (const [event, action] of [["play", "play"], ["pause", "pause"], ["seeked", "seek"], ["ratechange", "rate"]]) {
        this.video.addEventListener(event, () => {
          if (this.isProgrammed(event, this.video) || !this.active || !this.state?.video_url
              || (event === "pause" && (this.isHidden() || this.video.ended))) return;
          const current = this.media();
          if (action === "play" || action === "seek") this.hideNotice();
          if (action === "play") {
            this.resetRetry(true); this.allowHiddenPlay = true;
            this.onAction("play", { position: this.loading ? this.targetPosition() : this.position(current) }, true);
            this.playMedia(current);
          } else {
            if (action === "pause") {
              clearTimeout(this.videoPauseTimer);
              const key = this.sourceKey;
              const pause = () => {
                this.videoPauseTimer = null;
                if (!this.active || this.isHidden() || key !== this.sourceKey || !this.video.paused || current.paused) return;
                this.cancelEarly();
                this.arm("pause", true); current.pause();
                this.onAction("pause", { position: this.position(current) });
              };
              if (navigator.userActivation?.isActive) pause();
              else this.videoPauseTimer = setTimeout(pause, 1500);
              return;
            }
            if (action === "seek") { this.cancelEarly(); this.arm("seeked", this.video.currentTime); this.seek(this.video.currentTime, current); }
            if (action === "rate") { this.arm("ratechange", this.video.playbackRate); current.playbackRate = this.video.playbackRate; }
            this.onAction(action, { position: this.position(current), ...(action === "rate" ? { rate: current.playbackRate } : {}) });
            this.syncVideo();
          }
        });
      }
      document.addEventListener("visibilitychange", () => this.visibilityChanged());
      window.addEventListener("pagehide", () => {
        this.cancelRecovery(); this.clearProgressChecks();
        if (this.active) this.record("visibility");
        this.flushLog(true);
      });
      $("auto").addEventListener("change", () => onAuto($("auto").checked));
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
        this.hideNotice(); this.resetRetry(true); this.allowHiddenPlay = true;
        this.onAction("play", { position: this.loading ? this.targetPosition() : this.position() }, true);
        this.playMedia(this.media());
      });
    }
    inPiP() { return this.pipActive; }
    isHidden() { return document.visibilityState === "hidden" && !this.inPiP(); }
    visibilityChanged() {
      clearTimeout(this.videoPauseTimer); this.videoPauseTimer = null;
      const hidden = this.isHidden();
      if (hidden !== !!this.hiddenRun) {
        this.cancelRecovery(); this.clearProgressChecks();
        this.hiddenRun = hidden ? { attempts: 0, since: null, position: null, gaveUp: false, skipped: false } : null;
      }
      if (!this.active) return;
      if (!hidden) {
        const ended = this.prepared?.ended;
        this.cancelEarly();
        if (ended) this.finishEnded();
        else this.prepareNext();
      }
      this.record("visibility");
      if (hidden && this.wantsPlay() && this.audio.paused && !this.audio.ended && !this.loading) {
        this.record("pause_hidden"); this.recover();
      }
      this.syncVideo(true);
    }

    setupPiP() {
      this.pipSupported = !!document.pictureInPictureEnabled
        && typeof this.video.requestPictureInPicture === "function" && typeof document.exitPictureInPicture === "function";
      const button = document.createElement("button");
      button.type = "button"; button.id = `${this.page}-pip`; button.className = "btn icon-btn player-pip";
      button.textContent = this.pipSupported ? "⧉" : "⛶";
      button.title = this.pipSupported ? "Màn hình nhỏ" : "Toàn màn hình";
      button.setAttribute("aria-label", button.title); button.setAttribute("aria-pressed", String(this.inPiP()));
      button.classList.toggle("on", this.inPiP());
      button.disabled = true; this.pipButton = button;
      button.addEventListener("click", () => this.togglePiP());
      this.$("controls").append(button);
      if (!this.pipSupported) {
        this.$("pip-hint").textContent = "Bật toàn màn hình rồi bấm nút Home để thu nhỏ";
        this.$("pip-hint").hidden = false;
        this.record("pip_unsupported", { err: window.isSecureContext === false ? "insecure"
          : typeof this.video.requestPictureInPicture !== "function" || typeof document.exitPictureInPicture !== "function" ? "api-missing" : "disabled" });
      }
      for (const [event, active] of [["enterpictureinpicture", true], ["leavepictureinpicture", false]]) {
        this.video.addEventListener(event, () => {
          this.pipActive = active;
          button.setAttribute("aria-pressed", String(active)); button.classList.toggle("on", active);
          this.record(active ? "pip_enter" : "pip_leave"); this.visibilityChanged();
        });
      }
    }
    async togglePiP() {
      if (!this.active || !this.state?.video_url || this.pipBusy) return;
      this.pipBusy = true; this.pipButton.disabled = true;
      try {
        if (this.pipSupported) {
          if (this.inPiP()) await document.exitPictureInPicture();
          else await this.video.requestPictureInPicture();
        } else if (document.fullscreenElement === this.video && document.exitFullscreen) await document.exitFullscreen();
        else if (this.video.requestFullscreen) await this.video.requestFullscreen();
        else if (this.video.webkitEnterFullscreen) this.video.webkitEnterFullscreen();
        else this.message("Trình duyệt không hỗ trợ toàn màn hình.");
      } catch (_) { this.message("Không mở được màn hình nhỏ / toàn màn hình. Hãy thử lại từ nút trên video."); }
      finally { this.pipBusy = false; this.pipButton.disabled = !this.state?.video_url; }
    }
    media() { return this.audio; }
    pad(current = this.media()) {
      return current !== this.video && /\.m4a(?:[?#]|$)/.test(current.getAttribute("src") || "") ? AUDIO_PAD : 0;
    }
    position(current = this.media()) { return Math.max(0, current.currentTime - this.pad(current)); }
    seek(position, current = this.media()) { current.currentTime = Math.max(0, position) + this.pad(current); }
    nextKey() {
      if (!this.state?.video_url) return null;
      const next = this.getNext();
      return next ? JSON.stringify([this.state.index + 1, next.url || next.video_url]) : null;
    }
    cancelEarly(keep = null) {
      const prepared = this.prepared;
      this.prepared = null;
      if (prepared && prepared !== keep && !prepared.media.paused) prepared.media.pause();
    }
    prepareNext() {
      const key = this.nextKey();
      if (!this.wantsPlay() || !this.state.auto || !key) { this.cancelEarly(); return; }
      if (this.prepared?.key === key && this.prepared.from === this.sourceKey) return;
      this.cancelEarly();
      const media = this.audios.find(audio => audio !== this.media());
      const next = this.getNext(), src = this.audioUrl(next.url || next.video_url);
      this.prepared = { key, from: this.sourceKey, media };
      media.volume = 1; media.src = src; media.load(); media.playbackRate = this.state.rate;
    }
    earlyValid(prepared) {
      return this.prepared === prepared && prepared.from === this.sourceKey && prepared.key === this.nextKey()
        && this.isHidden() && this.wantsPlay() && this.state.auto && this.$("auto").checked;
    }
    earlyFailed(prepared, error) {
      if (this.prepared !== prepared || prepared.failed) return;
      prepared.failed = true; prepared.pending = false;
      this.record("early_blocked", { err: String(error.name || error.code || "Error").slice(0, 80) });
      if (!prepared.media.paused) prepared.media.pause();
      if (prepared.ended && this.earlyValid(prepared)) this.advanceHidden();
    }
    startEarly() {
      const prepared = this.prepared;
      if (!prepared || prepared.pending || prepared.failed || !this.earlyValid(prepared)) return;
      prepared.pending = true;
      prepared.media.currentTime = 0; prepared.media.volume = 1; prepared.media.playbackRate = this.state.rate;
      prepared.media.play().then(() => {
        if (!this.earlyValid(prepared) || prepared.failed) {
          if (prepared.media !== this.media() && this.prepared?.media !== prepared.media && !prepared.media.paused) prepared.media.pause();
          return;
        }
        prepared.pending = false;
        this.record("early_start"); this.adopting = prepared;
        this.advanceHidden();
      }).catch(error => this.earlyFailed(prepared, error));
    }
    advanceHidden() {
      this.record("hidden_advance");
      this.finishedKey = this.endedKey = this.sourceKey;
      this.cancelRecovery(); this.clearProgressChecks();
      const next = this.getNext();
      if (this.onEnded) {
        const previous = this.state, now = previous.server_time + (performance.now() - this.receivedAt) / 1000;
        // Retain the server's index + URL so its acknowledgement reuses the playing audio.
        this.setState({ ...previous, ...next, index: previous.index + 1,
          video_url: next.url || next.video_url, title: next.title, fav: next.fav || null,
          position: 0, paused: false, finished: false, advance_at: null, updated_at: now, server_time: now }, true, this.syncBlocked);
        this.onHiddenAdvance(previous.version);
      } else this.onNavigate("next");
    }
    finishEnded() {
      if (this.onEnded) this.onEnded(this.position());
      else {
        this.onAction("pause", { position: this.position() }, true);
        this.localAdvanceAt = !this.isHidden() && this.state.auto && this.nextInGroup() ? performance.now() + 3000 : null;
      }
      this.renderAdvance(); this.scrollToVideo();
    }
    syncVideo(force = false) {
      const video = this.video, audio = this.audio;
      video.muted = true;
      if (!this.active || !this.state?.video_url) return;
      const hidden = this.isHidden();
      if (hidden || audio.paused || audio.ended) {
        if (!video.paused) { this.arm("pause", true, video); video.pause(); }
        if (hidden) return;
      }
      if (!video.readyState || !audio.readyState) return;
      const drift = this.position(audio) - video.currentTime;
      if (force || Math.abs(drift) > .5) {
        this.arm("seeked", this.position(audio), video); video.currentTime = this.position(audio);
        if (Math.abs(drift) > .5) this.record("video_resync", { drift: Math.round(drift * 1000) / 1000 });
      }
      if (video.playbackRate !== audio.playbackRate) {
        this.arm("ratechange", audio.playbackRate, video); video.playbackRate = audio.playbackRate;
      }
      if (!audio.paused && !audio.ended && video.paused && !this.videoPlayPending && !this.videoPauseTimer) {
        const mark = this.arm("play", false, video), attempt = { key: this.sourceKey };
        this.videoPlayPending = attempt;
        video.play().then(() => {
          if (this.videoPlayPending !== attempt || attempt.key !== this.sourceKey) return;
          if (!this.active || this.isHidden() || audio.paused || audio.ended) { this.arm("pause", true, video); video.pause(); }
        }).catch(() => {
          if (this.programmed.get("video:play") === mark) this.programmed.delete("video:play");
        }).finally(() => { if (this.videoPlayPending === attempt) this.videoPlayPending = null; });
      }
    }
    static heading(entry) { return entry ? `${entry.code ? entry.code + " — " : ""}${entry.title || "Video"}` : ""; }
    static duration(seconds) {
      if (!Number.isFinite(seconds) || seconds < 0) return "—";
      const whole = Math.floor(seconds); return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
    }
    static queueButton(entry, onClick) {
      const button = document.createElement("button"), code = document.createElement("code"), title = document.createElement("span"), duration = document.createElement("span");
      button.type = "button"; button.className = "btn player-track";
      code.className = "player-code"; code.textContent = entry.code || entry.clip_id || "—";
      title.className = "player-track-title"; title.textContent = entry.title || "Video";
      duration.className = "player-duration"; duration.textContent = AutoShortPlayer.duration(entry.duration);
      button.append(code, title, duration); button.addEventListener("click", onClick); return button;
    }
    scrollToVideo() {
      if (document.visibilityState !== "visible" || !this.active) return;
      let offset = 12;
      for (const bar of document.querySelectorAll(".topbar, .watch-invite")) {
        if (bar.hidden) continue;
        const position = getComputedStyle(bar).position;
        if (position === "sticky" || position === "fixed") offset += bar.getBoundingClientRect().height;
      }
      this.video.style.scrollMarginTop = `${offset}px`;
      this.video.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    // Scroll only inside the list box; never move the page (AC 29).
    static scrollWithin(container, item) {
      const box = container.getBoundingClientRect(), row = item.getBoundingClientRect();
      if (row.top < box.top) container.scrollTop += row.top - box.top;
      else if (row.bottom > box.bottom) container.scrollTop += row.bottom - box.bottom;
    }
    currentEntry() { return this.getItems()[this.state?.index] || this.state; }
    // All navigation, lists and end cards share one group identity (episode or favorites part).
    group(entry) {
      if (!entry) return null;
      if (entry.group) return entry.group;
      // Compatibility with rooms created by older clients; new favorites rooms send explicit groups.
      if (this.state?.continuous) return { id: "legacy-continuous", label: "Yêu thích" };
      return this.episode(entry);
    }
    nextInGroup() {
      const next = this.getNext(), now = this.group(this.currentEntry()), then = this.group(next);
      return next && (now?.id ?? null) === (then?.id ?? null) ? next : null;
    }
    // Distinct groups of the list, in order.
    groups() {
      const seen = new Map();
      for (const entry of this.getItems()) { const e = this.group(entry); if (e && !seen.has(e.id)) seen.set(e.id, e); }
      return [...seen.values()];
    }
    // Show only the playing group; scroll inside the list box (AC 29/30/43).
    renderGroupList(container, items, index, onPick, scroll = true) {
      const here = this.group(items[index]), key = here?.id ?? null;
      const members = [];
      items.forEach((entry, n) => { if ((this.group(entry)?.id ?? null) === key) members.push(n); });
      const label = here?.label;
      const signature = JSON.stringify([key, label, members, items.map((e) => [e.code, e.title, e.url])]);
      if (container.dataset.signature !== signature) {
        container.dataset.signature = signature;
        const head = document.createElement("p"), list = document.createElement("ol");
        head.className = "player-episode-head"; head.textContent = items.length ? `${label || "Danh sách"} · ${members.length} bài` : "";
        for (const n of members) {
          const li = document.createElement("li"), button = AutoShortPlayer.queueButton(items[n], () => onPick(n));
          button.dataset.index = n; li.append(button); list.append(li);
        }
        container.replaceChildren(head, list);
      }
      let current = null;
      container.querySelectorAll("button[data-index]").forEach((button) => {
        if (Number(button.dataset.index) === index) { button.setAttribute("aria-current", "true"); current = button; }
        else button.removeAttribute("aria-current");
      });
      if (current && scroll && document.visibilityState === "visible" && this.active) AutoShortPlayer.scrollWithin(container, current);
    }
    episode(entry) {
      if (!entry) return null;
      const match = (entry.video_url || entry.url || "").split("?")[0].match(/^\/files\/([^/]+)\/[^/]+\.mp4$/);
      const id = entry.base_episode_id || entry.episode_id || match?.[1];
      if (!id) return null;
      return { id: id.replace(/\.kt$/, ""), label: `Tập ${entry.ep_label || entry.ep_index || id.replace(/\.kt$/, "")}` };
    }
    // Sizes live here only; the server uses the group metadata sent with the queue.
    static favoritePartSizes = Object.freeze({ khaithi: 15, short: 35, both: 4 });
    static groupFavorites(items, filter) {
      const size = AutoShortPlayer.favoritePartSizes[filter], parts = [];
      let episodes = 0, lastEpisode;
      for (const [n, item] of items.entries()) {
        const eid = item.base_episode_id || item.episode_id.replace(/\.kt$/, "");
        if (eid !== lastEpisode) { episodes++; lastEpisode = eid; }
        const part = Math.floor((filter === "both" ? episodes - 1 : n) / size);
        (parts[part] ||= []).push(item);
      }
      let offset = 0;
      return parts.flatMap((members, n) => {
        const label = `Phần ${n + 1}`, first = members[0], last = members[members.length - 1];
        const span = filter === "both" ? `Tập ${first.ep_label || first.ep_index || first.base_episode_id}–${last.ep_label || last.ep_index || last.base_episode_id}`
          : `bài ${offset + 1}–${offset + members.length}`;
        offset += members.length;
        const group = { id: `favorites:${filter}:${n + 1}`, label, choice: `${label} (${span})`, kind: "part" };
        return members.map((item) => ({ ...item, group }));
      });
    }
    hideNotice() {
      clearTimeout(this.advanceTimer); this.localAdvanceAt = null; this.finishedKey = null;
      this.advanceSignature = null; this.$("notice").hidden = true;
    }
    advanceNow() {
      if (this.onEnded && this.state.advance_at != null) this.onAdvance();
      else { this.hideNotice(); this.onNavigate("next"); }
    }
    cancelAdvance() {
      if (this.onEnded) this.onCancelAdvance();
      else { this.localAdvanceAt = null; this.renderAdvance(); }
    }
    renderAdvance() {
      clearTimeout(this.advanceTimer);
      if (!this.active || !this.state?.video_url) return;
      const at = this.onEnded ? this.state.advance_at : this.localAdvanceAt;
      if (at != null || (this.onEnded && this.state.finished)) this.finishedKey = this.sourceKey;
      if (this.finishedKey !== this.sourceKey) { this.$("notice").hidden = true; return; }
      const next = this.getNext(), current = this.group(this.currentEntry()), upcoming = this.group(next);
      const boundary = current && (!next || upcoming?.id !== current.id);
      const signature = JSON.stringify([this.sourceKey, at ?? null, next?.code, next?.title, boundary]);
      if (signature !== this.advanceSignature) {
        this.advanceSignature = signature;
        const notice = this.$("notice"), end = document.createElement("strong"), title = document.createElement("p"), count = document.createElement("span");
        if (boundary) end.textContent = `Đã hết ${current.label}.`;
        end.hidden = !boundary;
        title.textContent = next ? `${boundary ? "Tiếp theo" : "Bài tiếp theo"}: ${AutoShortPlayer.heading(next)}` : "Đã hết danh sách";
        title.className = "player-up-next"; count.className = "small muted"; this.advanceCount = count;
        notice.replaceChildren(end, title, count);
        if (next) {
          const actions = document.createElement("div"), play = document.createElement("button");
          actions.className = "actions"; play.type = "button"; play.className = "btn primary small"; play.textContent = boundary ? `Nghe ${upcoming?.label || "nhóm tiếp theo"}` : "Phát ngay";
          const key = this.sourceKey;
          play.addEventListener("click", () => { if (key === this.sourceKey) this.advanceNow(); }); actions.append(play);
          if (at != null) {
            const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn small"; cancel.textContent = "Hủy";
            cancel.addEventListener("click", () => { if (key === this.sourceKey) this.cancelAdvance(); }); actions.append(cancel);
          }
          notice.append(actions);
        }
        const others = this.groups();
        if (boundary && this.onGroup && others.length > 1) {
          const pick = document.createElement("select");
          const noun = current.kind === "part" ? "phần" : "tập";
          pick.setAttribute("aria-label", `Chọn ${noun} khác`);
          const option = (value, text) => { const o = document.createElement("option"); o.value = value; o.textContent = text; return o; };
          pick.append(option("", `Chọn ${noun} khác…`));
          for (const e of others) if (e.id !== current.id) pick.append(option(e.id, e.choice || e.label));
          const key = this.sourceKey;
          pick.addEventListener("change", () => { if (pick.value && key === this.sourceKey) this.onGroup(pick.value); });
          notice.append(pick);
        }
        notice.hidden = false;
      }
      if (at == null) { this.advanceCount.textContent = next && !boundary ? "Tự chuyển đã dừng." : ""; return; }
      const left = this.onEnded ? at - (this.state.server_time + (performance.now() - this.receivedAt) / 1000) : (at - performance.now()) / 1000;
      const label = left > 0 ? `Sau ${Math.ceil(left)} s` : "Đang chuyển bài…";
      if (this.advanceCount.textContent !== label) this.advanceCount.textContent = label;
      if (left <= 0 && !this.onEnded) { this.hideNotice(); this.onNavigate("next"); return; }
      this.advanceTimer = setTimeout(() => this.renderAdvance(), 200);
    }
    programKey(event, media = this.media()) {
      return media === this.video ? `video:${event}` : media === this.audios[0] ? event : `audio2:${event}`;
    }
    arm(event, value, media = this.media()) {
      const mark = { value, media, until: performance.now() + 5000 };
      this.programmed.set(this.programKey(event, media), mark); return mark;
    }
    isProgrammed(event, current = this.media()) {
      const key = this.programKey(event, current);
      if (this.loading && current === this.audio) {
        const marked = this.programmed.has(key);
        this.programmed.delete(key);
        // Native controls can emit a user play before metadata has arrived.
        return event !== "play" || marked;
      }
      const mark = this.programmed.get(key);
      if (!mark || mark.media !== current) return false;
      const actual = event === "seeked" ? this.position(current) : event === "ratechange" ? current.playbackRate : current.paused;
      const matches = typeof actual === "number" ? Math.abs(actual - mark.value) < (event === "ratechange" ? .001 : 1) : actual === mark.value;
      this.programmed.delete(key);
      return performance.now() < mark.until && matches;
    }
    targetPosition() {
      const s = this.state;
      return s.position + (s.paused ? 0 : Math.max(0,
        s.server_time - s.updated_at + (performance.now() - this.receivedAt) / 1000) * s.rate);
    }
    wantsPlay() { return this.active && !!this.state?.video_url && !this.state.paused; }
    cancelRecovery() {
      if (this.recovery) this.recovery.timers.forEach(clearTimeout);
      this.recovery = null;
    }
    clearProgressChecks() {
      this.progressChecks.forEach(clearTimeout); this.progressChecks.clear();
    }
    resetRetry(userPlay = false) {
      this.cancelRecovery(); this.clearProgressChecks();
      if (this.hiddenRun) Object.assign(this.hiddenRun, { attempts: 0, since: null, position: null, gaveUp: false });
      if (userPlay) {
        this.playPending = null;
        clearTimeout(this.videoPauseTimer); this.videoPauseTimer = null;
      }
    }
    giveUpRetry() {
      const run = this.hiddenRun;
      if (!run || run.gaveUp || run.since == null || performance.now() - run.since < 300000) return;
      run.gaveUp = true; this.cancelRecovery(); this.clearProgressChecks();
      this.record("retry_gave_up");
    }
    checkRetryProgress(run, key, started) {
      const timer = setTimeout(() => {
        this.progressChecks.delete(timer);
        if (this.hiddenRun !== run || run.gaveUp || !this.isHidden() || key !== this.sourceKey || !this.wantsPlay()) return;
        if (this.position() > started) {
          this.resetRetry();
          if (this.media().paused && !this.media().ended) this.recover();
        }
      }, 2000);
      this.progressChecks.add(timer);
    }
    recover() {
      const run = this.hiddenRun, current = this.media();
      if (!this.isHidden() || !run || run.gaveUp || this.recovery || !this.wantsPlay() || current.ended) return;
      run.since ??= performance.now(); run.position ??= this.position(current);
      const cycle = { key: this.sourceKey, timers: [] };
      this.recovery = cycle;
      const retry = () => {
        if (this.recovery !== cycle || cycle.key !== this.sourceKey || !this.wantsPlay() || !this.isHidden() || current.ended) return;
        if (this.position(current) > run.position) {
          this.resetRetry();
          if (current.paused) this.recover();
          return;
        }
        const elapsed = performance.now() - run.since;
        if (elapsed >= 300000) { this.giveUpRetry(); return; }
        if (current.paused) this.playMedia(current, cycle);
        const next = [1000, 3000, 10000].find((at) => at > elapsed);
        cycle.timers = [setTimeout(retry, Math.min(next ? next - elapsed : 15000, 300000 - elapsed))];
      };
      cycle.timers = [setTimeout(retry, 1000)];
    }
    playMedia(current, recovery = null) {
      if (!this.active || this.playPending) return;
      const run = recovery ? this.hiddenRun : null;
      if (recovery) {
        if (!run || run.gaveUp) return;
        if (performance.now() - run.since >= 300000) { this.giveUpRetry(); return; }
        run.attempts++;
      }
      const playMark = this.arm("play", false), attempt = { key: this.sourceKey };
      this.playPending = attempt;
      const stillCurrent = () => this.playPending === attempt && attempt.key === this.sourceKey && current === this.media();
      current.play().then(() => {
        if (!stillCurrent()) return;
        if (!this.wantsPlay()) { this.arm("pause", true); current.pause(); return; }
        if (recovery && this.hiddenRun === run && !run.gaveUp) {
          this.record("retry_ok"); this.checkRetryProgress(run, attempt.key, this.position(current));
        }
        if (current.paused) return;
        this.$("play").hidden = true; if (!recovery) this.cancelRecovery();
      }).catch((error) => {
        const key = this.programKey("play", current);
        if (this.programmed.get(key) === playMark) this.programmed.delete(key);
        if (!stillCurrent()) return;
        if (recovery && this.hiddenRun === run && !run.gaveUp) {
          this.record("retry_blocked", { err: String(error.name || "Error").slice(0, 80) });
        }
        if (!recovery && this.isHidden() && this.wantsPlay()) this.recover();
        if (this.wantsPlay()) this.$("play").hidden = false;
      }).finally(() => {
        if (this.playPending === attempt) this.playPending = null;
      });
    }
    sync(keepPosition = false) {
      const current = this.media(), s = this.state;
      if (!this.active || !s?.video_url || this.syncBlocked) return;
      if (s.paused && !current.paused) { this.arm("pause", true); current.pause(); }
      if (this.loading || !current.readyState) return;
      const hidden = this.isHidden(), explicit = this.seekRequested;
      const target = Math.min(this.targetPosition(), Number.isFinite(current.duration) ? current.duration - this.pad() : Infinity);
      const drift = target - this.position(current);
      if (!keepPosition && Math.abs(drift) > 1) {
        if (!hidden || explicit) { this.arm("seeked", target); this.seek(target, current); }
        else this.record("seek_skipped_hidden", { drift: Math.round(drift * 1000) / 1000 });
      }
      if ((!hidden || explicit || this.allowHiddenPlay) && current.playbackRate !== s.rate) {
        this.arm("ratechange", s.rate); current.playbackRate = s.rate;
      }
      if (s.paused) {
        this.cancelRecovery();
        if (!current.paused) { this.arm("pause", true); current.pause(); }
        this.$("play").hidden = !current.paused;
      } else if (current.paused && !current.ended && (!hidden || this.allowHiddenPlay)) this.playMedia(current);
      this.seekRequested = false; this.allowHiddenPlay = false;
      this.syncVideo();
    }
    record(type, extra = {}) {
      const now = performance.now();
      if (type === "seek_skipped_hidden") {
        if (!this.hiddenRun || this.hiddenRun.skipped) return;
        this.hiddenRun.skipped = true;
      }
      if (["waiting", "stalled", "video_resync"].includes(type)) {
        if (now - (this.logMarks.get(type) ?? -Infinity) < 5000) return;
        this.logMarks.set(type, now);
      }
      const event = { type, hidden: this.isHidden(), ...extra };
      if (type === "pause_hidden") Object.assign(event, { rs: this.audio.readyState, ns: this.audio.networkState });
      if (Number.isFinite(this.position())) event.t = Math.round(this.position() * 1000) / 1000;
      this.events.push(event);
      if (this.events.length > 20) this.events.shift();
      this.scheduleLog();
    }
    scheduleLog() {
      if (!this.logTimer && this.events.length) this.logTimer = setTimeout(() => {
        this.logTimer = null; this.flushLog();
      }, Math.max(0, 5000 - (performance.now() - this.lastLogAt)));
    }
    flushLog(beacon = false) {
      clearTimeout(this.logTimer); this.logTimer = null;
      if (!this.events.length) return;
      if (performance.now() - this.lastLogAt < 5000) { this.scheduleLog(); return; }
      const events = this.events.slice(0, 20), payload = () => JSON.stringify({ client: this.client, page: this.page, events });
      while (events.length && new TextEncoder().encode(payload()).length > 2048) events.pop();
      if (!events.length) { this.events.shift(); return; }
      const body = payload();
      if (beacon) {
        if (!navigator.sendBeacon("/api/watch/log", new Blob([body], { type: "application/json" }))) return;
      } else {
        fetch("/api/watch/log", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => {});
      }
      this.lastLogAt = performance.now(); this.events.splice(0, events.length);
      if (!beacon) this.scheduleLog();
    }
    audioUrl(url) { return url.replace(/\.mp4(?=[?#]|$)/, ".m4a"); }
    loadMedia(current, src, position, rate) {
      if (!current.paused) this.arm("pause", true, current);
      current.src = src; current.load();
      this.arm("seeked", position, current); this.seek(position, current);
      this.arm("ratechange", rate, current); current.playbackRate = rate;
    }
    load() {
      const adopted = this.adopting?.key === this.sourceKey ? this.adopting : null;
      this.adopting = null;
      this.cancelEarly(adopted);
      if (adopted) {
        if (!this.audio.paused) { this.arm("pause", true); this.audio.pause(); }
        this.audio = adopted.media;
        this.audio.playbackRate = this.state.rate;
      }
      this.loading = adopted ? !this.audio.readyState : true;
      this.programmed.clear(); this.playPending = this.videoPlayPending = null;
      this.video.muted = true; this.audioFallback = false; this.fallbackResume = null;
      for (const current of [this.audio, this.video]) {
        if (adopted && current === this.audio) continue;
        const src = current === this.audio ? this.audioUrl(this.state.video_url) : this.state.video_url;
        this.loadMedia(current, src, this.state.position, this.state.rate);
      }
      if (adopted) {
        // Keep the inserted silence and the already-running clock through metadata / room acknowledgements.
        this.fallbackResume = { state: this.state, position: this.position(), raw: true };
        this.arm("play", false); this.arm("seeked", this.position()); this.arm("ratechange", this.audio.playbackRate);
        this.seekRequested = false; this.allowHiddenPlay = false;
      }
      // Start the established audio element inside the click / ended handler, before metadata or a network reply.
      if (this.wantsPlay() && (!adopted || this.audio.paused)) this.playMedia(this.audio);
      this.prepareNext();
    }
    setState(state, sync = true, blocked = false, remote = false) {
      const previous = this.state, oldKey = this.sourceKey, advanced = this.endedKey != null && this.endedKey === oldKey;
      const canceledEnd = this.prepared?.ended && !state.auto && !state.paused;
      if (previous?.paused && !state.paused && state.advance_at == null) this.hideNotice();
      if (previous && remote && previous.version !== state.version) {
        const expected = previous.position + (previous.paused ? 0 : Math.max(0, state.updated_at - previous.updated_at) * previous.rate);
        const jumped = Math.abs(state.position - expected) > 1;
        if (jumped) this.cancelEarly();
        this.seekRequested ||= jumped;
        this.allowHiddenPlay ||= !state.paused && (previous.paused || jumped);
      }
      if (state.paused || !state.video_url || !state.auto) {
        this.resetRetry();
        this.cancelEarly();
      }
      this.state = state; this.receivedAt = performance.now(); this.syncBlocked = blocked;
      const key = state.video_url ? JSON.stringify([state.index, state.video_url]) : null;
      if (key !== this.sourceKey) {
        clearTimeout(this.videoPauseTimer); this.videoPauseTimer = null;
        this.resetRetry();
        this.hideNotice(); this.sourceKey = key; this.playPending = null;
        this.seekRequested = true; this.allowHiddenPlay = true;
        if (key === null) {
          this.cancelEarly();
          this.loading = true;
          for (const current of [this.video, ...this.audios]) {
            if (!current.paused) { this.arm("pause", true, current); current.pause(); }
            current.removeAttribute("src"); current.load();
          }
          this.hideNotice();
        } else this.load();
      } else if (sync) this.sync();
      this.prepareNext();
      if (!state.auto && this.localAdvanceAt != null) this.localAdvanceAt = null;
      this.render(); this.renderAdvance();
      if (canceledEnd && key === oldKey) this.finishEnded();
      // Track changed after the end of a track (auto or "Phát ngay"): bring the video back into view.
      if (advanced && key !== null && key !== oldKey) { this.endedKey = null; this.scrollToVideo(); }
    }
    render() {
      const s = this.state, active = !!s?.video_url;
      this.video.hidden = !active;
      this.pipButton.disabled = !active || !!this.pipBusy;
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
      try { navigator.mediaSession.setActionHandler("enterpictureinpicture", () => this.togglePiP()); } catch (_) { /* Optional action. */ }
      for (const [name, action] of [["play", "play"], ["pause", "pause"], ["previoustrack", "prev"], ["nexttrack", "next"]]) {
        try {
          navigator.mediaSession.setActionHandler(name, () => {
            if (!this.active || !this.state?.video_url) return;
            if (action === "prev" || action === "next") this.onNavigate(action);
            else {
              this.hideNotice(); this.cancelRecovery();
              if (action === "pause") this.cancelEarly();
              if (action === "play") { this.resetRetry(true); this.allowHiddenPlay = true; }
              this.onAction(action, { position: this.loading ? this.targetPosition() : this.position() }, true);
              if (action === "play") this.playMedia(this.media());
            }
          });
        } catch (_) { /* Unsupported action. */ }
      }
    }
    suspend() {
      this.active = false; this.cancelRecovery(); this.clearProgressChecks();
      this.cancelEarly();
      for (const current of [this.video, ...this.audios]) if (!current.paused) { this.arm("pause", true, current); current.pause(); }
      this.hideNotice();
      if ("mediaSession" in navigator) {
        navigator.mediaSession.playbackState = "none";
        for (const action of ["play", "pause", "previoustrack", "nexttrack", "enterpictureinpicture"]) {
          try { navigator.mediaSession.setActionHandler(action, null); } catch (_) { /* Unsupported action. */ }
        }
      }
    }
    activate() { this.active = true; this.cancelRecovery(); this.visibilityChanged(); this.render(); this.renderAdvance(); }
  };
})();
