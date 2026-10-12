/* Đọc Kinh (SR1 S7, S8): library + reader. Vanilla JS; all sutra data goes into the DOM via textContent only.
 *
 * sutra-awake.mp4 (S8 fallback, ~2 KB) was generated with:
 *   ffmpeg -f lavfi -i color=c=black:s=16x16:r=1 -f lavfi -i anullsrc=r=8000:cl=mono -t 2 -c:v libx264 \
 *     -pix_fmt yuv420p -c:a aac -b:a 8k -movflags +faststart sutra-awake.mp4
 */
(function () {
  "use strict";

  var SETTINGS_KEY = "sutra:settings";
  var DEFAULTS = { size: 18, line: 1.7, serif: true, theme: "paper", awake: true, weight: 400, mode: "scroll" };
  var STRONG_OF = { 400: 700, 500: 700, 700: 800 };   // `strong` lines: one step heavier than the body, max 800

  // --- helpers -------------------------------------------------------------------------------------

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function $(id) { return document.getElementById(id); }
  function store(key, value) {
    try {
      if (value === undefined) { var v = window.localStorage.getItem(key); return v === null ? null : JSON.parse(v); }
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { /* no storage (private mode...): the page still works */ }
    return null;
  }
  function loadSettings() {
    var s = store(SETTINGS_KEY), out = {}, k;
    for (k in DEFAULTS) out[k] = DEFAULTS[k];
    if (s && typeof s === "object") for (k in DEFAULTS) if (typeof s[k] === typeof DEFAULTS[k]) out[k] = s[k];
    out.size = Math.min(32, Math.max(14, Math.round(out.size / 2) * 2));
    if (["light", "paper", "dark"].indexOf(out.theme) < 0) out.theme = "paper";
    if ([1.4, 1.7, 2.0].indexOf(out.line) < 0) out.line = 1.7;
    if ([400, 500, 700].indexOf(out.weight) < 0) out.weight = 400;
    if (["scroll", "page"].indexOf(out.mode) < 0) out.mode = "scroll";
    return out;
  }
  // body: a plain object (sent as JSON) or a File / Blob (sent raw, S5 upload)
  function api(method, url, body) {
    var opts = { method: method, credentials: "same-origin" };
    if (body !== undefined) {
      if (typeof Blob !== "undefined" && body instanceof Blob) opts.body = body;
      else { opts.body = JSON.stringify(body); opts.headers = { "Content-Type": "application/json" }; }
    }
    return fetch(url, opts).then(function (r) {
      if (r.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); throw new Error("401"); }
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (!r.ok) { var err = new Error(body.detail || ("Lỗi " + r.status)); err.status = r.status; err.body = body; throw err; }
        return body;
      });
    });
  }
  function dayKey(d) {
    var m = d.getMonth() + 1, day = d.getDate();
    return d.getFullYear() + "-" + (m < 10 ? "0" : "") + m + "-" + (day < 10 ? "0" : "") + day;
  }
  function fmtDate(iso) {
    var d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString("vi-VN") + " " + d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
  }

  // --- library -------------------------------------------------------------------------------------

  function initLibrary() {
    var list = $("lib-list"), msg = $("lib-msg");
    api("GET", "/api/sutras").then(function (items) {
      msg.textContent = items.length ? "" : "Chưa có bộ kinh nào.";
      items.forEach(function (it) {
        var li = el("li", "lib-item");
        li.appendChild(el("span", "lib-title", it.title));
        var info = it.sections + " mục · " + it.recitations.total + " biến";
        if (it.recitations.last_at) info += " · lần tụng cuối " + fmtDate(it.recitations.last_at);
        li.appendChild(el("span", "muted small", info));
        var acts = el("div", "lib-actions");
        var href = "/sutras/" + encodeURIComponent(it.slug);
        var pos = store("sutra:pos:" + it.slug);
        if (pos && pos.section) {
          var a = el("a", "btn primary small", "Đọc tiếp"); a.href = href; acts.appendChild(a);
          var b = el("a", "btn small", "Đọc từ đầu"); b.href = href + "?start=1"; acts.appendChild(b);
        } else {
          var c = el("a", "btn primary small", "Đọc từ đầu"); c.href = href; acts.appendChild(c);
        }
        li.appendChild(acts);
        list.appendChild(li);
      });
    }).catch(function (e) { if (e.message !== "401") msg.textContent = "Không tải được thư viện: " + e.message; });
  }

  // --- reader --------------------------------------------------------------------------------------

  function initReader() {
    var slug = decodeURIComponent(location.pathname.replace(/^\/sutras\//, "").replace(/\/$/, ""));
    var settings = loadSettings();
    var data = null, entries = [], total = 0;
    var sections = [];           // [{id, title, el}]
    var restoring = true;
    var bar = $("rbar"), reader = $("reader");

    // settings -------------------------------------------------------------------------------------
    var paged = false, padLeft = 16, laidW = 0, laidH = 0, lastAnchor = null, lastInnerW = window.innerWidth;
    function saveSettings() { store(SETTINGS_KEY, settings); }
    function applySettings() {
      document.body.setAttribute("data-theme", settings.theme);
      reader.style.setProperty("--fs", settings.size + "px");
      reader.style.setProperty("--lh", String(settings.line));
      reader.style.setProperty("--wt", String(settings.weight));
      reader.style.setProperty("--wt-strong", String(STRONG_OF[settings.weight]));
      reader.classList.toggle("sans", !settings.serif);
      var p = settings.mode === "page";
      if (p !== paged) setPaged(p);
    }
    // a change that re-flows the text: remember the passage at the top of the view, apply, put it back
    function commit(change) {
      var a = data ? captureAnchor() : null;
      change(); saveSettings(); applySettings();
      if (data) relayout(a);
      buildSettings();
    }
    function choice(row, label, options, isOn, onPick) {
      var wrap = el("div", "set-row");
      wrap.appendChild(el("span", null, label));
      options.forEach(function (o) {
        var b = el("button", "rbtn" + (isOn(o[0]) ? " on" : ""), o[1]);
        b.type = "button";
        b.addEventListener("click", function () { commit(function () { onPick(o[0]); }); });
        wrap.appendChild(b);
      });
      row.appendChild(wrap);
    }
    function buildSettings() {
      var box = $("settings");
      box.textContent = "";
      var size = el("div", "set-row");
      size.appendChild(el("span", null, "Cỡ chữ"));
      var minus = el("button", "rbtn", "A−"), plus = el("button", "rbtn", "A+");
      minus.type = plus.type = "button";
      minus.addEventListener("click", function () { commit(function () { settings.size = Math.max(14, settings.size - 2); }); });
      plus.addEventListener("click", function () { commit(function () { settings.size = Math.min(32, settings.size + 2); }); });
      size.appendChild(minus); size.appendChild(el("span", null, settings.size + " px")); size.appendChild(plus);
      box.appendChild(size);
      choice(box, "Giãn dòng", [[1.4, "Sát"], [1.7, "Vừa"], [2.0, "Rộng"]],
        function (v) { return settings.line === v; }, function (v) { settings.line = v; });
      choice(box, "Độ đậm chữ", [[400, "Thường"], [500, "Đậm vừa"], [700, "Đậm"]],
        function (v) { return settings.weight === v; }, function (v) { settings.weight = v; });
      choice(box, "Kiểu chữ", [[true, "Có chân"], [false, "Không chân"]],
        function (v) { return settings.serif === v; }, function (v) { settings.serif = v; });
      choice(box, "Kiểu đọc", [["scroll", "Cuộn dọc"], ["page", "Lật trang ngang"]],
        function (v) { return settings.mode === v; }, function (v) { settings.mode = v; });
      choice(box, "Nền", [["light", "Sáng"], ["paper", "Giấy"], ["dark", "Tối"]],
        function (v) { return settings.theme === v; }, function (v) { settings.theme = v; });
      var awakeRow = el("div", "set-row");
      awakeRow.appendChild(el("span", null, "Màn hình"));
      var ab = el("button", "rbtn" + (settings.awake ? " on" : ""), "Giữ màn hình sáng");
      ab.type = "button";
      ab.addEventListener("click", function () {
        settings.awake = !settings.awake; saveSettings();
        if (settings.awake) startAwake(); else stopAwake();
        buildSettings();
      });
      awakeRow.appendChild(ab);
      box.appendChild(awakeRow);
    }

    // paging (SR1.4): CSS columns one page wide inside a fixed, horizontally scrolled viewport -------
    function leaves() { return $("text").querySelectorAll("h1, h2, h3, .intro, .line"); }
    function firstRect(e) {
      var rs = e.getClientRects(), i;
      for (i = 0; i < rs.length; i++) if (rs[i].width > 0 || rs[i].height > 0) return rs[i];
      return null;
    }
    function pageW() { return Math.max(1, reader.clientWidth); }
    function pages() { return Math.max(1, Math.ceil((reader.scrollWidth - 1) / pageW())); }
    function curPage() { return Math.min(pages() - 1, Math.max(0, Math.round(reader.scrollLeft / pageW()))); }
    function pageOfRect(r) { return Math.floor((r.left + reader.scrollLeft) / pageW()); }
    function pageOf(e) { var r = firstRect(e); return r ? Math.max(0, pageOfRect(r)) : 0; }
    function updatePageNo() { $("pageno").textContent = (curPage() + 1) + " / " + pages(); }
    var posTimer = null;
    function schedSave() { clearTimeout(posTimer); posTimer = setTimeout(function () { savePos(); lastAnchor = captureAnchor(); }, 300); }
    function goPage(p) {
      p = Math.min(pages() - 1, Math.max(0, p));
      reader.scrollLeft = p * pageW();
      updatePageNo();
      lastAnchor = captureAnchor();
      schedSave();
    }
    function layoutPaged() {
      var pw = pageW(), ph = reader.clientHeight, art = $("text");
      var textW = Math.min(pw - 32, 672), top = 56, bottom = 36;
      if (textW < 100) textW = Math.max(50, pw - 8);
      padLeft = Math.floor((pw - textW) / 2);
      art.style.width = textW + "px";
      art.style.columnWidth = textW + "px";
      art.style.columnGap = (pw - textW) + "px";
      art.style.height = Math.max(100, ph - top - bottom) + "px";
      art.style.marginLeft = padLeft + "px";
      art.style.marginTop = top + "px";
      laidW = pw; laidH = ph;
    }
    function setPaged(p) {
      paged = p;
      reader.classList.toggle("paged", p);
      document.body.classList.toggle("paged", p);
      $("pageno").hidden = !p;
      var art = $("text"), fin = document.querySelector(".finish");
      if (p) { art.appendChild(fin); window.scrollTo(0, 0); }
      else {
        reader.appendChild(fin);
        reader.scrollLeft = 0;
        ["width", "columnWidth", "columnGap", "height", "marginLeft", "marginTop"].forEach(function (k) { art.style[k] = ""; });
      }
    }
    // the passage at the top of the current view: {el, top}
    function captureAnchor() {
      if (!data) return null;
      var list = leaves(), i, r, k, rs, cur = paged ? curPage() : 0;
      for (i = 0; i < list.length; i++) {
        if (paged) {
          rs = list[i].getClientRects();
          for (k = 0; k < rs.length; k++) if (rs[k].width > 0 && pageOfRect(rs[k]) >= cur) return { el: list[i], top: null };
        } else {
          r = list[i].getBoundingClientRect();
          if (r.height > 0 && r.bottom > 4) return { el: list[i], top: r.top };
        }
      }
      return null;
    }
    function relayout(a) {
      if (paged) {
        layoutPaged();
        goPage(a && a.el ? pageOf(a.el) : curPage());
      } else if (a && a.el) {
        var want = a.top == null ? 0 : a.top;
        window.scrollTo(0, a.el.getBoundingClientRect().top + window.scrollY - want);
        lastAnchor = captureAnchor();
      }
    }
    // linear coordinate along the text: y in scroll mode, x (columns laid side by side) in page mode
    function lin(e) {
      if (paged) { var r = firstRect(e); return r ? r.left + reader.scrollLeft : 0; }
      return e.getBoundingClientRect().top + window.scrollY;
    }
    function viewStart() { return paged ? reader.scrollLeft : window.scrollY; }
    function docEnd() { return paged ? pages() * pageW() : document.documentElement.scrollHeight; }
    function slack() { return paged ? padLeft + 8 : 8; }
    function goLin(v) { if (paged) goPage(Math.floor(v / pageW())); else window.scrollTo(0, v); }
    function nextPage(d) { if (paged) goPage(curPage() + d); }
    var rzTimer = null;
    function onResize() {
      clearTimeout(rzTimer);
      rzTimer = setTimeout(function () {
        if (!data) return;
        if (paged) { if (reader.clientWidth !== laidW || reader.clientHeight !== laidH) relayout(lastAnchor); }
        else if (window.innerWidth !== lastInnerW) relayout(lastAnchor);
        lastInnerW = window.innerWidth;
      }, 150);
    }
    window.addEventListener("resize", onResize);
    window.addEventListener("orientationchange", onResize);

    // sheets ---------------------------------------------------------------------------------------
    function openSheet(id) { $(id).hidden = false; bar.classList.remove("hidden"); }
    function sheetsOpen() { return ["sheet-toc", "sheet-set", "sheet-count", "sheet-menu"].some(function (i) { return !$(i).hidden; }); }
    function closeSheets() { ["sheet-toc", "sheet-set", "sheet-count", "sheet-menu"].forEach(function (i) { $(i).hidden = true; }); }
    Array.prototype.forEach.call(document.querySelectorAll(".sheet"), function (s) {
      s.addEventListener("click", function (ev) { if (ev.target === s) closeSheets(); });
    });
    Array.prototype.forEach.call(document.querySelectorAll(".sheet-close"), function (b) { b.addEventListener("click", closeSheets); });
    $("btn-set").addEventListener("click", function () { buildSettings(); openSheet("sheet-set"); });
    $("btn-toc").addEventListener("click", function () { updateCurrent(); openSheet("sheet-toc"); });
    $("btn-count").addEventListener("click", function () { buildHistory(); openSheet("sheet-count"); });
    $("btn-menu").addEventListener("click", function () {
      $("menu-edit").href = "/sutras/" + encodeURIComponent(slug) + "/edit";
      $("menu-msg").textContent = "";
      openSheet("sheet-menu");
    });
    $("menu-delete").addEventListener("click", function () {
      var title = data ? data.title : slug;
      var msg = "Xóa bộ kinh “" + title + "”?\n\nLịch sử tụng (" + total + " biến) cũng sẽ mất. Không hoàn tác được.";
      if (!window.confirm(msg)) return;
      var b = $("menu-delete");
      b.disabled = true;
      api("DELETE", "/api/sutras/" + encodeURIComponent(slug)).then(function () {
        try { window.localStorage.removeItem("sutra:pos:" + slug); } catch (e) { /* ignore */ }
        restoring = true;  // do not re-save the reading position while leaving
        location.href = "/sutras";
      }).catch(function (e) { $("menu-msg").textContent = "Không xóa được: " + e.message; b.disabled = false; });
    });

    // render ---------------------------------------------------------------------------------------
    function addLine(parent, ln, notes) {
      var span = el("span", "line " + ln.kind);
      var parts = ln.text.split(/(\[\^\d{1,3}\])/);
      parts.forEach(function (part) {
        var m = /^\[\^(\d{1,3})\]$/.exec(part);
        if (!m) { if (part) span.appendChild(document.createTextNode(part)); return; }
        var n = m[1], btn = el("button", "fn", n);
        btn.type = "button";
        btn.setAttribute("aria-label", "Chú thích " + n);
        btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          var next = span.nextSibling;
          if (next && next.classList && next.classList.contains("note") && next.getAttribute("data-n") === n) {
            next.remove();
          } else {
            var note = el("span", "note", n + ". " + (notes[n] || ""));
            note.setAttribute("data-n", n);
            span.parentNode.insertBefore(note, span.nextSibling);
          }
          if (paged) goPage(pageOf(btn));   // the text re-flowed: stay on the page of the footnote mark
        });
        span.appendChild(btn);
      });
      parent.appendChild(span);
    }
    function render() {
      var art = $("text"), fin = document.querySelector(".finish");
      if (fin.parentNode === art) reader.appendChild(fin);   // page mode keeps it inside the article: do not lose it
      art.textContent = "";
      art.appendChild(el("h1", null, data.title));
      data.intro.forEach(function (t) { art.appendChild(el("p", "intro", t)); });
      var toc = $("toc");
      toc.textContent = "";
      sections = [];
      data.groups.forEach(function (g) {
        if (g.title) {
          art.appendChild(el("h2", "group", g.title));
          toc.appendChild(el("div", "toc-group", g.title));
        }
        g.sections.forEach(function (s) {
          var h = el("h3", "sec", s.title);
          h.id = s.id;
          art.appendChild(h);
          s.paragraphs.forEach(function (p) {
            var pe = el("p", "para"), chars = 0;
            p.forEach(function (ln) { chars += ln.text.length; });
            if (chars < 200) pe.classList.add("short");   // page mode keeps short blocks on one page
            p.forEach(function (ln) { addLine(pe, ln, s.notes); });
            art.appendChild(pe);
          });
          var item = el("button", "toc-item", s.title);
          item.type = "button";
          item.setAttribute("data-id", s.id);
          item.addEventListener("click", function () { closeSheets(); if (paged) goPage(pageOf(h)); else h.scrollIntoView(); });
          toc.appendChild(item);
          sections.push({ id: s.id, title: s.title, el: h });
        });
      });
      $("rtitle").textContent = data.title;
      document.title = data.title + " — Đọc Kinh";
    }

    // position -------------------------------------------------------------------------------------
    function sectionEnd(i) { return i + 1 < sections.length ? lin(sections[i + 1].el) : docEnd(); }
    function current() {
      // last section whose heading is at / above the top of the view (+ small slack)
      var cur = null, i, vs = viewStart();
      for (i = 0; i < sections.length; i++) {
        if (lin(sections[i].el) <= vs + slack()) cur = i; else break;
      }
      if (cur === null) return sections.length ? { index: 0, offset: 0 } : null;
      var top = lin(sections[cur].el), span = Math.max(1, sectionEnd(cur) - top);
      return { index: cur, offset: Math.min(1, Math.max(0, (vs - top) / span)) };
    }
    function savePos() {
      if (restoring || !data) return;
      var c = current();
      if (!c) return;
      store("sutra:pos:" + slug, { section: sections[c.index].id, offset: c.offset, sha256: data.sha256, at: Date.now() });
    }
    function updateCurrent() {
      var c = current(), id = c ? sections[c.index].id : null;
      Array.prototype.forEach.call(document.querySelectorAll(".toc-item"), function (b) {
        b.classList.toggle("current", b.getAttribute("data-id") === id);
      });
    }
    function restore() {
      var params = new URLSearchParams(location.search);
      var pos = params.get("start") === "1" ? null : store("sutra:pos:" + slug);
      if (pos && pos.section) {
        var sec = null;
        sections.forEach(function (s) { if (s.id === pos.section) sec = s; });
        if (sec) {
          var top = lin(sec.el), end = sectionEnd(sections.indexOf(sec));
          var off = pos.sha256 === data.sha256 && typeof pos.offset === "number" ? pos.offset : 0;
          goLin(top + off * Math.max(1, end - top));
        }
      }
      restoring = false;
      if (paged) updatePageNo();
      lastAnchor = captureAnchor();
    }
    var lastY = 0;
    window.addEventListener("scroll", function () {
      var y = window.scrollY;
      if (y > lastY + 10 && y > 80) { if (!sheetsOpen()) bar.classList.add("hidden"); }
      else if (y < lastY - 10) bar.classList.remove("hidden");
      lastY = y;
      clearTimeout(posTimer);
      posTimer = setTimeout(function () { savePos(); lastAnchor = captureAnchor(); }, 300);
    }, { passive: true });
    window.addEventListener("pagehide", savePos);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") { savePos(); pauseAwake(); } else { resumeAwake(); }
    });
    var lastSwipe = 0, tx = 0, ty = 0;
    reader.addEventListener("click", function (ev) {
      if (ev.target.closest("button, a")) return;
      if (paged) {
        if (Date.now() - lastSwipe < 500) return;
        var w = reader.clientWidth;
        if (ev.clientX < w * 0.25) { nextPage(-1); return; }
        if (ev.clientX > w * 0.75) { nextPage(1); return; }
      }
      bar.classList.toggle("hidden");
    });
    reader.addEventListener("touchstart", function (ev) {
      if (ev.touches.length === 1) { tx = ev.touches[0].clientX; ty = ev.touches[0].clientY; } else tx = null;
    }, { passive: true });
    reader.addEventListener("touchend", function (ev) {
      if (!paged || tx === null || !ev.changedTouches.length) return;
      var dx = ev.changedTouches[0].clientX - tx, dy = ev.changedTouches[0].clientY - ty;
      tx = null;
      if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy)) { lastSwipe = Date.now(); nextPage(dx < 0 ? 1 : -1); }
    }, { passive: true });
    document.addEventListener("keydown", function (ev) {
      if (!paged || sheetsOpen() || ev.altKey || ev.ctrlKey || ev.metaKey) return;
      if (ev.key === "ArrowRight" || ev.key === "PageDown") { ev.preventDefault(); nextPage(1); }
      else if (ev.key === "ArrowLeft" || ev.key === "PageUp") { ev.preventDefault(); nextPage(-1); }
    });

    // recitations ----------------------------------------------------------------------------------
    function todayCount() {
      var k = dayKey(new Date()), n = 0;
      entries.forEach(function (e) { if (dayKey(new Date(e.at)) === k) n++; });
      return n;
    }
    function refreshCounter() {
      $("btn-count").textContent = "Đã tụng " + total + " biến · hôm nay " + todayCount();
      $("btn-undo").disabled = total === 0;
    }
    function buildHistory() {
      var box = $("history");
      box.textContent = "";
      var counts = {}, order = [], today = new Date(), i;
      entries.forEach(function (e) { var k = dayKey(new Date(e.at)); counts[k] = (counts[k] || 0) + 1; });
      for (i = 0; i < 30; i++) {
        var d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i), k2 = dayKey(d);
        if (counts[k2]) order.push([d, counts[k2]]);
      }
      if (!order.length) box.appendChild(el("p", "muted small", "Chưa có biến nào trong 30 ngày gần nhất."));
      order.forEach(function (o) {
        var row = el("div", "hist-row");
        row.appendChild(el("span", null, o[0].toLocaleDateString("vi-VN")));
        row.appendChild(el("strong", null, o[1] + " biến"));
        box.appendChild(row);
      });
      $("undo-msg").textContent = total > entries.length ? "Tổng " + total + " biến (lịch sử chỉ hiện các biến gần nhất)." : "";
      $("btn-undo").disabled = total === 0;
    }
    function reloadRecitations() {
      return api("GET", "/api/sutras/" + encodeURIComponent(slug)).then(function (d) {
        entries = d.recitations.entries; total = d.recitations.total; refreshCounter(); buildHistory();
      });
    }
    $("btn-done").addEventListener("click", function () {
      var b = $("btn-done");
      b.disabled = true;
      api("POST", "/api/sutras/" + encodeURIComponent(slug) + "/recitations").then(function (r) {
        entries.push(r.entry); total = r.total; refreshCounter();
        $("done-msg").textContent = "Đã ghi biến thứ " + total + ".";
      }).catch(function (e) { $("done-msg").textContent = "Không ghi được: " + e.message; })
        .then(function () { b.disabled = false; });
    });
    $("btn-undo").addEventListener("click", function () {
      var b = $("btn-undo");
      b.disabled = true;
      api("DELETE", "/api/sutras/" + encodeURIComponent(slug) + "/recitations/last").then(function () {
        return reloadRecitations();
      }).then(function () { $("undo-msg").textContent = "Đã hoàn tác."; $("done-msg").textContent = ""; })
        .catch(function (e) {
          $("undo-msg").textContent = e.message;
          return e.status === 409 ? reloadRecitations() : null;
        });
    });

    // keep screen awake (S8) -----------------------------------------------------------------------
    var sentinel = null, video = $("awake"), usingVideo = false;
    function startAwake() {
      if (!settings.awake) return;
      if (navigator.wakeLock && typeof navigator.wakeLock.request === "function") {
        navigator.wakeLock.request("screen").then(function (s) {
          sentinel = s; usingVideo = false;
          s.addEventListener("release", function () { if (sentinel === s) sentinel = null; });
        }).catch(playVideo);
      } else playVideo();
    }
    function playVideo() {
      usingVideo = true;
      try { var p = video.play(); if (p && p.catch) p.catch(function () { /* needs a user tap */ }); } catch (e) { /* ignore */ }
    }
    function stopAwake() {
      usingVideo = false;
      if (sentinel) { try { sentinel.release(); } catch (e) { /* ignore */ } sentinel = null; }
      try { video.pause(); } catch (e) { /* ignore */ }
    }
    function pauseAwake() { try { video.pause(); } catch (e) { /* ignore */ } }
    function resumeAwake() {
      if (!settings.awake) return;
      if (usingVideo) playVideo(); else if (!sentinel) startAwake();
    }
    // video playback must start inside a user gesture: arm on the first click / tap / key
    function onFirstGesture() {
      ["click", "touchend", "keydown"].forEach(function (t) { document.removeEventListener(t, onFirstGesture, true); });
      startAwake();
    }
    ["click", "touchend", "keydown"].forEach(function (t) { document.addEventListener(t, onFirstGesture, true); });

    // boot -----------------------------------------------------------------------------------------
    applySettings();
    api("GET", "/api/sutras/" + encodeURIComponent(slug)).then(function (d) {
      data = d; entries = d.recitations.entries; total = d.recitations.total;
      $("r-msg").hidden = true;
      render();
      if (paged) layoutPaged();
      refreshCounter();
      $("btn-done").hidden = false;
      restore();
      updateCurrent();
    }).catch(function (e) { if (e.message !== "401") $("r-msg").textContent = "Không tải được kinh: " + e.message; });
  }

  // --- editor (SR1.2) ------------------------------------------------------------------------------

  function initEdit() {
    var m = /^\/sutras\/([^/]+)\/edit\/?$/.exec(location.pathname);
    var slug = m ? decodeURIComponent(m[1]) : null;       // null = new sutra
    var area = $("ed-text"), saveBtn = $("ed-save"), msg = $("ed-msg");
    var baseSha = null, dirty = false, seq = 0, timer = null, valid = false, saving = false;

    function setMsg(text) { msg.textContent = text || ""; }
    function updateButtons() { saveBtn.disabled = saving || !area.value.trim() || (slug !== null && baseSha === null); }

    // jump to a line: select it, and scroll the textarea so it is visible (a hidden mirror measures wrapped lines)
    function gotoLine(n) {
      var lines = area.value.split("\n"), start = 0, i;
      if (n < 1) n = 1;
      if (n > lines.length) n = lines.length;
      for (i = 0; i < n - 1; i++) start += lines[i].length + 1;
      var end = start + lines[n - 1].length;
      var cs = window.getComputedStyle(area), mirror = el("div", "ed-mirror");
      ["fontFamily", "fontSize", "lineHeight", "letterSpacing", "paddingLeft", "paddingRight", "borderLeftWidth", "borderRightWidth"]
        .forEach(function (k) { mirror.style[k] = cs[k]; });
      mirror.style.width = area.clientWidth + "px";
      mirror.style.boxSizing = "border-box";
      mirror.textContent = area.value.slice(0, start) + "​";
      document.body.appendChild(mirror);
      var y = mirror.scrollHeight;
      document.body.removeChild(mirror);
      area.focus();
      area.setSelectionRange(start, end);
      area.scrollTop = Math.max(0, y - area.clientHeight / 3);
    }

    function showErrors(list) {
      var ul = $("ed-errors");
      ul.textContent = "";
      list.forEach(function (er) {
        var li = el("li"), b = el("button", null, (er.line ? "Dòng " + er.line + ": " : "") + er.message);
        b.type = "button";
        if (er.line) b.addEventListener("click", function () { gotoLine(er.line); });
        li.appendChild(b);
        ul.appendChild(li);
      });
    }

    function renderPreview(doc) {
      var box = $("ed-preview"), shown = 0;
      box.textContent = "";
      box.appendChild(el("h4", null, doc.title));
      doc.intro.forEach(function (t) { box.appendChild(el("p", "muted small", t)); });
      var count = 0;
      doc.groups.forEach(function (g) { count += g.sections.length; });
      box.appendChild(el("p", "small muted", "Mục lục — " + count + " mục"));
      doc.groups.forEach(function (g) {
        if (g.title) box.appendChild(el("div", "ed-group", g.title));
        var ol = el("ol");
        g.sections.forEach(function (s) { ol.appendChild(el("li", null, s.title)); });
        box.appendChild(ol);
      });
      var sample = el("div", "ed-sample");
      doc.groups.forEach(function (g) {
        g.sections.forEach(function (s) {
          s.paragraphs.forEach(function (p) {
            if (shown >= 3) return;
            shown++;
            var pe = el("p");
            p.forEach(function (ln, i) { if (i) pe.appendChild(document.createElement("br")); pe.appendChild(document.createTextNode(ln.text)); });
            sample.appendChild(pe);
          });
        });
      });
      if (shown) { box.appendChild(el("p", "small muted", "Vài đoạn đầu")); box.appendChild(sample); }
    }

    function preview() {
      var mine = ++seq, text = area.value;
      if (!text.trim()) {
        valid = false; showErrors([]); setMsg("");
        $("ed-preview").textContent = ""; $("ed-preview").appendChild(el("p", "muted small", "Chưa có văn bản."));
        updateButtons();
        return Promise.resolve();
      }
      return api("POST", "/api/sutras?dry_run=1", { text: text }).then(function (doc) {
        if (mine !== seq) return;
        valid = true; showErrors([]); renderPreview(doc); setMsg("Văn bản hợp lệ."); updateButtons();
      }).catch(function (e) {
        if (mine !== seq || e.message === "401") return;
        valid = false;
        if (e.status === 400 && e.body && e.body.errors) { showErrors(e.body.errors); setMsg(e.body.errors.length + " lỗi — bấm vào lỗi để tới dòng đó."); }
        else { showErrors([]); setMsg(e.message); }
        updateButtons();
      });
    }

    area.addEventListener("input", function () {
      dirty = true; updateButtons();
      clearTimeout(timer);
      timer = setTimeout(preview, 600);
    });

    $("ed-file").addEventListener("change", function () {
      var f = this.files && this.files[0], input = this;
      if (!f) return;
      if (area.value.trim() && !window.confirm("Thay văn bản đang soạn bằng nội dung file này?")) { input.value = ""; return; }
      var isPdf = /\.pdf$/i.test(f.name);
      $("ed-file-msg").textContent = "Đang đọc " + f.name + (isPdf ? " (PDF có thể mất vài chục giây)…" : "…");
      api("POST", "/api/sutras/import?name=" + encodeURIComponent(f.name), f).then(function (r) {
        area.value = r.text; dirty = true;
        $("ed-file-msg").textContent = f.name + (isPdf ? " — chữ trích từ PDF cần soát lại (mục, ngắt dòng, chú thích) trước khi lưu."
                                                       : " — đã chuyển sang văn bản kinh, hãy soát lại trước khi lưu.");
        var ul = $("ed-warn");
        ul.textContent = "";
        r.warnings.forEach(function (w) { ul.appendChild(el("li", null, w)); });
        updateButtons();
        return preview();
      }).catch(function (e) { if (e.message !== "401") $("ed-file-msg").textContent = "Không đọc được file: " + e.message; })
        .then(function () { input.value = ""; });
    });

    saveBtn.addEventListener("click", function () {
      clearTimeout(timer);
      saving = true; updateButtons(); setMsg("Đang lưu…");
      var req = slug === null ? api("POST", "/api/sutras", { text: area.value })
                              : api("PUT", "/api/sutras/" + encodeURIComponent(slug), { text: area.value, sha256: baseSha });
      req.then(function (r) {
        dirty = false;
        location.href = "/sutras/" + encodeURIComponent(r.slug || slug);
      }).catch(function (e) {
        saving = false; updateButtons();
        if (e.message === "401") return;
        if (e.status === 400 && e.body && e.body.errors) { valid = false; showErrors(e.body.errors); setMsg("Chưa lưu: " + e.body.errors.length + " lỗi."); }
        else setMsg(e.status === 409 ? "Bộ kinh đã được sửa ở nơi khác — mở lại trang để tải bản mới (chữ đang soạn sẽ mất, hãy sao chép trước)." : "Không lưu được: " + e.message);
      });
    });

    window.addEventListener("beforeunload", function (ev) { if (dirty && !saving) { ev.preventDefault(); ev.returnValue = ""; } });

    if (slug === null) { updateButtons(); return; }
    $("ed-heading").textContent = "Sửa bộ kinh";
    $("ed-load").hidden = false; $("ed-load").textContent = "Đang tải…";
    $("ed-form").hidden = true;
    api("GET", "/api/sutras/" + encodeURIComponent(slug) + "/text").then(function (t) {
      area.value = t.text; baseSha = t.sha256;
      $("ed-load").hidden = true; $("ed-form").hidden = false;
      updateButtons();
      return preview();
    }).catch(function (e) { if (e.message !== "401") $("ed-load").textContent = "Không tải được văn bản: " + e.message; });
  }

  var page = document.body.getAttribute("data-page");
  if (page === "library") initLibrary(); else if (page === "reader") initReader(); else if (page === "edit") initEdit();
})();
