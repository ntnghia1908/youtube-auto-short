# Task: THUMB2-codex-compilation-thumbs — Thumbnail video ghép dạng khai thị (bìa KT + chân dung); bỏ trang Đóng gói, gộp vào thẻ video

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-28: "trang đống gói hiện rất phức tạp khó sài … thiết kế lại trang này sao cho dễ sài nhất có thể. Hoặc bỏ luôn nếu không cần thiết" → chọn "Bỏ, gộp vào thẻ video"; 2026-10-29 amendment (D-THUMB2-7 … 9): chọn "Chỉ dạng KT", "Theo tập của đoạn đầu", "TUYỂN TẬP KHAI THỊ"
- Parallel group: —
- Owned paths: `src/auto_short/packaging/compilation_thumbs.py` (mới), `src/auto_short/packaging/khaithi_thumbs.py` (chỉ tham số hóa nhãn / dòng tên kinh cho `layout` / `draw` / `cache_key`; thumbnail KT clip giữ byte-identical), `src/auto_short/packaging/record.py`, `src/auto_short/packaging/thumbnail.py` (gỡ phần theme A/B/C), phần VIS1 / AUD1 / duyệt bản đăng trong `src/auto_short/packaging/` (`visual.py`, `music.py`, `variant.py`, `assets.py` khi chỉ phục vụ trang Đóng gói), `src/auto_short/web/compilations.py`, `src/auto_short/web/packaging.py`, `src/auto_short/web/app.py` / `src/auto_short/web/jobs.py` (gỡ route / kind job Đóng gói, thêm kind job dựng thumbnail video ghép), `src/auto_short/web/static/favorites.{html,js}`, `src/auto_short/web/static/package.{html,js}` (xóa), `src/auto_short/web/static/theme_plan.js`, `docs/decisions/PKG-video-packaging-authorization.md` (chỉ ghi chú phần bị gỡ), `tests/test_compilation_thumbs.py` (mới), test hiện có của module trên khi khẳng định hành vi bị gỡ (`tests/test_packaging_thumbnail.py`, `tests/test_web_packaging.py`, `tests/test_web_compilation.py`, test VIS1 / AUD1 / PKG3 / PKG3.1), contract này
- Dependencies: THUMB1 (#182, đã merge: bìa KT `kt_vertical` / `kt_landscape`, chân dung `portraits.json`, `khaithi_thumbs.layout` / `draw`); CP8.33 (video ghép yêu thích); TC3 / PKG3 (tuyển tập chủ đề + Đóng gói)
- Base commit / branch: `origin/main` `720dc10` / `feature/thumb2-compilation-thumbs`
- Human Lead approval: APPROVED 2026-10-28; amendment APPROVED 2026-10-29 (D-THUMB2-7 … 9)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi sản phẩm đóng gói PKG (quyết định PKG: gỡ trang Đóng gói, VIS1, AUD1, thumbnail A/B/C tuyển tập) và thêm route + job web có auth.

## Bối cảnh / quyết định

- D-THUMB2-1: áp dụng cho cả hai loại video ghép: (a) video ghép yêu thích CP8.33 (`_compilations/<pid>/<cid>.mp4`, 9:16, hiện chưa có thumbnail; có thể trộn Short và khai thị); (b) tuyển tập chủ đề TC3 (`<pid>/theme/<plan_id>-r<rev>.mp4`, 16:9, đang có PKG3 A/B/C).
- D-THUMB2-4 (HUMAN LEAD 2026-10-28: "Bỏ luôn A/B/C của khai thị ghép làm sao cho phần thumail đơn giản dễ sài nhất cho end user"): gỡ PKG3 A/B/C + preset PKG3.1 của tuyển tập chủ đề (UI, dựng, file). Không chọn kiểu, không chỉnh chữ / ảnh / thanh trượt. PKG2 A/B/C của thumbnail **tập** (backend, intro bản dọc VERT2 khi bộ chưa có ảnh bìa) giữ nguyên.
- D-THUMB2-5 (HUMAN LEAD 2026-10-28, chọn "Bỏ, gộp vào thẻ video"): **bỏ trang Đóng gói** (`/playlists/{pid}/theme-plans/{plan_id}/package`). Mỗi video ghép (cả (a) và (b)) trên trang Yêu thích là một thẻ với: Xem · Tải video · Copy tiêu đề · Copy mô tả · khối thumbnail. Bỏ bước "Duyệt bản đăng", hình ambient (VIS1) và nhạc nền (AUD1) khỏi UI + API; video đã dựng có nhạc / hình trên đĩa: để nguyên, không xóa. Tiêu đề / mô tả tải về: lấy từ sidecar render hiện có (không cần duyệt).
- D-THUMB2-6 (HUMAN LEAD 2026-10-29: "với video ghép là ghép từ nhiều tập nên không có số tập trong thumbnail với dạng này"): dòng cuối chỉ có **tên bộ kinh**, **không** có "· Tập N".
- D-THUMB2-7 (HUMAN LEAD 2026-10-29, chọn "Chỉ dạng KT"): thumbnail video ghép = **dạng khai thị THUMB1**: bìa KT đã cài của bộ (`kt_vertical` / `kt_landscape`) + chân dung tách nền + toàn bộ chữ do code viết (cùng `layout` / font / vị trí chân dung / lật `facing` của KT clip). **Không gọi Codex cho từng video**; bỏ "2 mẫu / Gợi ý thêm / chọn / vẽ khổ thứ hai" của bản contract 2026-10-28 (D-THUMB2-2, D-THUMB2-3 cũ bị thay). Dựng luôn **2 khổ** (dọc 1080×1920, ngang 1280×720 `EPISODE_SIZES`) cho mỗi video ghép, bất kể khổ video.
- D-THUMB2-8 (HUMAN LEAD 2026-10-29, chọn "Theo tập của đoạn đầu"): chân dung = `choose_portrait(portraits, N)` với N = số tập của **đoạn đầu tiên** trong video ghép ((a) thứ tự đoạn trong `<cid>.json`; (b) `approved["clips"][0]`), cùng quy tắc xoay vòng 20 tập của KT clip; ổn định khi dựng lại. Không có chân dung → dựng không chân dung (như KT clip).
- D-THUMB2-9 (HUMAN LEAD 2026-10-29): nhãn nhỏ trên tiêu đề = **"TUYỂN TẬP KHAI THỊ"** (KT clip giữ "TRÍCH ĐOẠN KHAI THỊ").
- Chữ: tiêu đề = (a) `title` trong `<cid>.json`, (b) tiêu đề plan đã duyệt; chủ giảng + tên bộ kinh = `khaithi_thumbs.display_fields` của tập đoạn đầu (tên bộ kinh của playlist thắng). Không có ô sửa chữ trên thẻ: đổi tiêu đề ở chỗ hiện có → thumbnail "cũ" → dựng lại. Mốc `khaithi_from.json` (D-THUMB1-13) **không** áp dụng cho video ghép.

## Goal

Trên trang Yêu thích, mỗi thẻ video ghép (yêu thích và tuyển tập chủ đề) có nút "Dựng thumbnail" → 2 khổ dạng khai thị (bìa KT của bộ + chân dung + "TUYỂN TẬP KHAI THỊ" + tiêu đề + chủ giảng + tên bộ kinh) để xem và tải; trang Đóng gói bị bỏ.

## Scope

- In scope:
  - `khaithi_thumbs.py`: `layout` / `draw` / `cache_key` nhận nhãn + dòng tên kinh (mặc định giữ nguyên chuỗi hiện tại → KT clip byte-identical, cache key không đổi).
  - `packaging/compilation_thumbs.py`: đọc tiêu đề + tập đoạn đầu của (a) / (b), dựng 2 khổ qua `khaithi_thumbs.draw`, cache key gồm tiêu đề / bìa / chân dung / nhãn / tên kinh / chủ giảng (đổi bất kỳ → "cũ", không đổi → dùng lại), ghi file tạm rồi `os.replace`, sidecar `thumbs.json` (file, key, sha256) ở (a) `_compilations/<pid>/thumbs/<cid>/`, (b) thư mục package record `<plan_id>-r<rev>`; dọn file thumbnail cũ không còn tham chiếu trong đúng thư mục đó.
  - Bộ chưa có bìa KT → không dựng, lý do "Bộ kinh chưa có ảnh bìa khai thị" + link trang thumbnail bộ kinh (THUMB1). Tiêu đề rỗng / không vừa khung → lỗi có lý do, không ghi file.
  - Web: kind job nền dựng thumbnail video ghép (làn nhẹ như dựng thumbnail tập, chặn chạy trùng cùng video → 409); trên thẻ (a) và (b) trang Yêu thích: Xem · Tải video · Copy tiêu đề · Copy mô tả · khối thumbnail [Dựng thumbnail] / [Dựng lại] khi "cũ" → 2 ảnh + [Tải ảnh] từng khổ.
  - Revision mới của tuyển tập (r+1) → thư mục mới, chưa có thumbnail → nút "Dựng thumbnail" (bản r cũ để nguyên trên đĩa).
  - Gỡ trang Đóng gói và thành phần theo D-THUMB2-4 / D-THUMB2-5 (mục "Code bị thay / xóa").
- Out of scope: thumbnail tập / KT clip (THUMB1, chỉ tham số hóa không đổi byte); Codex vẽ ảnh cho video ghép; chọn chân dung trên thẻ; đưa thumbnail video ghép vào zip / PUB2; tự đăng YouTube; OCR kiểm dấu.

## Phải giữ nguyên

- Thumbnail KT clip + thumbnail tập THUMB1 (byte + cache key); PKG2 thumbnail tập; package record của tuyển tập (video, mô tả, tên tải) và route tải video; video ghép + mô tả CP8.33; file A/B/C, nhạc, hình ambient đã có trên đĩa (không xóa, không còn hiện).

## Code bị thay / xóa

- Trang Đóng gói: `package.{html,js}`, route `/playlists/{pid}/theme-plans/{plan_id}/package` + API `…/package/*`, VIS1 (hình ambient), AUD1 (nhạc nền), duyệt bản đăng → xóa cùng test; link "Đóng gói" trong `theme_plan.js` → thay bằng các nút trong thẻ. Quyết định `docs/decisions/PKG-video-packaging-authorization.md`: ghi chú phần bị gỡ (pointer tới contract này).
- PKG3 / PKG3.1: `thumbnail.theme_badge` / `theme_look` / `theme_text` / `check` / `build_theme` / `key` / `build` / `ready` và preset theme (nếu chỉ phục vụ tuyển tập), `record.STYLES` A/B/C của theme, job dựng thumbnail A/B/C trong `web/packaging.py`, route tải file `{A|B|C}-…jpg` → xóa; test tương ứng → xóa / thay. Helper nào còn được PKG2 / THUMB1 / VERT2 dùng thì giữ (kiểm bằng grep trước khi xóa).
- Phần Codex của bản contract 2026-10-28 (runner riêng, lượt vẽ, "Gợi ý thêm") không làm; không sửa `cover_suggest.py`.

## Acceptance Criteria

1. (D-THUMB2-7 / 9 / 6) Video ghép (a) và (b) có bìa KT: dựng đúng 2 file 1080×1920 + 1280×720, có "TUYỂN TẬP KHAI THỊ", tiêu đề ≤ 3 dòng, chủ giảng, tên bộ kinh **không** "Tập N", tất cả trong khung; sha256 + key ghi `thumbs.json`; dựng lại không đổi gì → dùng lại (không ghi file); đổi tiêu đề / bìa KT / chân dung → dựng lại, file cũ bị dọn.
2. (D-THUMB2-8) Chân dung theo tập của đoạn đầu (ví dụ đoạn đầu tập 23 → chân dung `((23 − 1) // 20) mod N`), lật theo `facing` ở khổ ngang như KT clip; không có chân dung → vẫn dựng.
3. Bộ không có bìa KT → không dựng, trả lý do; tiêu đề rỗng / không vừa → lỗi có lý do, không ghi file; KT clip + thumbnail tập THUMB1 byte-identical và cache key không đổi (test với khung thật VLT / Địa Tạng sẵn có).
4. Trang Yêu thích: mỗi thẻ (a) / (b) có Xem / Tải video / Copy tiêu đề / Copy mô tả / khối thumbnail (Dựng, Dựng lại khi cũ, Tải ảnh 2 khổ, lý do khi thiếu bìa KT); job trùng cùng video → 409; route + trang Đóng gói, A/B/C, preset, VIS1, AUD1, duyệt bản đăng bị gỡ (404); file cũ trên đĩa không bị xóa; PKG2 thumbnail tập không đổi byte.
5. Route yêu cầu đăng nhập, chặn id / tên file lạ (traversal, symlink).
6. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix như THUMB1.

- `<prefix> tests/test_compilation_thumbs.py tests/test_khaithi_thumbs.py` — AC 1–3 (không socket, Codex IMPLEMENTER chạy được).
- `<prefix> tests/test_web_compilation.py tests/test_web_packaging.py tests/test_packaging_thumbnail.py` — AC 4–5 (TestClient: ORCHESTRATOR).
- `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 6.
- Chạy thật (ORCHESTRATOR, 8080 ghim commit nhánh): 1 video ghép yêu thích + 1 tuyển tập chủ đề của bộ đã có bìa KT (VLT); gửi ảnh 2 khổ cho HUMAN LEAD xem + kiểm dấu.

## Manual test checklist (Tech Lead)

Không chạm database / security model; thêm route có auth + gỡ trang → manual test là gate trước merge.

- [ ] Thumbnail 2 khổ đúng dấu, tiêu đề đọc rõ ở cỡ nhỏ, chân dung không che chữ, không có "Tập N".
- [ ] Thẻ video ghép trên trang Yêu thích dễ dùng (Xem / Tải / Copy / thumbnail); không còn link Đóng gói.

## Result

- Mốc bàn giao: **READY phần IMPLEMENTER**. Status toàn task giữ `IN_PROGRESS`: AC6 full suite và manual/8080 còn thuộc ORCHESTRATOR, chưa tuyên bố PASS.
- Main changes:
  - Thêm `packaging/compilation_thumbs.py`: adapter CP8.33 / `theme_plan.approved_plan`, hai khổ KT, nhãn "TUYỂN TẬP KHAI THỊ", tên kinh không số tập, chân dung theo tập đầu; không áp `khaithi_from.json`.
  - `khaithi_thumbs.py` chỉ thêm tùy chọn `label` / `series_line`; `_fit` đã nhận hai chuỗi này. Mặc định giữ key và byte KT. `record.py` giữ đường dẫn revision; `thumbnail.py` giữ renderer PKG2 và bỏ theme A/B/C / palette / blur.
  - `web/packaging.py` thay service cũ bằng kind `compilation_thumbs`, lane render, POST trùng → 409, GET trạng thái / tải ảnh có auth chung. Route mới: `/api/playlists/{pid}/compilations/{ident}/thumbs[/{name}]` và `/api/playlists/{pid}/theme-plans/{ident}/thumbs[/{name}]`; id / tên file / symlink bị chặn.
  - `web/compilations.py`, `web/app.py`, `favorites.html/js`, `theme_plan.js`: thẻ Xem / Tải video / Copy tiêu đề / Copy mô tả và khối thumbnail chung; hiển thị cũ / lỗi / link cài bìa.
  - Xóa `package.html/js`, module `visual.py`, `music.py`, `variant.py`, route Đóng gói / A/B/C / VIS1 / AUD1 / duyệt bản đăng và test tương ứng. Giữ file legacy trên đĩa, metadata / route tải video TC3, renderer PKG2 / THUMB1 / VERT2 và asset CLI. Decision PKG có pointer tới contract này.
- Tests / AC → test:

  | AC | Bằng chứng chính |
  |---|---|
  | 1 | `test_two_real_shapes_text_and_cache`, `test_changed_inputs_stale_rebuild_and_scoped_cleanup`, `test_new_theme_revision_has_no_thumbnails_and_keeps_old` |
  | 2 | `test_first_segment_episode_23_portrait_and_landscape_flip`; ca AC1 không có chân dung vẫn dựng |
  | 3 | `test_missing_cover_or_bad_title_writes_nothing`, `test_default_kt_bytes_and_key_equal_pre_thumb2`, `test_thumb1_episode_bytes_and_key_unchanged` (khung thật VLT / Địa Tạng); baseline PKG2 `test_episode_filtergraph_identical_to_pre_refactor` giữ nguyên |
  | 4 | `test_video_card_routes_job_lane_duplicate_cache_and_downloads`, `test_missing_cover_new_revision_and_preserve_retired_files`, `test_both_video_cards_thumbnail_actions_and_polling` |
  | 5 | `test_retired_package_routes_are_404_and_new_routes_require_auth`, `test_symlinks_are_blocked`, `test_tampered_thumbnails_fail_closed` |
  | 6 | Framework-check + diff-check đã chạy; full suite / TestClient / manual còn chờ ORCHESTRATOR |

  Test thêm cho failure giữa hai lần encode / đầu vào đổi trong lúc dựng nhằm kiểm publication không làm hỏng sidecar, file ảnh và video cũ.
- Lệnh đã chạy (prefix `P` = `env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/thumb2/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest`):
  - `P -q -x --tb=short tests/test_compilation_thumbs.py tests/test_khaithi_thumbs.py tests/test_packaging_thumbnail.py tests/test_packaging_episode.py`: **231 PASS**, 220.67 s (trước khi thêm 4 ca khung tập VLT / Địa Tạng).
  - `P -q tests/test_compilation_thumbs.py tests/test_khaithi_thumbs.py tests/test_packaging_thumbnail.py tests/test_packaging_episode.py`: **235 PASS**, 224.33 s.
  - `P -q -x --tb=short tests/test_web_packaging.py`: **12 PASS**, 21.47 s; sau thêm Node smoke, chạy `tests/test_web_packaging.py tests/test_web_theme_plan.py -k 'not test_js_smoke_and_text_only and not test_js_favorites_tabs_and_manual_compilation and test_web_packaging'`: **15 PASS**, 94 deselected, 19.06 s. Không tạo TestClient.
  - `P -q -x --tb=short tests/test_web_theme_plan.py -k 'test_js_smoke_and_text_only or test_js_favorites_tabs_and_manual_compilation or test_favorites_tab_panel_ownership'`: **29 PASS**, 65 deselected, 2.85 s; không tạo TestClient.
  - Sau rà soát: chọn `default_kt_bytes or filtergraph_identical` trên hai file `test_compilation_thumbs.py` / `test_packaging_thumbnail.py`: **20 PASS**, 48 deselected, 1.48 s (gồm nhãn mặc định NFD không đổi key); `P -q -x --tb=short tests/test_compilation_thumbs.py -k two_real_shapes_text_and_cache`: **2 PASS**, 46 deselected, 4.35 s (dùng lại `episode.FILE_NAME`, mọi caller `reusable` truyền pattern rõ ràng).
  - `node --check src/auto_short/web/static/favorites.js`, `node --check src/auto_short/web/static/theme_plan.js`: PASS. `node scripts/framework-check.mjs`: PASS. `git diff --check`: PASS sau sửa hai dòng trắng cuối file.
- Diff + / − (app, test; gồm hai file mới chưa stage): app **+333 / −1984**, test **+486 / −1579**.
- Helper mới (đã tìm, lý do không tái dùng):
  - Đã tìm bằng `rg -n '^def |^class ' src/auto_short/packaging/{khaithi_thumbs,episode,thumbnail,record}.py` và `rg -n 'reusable|render_key|ThumbnailTarget|package|visual|music|variant' src tests scripts` trước khi thay / xóa.
  - `compilation_thumbs.Source`, `_source`, `favorite`, `theme`: chuẩn hóa hai nguồn + thư mục khác nhau. Adapter KT hiện tại chỉ đọc tiêu đề từng clip `.kt`, có đánh số clip / mốc bắt đầu không áp dụng cho video ghép.
  - `compilation_thumbs._inputs`, `read`, `valid_files`, `build`: kiểm hai khổ / sidecar theo identity video hoặc revision; tái dùng `kt.layout/draw/display_fields/portraits/choose_portrait/cache_key`, `episode.FILE_NAME/_no_symlinks/header/playlist`, `cover.current/directory`, `thumbnail.reusable/EPISODE_SIZES`, `record.directory`, `atomic_write_json`, `sha256_file`. Không gọi builder KT clip vì khác identity, sidecar và luật thiếu bìa / mốc bắt đầu.
  - Service `Packages.source/view/render/download`, `ThumbnailTarget`, `render_key` và route factory trong `web/packaging.py`: tái dùng pattern `episode_thumbs`, runner / `Step(RENDER)` / `job_view` / auth app; service cũ chỉ phục vụ A/B/C / variant / approval đã bỏ.
  - `Favorites.thumbnailBlock` (kèm `refresh`): một khối cho cả hai thẻ, dùng helper DOM/API/clipboard có sẵn; lưới thumbnail tập không có hành vi per-video / job này. Không thêm runner, dependency hoặc config mới.
- Review: IMPLEMENTER đã review diff-first, kiểm Owned paths và grep chỗ dùng trước / sau xóa. ORCHESTRATOR review độc lập và verification ngoài sandbox còn chờ; không gọi agent khác.
- Important findings / decisions: CP8.33 concat/auto hiện có thể lưu `title: null`; theo contract, trả lỗi tiêu đề rỗng và không dựng, không tự thay bằng tên file hay đổi logic đặt tiêu đề CP8.33.
- Known limitations / lệnh chưa chạy: `P -q tests/test_web_compilation.py` và các HTTP TestClient khác; `P -q -n auto` (full suite); chạy thật 8080 cho một video yêu thích + một tuyển tập VLT, gửi ảnh / kiểm dấu và manual checklist. Bỏ qua tại IMPLEMENTER theo chỉ định sandbox không có socket loopback; chưa PASS AC6 toàn bộ / manual gate.
- PR: không tạo (IMPLEMENTER); ORCHESTRATOR mở PR draft.
- ORCHESTRATOR (2026-10-29): review diff (inventory ⊆ Owned paths; không còn import `music` / `visual` / `variant`; route mới dưới auth middleware chung, id qua `CID_RE` / `PLAN_ID` + `_no_symlinks`; key KT mặc định không đổi). Codex 197.327 tokens, 1 vòng.
  - `P -q tests/test_web_compilation.py tests/test_web_packaging.py tests/test_compilation_thumbs.py tests/test_packaging_thumbnail.py -n 8` (TestClient): **102 passed**.
  - `P -q -n auto` (full suite): **3449 passed, 1 skipped**, 197.79 s.
  - Dữ liệu thật 8080: chưa có video ghép yêu thích nào đã dựng (chỉ `favorites.json`); tuyển tập chủ đề: VLT 4, Cảm Ứng Thiên 8 (CƯT chưa có bìa KT). Chạy thật: tuyển tập VLT; loại (a) chỉ có test tự động.
  - Còn: chạy thật 8080 (khi làn render rảnh) + manual checklist HUMAN LEAD.
