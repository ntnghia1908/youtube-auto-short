# Task: FIX-keep-khaithi-source — Tự dọn không xóa video nguồn của video có khai thị

## Status / Approval

- Status: DRAFT
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session
- Implementer: codex — `codex exec` (gpt-6.1-sol), một writer; chạy sau TC3 (không song song writer)
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-18: “Hiện tại nếu bấm tải (khai thị + Short) thì sẽ tự xóa luôn file nguồn gây ảnh hưởng đến điểm này, hãy tìm cách khắc phục” (sau khi chọn “Tải lại file nguồn nếu cần, sửa lại không xóa file nguồn khi bấm tải về”)
- Parallel group: —
- Owned paths: `src/auto_short/web/storage.py` (chỉ `auto_archive_plan`), `tests/test_storage_suggest.py`, `docs/decisions/CP8.3-web-contract.md` (W9, một câu + header), contract này
- Dependencies: none
- Base commit / branch: `d56d200` / `fix/keep-khaithi-source`, worktree `/home/ntnghia/youtube-auto-short-keepsrc`
- Human Lead approval: accepted (yêu cầu trực tiếp 2026-10-18)
- Implementation authorized: YES

Lifecycle: `task` mode. Push / PR / merge / restart 8080 cần HUMAN LEAD cho phép riêng.

## Goal

Tải zip (Short + khai thị) vẫn tick "Đã đăng", nhưng tự dọn nguồn (W9 S5, `[storage] auto_archive`) **không** xóa video nguồn của một video có phần khai thị (`<id>.kt`), để TC3 dựng lại video ngang từ nguồn mà không phải tải lại.

## Scope

- In scope: `auto_archive_plan` bỏ qua video có ít nhất một phần khai thị; tests; câu W9 trong CP8.3.
- Out of scope: dọn tay ở tab Bộ nhớ (vẫn cho phép, người dùng chủ động), gợi ý dọn (`recommend`), tick "Đã đăng", nguồn đã bị xóa trước đây (TC3 tải lại), config mới.

## Authority / key decisions

- CP8.3 W9 S5 (FIX-storage-suggest) là canonical owner; sửa đổi ghi vào header + W9.
- Ước lượng ổ: 144 file nguồn hiện có = 29 GB (≈ 200 MB / video); 108 workspace khai thị; ổ còn 109 GB.

## Acceptance Criteria

1. Video có phần `.kt` (dù khai thị đã xong / đã tải): `auto_archive_plan` không trả video đó. Video chỉ có Short: hành vi cũ.
2. Dọn tay (`archive_source` qua tab Bộ nhớ) không đổi.
3. Full suite PASS; framework-check PASS.

## Required verification

- `env PYTHONPATH=/home/ntnghia/youtube-auto-short-keepsrc/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_enhance_state.py tests/test_storage_suggest.py tests/test_storage_cp86.py -x --tb=short` — AC1–2.
- Cùng prefix `-m pytest -q -n auto`; `node scripts/framework-check.mjs`; `git diff --check`.

## Manual test checklist (Tech Lead)

Không chạm database / security / public API.

- [ ] Sau khi deploy: tải zip một video có khai thị, chờ > 30 phút: `work/<id>/source.*` vẫn còn.

## Result

- Main changes:
- Tests:
- Review:
- Known limitations:
- PR:
