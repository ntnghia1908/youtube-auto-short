# Task: CP8.38 — Xóa tập nhưng giữ bài đăng chưa đăng

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session
- Implementer: codex — `codex exec` (gpt-6.1-sol, high); phần lõi tự chứa, spec rõ; test web / full suite do ORCHESTRATOR chạy
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-24 “Nên có cơ chế Xóa tập nhưng không xóa bài đăng”, chọn phương án “Cảnh báo + giữ bài” (hộp xác nhận báo còn N bài chưa đăng; xóa video / Short nhưng giữ bài — chữ + ảnh + link — xem, copy, tick “đã đăng” được)
- Parallel group: —
- Owned paths: `src/auto_short/post/kept.py` (mới), `src/auto_short/review/delete.py`, `src/auto_short/web/app.py` / router liên quan (route mới + `post_unticked` ở view tập), `src/auto_short/web/static/app.js`, `src/auto_short/web/static/index.html`, tests mới `tests/test_post_kept.py` + tests delete / web liên quan, `docs/decisions/CP8.3-web-contract.md` (§ Xóa tập), `docs/decisions/CP8.15-community-post-contract.md` (pointer P7), contract này
- Dependencies: none
- Base commit / branch: `34b2629` / `feature/cp8.38-delete-keep-posts`, worktree `.claude/worktrees/cp8.38-delete-keep-posts` (delegation HUMAN LEAD 2026-10-24)
- Human Lead approval: accepted (HUMAN LEAD 2026-10-24 “duyệt contract CP8.38”)
- Implementation authorized: YES

## Goal

Bấm “Xóa tập” (trang tập hoặc nút gợi ý tab Bộ nhớ) khi tập còn bài đăng cộng đồng chưa tick “Đã đăng bài” → hộp xác nhận nói rõ “còn N bài chưa đăng, sẽ được giữ lại”; sau khi xóa, các bài đó vẫn xem / copy / tick “Đã đăng bài” được trong mục **“Bài đăng của tập đã xóa”** trên trang chủ. Sự cố gốc: 2026-10-21 xóa tập 10 Thập Thiện Nghiệp Đạo (`W2d-xS4ttTw`) mất bài chưa đăng.

## Scope

- In scope:
  - `delete_episode` (mọi đường, cả tập `.kt`): trước `rmtree`, mọi entry `posts.json` có `posted_at = null` và `paragraphs` không rỗng → ghi `<workspace.dir>/_deleted/<id>.posts.json` (atomic).
  - Route: `GET /api/kept-posts` (danh sách), `POST /api/kept-posts/{id}/{clip}/posted` `{"value": bool}`, `DELETE /api/kept-posts/{id}` (bỏ mọi bài giữ lại của tập).
  - `GET /api/episodes/{id}` thêm `post_unticked` (cùng luật đếm với `web/storage.py` tab Bộ nhớ) để trang tập cảnh báo.
  - UI trang chủ: mục thu gọn “Bài đăng của tập đã xóa (n chưa đăng)”; mỗi bài: tên tập + Short, chữ bài, ảnh, link, nút “Copy” (copy `copy_text`, cùng helper copy của tab Bài đăng), ô “Đã đăng bài”; mỗi tập một nút “Bỏ khỏi danh sách” (confirm, nói rõ số bài chưa đăng sẽ mất).
  - Câu xác nhận của `deleteEpisode` (trang tập) và `runAction` (tab Bộ nhớ) đổi sang “Còn N bài đăng chưa đăng — sẽ được giữ trong mục ‘Bài đăng của tập đã xóa’ ở trang chủ.”
- Out of scope: sửa chữ / đổi ảnh bài giữ lại; đưa bài giữ lại về tập khi xử lý lại; tự dọn (archive) — không xóa `posts.json` nên không đổi; tính bài giữ lại vào “ảnh ít dùng nhất” (P5) / chia lại ảnh (P5d); khôi phục dữ liệu đã mất trước task.

## Authority / key decisions

