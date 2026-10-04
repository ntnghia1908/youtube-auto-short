# Task: CP8.26 — Ưu tiên tập / bộ kinh trong hàng đợi

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `1967217` (`main`, sau FIX-youtube-botcheck-wait) / `feature/cp8.26-priority` (worktree `../youtube-auto-short-prio`)
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

- Main changes: `web/priority.py` (`Priority`: ordered marks per base video id, `.web_priority.json` in the workspace; `<id>.kt`, `#post`, `#hd` share the mark of `<id>`); `JobRunner` takes the best-ranked job of a lane (`_pick` / `_pop`; stable among equal ranks; used by the normal take, the YouTube-wait retry / no-download pick and the GPU-wait add / post pick) and `queue_position` follows it; `EnhanceService._lease_order`: waiting-HD > priority (mark order) > CP13.2 order; API `POST /api/episodes/{id}/priority`, `POST /api/playlists/{id}/priority` (mark = unfinished entries in episode order; unmark = all), `priority` in episode / list / playlist views, `priority_count`; UI: "Ưu tiên" / "Bỏ ưu tiên" on playlist rows, "Tập lẻ" rows and episode page, "Ưu tiên cả bộ" / "Bỏ ưu tiên cả bộ (n)", label "★ ưu tiên".
- Tests: `tests/test_priority_cp826.py` (10 tests, AC1-5); `python -m pytest -q -n auto` = 1479 passed, 1 skipped (117 s); `node scripts/framework-check.mjs` PASS; 8081 real run (copy under `~/.cache/auto-short-cp826-test/`, enhance off, queue paused, jobs a, b, c): mark c via API -> `queue_position` c=1, a=2, b=3, `.web_priority.json` written; server stopped.
- Review: ORCHESTRATOR 2026-10-04 — ACCEPTED, không có blocking finding. Đã kiểm: mọi chỗ lấy job trong làn (thường, đợi YouTube, đợi GPU) đi qua `_pop` theo hạng ưu tiên, ổn định trong nhóm; job đang chạy không bị ngắt; lease: đợi HD > ưu tiên > bộ + số tập; chạy lại 52 test liên quan PASS. Non-blocking: dấu ưu tiên không tự xóa khi tập xong; "Ưu tiên cả bộ" không áp cho tập thêm sau khi cập nhật danh sách.
- Important findings / decisions: marks are kept per video until unmarked (no auto-clear when the video completes); a running job is never interrupted, the mark only affects which queued job starts next. "Ưu tiên cả bộ" skips unavailable / deleted / complete entries and does not follow episodes added by a later refresh.
- Known limitations: no priority levels; no manual test on 8080 yet (checklist above).
- PR: #67
