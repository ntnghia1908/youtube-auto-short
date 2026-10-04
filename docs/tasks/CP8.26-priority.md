# Task: CP8.26 — Ưu tiên tập / bộ kinh trong hàng đợi

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `0e0581f` (`main`) / `feature/cp8.26-priority` (worktree `../youtube-auto-short-prio`). Bắt đầu sau khi FIX-youtube-botcheck-wait merge (chung `web/jobs.py`, `static/app.js`): rebase lên `main` mới rồi mới implement.
- Human Lead approval: APPROVED 2026-10-04 ("nên có chế độ ưu tiên" + "Đồng ý" phạm vi ORCHESTRATOR đề xuất cùng ngày)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: thêm thao tác sắp lại hàng đợi trong khuôn làn CP8.10 / CP8.22 và thứ tự lease CP13.2; không đổi dependency, security model, public API của worker.

## Bối cảnh

2026-10-04: làn `prepare` có ~93 tập Địa Tạng ("Chuẩn bị + HD", ~40 giờ); 13 video bộ khác bị lỗi YouTube chặn bot phải chèn lên đầu bằng cách sửa tay `.web_queue.json` khi server tắt. HUMAN LEAD muốn làm việc đó trên web.

## Goal

Nút "Ưu tiên" cho một tập và "Ưu tiên cả bộ" cho bộ kinh: các job đang chờ của tập / bộ đó lên đầu mọi làn (`prepare`, `ai`, `render`) và GPU enhance nhận các tập đó trước; "Bỏ ưu tiên" trả về thứ tự thường. Bền qua khởi động lại.

## Scope

- In scope:
  - **P1 Đánh dấu ưu tiên** theo tập (Short + khai thị cùng video) — lưu bền (ví dụ trong `.web_queue.json` hoặc file nhẹ trong `work/<id>/`), sống qua khởi động lại.
  - **P2 Hàng đợi.** Mỗi làn chọn job ưu tiên trước (giữ thứ tự tương đối giữa các job ưu tiên — thứ tự bấm, rồi số tập — và giữa các job thường); job đang chạy không bị ngắt. Job ưu tiên sinh ra sau (ví dụ "Chạy tiếp" tập đã đánh dấu) cũng ưu tiên. Không phá các luật hiện có: tạm dừng toàn cục (CP8.22), đợi GPU (FIX-ollama-wait), đợi YouTube (FIX-youtube-botcheck-wait), prefetch làn `prepare`.
  - **P3 Enhance.** `lease()`: "đợi HD" trước (như CP13.1b), rồi tập ưu tiên, rồi thứ tự CP13.2 (bộ + số tập).
  - **P4 UI.** Nút ở dòng tập (trang bộ kinh, trang tập lẻ) và "Ưu tiên cả bộ" / "Bỏ ưu tiên cả bộ" ở trang bộ kinh; nhãn "Ưu tiên" trên tập; trạng thái hàng đợi (nếu có) phản ánh thứ tự mới.
  - Test + README / hướng dẫn nếu có.
- Out of scope: ngắt job đang chạy; nhiều mức ưu tiên; đổi số worker làn.

## Authority / key decisions

- `docs/tasks/CP8.10-queue-lanes.md`, `docs/tasks/CP8.22-queue-pause-persist.md`, `docs/tasks/CP13.1b-enhance-vm.md`, `docs/tasks/CP13.2-hd-first.md`, `docs/tasks/FIX-ollama-wait.md`, `docs/tasks/FIX-youtube-botcheck-wait.md`.

## Acceptance Criteria

1. Làn có job A, B, C (thường); đánh dấu C ưu tiên → job kế tiếp là C, rồi A, B.
2. "Ưu tiên cả bộ" với 3 tập trong 100 job chờ → 3 tập (Short + khai thị) lên đầu theo số tập; "Bỏ ưu tiên cả bộ" → về thứ tự cũ.
3. Job đang chạy không bị ngắt; tạm dừng / đợi GPU / đợi YouTube vẫn đúng với job ưu tiên.
4. Lease enhance: đợi HD > ưu tiên > thứ tự bộ + số tập.
5. Khởi động lại: đánh dấu và thứ tự ưu tiên khôi phục.
6. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–6.
- `node scripts/framework-check.mjs`.
- Chạy thật trên server test 8081 (bản sao dữ liệu nhỏ, enhance tắt hoặc token giả, không đụng 8080): đánh dấu ưu tiên một tập giữa hàng đợi đang tạm dừng → thứ tự trong API đúng.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080: bấm "Ưu tiên" một tập Địa Tạng ở cuối hàng → tập đó chạy ngay sau job hiện tại.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
