/* CP8.34: pure state machine of the sequential-download queue (no DOM, no network, no timers: the page feeds it the
   clock and the server's /api/downloads/<token> answers). Loaded by playlist.html and by the Node test. */
"use strict";

(function (root) {
  const DEFAULTS = { concurrency: 2, maxRetries: 2, retryWaitMs: 5000, noRequestMs: 60000 };

  function createQueue(options) {
    const opt = Object.assign({}, DEFAULTS, options || {});
    const items = [];
    let paused = false;
    let seq = 0;

    function clampConcurrency(n) { n = Math.round(Number(n)); return n >= 1 && n <= 3 ? n : DEFAULTS.concurrency; }
    let concurrency = clampConcurrency(opt.concurrency);

    function sendingCount() { return items.filter((i) => i.status === "sending").length; }

    function fail(item, now, reason) {
      item.reason = reason;
      if (item.attempts <= opt.maxRetries) { // attempts counts the starts so far: 1 first try + maxRetries retries
        item.status = "retrywait";
        item.retryAt = now + opt.retryWaitMs;
      } else {
        item.status = "error";
      }
    }

    return {
      items,
      /** specs: [{key, name, url, kind, skipped?: reason}] -> new items (a spec whose key is already live is ignored). */
      add(specs) {
        const added = [];
        for (const s of specs) {
          const live = items.find((i) => i.key === s.key && !["done", "error", "skipped"].includes(i.status));
          if (live) continue;
          const item = { id: ++seq, key: s.key, name: s.name, url: s.url, kind: s.kind, status: s.skipped ? "skipped" : "waiting",
            reason: s.skipped || "", attempts: 0, token: null, startedAt: 0, retryAt: 0, seen: false, bytesSent: 0, bytesTotal: null };
          items.push(item);
          added.push(item);
        }
        return added;
      },
      setConcurrency(n) { concurrency = clampConcurrency(n); },
      getConcurrency() { return concurrency; },
      pause() { paused = true; },
      resume() { paused = false; },
      isPaused() { return paused; },
      /** The user presses "Thử lại" on an error row: a fresh set of attempts, at the end of the line. */
      retry(id) {
        const item = items.find((i) => i.id === id);
        if (!item || item.status !== "error") return false;
        item.status = "waiting"; item.attempts = 0; item.reason = "";
        return true;
      },
      /** Move due retries back to waiting, then start waiting items up to the concurrency. Returns [{item, token}]
       *  the caller must start (the item is already `sending` with its new token). */
      step(now, makeToken) {
        for (const i of items) if (i.status === "retrywait" && i.retryAt <= now) i.status = "waiting";
        const started = [];
        if (paused) return started;
        for (const i of items) {
          if (sendingCount() >= concurrency) break;
          if (i.status !== "waiting") continue;
          i.status = "sending"; i.attempts += 1; i.token = makeToken(); i.startedAt = now; i.seen = false;
          i.bytesSent = 0; i.bytesTotal = null; i.reason = "";
          started.push({ item: i, token: i.token });
        }
        return started;
      },
      /** A poll answer for an item that is `sending`: ``info`` = {state, bytes_sent, bytes_total} or null (404: the
       *  server has not seen the request yet). A stale answer (another token) is ignored. */
      report(id, token, info, now) {
        const i = items.find((x) => x.id === id);
        if (!i || i.status !== "sending" || i.token !== token) return;
        if (!info) {
          if (!i.seen && now - i.startedAt > opt.noRequestMs) fail(i, now, "máy chủ không nhận được yêu cầu tải");
          return;
        }
        i.seen = true;
        i.bytesSent = info.bytes_sent || 0;
        i.bytesTotal = info.bytes_total == null ? null : info.bytes_total;
        if (info.state === "done") { i.status = "done"; i.reason = ""; }
        else if (info.state === "aborted") fail(i, now, "bị ngắt giữa chừng");
      },
      /** Anything still to do (drives the timer and the Wake Lock). */
      active() { return items.some((i) => ["waiting", "sending", "retrywait"].includes(i.status)); },
      counts() {
        const c = { waiting: 0, sending: 0, retrywait: 0, done: 0, error: 0, skipped: 0 };
        for (const i of items) c[i.status] += 1;
        return c;
      },
    };
  }

  /** Append ``dl=<token>`` to a download URL. */
  function withToken(url, token) { return url + (url.indexOf("?") >= 0 ? "&" : "?") + "dl=" + encodeURIComponent(token); }

  const api = { createQueue, withToken, DEFAULTS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DownloadQueue = api;
})(typeof window !== "undefined" ? window : this);
