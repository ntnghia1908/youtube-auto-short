# Task: TC-AIQ2 — Đề xuất chủ đề TC2 đủ 30–40 phút (6–8 clip) thay vì 3 clip

## Status / Approval

- Status: DRAFT
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — đổi prompt / validator / một vòng AI bổ sung trong một module tự chứa có test fake-Ollama sẵn, effort `high`; Sonnet subagent `implementer` nếu quota Codex vượt ngưỡng (`.claude/rules/execution.md`)
- Authorization mode: boundary
- Authorization source: `docs/decisions/TC1-TC3-implementation-authorization.md` (ACCEPTED 2026-10-18) §2 / §4 ("Prefer a 30–40 minute natural playlist of approximately 5–10 distinct 5–7 minute clips"); follow-up "Known limitations" của `docs/tasks/TC-AIQ-theme-ai-quality.md`
- Parallel group: —
- Owned paths: `src/auto_short/theme_plan/__init__.py`, `tests/test_theme_plan.py`, file này
- Dependencies: TC-AIQ (#127, đã merge)
- Base commit / branch: `2e0d125` (origin/main) / `feature/tc-aiq2`
- Human Lead approval: inherited from boundary (§1); D2 pending — chuyển `Implementation authorized` sang YES khi HUMAN LEAD chốt D2
- Implementation authorized: NO

Lifecycle: `boundary` mode = `DRAFT → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ đổi prompt / schema AI / validator và artifact nội bộ `theme_proposals.json` theo hướng tương thích (thêm trường); không route / API / dependency mới; không đổi TC1 nên `input_fingerprint` và plan đã duyệt không đổi.

## Bối cảnh — bằng chứng (2026-10-24, ORCHESTRATOR, đọc read-only dữ liệu thật)

Playlist `PLOynZc0cJJfA6C9mATbfggiF7ATJmwSJa`: `theme_index.json` 108 favorite, 39 indexed (`tc1-v4`), 10 tập, tổng 185,3 phút, trung bình 285 s / clip; `theme_proposals.json` `tc2-v4` (2026-10-20):

| Theme | Clip | Tập | Phút | Status |
|---|---|---|---|---|
| Trung đạo và đạo lý trung thành | 3 | 2 | 17,4 | short |
| Nhân quả và đạo đức | 3 | 3 | 12,6 | short |
| Tu hành chân thật | 3 | 2 | 16,1 | short |
| Giáo dục đạo đức và đạo hiếu | 3 | 3 | 12,9 | short |
| Tâm và bản tính | 3 | 3 | 13,1 | short |

- 5/5 theme `short`, đúng 3 clip mỗi theme, 15/39 clip được dùng; `dropped_for_length = 0` → model chọn ít, không phải code cắt.
- `SYSTEM` prompt TC2 không nêu thời lượng mục tiêu, số clip, hay rằng một clip được phép xuất hiện ở nhiều theme; payload có `duration_s` từng clip nhưng không có tổng mục tiêu.
- Topic TC1: 39 nhãn khác nhau cho 39 clip; subtopic null 37/39 → tín hiệu gom nhóm chủ yếu là synopsis + key message (đã đủ ý sau TC-AIQ).
- Đổi `PROMPT_VERSION` TC2 không làm plan stale (stale chỉ theo TC1 `input_fingerprint`, `theme_plan._check`); 3 plan hiện có giữ nguyên.

## Goal

Chạy "Đề xuất chủ đề" trên playlist thật cho đa số theme `ok` (tổng 1800–2400 s, ≈ 6–8 clip, từ ≥ 3 tập khi dữ liệu cho phép) thay vì 3 clip `short`; khi không đủ clip cùng ý, theme vẫn `short` và báo thiếu bao nhiêu (không độn clip lạc đề).

## Scope

- In scope:
  - Prompt TC2: nêu mục tiêu tổng `duration_s` 1800–2400 s (≈ 6–8 clip), ưu tiên ít theme mà đủ dài hơn nhiều theme ngắn, cho phép một clip có ở nhiều theme, không thêm clip lạc đề chỉ để đủ giờ; payload kèm `target_seconds` {min, max}. Bump `tc2-v5`.
  - **Vòng bổ sung (D2):** với mỗi theme hợp lệ còn `short`, gọi AI thêm **một** lần: gửi label, rationale, clip đã chọn (theo thứ tự) và các clip ứng viên còn lại (không trùng), yêu cầu trả danh sách id thêm vào + vị trí chèn (hoặc thứ tự mới đầy đủ); schema `enum` id ứng viên (bài học `pitfall-ollama-id-enum`). Code kiểm id, không trùng, giữ clip cũ, cắt ở `TARGET_MAX`; lỗi / output lạ → giữ nguyên theme vòng 1, ghi `fill_error`. Tiêu đề TC2.2 giữ của vòng 1.
  - Proposal thêm `filled_count` (số clip vòng bổ sung thêm vào) để HUMAN LEAD thấy.
- Out of scope: TC1 (topic / subtopic / synopsis, prompt `tc1-v4`), model / `think` / tốc độ; UI / route / API; thuật toán chọn clip tất định không qua AI (embedding, clustering); đổi `TARGET_MIN` / `TARGET_MAX` / `MAX_THEMES`; plan / MP4 đã có.

## Authority / key decisions

- Boundary TC1–TC3 §2 / §4 (30–40 phút, 5–10 clip, không độn / lặp, báo shortfall); `docs/tasks/TC2-theme-compilation-planner.md`; `docs/tasks/TC-AIQ-theme-ai-quality.md`.
- Local S1: clip được dùng lại giữa các theme (HUMAN LEAD chọn một proposal để tạo plan; trùng giữa theme đã được validator cho phép, chỉ cấm trùng trong một theme).
- **D2 (HUMAN LEAD — pending):** bật vòng bổ sung. Chi phí: tối đa `MAX_THEMES` = 5 lần gọi qwen3:30b thêm cho mỗi lần "Đề xuất chủ đề" (ước 1–3 phút / lần với `think`, tức job từ vài phút lên tới ≈ 10–15 phút khi mọi theme đều short). Không bật → chỉ đổi prompt, rẻ nhưng qwen3 dễ phớt lờ yêu cầu số lượng. Đề xuất: bật.

## Implementation approach

1. Prompt + payload `target_seconds`; quy tắc "fewer complete themes", "clip may appear in several themes", "never pad with off-topic clips".
2. `_fill_theme(...)`: một lần gọi / theme short, schema enum id ứng viên, validator thuần code; ghép kết quả qua `_build_proposal` hiện có để giữ logic cắt / `status` / `shortfall_seconds`.
3. Tests fake-Ollama cho prompt / payload, fill thành công, fill lỗi / id lạ / trùng, theme đã `ok` không gọi fill; ORCHESTRATOR chạy full suite + propose thật.

## Phải giữ nguyên

- Code (không phải AI) quyết định id hợp lệ, trùng, cắt `TARGET_MAX`, `status`, `shortfall_seconds`; output AI lạ không làm hỏng file proposals cũ.
- Shape proposal hiện có (`proposal_id`, `label`, `rationale`, `clips`, `episode_count`, `total_duration`, `status`, `shortfall_seconds`, `dropped_for_length`, `speaker`, `titles`, `title_rejected`) — chỉ thêm trường; web TC2.3 đọc như cũ.
- Plan / approval / stale logic, `create_plan` / `approve_plan` (vẫn yêu cầu `duration_override` khi ngoài 1800–2400 s).
- Payload không `episode_id`, thứ tự xáo theo hash (TC-AIQ); extractive — không sinh lời giảng.
- Không gọi AI thật trong tests.

## Code bị thay / xóa

- Câu `SYSTEM` hiện hành của TC2 phần gom nhóm (thay bằng bản có mục tiêu thời lượng); phần tiêu đề TC2.2 giữ nguyên.
- Tests khẳng định `prompt_version == 'tc2-v4'` — cập nhật `tc2-v5`.

## Acceptance Criteria

1. Prompt / payload gửi AI có mục tiêu 1800–2400 s và quy tắc mới; `prompt_version` `tc2-v5`; payload vẫn không có `episode_id`.
2. Theme `short` được gọi bổ sung đúng một lần; clip thêm vào hợp lệ, không trùng trong theme, clip vòng 1 giữ nguyên; tổng không vượt `TARGET_MAX`; `filled_count` đúng.
3. Theme đã `ok` không gọi bổ sung; output bổ sung lỗi / id lạ / trùng → theme vòng 1 giữ nguyên + `fill_error`, các theme khác không bị ảnh hưởng.
4. Tests targeted + full suite PASS; framework-check, `git diff --check` PASS; inventory ⊆ Owned paths.
5. Chạy thật (ORCHESTRATOR, 8080 pin commit branch): "Đề xuất chủ đề" trên playlist trên — báo số clip / tập / phút / status từng theme, số clip dùng, thời gian job, so với bảng bối cảnh. Kỳ vọng đa số theme `ok`; đây là bằng chứng cho HUMAN LEAD chấm, không phải ngưỡng PASS tự động về ngữ nghĩa.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_plan.py tests/test_web_theme_plan.py -x --tb=short` — AC1–3.
- Cùng prefix `-m pytest -q -n auto` — full suite (ORCHESTRATOR, ngoài sandbox).
- `node scripts/framework-check.mjs`; `git diff --check` — AC4.
- Propose thật trên 8080 pin vào commit branch — AC5.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract; manual test sau automated verification là điểm danh.

- [ ] "Đề xuất chủ đề" mới: các clip trong từng chủ đề có thật cùng ý, không có clip lạc đề bị độn vào?
- [ ] Chủ đề dài 30–40 phút có nghe hợp lý theo thứ tự đề xuất?

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