- `docs/decisions/CP8.3-web-contract.md` § Xóa tập (bia mộ CP8.7, giữ yêu thích CP8.33 G11) — task sửa đổi mục này, ghi “Sửa đổi CP8.38”.
- `docs/decisions/CP8.15-community-post-contract.md` P4 (bố cục copy), P7 (`posts.json`), P8 (tick).
- D1 (HUMAN LEAD 2026-10-24): cảnh báo + giữ bài chưa đăng. Bài đã tick “Đã đăng bài” không giữ.
- D2 (ORCHESTRATOR, cục bộ): `<id>.posts.json` `{"schema_version": 1, "episode_id", "title" (metadata), "deleted_at", "posts": [{"clip_id", "short_title" (title trong render manifest hoặc null), "paragraphs", "image", "link", "copy_text", "posted_at"}]}`. `copy_text` chụp lúc xóa bằng chính helper của tab Bài đăng (`web/context.py`, P4 + hashtag lúc đó) → không cần workspace để copy. Ảnh nằm ở `[post] image_dir` dùng chung, không bị xóa; ảnh không còn → hiện không ảnh, vẫn copy được.
- D3: ghi file giữ bài lỗi → không xóa gì, lỗi như G11. Xóa lại cùng id khi file đã có (tập được xử lý lại rồi xóa lần nữa): giữ các bài cũ, thêm bài mới; bỏ bài mới có `paragraphs` y hệt một bài đã có cùng `clip_id`.
- D4: mục “Bài đăng của tập đã xóa” độc lập với bia mộ: hiện cả khi tập đã có workspace mới; “Xóa khỏi lịch sử” bia mộ không xóa bài giữ lại. File chỉ mất khi bấm “Bỏ khỏi danh sách”. Tick hết không tự xóa file.

## Implementation approach

- Module mới `post/kept.py`: build (từ workspace + render manifest + context helper), merge, read / write / tick, validate schema (mẫu `review/tombstone.py` + `post/store.py`).
- `delete_episode`: gọi build + write ngay sau `write_tombstone`, trước `rmtree`.
- Route theo nhóm `/api/deleted` hiện có; tick / bỏ trong `post_lock`.
- UI theo mục “Đã xóa (n)” (`loadDeleted` trong `app.js`) và nút Copy của tab Bài đăng.

## Phải giữ nguyên

- Bia mộ CP8.7, giữ yêu thích G11, kiểm “không có job” + 409, kiểm đường dẫn trước `rmtree`.
- Tập không có `posts.json` / mọi bài đã đăng / `posts.json` hỏng → xóa như cũ, không tạo file (hỏng: log warning, xóa vẫn chạy — `posts.json` hỏng vốn không đọc được trên web).
- `GET /api/deleted` / `DELETE /api/deleted/{id}` không đổi.
- Tab Bài đăng, auto-archive, P5d chia lại ảnh không đổi hành vi.

## Code bị thay / xóa

- Câu `postWarn` “xóa cả tập sẽ mất bài đã soạn” trong `runAction` (`app.js`) — thay bằng câu mới.

## Acceptance Criteria

1. Xóa tập có 3 bài (2 chưa đăng, 1 đã đăng) → `_deleted/<id>.posts.json` có đúng 2 bài, đủ field D2, `copy_text` bằng `copy_text` tab Bài đăng trước khi xóa.
2. Tập không có bài chưa đăng, không có `posts.json`, hoặc `posts.json` hỏng → không tạo file; xóa vẫn thành công.
3. Ghi file giữ bài lỗi → `delete_episode` raise, workspace / output còn nguyên.
4. Xóa lần hai cùng id → merge theo D3.
5. `GET /api/kept-posts` liệt kê bài (mới xóa trước); tick / bỏ tick → `posted_at` đổi; clip / tập không có → 404; `value` không bool → 422; `DELETE` → file mất, 404 lần hai.
6. `GET /api/episodes/{id}` có `post_unticked` đúng; confirm trang tập và tab Bộ nhớ hiện câu mới khi N > 0, không hiện khi N = 0.
7. Trang chủ: mục “Bài đăng của tập đã xóa” hiện / ẩn đúng, Copy ra đúng `copy_text`, tick lưu được, trên điện thoại nút ≥ 40 px, không cuộn ngang.
8. Xóa tập `.kt` có bài chưa đăng → giữ như tập Short.

## Required verification

- `PYTHONPATH=src python -m pytest tests/test_post_kept.py -q` (IMPLEMENTER) — AC1–AC4, AC8.
- `PYTHONPATH=src python -m pytest tests -q -k "delete or deleted or kept or storage"` (ORCHESTRATOR, cần socket) — AC5, AC6 phần API.
- `PYTHONPATH=src python -m pytest -q` full suite (ORCHESTRATOR).
- `node --check src/auto_short/web/static/app.js` — cú pháp JS.
- Chạy thật trên bản sao `work/` (ORCHESTRATOR): xóa một tập copy có bài chưa đăng, xem file + API.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task không chạm database, security model; thêm route nội bộ web (cookie như mọi route) — không phải public API contract. Manual test sau automated verification là điểm danh.

- [x] Trang tập có bài chưa đăng → `post_unticked` đúng (nguồn câu “Xóa tập này” báo số bài sẽ giữ). *ORCHESTRATOR, API 8080.*
- [x] Sau khi xóa: `/api/kept-posts` có tập, đúng số bài, `copy_text` đúng P4, ảnh mở được. *ORCHESTRATOR, API 8080.*
- [x] Tick / bỏ tick lưu được; “Bỏ khỏi danh sách” xóa file (lần hai 404). *ORCHESTRATOR, API 8080.*
- [ ] Nhìn trên điện thoại: hộp xác nhận, mục trang chủ, Copy dán vào app, nút ≥ 40 px — HUMAN LEAD (không có trình duyệt headless trên VM).

ORCHESTRATOR 2026-10-24, 8080 @ `9033cb5`: tập thử `zzTestCP838` (bản sao dữ liệu tập 10, không video, 1/13 bài tick sẵn) → 12/12 bước PASS (post_unticked 12; xóa; 12 bài giữ; ảnh 200; tick / bỏ tick; 404 clip lạ; bia mộ còn; bỏ khỏi danh sách; 404 lần hai; dọn bia mộ; không còn dấu vết). 8080 phục vụ `index.html` / `app.js` mới.

## Result

- Main changes: `post/kept.py` mới (snapshot `_deleted/<id>.posts.json`: build / merge D3 / read / tick / remove); `review/delete.py` ghi snapshot sau bia mộ, trước `rmtree` (lỗi → không xóa); route xóa (`web/routes/episodes.py`) tính `copy_text` bằng `WebContext.post_entry_view` dưới `post_lock`, view tập thêm `post_unticked`; `web/routes/status.py` thêm `GET /api/kept-posts`, `POST /api/kept-posts/{id}/{clip}/posted[?index=n]`, `DELETE /api/kept-posts/{id}`; trang chủ mục “Bài đăng của tập đã xóa”; hai confirm dùng `keptPostsWarning`. CP8.3 § Xóa tập + pointer CP8.15 P7.
- Tests:

  | AC | Test |
  |---|---|
  | AC1 | `test_post_kept.py::test_delete_keeps_only_unticked_complete_snapshot`, web `test_kept_posts_delete_copy_tick_and_remove` |
  | AC2 | `test_delete_without_usable_unticked_posts`, web `test_episode_post_unticked_zero_and_delete_without_kept_file` |
  | AC3 | `test_failed_atomic_write_preserves_workspace_and_output`, web `test_delete_route_write_failure_keeps_files_and_undoes_favorites` |
  | AC4 | `test_second_delete_merges_versions_preserves_ticks_and_deduplicates` |
  | AC5 | web `test_kept_post_route_validation_sorting_and_version_ticks`, `test_kept_posts_delete_copy_tick_and_remove` |
  | AC6 | web hai test trên (đếm `post_unticked`); câu confirm: manual |
  | AC7 | `node --check` + manual điện thoại |
  | AC8 | tham số `.kt` của AC1 (lõi + web) |

  ORCHESTRATOR 2026-10-24: `tests/test_post_kept.py` + `tests/test_web_kept_posts_cp838.py` 28 passed; full suite `PYTHONPATH=src python -m pytest -q` **2245 passed, 1 skipped** (10 phút 20); `node --check app.js` PASS. Chạy thật trên bản sao `work/W2d-xS4ttTw` (13 bài chưa đăng, config thật): 13 bài giữ lại, `copy_text` đúng P4, workspace / output bị xóa, bia mộ có.
- Diff + / − (app, test): app +311 / −5, test +364 / −0.
- Helper mới (đã tìm, lý do không tái dùng): nhóm hàm `post/kept.py` (schema / vòng đời D2–D4 khác bia mộ và P7); `loadKeptPosts`, `keptPostsWarning` (JS); `tests/kept_post_helpers.py`. Tái dùng `tombstone_dir`, `atomic_write_json`, `read_posts`, `list_titles`, `compose_copy_text`, helper `WebContext`, `copyTitleButton`, route `/files/post-images`.
- Review: ORCHESTRATOR đọc diff backend + JS: không blocking. Một sửa test: `test_delete_blocked_by_queued_job_keeps_posts_in_workspace` gửi link với `EID` 12 ký tự (422, không phải YouTube id) → đổi sang xếp job thẳng vào runner đang tạm ngưng; vẫn kiểm 409 + bài còn trong workspace.
- Implementer: Codex `gpt-6.1-sol` high, 1 lượt, 159k tokens, 0 vòng sửa.
- Important findings / decisions: tick theo `index` khi cùng clip có nhiều phiên bản (merge chỉ append). Câu cảnh báo đếm như tab Bộ nhớ (clip còn rendered); snapshot giữ mọi bài chưa tick.
- Known limitations: bài giữ lại không tính vào “ảnh ít dùng nhất” / chia lại ảnh; không sửa chữ; xóa không qua web (CLI) dùng hashtag mặc định config.
- PR: #128 (draft)
