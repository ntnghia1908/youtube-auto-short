# Task: PUB2M — PUB2 nhận tên file `[HD Mobile]`

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: single-agent (sửa 1 regex + 1 test)
- Orchestrator: claude-code
- Authorization mode: task
- Authorization source: `docs/decisions/HD1-hd-backup-release.md` G6 ("Hệ quả cho PUB2: nhận cả `[HD Mobile]` lẫn `[HD Dọc]`"); HUMAN LEAD 2026-11-02 "Đồng ý, sửa PUB2 nhận HD Mobile"
- Owned paths: `src/auto_short/publish/thumbs.py`, `tests/test_publish_thumbs.py`, `docs/decisions/PUB2-youtube-thumbnail-set.md`, file này
- Dependencies: none
- Base commit / branch: `d665342` (origin/main) / `fix/pub2-hd-mobile`
- Human Lead approval: accepted
- Implementation authorized: YES

## Goal

Video upload với tên chuẩn của kho 3090 `[HD Mobile] <bộ kinh> - Tập N.mp4` được PUB2 ghép với thumbnail dọc của tập.

## Scope

- In scope: mẫu tên trong `publish/thumbs.py`, lý do "bỏ qua".
- Out of scope: tên file tải từ web (`…_TậpN_Doc.mp4`) — HUMAN LEAD 2026-11-02 thống nhất dùng tên kho, không hỗ trợ tên cũ.

## Acceptance criteria

1. `[HD Mobile] <bộ kinh> - Tập N.mp4` → khuôn `vertical`, sẵn sàng.
2. `[HD]` / `[HD Dọc]` giữ nguyên hành vi.
3. Thẻ viết thường (`[hd mobile]`) → bỏ qua, lý do nêu mẫu.

## Verification

- `tests/test_publish_thumbs.py::test_hd_mobile_store_name_is_vertical` (AC1, AC3); test cũ của file (AC2); full suite.

## Result

- `tests/test_publish*.py` 31 passed; full suite (`-n 4`, nice 10): 3664 passed, 1 skipped.
- Ngoài task (vận hành, HUMAN LEAD 2026-11-02): 32 bản dọc đã upload với tên web cũ `…_TậpN_Doc.mp4` (VLT 10, Cảm Ứng Thiên 22) được gắn thumbnail bằng script một lần `output/_operations/pub2-test-2026-11-02/pub2_old_names.py` (dùng nguyên `thumbs.plan` / `apply`; `fileName` trên YouTube chỉ đọc, không đổi được). Nhật ký `work/_publish/thumbs.json` 32 bản ghi.
