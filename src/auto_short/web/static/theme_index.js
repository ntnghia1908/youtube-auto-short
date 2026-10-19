// TC-WEB1: read-only view of the TC1 theme index. All text goes through textContent (no HTML injection).
(function () {
  "use strict";
  var parts = location.pathname.split("/");
  var pid = decodeURIComponent(parts[parts.length - 2] || "");
  var ABSENT = "không có";
  var STATUS = {
    indexed: "Đã lập chỉ mục",
    eligible: "Đủ điều kiện (chưa có chỉ mục)",
    ineligible: "Không đủ điều kiện",
    ai_error: "Chưa có chỉ mục hợp lệ"
  };

  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  function val(v) {
    if (v === undefined || v === null || v === "") return ABSENT;
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }
  function row(dl, k, v) { dl.appendChild(el("dt", k)); dl.appendChild(el("dd", val(v))); }
  function det(title, build) {
    var d = el("details");
    d.appendChild(el("summary", title));
    d.appendChild(build());
    return d;
  }
  function list(items, fmt) {
    if (!items || !items.length) return el("p", ABSENT, "muted small");
    var ul = el("ul", null, "small");
    items.forEach(function (x) { ul.appendChild(el("li", fmt(x))); });
    return ul;
  }
  function ref(r) {
    if (!r) return ABSENT;
    var ids = r.evidence_ids;
    var label = ids && ids.length > 1 ? ids[0] + "–" + ids[ids.length - 1] : r.evidence_id;
    return label + ": " + r.text;
  }

  function render(r) {
    var li = el("li");
    var id = r.identity || {};
    var fav = r.favorite || {};
    li.appendChild(el("strong", "#" + r.favorite_position + " · " + val(id.episode_id || fav.episode_id) + " / " +
      val(id.clip || fav.clip)));
    li.appendChild(el("span", " — " + (STATUS[r.status] || r.status) + (r.cached ? " (cache hợp lệ)" : ""), "small"));
    var dl = el("dl", null, "small");
    row(dl, "Trạng thái TC1", r.status);
    row(dl, "Lý do", r.reason);
    row(dl, "Thời lượng (giây)", r.duration);
    row(dl, "Final segments", r.final_segments);
    row(dl, "Chỉ mục lúc", r.indexed_at);
    row(dl, "Cache", r.cached === undefined ? null : (r.cached ? "hit (đã kiểm lại bằng TC1)" : "không"));
    row(dl, "Input fingerprint", r.input_fingerprint);
    row(dl, "Bất định (record)", (r.uncertainty || []).length ? r.uncertainty.join("; ") : null);
    li.appendChild(dl);
    if (r.status === "ai_error") {
      li.appendChild(el("p", "Chưa có index hợp lệ; preview không sinh metadata.", "small"));
    }
    var m = r.metadata;
    if (m) {
      li.appendChild(det("Metadata (giả lập, extractive)", function () {
        var d = el("dl", null, "small");
        row(d, "Chủ đề", m.topic);
        row(d, "Chủ đề phụ", m.subtopic);
        row(d, "Tóm tắt (trích)", ref(m.synopsis));
        d.appendChild(el("dt", "Ý chính (trích)"));
        var dd = el("dd"); dd.appendChild(list(m.key_messages, ref)); d.appendChild(dd);
        row(d, "Bất định (metadata)", (m.uncertainty || []).length ? m.uncertainty.join("; ") : null);
        return d;
      }));
    }
    if (r.evidence) {
      li.appendChild(det("Evidence (" + r.evidence.length + ")", function () {
        return list(r.evidence, function (e) {
          return e.evidence_id + " [" + e.start + "–" + e.end + "] " + e.text;
        });
      }));
    }
    if (r.provenance || r.source_reference || r.inputs) {
      li.appendChild(det("Provenance / nguồn", function () {
        var d = el("dl", null, "small");
        var p = r.provenance || {};
        ["model", "options", "think", "prompt_version", "prompt_sha256", "method"].forEach(function (k) { row(d, k, p[k]); });
        var s = r.source_reference || {};
        row(d, "Nguồn (tham chiếu)", s.reference);
        row(d, "Nguồn sha256", s.sha256);
        row(d, "Nguồn gốc sha256", s.original_sha256);
        var i = r.inputs || {};
        row(d, "Render sha256", i.render_sha256);
        row(d, "Render manifest", i.render_manifest);
        row(d, "Playlist hash", i.playlist);
        return d;
      }));
    }
    li.appendChild(det("Favorite gốc", function () { return el("pre", JSON.stringify(r.favorite, null, 1), "small"); }));
    return li;
  }

  function msg(text) {
    var m = document.getElementById("ti-msg");
    m.hidden = !text;
    m.textContent = text || "";
  }

  // A re-check first drops the previous snapshot, so a failed refresh never leaves old rows looking current.
  function reset() {
    ["ti-list", "ti-counts", "ti-checked", "ti-mode"].forEach(function (id) { document.getElementById(id).textContent = ""; });
    document.getElementById("ti-total").textContent = "0";
  }

  function load() {
    var btn = document.getElementById("ti-refresh");
    btn.disabled = true;
    reset();
    msg("Đang kiểm tra lại…");
    fetch("/api/playlists/" + encodeURIComponent(pid) + "/theme-index", { credentials: "same-origin", cache: "no-store" })
      .then(function (res) {
        if (res.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return null; }
        return res.json().then(function (body) { return { ok: res.ok, status: res.status, body: body }; });
      })
      .then(function (out) {
        if (!out) return;
        var ul = document.getElementById("ti-list");
        if (!out.ok) {
          msg("Lỗi " + out.status + ": " + ((out.body && out.body.detail) || ""));
          return;
        }
        var d = out.body;
        document.getElementById("ti-mode").textContent = "data_mode: " + d.data_mode + " · generation_enabled: " + d.generation_enabled;
        document.getElementById("ti-checked").textContent = "Kiểm tra lúc " + d.checked_at;
        document.getElementById("ti-total").textContent = String(d.total);
        document.getElementById("ti-counts").textContent = Object.keys(d.counts).map(function (k) { return k + ": " + d.counts[k]; }).join(" · ");
        if (!d.records.length) ul.appendChild(el("li", "Chưa có mục yêu thích nào (danh sách rỗng, không phải lỗi).", "muted"));
        d.records.forEach(function (r) { ul.appendChild(render(r)); });
        msg("");
      })
      .catch(function () { reset(); msg("Không tải được kết quả; không có dữ liệu hiện hành."); })
      .then(function () { btn.disabled = false; });
  }

  document.getElementById("ti-refresh").addEventListener("click", load);
  load();
})();
