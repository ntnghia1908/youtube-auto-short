# Task: KTI1-khaithi-thumb-intro — Clip khai thị có 3 giây thumbnail khai thị ở đầu video

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`); dự phòng subagent `implementer` (Sonnet)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-29: "Tôi muốn khai thị cũng có thumnail 3s đầu. Việc này áp dụng với tất cả khai thị của cảm ứng thiên, thập thiện nghiệp đạo từ tập 21 trở về sau. Với Vô Lượng Tho từ tập 31 về sau"; "lưu ý với video khai thị ghép không ghép phần 3s này vào. Ghép như hiện tại"; G1–G3 bên dưới
- Parallel group: —
- Owned paths: đường render clip khai thị (`src/auto_short/render/stage.py` và module render clip liên quan), `src/auto_short/packaging/khaithi_thumbs.py` (dựng ảnh cho 1 clip theo yêu cầu render), mọi đường đọc file clip khai thị để ghép: `src/auto_short/compilation/`, `src/auto_short/web/compilations.py`, `src/auto_short/theme_index/__init__.py`, `src/auto_short/theme_render/__init__.py`, `src/auto_short/store/shorts.py` (mượn clip từ kho), `src/auto_short/web/static/` (chỉ thông báo "chưa có bìa" + link trang Thumbnail), test tương ứng + `tests/test_khaithi_intro.py` (mới), contract này
- Dependencies: THUMB1 (#182: bìa KT, `khaithi_thumbs`, `khaithi_from.json`), VERT2 (intro 3 s bản dọc: filter + key), SHO1 (clip trên kho 3090, bản `(rN)`), HDI1 (#183: mẫu độ lệch intro + sha nội dung). Bắt đầu sau khi THUMB2 merge (cùng sửa `khaithi_thumbs.py`).
- Base commit / branch: `0a1277f` (`feature/thumb2-compilation-thumbs`, PR #184 — xếp chồng vì cùng sửa `khaithi_thumbs.py`; đổi base sang main sau khi #184 merge) / `feature/kti1-khaithi-thumb-intro`
- Human Lead approval: APPROVED 2026-10-29
- Implementation authorized: YES

S2 vì: đổi sản phẩm video khai thị đã đăng / trên kho (bản `(rN)`), mọi đường ghép clip phải bù độ lệch, và có đợt dựng lại hàng loạt khoảng 500 clip.

## Quyết định

- D-KTI1-1: clip khai thị dựng mới = **3 s ảnh thumbnail khai thị dọc** của clip (THUMB1, `kt_vertical`, cùng chữ / chân dung như ảnh tải về) **trước** nội dung, tiếng im lặng (như VERT2 G2). Phạm vi theo `khaithi_from.json` (VLT ≥ 31, Cảm Ứng Thiên ≥ 21, Thập Thiện ≥ 21); tập trước mốc: không intro, không đổi.
- D-KTI1-2 (G1 = "Dựng lại tất cả"; G2 = "Dựng lại luôn"): sau merge, ORCHESTRATOR xếp dựng lại mọi clip khai thị đã render trong phạm vi, **kể cả tập đã đăng**; tiêu đề / đoạn cắt giữ nguyên; bản mới lên kho 3090 thành `(rN)` (SHO1b). Thứ tự theo D-KTI1-5.
- D-KTI1-5 (HUMAN LEAD 2026-10-29, thứ tự ưu tiên khi thiếu CPU / GPU): (1) video khai thị ghép có thumbnail (THUMB2); (2) clip khai thị có intro — **mỗi bộ chạy trước 10 tập** (VLT 31–40, Cảm Ứng Thiên 21–30, Thập Thiện 21–30), đánh dấu "Ưu tiên" (CP8.26 `priority.mark`) để vượt các job bản dọc Địa Tạng còn chờ; phần còn lại xếp sau, không ưu tiên; (3) Kinh Địa Tạng: thumbnail bản dọc (VERT2, đang render) và bản ngang (HDI1).
- D-KTI1-3 (G3, HUMAN LEAD: "báo chưa có bìa và chuyển qua trang thiết kế bìa"): bộ trong phạm vi chưa có bìa KT → **không render clip thiếu intro**; job khai thị dừng với lý do "Bộ kinh chưa có ảnh bìa khai thị", web hiện thông báo + link sang trang Thumbnail của bộ (THUMB1). Cài bìa xong → chạy lại job.
- D-KTI1-4 (HUMAN LEAD 2026-10-29: "video khai thị ghép không ghép phần 3s này vào. Ghép như hiện tại"): video ghép yêu thích (CP8.33) và tuyển tập chủ đề (TC3) **bỏ 3 s intro** của từng clip: nội dung ghép giống hiện tại. Sidecar clip ghi độ lệch intro + sha nội dung (mẫu HDI1); fingerprint index / plan đã duyệt dựa trên nội dung → plan **không** stale chỉ vì thêm intro.
- Thumbnail đổi (sửa tiêu đề, đổi bìa / chân dung) → key render đổi → clip cũ không còn hiện hành, dựng lại như sửa tiêu đề hiện nay.

## Goal

Clip khai thị trong phạm vi (VLT ≥ 31, Cảm Ứng Thiên / Thập Thiện ≥ 21) mở đầu bằng 3 giây thumbnail khai thị; video ghép vẫn y như hiện tại.

## Scope

- In scope: dựng ảnh KT dọc cho clip lúc render (tái dùng `khaithi_thumbs` + cache), filter intro 3 s + `anullsrc` (tái dùng VERT2 `full.py`: lệnh / filter intro, tách helper chung nếu cần), key render gồm sha ảnh + độ dài intro, sidecar clip `intro` (sha ảnh, giây) + sha nội dung; mọi đường ghép bỏ intro theo sidecar; bộ thiếu bìa KT → lỗi có lý do + link web; lệnh / API xếp dựng lại clip KT theo playlist + mốc tập (cho đợt D-KTI1-2).
- Out of scope: Short; bản dọc / HD (VERT2 / HDI1); clip trước mốc `khaithi_from.json`; tự đăng YouTube / thay video đã đăng; đổi giao diện thumbnail KT.

## Phải giữ nguyên

- Video ghép yêu thích + tuyển tập chủ đề: nội dung ghép như hiện tại (không intro); plan đã duyệt không stale vì intro; Short không đổi byte; clip khai thị trước mốc không đổi; thumbnail KT tải về (THUMB1) không đổi.

## Code bị thay / xóa

- Không xóa; filter render clip khai thị thêm nhánh intro.

## Acceptance Criteria

1. Clip khai thị trong phạm vi: 3 s đầu là ảnh KT dọc của đúng clip (so khung), tiếng im lặng, độ dài = nội dung + 3 s; sidecar có `intro` + sha nội dung; render lại không đổi gì → cache.
2. Clip trước mốc / Short: không intro, byte / key không đổi.
3. Bộ trong phạm vi chưa có bìa KT → job dừng với lý do "Bộ kinh chưa có ảnh bìa khai thị", không ghi clip; API / web trả link trang Thumbnail.
4. Video ghép yêu thích + tuyển tập chủ đề từ clip có intro: không chứa 3 s intro (so framemd5 nội dung với bản ghép từ clip không intro), plan đã duyệt không stale; mượn clip `(rN)` từ kho bù đúng độ lệch.
5. Sửa tiêu đề clip → thumbnail + intro đổi, clip dựng lại.
6. Lệnh xếp dựng lại theo playlist + mốc tập: xếp đúng các clip trong phạm vi, bỏ qua clip đã có intro hiện hành.
7. Full suite PASS; `framework-check`, `git diff --check` PASS.

## Required verification

Prefix như THUMB1.

- `<prefix> tests/test_khaithi_intro.py tests/test_khaithi_thumbs.py` + test render / compilation / theme hiện có — AC 1–6 (không socket).
- TestClient (ORCHESTRATOR) cho AC3 web; `<prefix> -n auto`; `node scripts/framework-check.mjs`; `git diff --check` — AC 7.
- Chạy thật (ORCHESTRATOR, 8080 ghim commit nhánh): 1 tập VLT ≥ 31 dựng lại clip khai thị → gửi HUMAN LEAD 10 s đầu 1 clip; ghép 1 video yêu thích có clip đó → so với bản cũ (không intro); 1 tập Cảm Ứng Thiên chưa có bìa → thấy thông báo + link.

## Manual test checklist (Tech Lead)

- [ ] 3 s đầu clip khai thị là đúng thumbnail của clip, dấu đúng.
- [ ] Video ghép không có đoạn 3 s ảnh giữa các clip.

## Result

-
