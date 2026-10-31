# Task: FV1 — Trang Yêu thích: tab "Video đã ghép", xem trực tiếp

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session
- Implementer: codex — `codex exec` gpt-6.1-sol, high; JS tự chứa, quota 5 giờ 40 % / tuần 56 %
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: HUMAN LEAD 2026-10-31: "trang ghep khai thi yeu thich bang AI kha kho su dung. Nen tach video da ghep sang tab khac (chi la goi y cua toi neu co cach tot hon thi de xuat) va cho xem truc tiep giong trang short thay vi nhan nut xem"
- Parallel group: —
- Owned paths: `src/auto_short/web/static/favorites.html`, `favorites.js`, `theme_plan.js`, `style.css` (cùng thư mục), `tests/test_web_theme_plan.py`, `tests/test_web_packaging.py` (stub harness + assert nút Xem theo hành vi mới), contract này
- Dependencies: TC2.3, CP8.33, KTI2 (merged)
- Base commit / branch: `abc8ba8` / `feature/fv1-video-tab`, worktree `.claude/worktrees/fv1-video-tab`
- Human Lead approval: accepted (yêu cầu trực tiếp 2026-10-31)
- Implementation authorized: YES

## Goal

Trên điện thoại, mở tab **Video đã ghép** là thấy ngay các video ghép (AI và ghép tay) với trình phát sẵn trên từng thẻ, bấm play là xem, không có nút "Xem" trung gian. Tab AI chỉ còn việc gợi ý / chọn chủ đề.

## Scope

- In scope: tab thứ ba, chuyển `#tp-plans` + `#fv-comps` sang tab đó, trình phát inline, gọn thẻ video, tránh gián đoạn khi đang xem, CSS mobile, tests.
- Out of scope: backend / API, nội dung `theme-plan`, luồng ghép, trang Short, đổi cách dựng thumbnail.

## Authority / key decisions

- Cải tiến so với gợi ý của HUMAN LEAD (ORCHESTRATOR quyết, báo trong READY): gom **cả** video ghép AI lẫn ghép tay vào một tab, vì hiện có hai danh sách ở hai tab.
- Ba tab: "Gợi ý chủ đề (AI)" (mặc định) | "Yêu thích & ghép tay" | "Video đã ghép (N)". N = số plan + số compilation.
- Trình phát như Short: `controls`, `playsinline`, `preload="metadata"`. Video ngang (theme) 16:9, video dọc (compilation) 9:16 không cao quá 70vh. 3 s đầu là thumbnail intro nên khung đầu đóng vai ảnh bìa; không cần `poster`.
- Thẻ chủ đề đã ghép không còn trình phát / nút tải: "✓ Đã ghép · … phút" + nút "Xem video" chuyển sang tab và cuộn tới thẻ.
- Sửa danh sách clip + thumbnail vào một `<details>`; cảnh báo "Thumbnail intro đã đổi" phải tự mở phần này để không bị giấu.

## Phải giữ nguyên

- Mọi route, payload; ghép một bước; Ghép lại / Gợi ý lại / Xóa / Tải / Copy; dựng + tải thumbnail; lưu draft; tab nhớ qua `localStorage`.

## Code bị thay / xóa

- Nút "Xem" / "Ẩn video" + `.tp-player` toggle (`appendOutput`), nút "Xem" mở tab mới của `compRow`; khối "Video đã ghép" trong tab AI, khối "Video ghép" trong tab tay; assert tương ứng ở `tests/test_web_theme_plan.py` (đổi theo hành vi mới, không phải che lỗi).

## Acceptance Criteria

1. Có ba tab; `#tp-plans` và `#fv-comps` nằm trong tab "Video đã ghép"; số N cập nhật; tab cuối được nhớ.
2. Mỗi video xong có sẵn `<video>` (src `…?inline=1`, metadata), không có nút Xem; video chưa xong hiện trạng thái, không có trình phát.
3. Đang phát: polling, focusout, `perform()` không dựng lại danh sách chứa video đó; trạng thái mới áp dụng khi dừng / hết bài. Video đang tạm dừng giữ nguyên vị trí qua lần dựng lại; đang fullscreen cũng không bị dựng lại.
4. Phát video này tự dừng video khác; rời tab tự dừng video.
5. Thẻ chủ đề đã ghép có "Xem video" đưa tới đúng thẻ ở tab mới; "Ghép lại với tiêu đề này" vẫn hoạt động.
6. Thẻ video gọn: Tải + Copy ở ngoài; sửa clip + thumbnail trong `<details>`; plan lỗi / chưa có output vẫn thấy "Ghép lại" ngoài; cảnh báo thumbnail intro tự mở `<details>`.
7. Lưới một cột ở ≤ 640 px, không tràn ngang; nút chạm đủ lớn.

## Required verification

- `node --check` các file JS; `git diff --check`; `node scripts/framework-check.mjs`.
- `python -m pytest -q tests/test_web_theme_plan.py tests/test_web_compilation.py -x --tb=short` (đúng `PYTHONPATH=<worktree>/src`) — harness Node cho AC 1–6.
- Full suite `python -m pytest -q -n auto` (ORCHESTRATOR, ngoài sandbox).
- Chụp màn hình 375 px và desktop trên dữ liệu thật (ORCHESTRATOR), phát thử cả hai loại video.

## Manual test checklist (Tech Lead)

Task không chạm database, security model hay public API contract; manual test là điểm danh.

- [ ] Điện thoại: mở tab Video đã ghép, phát video ngang và dọc; đang phát có job ghép chạy song song không bị giật / mất vị trí.

## Result

- Codex 2 vòng (86k + 114k tokens), 0 finding còn mở; ORCHESTRATOR sửa assert nút Xem + stub `paused` trong `tests/test_web_packaging.py`.
- PASS: full suite 3581 passed, 1 skipped; `node --check`, framework-check, `git diff --check`.
- CHƯA chạy: chụp màn hình 375 px / desktop và phát thử trên dữ liệu thật (máy không có trình duyệt tự động; 8080 chưa ghim nhánh vì làn render còn 4 job). Kiểm Range trên route compilation thật chưa xong: API `compilations` quá 15 s. Vì vậy task chưa READY; chờ manual test.
