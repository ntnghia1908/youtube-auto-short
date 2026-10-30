# Task: KTI2-short-compilation-intro — Short và video khai thị ghép có 3 giây thumbnail ở đầu

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-30: "Tôi muốn short cũng làm thubnail 3s giống giai thị. Cảm Ứng Thiên và thật sự nghiệp đạo bắt đầu lại từ tập 21 và Vô Lượng Thọ bắt đầu lại từ tập 31"; "Khai Thị ghép cũng tương tự và ưu tiên Khai Thị ghép của Vô Lượng Thọ và cảm ứng thiên trước"; G1–G3 bên dưới (chọn 2026-10-30)
- Parallel group: —
- Owned paths: `src/auto_short/render/stage.py`, `src/auto_short/render/intro.py`, `src/auto_short/packaging/khaithi_thumbs.py`, `src/auto_short/packaging/compilation_thumbs.py`, `src/auto_short/compilation/`, `src/auto_short/web/compilations.py`, `src/auto_short/theme_index/__init__.py`, `src/auto_short/theme_render/__init__.py`, `src/auto_short/store/shorts.py`, `src/auto_short/web/static/` (chỉ thông báo lỗi / trạng thái intro), test tương ứng + `tests/test_short_compilation_intro.py` (mới), contract này
- Dependencies: KTI1 (#187: `render/intro.py`, sidecar `intro` / `content_offset` / `content_sha256`, `enqueue_intro_rebuild`), THUMB1 / THUMB2 (#182, #184: `khaithi_thumbs.draw` có tham số nhãn, `compilation_thumbs`), SHO1b (Short trên kho → `(rN)`)
- Base commit / branch: `origin/main` `06f7f92` / `feature/kti2-short-compilation-intro`
- Human Lead approval: APPROVED 2026-10-30
- Implementation authorized: YES

S2 vì: đổi sản phẩm Short / video ghép đã đăng hoặc đã lên kho (`(rN)`), đợt dựng lại ≈ 1.028 Short + mọi video khai thị ghép của 3 bộ.

## Quyết định

- D-KTI2-1: Short dựng mới trong phạm vi = **3 s ảnh thumbnail dọc** của chính Short trước nội dung, im lặng, **hòa tan 1 s** sang khung đầu nội dung (y hệt KTI1 D-KTI1-1 / D-KTI1-6, cùng `render/intro.py`). Nội dung giữ nguyên packet (concat copy).
- D-KTI2-2 (phạm vi): file runtime mới `<asset_dir>/short_intro_from.json` (`schema_version 1`, `playlists {pid: tập đầu}`), tách khỏi `khaithi_from.json`. Giá trị chạy thật: Vô Lượng Thọ 31, Cảm Ứng Thiên 21, Thập Thiện Nghiệp Đạo 21. Tập trước mốc / bộ không có trong file: Short không đổi byte / key.
- D-KTI2-3 (G1 = "Chung bìa khai thị"; G2 = "TRÍCH ĐOẠN"): ảnh Short = dạng THUMB1 dọc: bìa `kt_vertical` của bộ + chân dung (`choose_portrait`, số tập) + nhãn **"TRÍCH ĐOẠN"** + tiêu đề Short + chủ giảng + tên bộ / tập. Thumbnail KT clip giữ byte + key ("TRÍCH ĐOẠN KHAI THỊ"). Bộ thiếu bìa KT → job dừng "Bộ kinh chưa có ảnh bìa khai thị" + link như D-KTI1-3.
- D-KTI2-4 (video khai thị ghép): video ghép yêu thích (CP8.33, 9:16) và tuyển tập chủ đề (TC3, 16:9) của bộ có trong `khaithi_from.json` mở đầu bằng **3 s thumbnail THUMB2 đúng khổ** (dọc / ngang) của chính video ghép + hòa tan 1 s vào khung đầu; các đoạn bên trong vẫn **bỏ** intro của từng clip (D-KTI1-4, nay cũng áp dụng cho Short có intro). Thumbnail chưa dựng → dựng lúc ghép; bìa KT thiếu → lỗi có lý do như THUMB2. Chapter trong mô tả tuyển tập: giữ `0:00`, các mốc sau cộng độ lệch intro. Plan đã duyệt không stale vì intro.
- D-KTI2-5 (G3 = "Dựng lại tất cả"): sau merge ORCHESTRATOR dựng lại mọi Short đã render trong phạm vi (kể cả đã đăng; tiêu đề / đoạn cắt giữ nguyên; bản mới lên kho `(rN)`) và mọi video khai thị ghép của 3 bộ. Thứ tự: (1) video ghép VLT + Cảm Ứng Thiên; (2) video ghép Thập Thiện; (3) Short VLT, Cảm Ứng Thiên, Thập Thiện (10 tập đầu mỗi bộ đánh dấu "Ưu tiên"). Đợt KTI1 còn chờ (nếu có) không bị đẩy lùi.
- D-KTI2-6 (HUMAN LEAD 2026-10-30: "Với short và khai thị của Kinh Địa Tạng nên lấy chân dung của hòa thượng giống như các bộ kinh khác"; chọn "Codex vẽ từ bìa tập", "Tất cả các tập", thumbnail tập "Giữ nguyên"): Kinh Địa Tạng vào phạm vi cả Short (KTI2) lẫn khai thị (KTI1) **từ tập 1** — mốc `1` trong `short_intro_from.json` / `khaithi_from.json` phải hợp lệ (hiện `start_episode` chỉ nhận > 1; `before_start` với mốc 1 = không tập nào trước mốc). Bìa KT Địa Tạng do Codex vẽ qua `suggest-kt` (THUMB1), HUMAN LEAD chọn mẫu rồi mới cài; chưa cài → D-KTI1-3 / D-KTI2-3 (dừng, báo thiếu bìa). Thumbnail tập Địa Tạng (PKG2 / intro HD / bản dọc) **không** đổi. Đợt dựng lại thêm 519 Short + 229 clip khai thị Địa Tạng, xếp sau 3 bộ của D-KTI2-5.
- Thumbnail đổi (sửa tiêu đề, bìa, chân dung) → key đổi → Short / video ghép không còn hiện hành, dựng lại như hiện nay.

## Goal

Short trong phạm vi (VLT ≥ 31, Cảm Ứng Thiên / Thập Thiện ≥ 21) và video khai thị ghép của 3 bộ mở đầu bằng 3 s thumbnail; nội dung và video ghép từ clip vẫn y như hiện tại.

## Scope

- In scope: phạm vi Short qua `short_intro_from.json`; dựng ảnh Short một clip lúc render (tái dùng `khaithi_thumbs.vertical_clip` / `draw` / `cache_key` với nhãn, thư mục / sidecar thumbs riêng cho Short, không đụng file KT); nhánh intro trong render Short (key gồm metadata intro, sidecar `intro` / `content_offset` / `content_sha256` như KTI1, đường thêm intro vào Short có sẵn không cần nguồn); mọi đường ghép bỏ intro của Short theo sidecar; intro đầu video ghép (a) và (b) + dời chapter; selector / hàm xếp dựng lại Short (mở rộng `enqueue_intro_rebuild` hoặc hàm song song) và video ghép, dùng được từ runner web đang chạy; web hiển thị lý do lỗi + link khi thiếu bìa.
- Out of scope: KT clip (KTI1, giữ nguyên), bản dọc / HD (VERT2 / HDI1), thumbnail tập PKG2, giao diện chọn kiểu thumbnail, tự đăng / thay video trên YouTube, bộ không có trong file cấu hình.

## Phải giữ nguyên

- Thumbnail + clip KT (byte / key); Short trước mốc / bộ ngoài phạm vi (byte / key); nội dung các đoạn trong video ghép (framemd5 như bản ghép hiện tại, sau 3 s intro đầu); plan TC3 đã duyệt không stale; thumbnail THUMB2 không đổi byte.

## Code bị thay / xóa

- Không xóa. Hook intro trong `stage.py` (hiện chỉ cho workspace `.kt`) mở rộng cho Short; selector KTI1 tái dùng / tham số hóa thay vì sao chép.

## Acceptance Criteria

1. Short trong phạm vi: 3 s đầu là ảnh "TRÍCH ĐOẠN" của đúng Short (so khung), hòa tan 1 s, im lặng, độ dài = nội dung + offset; sidecar đủ; render lại không đổi → cache; sửa tiêu đề → ảnh / key / clip đổi.
2. Short trước mốc / bộ ngoài phạm vi, KT clip: byte + key không đổi.
3. Bộ trong phạm vi thiếu bìa KT → job Short dừng với lý do + link, không ghi clip.
4. Short đã có (kể cả nguồn đã dọn / Short trên kho) được thêm intro không cần nguồn khi nội dung hiện hành xác minh được; lên kho thành `(rN)`.
5. Video ghép yêu thích + tuyển tập chủ đề của 3 bộ: 3 s đầu là thumbnail THUMB2 đúng khổ, sau đó nội dung giống bản ghép hiện tại (framemd5), không chứa intro của từng Short / KT; chapter dời đúng; plan đã duyệt không stale.
6. Hàm xếp dựng lại: chọn đúng Short / video ghép chưa hiện hành theo thứ tự D-KTI2-5, bỏ cái đã hiện hành, đánh dấu ưu tiên.
7. Mốc `1` (D-KTI2-6): mọi tập trong phạm vi (Short + khai thị); mốc không phải số nguyên ≥ 1 → không phạm vi như hiện nay.
8. Full suite PASS; `node scripts/framework-check.mjs`, `git diff --check` PASS.

## Required verification

- `timeout 290s env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short -n 2 tests/test_short_compilation_intro.py tests/test_khaithi_intro.py tests/test_khaithi_thumbs.py tests/test_compilation_thumbs.py` + test render / compilation / theme hiện có (AC 1–7, không socket).
- ORCHESTRATOR: TestClient AC3, full suite `-n auto`, framework-check, `git diff --check` (AC 8).
- Chạy thật (ORCHESTRATOR, 8080): 1 tập VLT ≥ 31 → mẫu 10 s đầu 1 Short + khung 1,5 s gửi HUMAN LEAD; ghép lại 1 video yêu thích VLT → mẫu 10 s đầu; rồi đợt D-KTI2-5.

## Manual test checklist (Tech Lead)

- [ ] 3 s đầu Short là đúng thumbnail "TRÍCH ĐOẠN" của Short, dấu đúng.
- [ ] Video ghép mở đầu bằng thumbnail video ghép, không có đoạn ảnh 3 s giữa các clip.

## Result

**READY phần IMPLEMENTER — 2026-10-30.** Task giữ `IN_PROGRESS`: AC8 full suite / TestClient và chạy thật / manual thuộc ORCHESTRATOR, chưa tuyên bố PASS. Đã nhận amendment D-KTI2-6 trong contract khi đang triển khai. Worktree `feature/kti2-short-compilation-intro`, HEAD giữ `98e88db`, merge-base `origin/main` là `06f7f92`. Không commit / push / PR, không gọi agent hay mạng thật.

### Kiến trúc và file đổi

- `render/stage.py`: mở hook KTI1 cho Short theo config riêng; `_intro_from_existing` kiểm hash config đúng loại workspace thay vì cố định KT. Giữ kiểm source/config/review/ranges/title/SHA trước khi dùng nội dung có sẵn, kể cả nguồn archived và Short released trên kho. Sidecar và render key tái dùng nguyên cơ chế KTI1 (`intro`, `content_offset`, `content_sha256`, `content_render_key`, fingerprint nội dung).
- `packaging/khaithi_thumbs.py`: tham số hóa `intro_context`, `titles`, `vertical_clip`, `read`, `enqueue_intro_rebuild` bằng `short`; `start_episode` / `before_start` nhận tên file mốc. Short đọc `titles.json` + review (manual/added/rejected) qua helper chung, không đòi `khaithi.json`; ảnh dùng cùng cover/portrait/layout nhưng nhãn `TRÍCH ĐOẠN`, thư mục `<output>/<id>/short_intro_thumbs/` và sidecar riêng. Mốc nguyên ≥ 1 hợp lệ cho cả hai file; bool, float, chuỗi, null, số ≤ 0 không mở phạm vi. Nhãn/key/byte KT mặc định giữ nguyên.
- `render/intro.py`: chỉ thêm tùy chọn kích thước cho `filters` / `prepend` để dùng cùng fade/silence/concat-copy cho video ngang. Mặc định VERT2/KTI1 không đổi. `compilation/assemble.py`: tùy chọn `intro_image`, thêm ảnh sau khi đã ghép nội dung không intro; trả offset thực và SHA file nội dung trước prepend. `compilation/meta.py`: chapter đầu giữ 0, các chapter sau cộng offset.
- `packaging/compilation_thumbs.py`: adapter favorite nhận `pending=True` để dựng THUMB2 trước khi video hoàn tất; `intro_image` dùng nguyên builder/sidecar THUMB2, `intro_current` kiểm ảnh hiện hành + SHA video (polling cho phép bỏ băm video dài). Builder THUMB2 không đổi byte.
- `web/compilations.py`: ghép favorite với thumbnail dọc, ghi metadata intro, kiểm current khi submit/view; lỗi thiếu bìa có lý do + URL, giữ file video cũ nếu thất bại trước khi công bố bản mới. `theme_render/__init__.py`: thumbnail ngang vào encode key, prepend một lần sau ghép, metadata/chapter/description theo offset; fingerprint plan giữ nguyên. `web/static/favorites.js`, `theme_plan.js`: link thiết kế bìa khi lỗi, cảnh báo intro tuyển tập cũ khi thumbnail đổi.
- Các consumer KTI1 trong `compilation/store.py`, `theme_index/__init__.py`, `store/shorts.py`, đường kept/borrow của `web/compilations.py` vốn đọc sidecar không phân biệt Short/KT: tái dùng trực tiếp, không nhân bản hay sửa để thêm điều kiện loại clip. TC1 vẫn chỉ index loại nội dung đã được TC1 duyệt; KTI2 không mở rộng loại plan.
- Test mới `tests/test_short_compilation_intro.py`; thêm 3 ca Node vào `tests/test_web_packaging.py`. Chuyển nguyên `ffmpeg`, `frame_hashes`, `assert_fade` từ `test_khaithi_intro.py` sang `tests/render_helpers.py` vì hai file cùng dùng; không đổi/bỏ assertion cũ. File tài liệu đổi: contract này; toàn bộ inventory nằm trong Owned paths.

### Helper mới và lý do

Đã tìm trước bằng `rg -n 'intro|def |khaithi'` trên render/stage, compilation/{assemble,store}, web/compilations, theme_render, theme_index, store/shorts; đọc toàn bộ `render/intro.py`, `khaithi_thumbs.py`, `compilation_thumbs.py` và tìm nguồn title/review hiện hành. Không thêm module ứng dụng, dependency, runner, route hay cơ chế upload mới.

- `_resolved_titles`: tách phần resolve title/review dùng chung từ `titles` KT; phần kiểm `khaithi.json` không áp dụng cho Short. `_clip_directory`: chọn cache riêng cho Short; không dùng thư mục thumbnail tập/KT để tránh đè sidecar.
- `compilation_thumbs.intro_image` / `intro_current`: adapter mỏng quanh `build` / `valid_files` / `render.intro.metadata`, vì THUMB2 cũ chỉ quản lý ảnh, chưa liên hệ ảnh với intro đã mux trong video.
- `Compilations.intro_current`: ghép config phạm vi với adapter trên; giữ đường không cấu hình như trước và tránh băm video dài ở mỗi lần polling.
- `compilation_thumbs.enqueue_intro_rebuild` (kèm hàm cục bộ `videos`): selector KTI1 chỉ xếp episode render, không xếp favorite/theme revision. Hàm mới dùng lại `Compilations.rebuild`, `ThemePlans.render`, `runner.submit/priority`, và selector episode KTI1 đã tham số hóa; không tạo cơ chế hàng đợi khác.
- Helper test mới `assert_picture` kiểm khung ảnh đầu cho Short và cả hai khổ video ghép; các helper media chung được chuyển nguyên như trên.

### Cách dùng sau merge (ORCHESTRATOR)

Trên runner web **đang chạy**, dùng các service hiện có, không tạo runner khác:

```python
from auto_short.packaging import compilation_thumbs, khaithi_thumbs

# Chỉ Short của một bộ / khoảng tập:
khaithi_thumbs.enqueue_intro_rebuild(
    config, app.state.runner, pid_vlt, 31, 500,
    short=True, prioritize_first_ten=True,
)
# Toàn đợt D-KTI2-5/6: bắt buộc truyền đúng thứ tự ba bộ đầu, Địa Tạng ở vị trí thứ tư.
compilation_thumbs.enqueue_intro_rebuild(
    config, app.state.runner, [pid_vlt, pid_cut, pid_tt, pid_dt],
    compilations=app.state.compilations, theme_plans=app.state.theme_plans,
)
```

Batch bỏ current/active duplicate, chỉ chọn video/Short đã render. Giữ marks cũ, thêm marks cho KTI1 đang chờ trước marks mới; xếp video ghép ba bộ trước Short, đánh dấu 10 tập Short từ mốc cấu hình mỗi bộ. Địa Tạng (video ghép nếu có, Short rồi KT) xếp sau ba bộ, không thêm ưu tiên vượt đợt trước. Bộ ngoài file mốc không được chọn. Chưa tạo/sửa file config runtime hoặc xếp job thật trong session; ORCHESTRATOR cài `short_intro_from.json` theo D-KTI2-2/6, thêm mốc 1 Địa Tạng vào `khaithi_from.json` và cài bìa sau khi HUMAN LEAD chọn mẫu. Thumbnail tập/HD/bản dọc không bị sửa.

### AC → test

| AC | Test chính / bằng chứng |
|---|---|
| 1 | `test_short_intro_pixels_silence_cache_title_and_review` (fresh / existing): so ảnh đầu, fade 1 s, silence, duration, sidecar/content SHA/key, cache và title override |
| 2 | `test_short_outside_scope_keeps_bytes_and_key`; hồi quy KTI1 `test_intro_pixels_silence_content_sha_cache_and_title`; THUMB2 `test_default_kt_bytes_and_key_equal_pre_thumb2` |
| 3 | `test_short_missing_cover_has_reason_link_and_no_clip` (stage + JobFailed, không socket); `test_kti2_intro_status_and_cover_links_on_both_cards` (Node DOM). HTTP TestClient còn chờ ORCHESTRATOR |
| 4 | `test_short_existing_archived_or_store_revision_without_source` (local/released): không gọi nguồn đã dọn, store giả lập lên `(r2)`, borrow kèm sidecar, framemd5 nội dung và skip current |
| 5 | `test_favorites_builds_thumb2_intro_and_removes_short_intros`; `test_theme_intro_preserves_content_plan_thumb2_and_chapters`; KTI1 `test_compilation_copy_and_reencode_skip_intro` (medium / NTSC). So ảnh đầu, fade, framemd5 sau offset, bỏ intro con, byte THUMB2/cache, chapter/description và approval; đổi thumbnail → stale/rebuild |
| 6 | `test_short_selector_range_priority_and_current`; `test_batch_queue_order_current_duplicates_priority_and_later_dia_tang`; ca AC4 kiểm skip current archived/released |
| 7 | `test_start_one_and_invalid_values` (hai file mốc, 8 giá trị); `test_episode_one_is_in_intro_context` (Short / KT) |
| 8 | Framework-check / diff-check PASS. Full suite chưa chạy; không đánh dấu toàn AC8 PASS |

### Verification thực tế

`P` = `timeout 290s env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/hdi1-hd-intro/.claude/worktrees/kti2/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest`. Mọi lệnh test có timeout ≤ 290 s.

| Lệnh | Kết quả |
|---|---|
| `P -q -x --tb=short -n 2 tests/test_short_compilation_intro.py tests/test_khaithi_intro.py tests/test_khaithi_thumbs.py tests/test_compilation_thumbs.py` | **182 passed**, 234.28 s; vòng cuối sau review + thêm assertion khung thật / giữ video cũ: **182 passed, 204.97 s** |
| `P -q -x --tb=short -n 2 tests/test_render_stage.py tests/test_render_reuse.py tests/test_render_cp9.py tests/test_render_parallel.py tests/test_render_plan.py tests/test_render_config.py tests/test_render_text.py tests/test_khaithi_ac1.py` | **128 passed**, 177.25 s |
| `P -q -x --tb=short -n 2 tests/test_compilation.py tests/test_theme_render.py tests/test_theme_index.py tests/test_theme_plan.py` | **263 passed**, 66.57 s |
| `P -q -x --tb=short -n 2 -m slow tests/test_render_stage.py tests/test_render_reuse.py tests/test_render_parallel.py` | **5 passed**, 47.16 s |
| `P -q -x --tb=short -n 2 tests/test_web_packaging.py tests/test_web_theme_plan.py -k 'kti2_intro_status or both_video_cards or test_js_smoke_and_text_only or test_js_favorites_tabs_and_manual_compilation or test_favorites_tab_panel_ownership'` | **35 passed**, 3.26 s; 2 warning deprecation từ import FastAPI TestClient, không tạo TestClient/socket |
| `P -q -x --tb=short tests/test_vertical_silence_intro.py -k test_kti1_fade_keeps_vert2_graph_and_command_bytes` | **2 passed**, 15 deselected, 1.18 s; graph + command VERT2 giữ byte |
| `node --check src/auto_short/web/static/favorites.js`; `node --check src/auto_short/web/static/theme_plan.js` | PASS |
| `node scripts/framework-check.mjs`; `git diff --check` | PASS; chạy lại sau ghi Result |

Các lượt trong vòng sửa cũng được ghi nhận: nhóm required ban đầu **1 failed / 29 passed, 72.12 s** (assertion mới so SHA hai container remux thay vì SHA file ngay trước prepend; vẫn giữ so framemd5 với baseline); lượt sau **1 failed / 43 passed, 69.43 s** (fixture KT tập 1 còn header tập gốc 31). Subset `-k 'favorites or theme or start_one'`: **1 failed / 15 passed, 18.46 s** (assertion mới nhầm tập 1 không trước mốc 31), sau sửa **18 passed, 27.97 s**. `-k batch_queue`: **1 passed / 29 deselected, 3.03 s**. Chỉ sửa setup/assertion của test mới; không nới assertion/test cũ. Không có lệnh test timeout.

- Diff ứng dụng: **+261 / −75**; test: **+421 / −30**, tính cả file test mới chưa stage. Phần xóa test cũ là chuyển nguyên helper sang file dùng chung; không xóa hành vi/assertion.
- Review riêng theo contract → diff → AC: inventory nằm trong Owned paths; default KT/THUMB2/VERT2 được giữ, consumer sidecar dùng chung, không có thay đổi dependency/API/security. Không gọi reviewer/agent khác theo ràng buộc session.
- Chưa chạy: `P -q -n auto` (full suite), toàn bộ `tests/test_web_compilation.py`, phần HTTP TestClient của `tests/test_web_theme_plan.py` / các test web khác; toàn suite slow; 8080 / mẫu 10 s + ảnh 1,5 s / manual checklist; upload 3090, cài config/bìa runtime và batch thật D-KTI2-5/6. Sandbox không có socket loopback; các phần này thuộc ORCHESTRATOR theo Required verification.
- Giới hạn kế thừa THUMB2: favorite có `title: null` vẫn báo lỗi tiêu đề rỗng, không tự đổi tiêu đề/tên video; ORCHESTRATOR cần kiểm dữ liệu này trước batch. Không gọi YouTube, Ollama hoặc kho thật để kiểm trong session.

### Vòng sửa 1 — ORCHESTRATOR review (2026-10-30)

- **READY phần IMPLEMENTER**, trên HEAD `83b4423`, không commit. ORCHESTRATOR báo full suite trước sửa: **3568 passed, 1 failed** (`test_compilation_released_clips_borrow_and_cleanup[None]`); không ghi nhận full suite đó là PASS.
- Sửa `web/compilations.py` và `theme_render/__init__.py`: chỉ đọc `done/result.content_offset` khi `image is not None`; không intro → không truyền tùy chọn mới cho `meta.chapters`, độ lệch kiểm duration vẫn 0. Giữ giao diện kết quả assemble cũ cho đường không intro. Rà toàn `src/auto_short` bằng `rg -n '\.(content_offset|content_sha256)'`: các lần đọc còn lại chỉ nằm trong nhánh có ảnh intro. Không thêm helper, không sửa bất kỳ test cũ nào.
- AC2/4/5 → test cũ `test_compilation_released_clips_borrow_and_cleanup` (kết quả giả chỉ có trường cũ), nhóm theme/compilation hiện hành và `test_short_compilation_intro.py` (giữ đường có intro).
- Đã chạy đúng lệnh: `timeout 290s env PYTHONPATH=/home/ntnghia/projects/youtube-auto-short/.claude/worktrees/hdi1-hd-intro/.claude/worktrees/kti2/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short -n 2 tests/test_store_shorts_edit.py tests/test_short_compilation_intro.py tests/test_theme_render.py tests/test_compilation.py` → **116 passed, 117.53 s**. `node scripts/framework-check.mjs` và `git diff --check`: **PASS**.
- Diff vòng sửa 1 so với `83b4423`: ứng dụng **+6 / −4**, test **+0 / −0**; thêm mục Result này. Review lại diff: chỉ hai file ứng dụng và contract, trong Owned paths.
- Chưa chạy lại full suite / HTTP TestClient sau sửa; manual/8080 và batch thật vẫn thuộc ORCHESTRATOR. Không gọi mạng thật, agent, commit/push/PR.

### ORCHESTRATOR (2026-10-30)

- Review vòng 1 (Codex 206.706 tokens): phạm vi `short_intro_from.json` tách khỏi `khaithi_from.json`, mốc ≥ 1; ảnh Short thư mục `short_intro_thumbs`, nhãn "TRÍCH ĐOẠN"; intro video ghép qua `intro.prepend` đúng khổ; chapter giữ 0:00; helper test dời nguyên văn sang `render_helpers.py` (không nới assertion). Clip id Short thật là `kNN` (khớp `CLIP_ID`).
- Full suite vòng 1: 3568 passed, **1 failed** `test_store_shorts_edit.py::test_compilation_released_clips_borrow_and_cleanup[None]` (đường không intro đọc `content_offset`) → finding gửi Codex (resume), sửa +6 / −4.
- Full suite sau vòng sửa: **3569 passed, 1 skipped**.
- Còn: chạy thật 8080 (8080 đang bận 38 job bản dọc Địa Tạng; script restart từ chối khi làn bận), mẫu 10 s Short + video ghép gửi HUMAN LEAD, cài bìa KT Địa Tạng (HUMAN LEAD chọn mẫu), tạo `short_intro_from.json` + thêm Địa Tạng vào `khaithi_from.json`, rồi đợt D-KTI2-5/6. Lưu ý vận hành: sau deploy, video ghép cũ của các bộ trong phạm vi hiện "Thumbnail intro đã đổi — cần ghép lại" (ẩn nút tải) đến khi ghép lại.
