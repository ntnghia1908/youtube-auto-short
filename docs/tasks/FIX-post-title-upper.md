# Task: FIX-post-title-upper — Tựa đề bài đăng cộng đồng VIẾT HOA TOÀN BỘ

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `0cb2f0c` (`main`) / `fix/post-title-upper` (worktree `../youtube-auto-short-upper`)
- Human Lead approval: APPROVED 2026-10-04 ("Sửa nhỏ: tựa đề của mỗi bài đăng nên VIẾT HOA TOÀN BỘ")
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: đổi bố cục P4 trong decision đã accepted `docs/decisions/CP8.15-community-post-contract.md` (canonical owner); thay đổi code nhỏ.

## Goal

Dòng đầu (tựa đề = title Short đang dùng) của văn bản bài đăng cộng đồng (nút "Sao chép bài", xem trước bài, API `text` / `chars`) viết hoa toàn bộ, đúng tiếng Việt (ví dụ "Điều gì là cúng dường chân thật theo kinh Địa Tạng?" → "ĐIỀU GÌ LÀ CÚNG DƯỜNG CHÂN THẬT THEO KINH ĐỊA TẠNG?").

## Scope

- In scope: `post/logic.compose_copy_text` (áp lúc đọc / sao chép, như R5 dòng nguồn); nơi hiển thị tựa đề bài trên tab "Bài đăng" nếu có hiển thị riêng → khớp chữ hoa; cập nhật P4 trong `docs/decisions/CP8.15-community-post-contract.md` (sửa đổi + ngày); test.
- Out of scope: title Short / header video / `titles.json` / `review.json` / tên file / chữ "Copy" của Short (CP8.21); đoạn văn bài; hashtag; `source_sha256` / `stale` không đổi (chỉ áp lúc đọc).

## Authority / key decisions

- `docs/decisions/CP8.15-community-post-contract.md` P4 (+ sửa đổi CP8.16 R5 làm mẫu "áp lúc đọc API").

## Acceptance Criteria

1. Văn bản bài (API `text`, nút sao chép) có dòng đầu = `title.upper()` đúng dấu tiếng Việt (đ → Đ, ư → Ư, ơ → Ơ, dấu thanh giữ nguyên); `chars` tính trên văn bản mới.
2. Không đổi title Short, `posts.json`, `source_sha256`, `stale`; bài cũ không bị đánh dấu cần soạn lại.
3. Không title → không có dòng tựa (như cũ).
4. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–4.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080: "Sao chép bài" một Short → dòng đầu viết hoa toàn bộ.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
