# Task: FIX-enhance-cuda-fatal — Worker tự khởi động lại sau lỗi CUDA nghiêm trọng; server không giao lại mãi một video lỗi

## Status / Approval

- Status: DRAFT
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session
- Implementer: codex — `codex exec` (gpt-6.1-sol), một writer; chạy sau TC3
- Human Lead: HUMAN LEAD
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-18 “ok fix cuda”
- Parallel group: —
- Owned paths: `tools/enhance_worker/worker.py`, `src/auto_short/enhance/service.py` (chỉ `lease` / `release`), tests worker / enhance service hiện có liên quan, contract này
- Dependencies: none
- Base commit / branch: `d56d200` / `fix/enhance-cuda-fatal`, worktree `/home/ntnghia/youtube-auto-short-cudafix`
- Human Lead approval: accepted 2026-10-18
- Implementation authorized: YES

Lifecycle: `task` mode. Push / PR / merge / restart 8080 / cập nhật worker trên máy GPU cần HUMAN LEAD.

## Goal

2026-10-18: worker RTX 3090 lặp 468 lần “doan 4 loi lien tiep: CUDA error: an illegal memory access” trên `ew1FgyT9cDI`: sau lỗi đó context CUDA của tiến trình hỏng vĩnh viễn, worker chỉ trả lease rồi nhận lại cùng video. Sau sửa: (1) worker gặp lỗi CUDA nghiêm trọng thì trả lease rồi thoát để `worker-wrapper.ps1` (vòng `while`, chờ 15 s) chạy lại tiến trình mới; (2) server không giao lại cùng video cho cùng worker sau nhiều lần trả lỗi liên tiếp trong một khoảng thời gian, để worker làm video khác.

## Scope

- In scope:
  - Worker: nhận diện lỗi CUDA nghiêm trọng (chuỗi `illegal memory access`, `device-side assert`, `CUDA error: unspecified launch failure`, `cudaErrorLaunchFailure`, `CUBLAS_STATUS_EXECUTION_FAILED` — danh sách hằng số) trong nhánh lỗi đoạn → release lease (reason ghi rõ) → thoát mã riêng (không phải 0 / 3) ngay, không thử lại đoạn trong cùng tiến trình. Lỗi thường giữ hành vi cũ (3 lần → release).
  - Server `EnhanceService`: đếm release liên tiếp có reason lỗi (không tính release do preempt / stop / “model khong ho tro” / cập nhật worker) theo (worker token, episode); từ 3 lần trong 1 giờ → lease không giao video đó cho worker đó trong 1 giờ (in-memory, mất khi restart là chấp nhận được); worker khác vẫn nhận. Lease thành công một đoạn (upload) hoặc video xong → xóa bộ đếm. Log một dòng khi bắt đầu tránh.
  - Tests với fake (không GPU, không mạng).
- Out of scope: tìm nguyên nhân gốc CUDA (driver / model / VRAM), đổi wrapper PowerShell, UI, config mới.

## Acceptance Criteria

1. Lỗi CUDA nghiêm trọng ở một đoạn → worker gọi release một lần rồi thoát với mã riêng; lỗi thường → hành vi cũ.
2. Server: 3 release lỗi liên tiếp của cùng worker cho cùng video trong 1 giờ → lease kế của worker đó bỏ qua video (nhận video khác hoặc 204); worker khác vẫn nhận video đó; hết 1 giờ hoặc có tiến triển → giao lại bình thường.
3. Release không phải lỗi không bị đếm. Full suite PASS (kể cả `-m slow` nếu test worker liên quan — Test policy project-profile §8).

## Required verification

- Tests liên quan (`tests/test_enhance*.py`, test worker) với `env PYTHONPATH=/home/ntnghia/youtube-auto-short-cudafix/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q <files> -x --tb=short`.
- Cùng prefix `-m pytest -q -n auto`; `-m pytest -q -n auto -m slow` (sửa `tools/enhance_worker/`); `node scripts/framework-check.mjs`; `git diff --check`.

## Manual test checklist (Tech Lead)

Không chạm database / security / public API.

- [ ] Sau deploy server + copy `worker.py` mới lên 3090 / 3050: log không còn lặp release cùng video.

## Result

- Main changes:
- Tests:
- Review:
- Known limitations:
- PR:
