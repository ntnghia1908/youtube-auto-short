# Task: KTI2-short-compilation-intro — Short và video khai thị ghép có 3 giây thumbnail ở đầu

## Status / Approval

- Status: APPROVED
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
7. Full suite PASS; `node scripts/framework-check.mjs`, `git diff --check` PASS.

## Required verification

- `timeout 290s env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q -x --tb=short -n 2 tests/test_short_compilation_intro.py tests/test_khaithi_intro.py tests/test_khaithi_thumbs.py tests/test_compilation_thumbs.py` + test render / compilation / theme hiện có (AC 1–6, không socket).
- ORCHESTRATOR: TestClient AC3, full suite `-n auto`, framework-check, `git diff --check` (AC 7).
- Chạy thật (ORCHESTRATOR, 8080): 1 tập VLT ≥ 31 → mẫu 10 s đầu 1 Short + khung 1,5 s gửi HUMAN LEAD; ghép lại 1 video yêu thích VLT → mẫu 10 s đầu; rồi đợt D-KTI2-5.

## Manual test checklist (Tech Lead)

- [ ] 3 s đầu Short là đúng thumbnail "TRÍCH ĐOẠN" của Short, dấu đúng.
- [ ] Video ghép mở đầu bằng thumbnail video ghép, không có đoạn ảnh 3 s giữa các clip.

## Result

(chưa chạy)
