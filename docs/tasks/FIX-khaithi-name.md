# Task: FIX-khaithi-name — Tên khai thị `T<tập>_KT<NN>`, bỏ tiền tố "Khai Thị: "

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `b57fc29` (`main`) / `fix/khaithi-name` (worktree `../youtube-auto-short-ktname`)
- Human Lead approval: APPROVED — HUMAN LEAD 2026-10-03 chỉ định trực tiếp thay đổi ("bỏ chữ Khai Thị, thay TK05 thành KT05"); contract chỉ ghi lại đúng yêu cầu đó.
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: đổi hành vi nhỏ (chuỗi tên) trong quy ước tên đã có của CP8.21 D3; không chạm decision gate mới. Authority CP8.3 / CP8.9 cập nhật theo.

## Goal

Video khai thị: tên file tải về `T<tập>_KT<NN>_<title>.mp4` và text Copy `T<tập>_KT<NN>_<title> #tag…` (không còn `Khai Thị: `, `TK` → `KT`). Short không đổi (`T<tập>_S<NN>_…`).

## Scope

- In scope: `review/names.py` (mã khai thị `KT`, bỏ `KHAITHI_COPY_PREFIX`), tests liên quan, authority (`docs/decisions/CP8.3-web-contract.md`, `docs/decisions/CP8.9-khai-thi-contract.md`), `docs/ai/project-profile.md`, `README.md`.
- Out of scope: tên zip; title trong video; Short; file `docs/tasks/CP8.21-*` (lịch sử, không sửa).

## Acceptance Criteria

1. Khai thị: tên file `T7_KT05_<title>.mp4`, Copy `T7_KT05_<title> #tag…`; không title → `T7_KT05.mp4`.
2. Short không đổi; giới hạn 100 ký tự / bớt hashtag giữ luật cũ.
3. Authority + README khớp; không còn `TK<NN>` / `Khai Thị: ` trong mô tả hiện hành.
4. `PYTHONPATH=<worktree>/src python -m pytest -q -n auto` PASS; `node scripts/framework-check.mjs` PASS.

## Required verification

- `PYTHONPATH=<worktree>/src python -m pytest -q -n auto` — AC 1, 2, 4.
- `node scripts/framework-check.mjs` — AC 3, 4.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API. Điểm danh sau merge trên 8080:

- [ ] Tải một khai thị: tên `T<tập>_KT<NN>_…`.
- [ ] Copy title khai thị: không có "Khai Thị: ".

## Result

- Main changes: `short_code` khai thị `KT`; bỏ `KHAITHI_COPY_PREFIX` (`copy_prefix` chỉ trả mã + `_`); tests + authority CP8.3 / CP8.9 + project-profile + README khớp.
- Tests: `pytest -q -n auto` 1337 passed, 1 skipped; `node scripts/framework-check.mjs` toàn PASS. Test độ dài prefix (19 → 9 ký tự) chỉnh title mẫu 50 → 60 để giữ ý đồ.
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
