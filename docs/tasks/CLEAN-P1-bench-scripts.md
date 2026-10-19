# Task: CLEAN-P1 — Xóa script bench / đo một lần

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — việc cơ học (xóa file + sửa pointer), effort `medium`; Sonnet subagent `implementer` nếu quota Codex vượt ngưỡng
- Authorization mode: task
- Authorization source: `docs/audit/code-growth-report.md` mục P1 (PR #113); HUMAN LEAD chọn P1 ngày 2026-10-19
- Parallel group: —
- Owned paths: `scripts/{cp11_bench,measure_doc_cut_title,enhance_quality_bench,enhance_bench_win,cp13_e1_bench,cp133_compare,sutra_pdf_measure}.py`, `scripts/enhance_quality_win.ps1`, `tools/measure_adaptive_boundary.py`, `docs/guides/enhance-gpu-windows.md`, `docs/guides/enhance-quality-gpu-windows.md`, `docs/decisions/{CP11-performance-data,CP8.20-doc-cut-title-report,CP13-enhance-report,CP13.3-enhance-quality-report,CP13.1-enhance-worker-contract,SR1-sutra-reader-contract}.md`, `docs/ai/project-profile.md` (dòng `sutra/`), comment trong `tools/enhance_worker/{srvgg,face,worker}.py`, file này
- Dependencies: none
- Base commit / branch: `240003f` (origin/main) / `chore/p1-remove-bench`
- Human Lead approval: accepted 2026-10-19 (chat)
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Bỏ ≈ 3,6k dòng script đo một lần khỏi cây làm việc. Số liệu đã đo vẫn nằm trong các report ở `docs/decisions/`. Ai cần chạy lại thì lấy script từ Git theo commit ghi trong report.

## Scope

- In scope:
  - Xóa 9 file (3620 dòng): `scripts/cp11_bench.py` 1163, `measure_doc_cut_title.py` 677, `enhance_quality_bench.py` 540, `enhance_quality_win.ps1` 147, `enhance_bench_win.py` 338, `cp13_e1_bench.py` 312, `cp133_compare.py` 312, `sutra_pdf_measure.py` 89, `tools/measure_adaptive_boundary.py` 42.
  - Xóa 2 hướng dẫn chỉ phục vụ đo: `docs/guides/enhance-gpu-windows.md` (CP13 E2), `docs/guides/enhance-quality-gpu-windows.md` (CP13.3). Giữ `enhance-worker-windows.md` (vận hành worker).
  - Trong 6 decision/report nêu trên: đổi dòng "Script" / "Hướng dẫn" thành pointer `đã xóa ở CLEAN-P1; lấy lại: git show 240003f:<path>`. Số liệu, kết luận giữ nguyên.
  - CP13.3 report §7 mục 6 ("chạy `enhance_quality_win.ps1` để có số GPU"): ghi chú đã lỗi thời vì CP13.4 đã ship GFPGAN; script lấy lại từ Git nếu cần.
  - `project-profile.md` dòng `sutra/`: bỏ nhắc `scripts/sutra_pdf_measure.py`.
  - `tools/enhance_worker/{srvgg,face,worker}.py`: comment "chép từ `scripts/...`" thêm `(đã xóa, xem git 240003f)`. Không đổi code.
- Out of scope:
  - Task contract cũ trong `docs/tasks/` và `docs/audit/` (file lịch sử, không sửa).
  - `scripts/codex-usage.py`, `token-audit.py`, `framework-check.mjs`, `theme_index_preview_fixture.py` (còn dùng).
  - P2 / P3 (gộp helper, fixture test chung, code chết trong `src/`).
  - Quy tắc "bench không commit vào `scripts/`" cho task sau: thuộc framework F1–F3 / upgrade riêng.

## Authority / key decisions

- Report audit P1 xác nhận các script này không được `src/` / `tests/` dùng (kiểm lại bằng `rg` trong AC2).
- Quyết định cục bộ S1: pointer theo commit `240003f` thay vì giữ bản sao; không thêm thư mục `archive/`.

## Implementation approach

- `git rm` 11 file; sửa pointer bằng Edit tay, từng dòng. Không đổi số liệu trong report.

## Acceptance Criteria

1. 11 file trong scope không còn trong cây làm việc; `git show 240003f:<path>` lấy lại được từng file.
2. `rg` theo tên 9 script + 2 guide, loại `docs/tasks/**`, `docs/audit/**`: mọi kết quả còn lại đều là pointer có `CLEAN-P1` hoặc `240003f`.
3. Diff chỉ xóa dòng ngoài các dòng pointer/comment trong Owned paths; không đổi file `src/`, `tests/`, config.
4. Test enhance worker vẫn đạt (comment đổi trong `tools/enhance_worker/`).

## Required verification

- `git diff --stat origin/main` + `git status --short` — AC1, AC3 (inventory ⊆ Owned paths).
- `for p in <11 path>; do git show 240003f:$p > /dev/null; done` — AC1.
- `rg -n -e cp11_bench -e measure_doc_cut_title -e enhance_quality_bench -e enhance_quality_win -e enhance_bench_win -e cp13_e1_bench -e cp133_compare -e sutra_pdf_measure -e measure_adaptive_boundary -e enhance-gpu-windows -e enhance-quality-gpu-windows --glob '!docs/tasks/**' --glob '!docs/audit/**' --glob '!work/**' .` — AC2.
- `python -m pytest -q tests/test_enhance_worker.py tests/test_enhance_face.py` (env `auto-short`) — AC4.
- `node scripts/framework-check.mjs` — docs vẫn hợp lệ.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract. Manual test là điểm danh.

- [ ] Liếc diff: chỉ xóa file + đổi dòng pointer.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
