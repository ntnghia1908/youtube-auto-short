# Task: CLEAN-P2P3 — Gộp helper trùng + xóa code chết

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — refactor cơ học, spec rõ từng file, effort `medium`; Sonnet subagent `implementer` nếu quota Codex vượt ngưỡng
- Authorization mode: task
- Authorization source: `docs/audit/code-growth-report.md` §5.2 mục P2, P3; HUMAN LEAD chọn P2 + P3 ngày 2026-10-19
- Parallel group: —
- Owned paths: `src/auto_short/workspace.py`, `src/auto_short/youtube_url.py` (mới), `src/auto_short/web/{urls,jobs,playlists,episodes}.py`, `src/auto_short/post/{logic,stage,doc}.py`, `src/auto_short/review/{archive,publish,watched,tombstone,logic}.py`, `src/auto_short/titling/{added,stage}.py`, `src/auto_short/{analysis,selection,render}/stage.py`, `src/auto_short/enhance/state.py`, `src/auto_short/compilation/store.py`, `src/auto_short/selection/logic.py`, `src/auto_short/render/plan.py`, `src/auto_short/web/static/{app,favorites}.js`, `src/auto_short/web/static/favorites.html`, `tools/enhance_worker/worker.py`, caller gọi `_read_json` private chéo module (bổ sung khi review vòng 1, chỉ đổi lời gọi): `src/auto_short/enhance/service.py`, `src/auto_short/web/{app,storage}.py`, `src/auto_short/render/full.py`, `tests/test_review_cp9.py`, `tests/test_render_plan.py`, test mới cho helper `workspace` / `youtube_url` (trong file test sẵn có của module), `docs/ai/project-profile.md` (§3 dòng đầu), file này
- Dependencies: none
- Base commit / branch: `e709e23` (origin/main) / `chore/p2p3-helper-dedup`
- Human Lead approval: accepted 2026-10-19 (chat; đồng ý cả 2 quyết định cục bộ)
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Mỗi helper nhỏ (giờ UTC, đọc JSON, phân tích URL YouTube, `el` / `api` / `copyText` JS) chỉ còn một bản; code chết trong audit §2.2 bị xóa. Hành vi người dùng không đổi, trừ 2 điểm ghi ở "Quyết định cục bộ".

## Scope

- In scope:
  - **P2a `_now`.** Thay `_now()` ở `web/jobs.py`, `web/playlists.py`, `review/archive.py`, `titling/added.py`, `post/stage.py`, `post/doc.py` và `review/publish.utc_now` bằng `workspace.utc_now`. `review/watched.py` import `utc_now` từ `workspace`.
  - **P2b đọc JSON tolerant.** Thêm `workspace.read_json_dict(path) -> dict | None` (lỗi đọc / parse / không phải object → `None`). Thay `enhance/state._read_json`, `review/tombstone._read_json`, `web/episodes._read_json`, `compilation/store._read`.
  - **P2c đọc JSON strict của stage.** Thêm `workspace.read_stage_json(path, what, error)`: giữ nguyên message `cannot read {path}: {exc}; re-run 'auto-short {what}'` và class exception của từng stage. Thay `_read_json` ở `analysis/`, `selection/`, `titling/`, `render/stage.py`.
  - **P2d URL YouTube.** Module core mới `src/auto_short/youtube_url.py`: chuyển nguyên `UrlError`, `canonical_url`, `parse_youtube_url` và hằng (`_VIDEO_ID_RE`, host, `MAX_URL_LENGTH`) từ `web/urls.py`. `web/urls.py` import lại các tên này (caller / test hiện có không đổi). `post/logic.normalize_link` gọi `parse_youtube_url` rồi đổi sang `LinkError`; bỏ bản chép trong `post/logic.py`.
  - **P2e `favorites.js`.** `app.js` export thêm `el`, `api`, `copyText` trong object `AutoShort`. `favorites.html` nạp `app.js` trước `favorites.js`. `favorites.js` bỏ bản `el` / `api` / `legacyCopy` / `copyText`, lấy từ `AutoShort`; vẫn export `{ init, el, api, fmtDur, copyText }` cho `theme_plan.js`.
  - **P3 code chết.** Xóa `review/logic.added_ids`, `review/logic.without_added`, `render/plan.planned_video_seconds`, `web/jobs.JobRegistry.active_vertical`, `enhance/state.FACE_MODELS`, `review/tombstone.KEYS`, `selection/logic.TIME_KEYS`, `tools/enhance_worker/worker.utcnow_iso`. Test chỉ phục vụ chúng: bỏ phần `without_added` trong `test_review_cp9.py::test_cut_and_added_round_trip_byte_identical` (giữ phần cut + thứ tự `added`), bỏ dòng assert `planned_video_seconds` trong `test_render_plan.py`.
  - `project-profile.md` §3 dòng `src/auto_short/` ghi thêm `youtube_url.py`.
- Out of scope:
  - `enhance/state.now_iso(clock)` (nhận clock inject) và `sutra/store._now` / `_iso` (trả `datetime`; package `sutra/` không import Auto Short theo SR1).
  - Bản đọc JSON có message riêng: `review/shorts._read`, `post/source._read`, `review/titles._read`, `theme_render/*._read`, `theme_index._read`.
  - `ingest/source.youtube_video_id` (cố ý dễ dãi hơn: `/embed/`, `/live/`, `music.youtube.com`; CP2).
  - Đọc doc `entries` cũ `post/stage.py` ↔ `titling/added.py` (audit §2.1, không nằm trong P2 được chọn).
  - `el` / `api` riêng của `theme_index.js`, `sutra.js` (chữ ký khác).
  - P4 fixture test chung, P5 tách `web/app.py`.

## Authority / key decisions

- Audit: `docs/audit/code-growth-report.md` §2.1, §2.2, §5.2.
- Hướng import: core module không import `auto_short.web` (quy ước ở `titling/playlist.py`, `post/doc.py`) → parser URL đặt ở module core `youtube_url.py`, không đặt trong `web/urls.py`.
- Quyết định cục bộ S1 (HUMAN LEAD đồng ý 2026-10-19):
  1. Ô "link" của bài đăng: tập link được nhận và kết quả chuẩn hóa không đổi; **câu báo lỗi** đổi sang câu của form gửi URL (W3), ví dụ `chỉ nhận URL YouTube (youtube.com, youtu.be)`, `không nhận playlist — dán link của một video`.
  2. Trang Yêu thích nạp `app.js` nên **có thanh hàng đợi** ở đầu trang như các trang khác (`initQueueBar`).

## Implementation approach

- Helper mới đặt trong `workspace.py` cạnh `utc_now` / `atomic_write_json` (đã được 34 file dùng lại).
- Không có test nào monkeypatch `_now` / `_read_json` (đã grep `tests/`); thay trực tiếp, không cần shim.
- Mỗi chỗ thay xóa luôn import thừa (`datetime`, `timezone`, `json`, `re`, `parse_qs`, `urlsplit`) nếu không còn dùng.

## Phải giữ nguyên

- Format thời gian `%Y-%m-%dT%H:%M:%SZ` ở mọi artifact.
- Message + class exception của 4 stage khi đọc input lỗi.
- `parse_youtube_url` / `UrlError` / `canonical_url` / `MAX_URL_LENGTH` vẫn import được từ `auto_short.web.urls`.
- `normalize_link`: cùng tập input hợp lệ / không hợp lệ, cùng output `https://youtube.com/shorts/<id>`, rỗng → `None`.
- `Favorites.{el, api, fmtDur, copyText}` vẫn có cho `theme_plan.js`; hành vi trang Yêu thích + Ghép chủ đề không đổi (ngoài thanh hàng đợi).
- Không đổi API HTTP, schema artifact, config.

## Code bị thay / xóa

- 6 hàm `_now` + `review/publish.utc_now` → `workspace.utc_now`.
- 4 hàm đọc JSON tolerant → `workspace.read_json_dict`.
- 4 hàm `_read_json` của stage → `workspace.read_stage_json`.
- Bản chép parser URL trong `post/logic.py` (`_VIDEO_ID_RE`, `_WATCH_HOSTS`, `_SHORT_HOST`, `MAX_LINK_LENGTH`, thân `normalize_link`) → `youtube_url.parse_youtube_url`; phần single-video trong `web/urls.py` chuyển sang `youtube_url.py`.
- `favorites.js`: `el`, `api`, `legacyCopy`, `copyText` → `AutoShort`.
- 8 mục code chết P3 + phần test chỉ phục vụ chúng (xem Scope).
- Ước lượng: app − 130…170, + 35…50; test − 10, + ≤ 20.

## Acceptance Criteria

1. `grep -rnE "^\s*def (_now|utc_now)\(" src` chỉ còn `workspace.py` và `sutra/store.py`; `grep -rnE "def (_read_json|_read)\(" src/auto_short/{enhance/state,review/tombstone,web/episodes,compilation/store,analysis/stage,selection/stage,titling/stage,render/stage}.py` rỗng.
2. `workspace.read_json_dict` trả `None` cho file thiếu / JSON hỏng / không phải object, trả dict khi hợp lệ; `workspace.read_stage_json` raise đúng class truyền vào với message cũ.
3. `post/logic.py` không còn parser URL riêng; `normalize_link` qua toàn bộ case hiện có trong `test_post_backend.py`; `test_web_urls.py`, `test_playlist_cp87.py` qua không sửa.
4. `favorites.js` không còn định nghĩa `el` / `api` / `copyText`; `favorites.html` nạp `app.js` trước `favorites.js`; test web Yêu thích / Ghép chủ đề qua.
5. 8 mục P3 không còn trong repo (`grep -rnw` rỗng).
6. Full suite PASS; `-m slow` PASS hoặc SKIP do thiếu env (đã sửa `tools/enhance_worker/`).

## Required verification

- `python -m pytest -q -x --tb=short tests/test_workspace.py tests/test_web_urls.py tests/test_playlist_cp87.py tests/test_post_backend.py tests/test_review_cp9.py tests/test_render_plan.py` — AC2, AC3, AC5.
- `python -m pytest -q -n auto -k "compilation or theme_plan or favorites"` — AC4.
- `node --check src/auto_short/web/static/app.js src/auto_short/web/static/favorites.js` — AC4.
- Lệnh grep trong AC1, AC5.
- `python -m pytest -q -n auto` — AC6.
- `python -m pytest -q -n auto -m slow` — AC6.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract (route / schema giữ nguyên). Manual test là điểm danh sau automated verification.

- [ ] Trang Yêu thích của một bộ kinh: danh sách hiện, tick + "Ghép", "Copy" mô tả, thanh hàng đợi hiện khi có việc.
- [ ] Bài đăng: dán link sai → báo lỗi; link `youtu.be/…` → lưu thành `youtube.com/shorts/…`.

## Result

- Main changes: P2a–P2e + P3 theo Scope. Helper mới trong `workspace.py`: `read_json_dict`, `read_stage_json`. Module core mới `youtube_url.py` (parser chuyển nguyên văn từ `web/urls.py`, `web/urls` import lại). Review vòng 1: bỏ alias `_read_json` / `partial`; caller private chéo module (`enhance/service`, `web/{app,storage}`, `render/full`) gọi thẳng helper `workspace` (Owned paths bổ sung).
- Tests:

| AC | Test / lệnh |
|---|---|
| 1, 5 | grep trong AC: chỉ còn `workspace.utc_now`, `sutra/store._now`; reader và 8 tên P3 rỗng |
| 2 | `test_workspace.py::test_read_json_dict`, `test_read_stage_json_error` (4 class × 2), `test_read_stage_json_valid` |
| 3 | `test_post_backend.py` (P6 link), `test_web_urls.py`, `test_playlist_cp87.py` không sửa |
| 4 | `node --check`; `test_web_theme_plan.py::test_js_favorites_tabs_and_manual_compilation` (harness Node nạp `app.js` trước `favorites.js` như trang) |
| 6 | `python -m pytest -q -n auto` → 2180 passed, 1 skipped; `-m slow` → 5 passed, 12 skipped (thiếu env `enhance-bench`) |

  Chạy với `PYTHONPATH=<worktree>/src` (editable install trỏ checkout chính). `node scripts/framework-check.mjs` PASS.
- Diff + / − (app, test): app +168 / −333 (gồm `youtube_url.py` 60 dòng mới); test +43 / −8.
- Helper mới (đã tìm, lý do không tái dùng): `read_json_dict`, `read_stage_json` — `workspace.py` chưa có reader; chuyển thân bản cũ, không thêm policy đọc mới.
- Review: ORCHESTRATOR vòng 1 (alias / import order). Harness JS `test_web_theme_plan.py` do ORCHESTRATOR sửa (test nạp riêng `favorites.js`, thiếu `AutoShort`).
- Implementer: Codex `gpt-6.1-sol` effort medium, 2 lượt, 80k + 101k tokens, 0 blocking.
- Important findings / decisions: 2 quyết định cục bộ đã duyệt (câu lỗi link bài đăng theo W3; thanh hàng đợi trên trang Yêu thích).
- Known limitations: chưa manual test trên 8080.
- PR: chưa tạo (chờ HUMAN LEAD).
