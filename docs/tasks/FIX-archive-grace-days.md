# Task: FIX-archive-grace-days — Tự dọn nguồn chờ vài ngày sau khi tải

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session
- Implementer: codex — `codex exec` (gpt-6.1-sol, medium); quota 5 giờ thấp
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-19: “khi bấm tải xuống toàn bộ thì nguồn đã bị xóa nên không sửa tiêu đề được … khi bấm tải thì khoan hãy dọn luôn nguồn, có thể lùi lại vài ngày”
- Parallel group: —
- Owned paths: `src/auto_short/config.py` (chỉ `StorageConfig.auto_archive_grace_minutes` default + bound), `config.example.toml` (mục `[storage]`), `docs/decisions/CP8.3-web-contract.md` (header + câu config W9), tests config / storage liên quan, contract này
- Dependencies: none
- Base commit / branch: `bf38297` / `fix/archive-grace-days`, worktree `/home/ntnghia/youtube-auto-short-grace`
- Human Lead approval: accepted (yêu cầu trực tiếp 2026-10-19)
- Implementation authorized: YES

## Goal

Tải zip (tick "Đã đăng") không còn làm mất video nguồn sau 30 phút: tự dọn chỉ chạy khi video đã "Xong" liên tục **3 ngày** (mặc định), để HUMAN LEAD còn sửa tiêu đề / render lại.

## Scope

- In scope: `auto_archive_grace_minutes` mặc định 4320 (3 ngày), cho phép 0–43200 (30 ngày); `config.example.toml` + CP8.3 W9 ghi đúng; tests bound / default / plan với grace dài.
- Out of scope: cơ chế "Xong" / tick, dọn tay, khôi phục nguồn đã xóa (việc riêng), video có khai thị (đã luôn giữ nguồn, #99).

## Authority / key decisions

- CP8.3 W9 S5 canonical; sửa đổi ghi header + câu config. `complete_since` (mốc "Xong" mới nhất) giữ nguyên ý nghĩa: sửa tiêu đề → render lại → mốc mới → đếm lại.

## Implementation approach

- Đổi default + bound, cập nhật doc / example, thêm test.

## Acceptance Criteria

1. Config không ghi `auto_archive_grace_minutes` → 4320; giá trị 43200 hợp lệ, 43201 lỗi rõ.
2. `auto_archive_plan` với grace 3 ngày: video "Xong" 2 ngày không bị dọn, 3 ngày thì dọn.
3. Full suite PASS.

## Required verification

- `env PYTHONPATH=/home/ntnghia/youtube-auto-short-grace/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_storage_suggest.py tests/test_config*.py -x --tb=short`; full suite (ORCHESTRATOR); framework-check; `git diff --check`.

## Result

- Main changes:
- Tests:
- Review:
- PR: chưa.
