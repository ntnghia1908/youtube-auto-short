# Task: FIX-post-doc-no-gpu — Bài từ văn bản gốc không đợi GPU

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; sửa job runner, cần review diff riêng.
- Base commit / branch: `853f60a` (`feature/cp8.19-post-doc-source`, CP8.19 PR #48 chưa merge — xếp chồng; rebase lên `main` sau khi #48 merge) / `fix/post-doc-no-gpu` (worktree `../youtube-auto-short-postgpu`)
- Human Lead approval: accepted (HUMAN LEAD 2026-10-02: APPROVE FIX-post-doc-no-gpu, F1–F4; không đụng server 8080 trong lúc làm)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì sửa luật đã duyệt `docs/tasks/FIX-ollama-wait.md` O5 (preflight trước mọi job `post`; chỉ job `add` không đợi khi `gpu_down`) — canonical job model `docs/decisions/CP8.3-web-contract.md` W5. Không đổi API, schema, UI, dependency.

## Bối cảnh

CP8.19 Known limitations: job `post` chạy preflight Ollama trước khi soạn, nên khi GPU / Ollama tắt (`gpu_down`) job đợi GPU dù mọi Short lấy được từ văn bản gốc (`origin: doc`, không gọi AI).

## Goal

GPU tắt: bài lấy được từ văn bản gốc vẫn được soạn ngay; chỉ những Short cần AI mới đợi GPU. Không Short nào cần AI → job xong, không preflight.

## Scope

- In scope: `post/stage.compose_posts` gọi preflight **trễ** (ngay trước lần gọi AI đầu tiên, qua callback); `PostComposeTarget` truyền preflight theo cách đó; job runner cho job `post` chưa chạy lượt nào được lấy ra khi `gpu_down` (như job `add`); ghi chú sửa đổi O5 ở `docs/tasks/FIX-ollama-wait.md`, pointer CP8.3 W5, CP8.15 P1.
- Out of scope: đổi làn của job `post`; job `post` đợi sau job `pipeline` khi GPU bình thường (thứ tự FIFO làn `ai` giữ nguyên); `serial` mode ngoài phần preflight trễ.

## Quyết định (HUMAN LEAD 2026-10-02: APPROVE)

- **F1. Preflight trễ.** `compose_posts` nhận `before_ai: Callable[[], None] | None`; gọi đúng một lần trước lần gọi AI đầu tiên của job (Short đầu tiên không lấy được từ văn bản). Lỗi của nó (`OllamaUnavailable`, `PreflightError`) lan ra như hiện nay. Bài `doc` đã ghi trước đó được giữ (mỗi Short ghi `posts.json` riêng, như CP8.15 P7). Không Short nào cần AI → không gọi preflight.
- **F2. `PostComposeTarget`.** Không preflight ở đầu job nữa; truyền `before_ai` = preflight hiện tại (`run_preflight(job, …)`). `OllamaUnavailable` → `GpuUnavailable` như cũ: job về đầu hàng `ai`, đợi GPU (O5); lần chạy lại tính lại danh sách Short (Short `doc` đã có bài thì `auto` bỏ qua; danh sách clip cụ thể thì soạn lại từ văn bản — không gọi AI, rẻ).
- **F3. Runner khi `gpu_down`.** Trong hàng `ai`, ngoài job `add`, job `post` **chưa chạy lượt nào** được lấy ra chạy ngay (thứ tự: `add` trước, rồi `post`, theo FIFO). Job `post` đã về hàng do `GpuUnavailable` thì đợi như mọi job khác (không quay vòng mỗi lần kiểm).
- **F4. Serial mode.** Cùng preflight trễ F1 (không đợi; lỗi → `failed` như cũ).

## Acceptance Criteria

1. `gpu_down`, job `post` mà mọi Short gióng được văn bản → job `done` ngay, không gọi preflight, không gọi AI.
2. `gpu_down`, job `post` có cả Short `doc` và Short cần AI → bài `doc` được ghi; job về đầu hàng `ai` (`gpu_wait`) ở Short đầu tiên cần AI; GPU có lại → job chạy tiếp, soạn nốt Short cần AI, không soạn lại bằng AI Short `doc`.
3. Job `post` đã về hàng vì `GpuUnavailable` không được lấy ra lại khi `gpu_down` cho tới lần kiểm GPU kế tiếp (không vòng lặp bận).
4. GPU bình thường: tập không có văn bản → preflight vẫn chạy trước lần gọi AI đầu tiên; hành vi FIX-ollama-wait O1–O8 khác không đổi; job `add` vẫn không đợi.
5. Toàn bộ suite PASS.

## Required verification

- `python -m pytest -q -n auto tests/test_web_post_doc_cp819.py tests/test_web_ollama_wait*.py tests/test_post_*.py` (+ test mới cho AC 1–3) — AC 1–4.
- `python -m pytest -q -n auto` — AC 5.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API. Manual test là điểm danh sau automated verification (8080): khi GPU tắt, bấm "Soạn lại" một bài của tập có văn bản gốc → bài cập nhật ngay, không hiện "đợi GPU".

- [ ] GPU tắt → "Soạn lại" bài tập có văn bản gốc xong ngay.

## Result

- Main changes: `post/stage.compose_posts(before_ai=…)` gọi preflight đúng một lần trước Short đầu tiên cần AI (F1); `PostComposeTarget` bỏ preflight đầu job, truyền `before_ai` (F2, cả serial F4); `Job.requeued` + `_take_locked` khi `gpu_down` lấy job `add`, rồi job `post` chưa về hàng lần nào (F3). Tài liệu: ghi chú O5 trong `docs/tasks/FIX-ollama-wait.md`, pointer CP8.3 W5, CP8.15 P1.
- Tests: 5 test mới `tests/test_ollama_wait_runner.py` (AC 1–4, F4) + test `before_ai` trong `tests/test_post_doc.py`; fake compose cũ (4 test runner, `FakeComposeAI` CP8.15) nhận `before_ai`. Toàn bộ `python -m pytest -q -n auto` 1324 passed, 1 skipped (ORCHESTRATOR chạy lại); framework-check PASS.
- Review: round 1 ACCEPTED, không có blocking finding.
- Important findings / decisions: không.
- Known limitations: khi GPU bình thường, job `post` vẫn đợi sau job `pipeline` trong làn `ai` (FIFO, ngoài scope). Manual test (GPU tắt trên 8080): chưa chạy; 8080 chưa đổi bản (HUMAN LEAD 2026-10-02: không đụng 8080).
- PR:
