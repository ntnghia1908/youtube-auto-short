# Task: TC-AIQ — Chất lượng AI TC1 / TC2: synopsis là trích đoạn đủ ý, chủ đề không gom theo tập

## Status / Approval

- Status: IN_PROGRESS
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — đổi prompt / validator trong hai module tự chứa có test fake-Ollama sẵn, effort `high`; Sonnet subagent `implementer` nếu quota Codex vượt ngưỡng (`.claude/rules/execution.md`)
- Authorization mode: boundary
- Authorization source: `docs/decisions/TC1-TC3-implementation-authorization.md` (ACCEPTED 2026-10-18) §3 / §4; `docs/workflow/current-state.md` Next action 3
- Parallel group: —
- Owned paths: `src/auto_short/theme_index/__init__.py`, `src/auto_short/theme_plan/__init__.py`, `src/auto_short/web/static/theme_index.js` (chỉ hàm `ref` / nhãn tóm tắt), `tests/test_theme_index.py`, `tests/test_theme_plan.py`, `tests/test_web_theme_index.py`, file này
- Dependencies: TC1 (#96), TC2 / TC2.3 (đã merge)
- Base commit / branch: `4cc0ed3` (origin/main) / `feature/tc-aiq` (contract từ `docs/task-tc-ai-quality`)
- Human Lead approval: inherited from boundary; D1 accepted 2026-10-19 (chat "Chốt D1")
- Implementation authorized: YES

Lifecycle: `boundary` mode = `DRAFT → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ đổi prompt, validator và artifact nội bộ `theme_index.json` / `theme_proposals.json` theo hướng tương thích (giữ khóa `evidence_id` + `text`); không route / API / dependency mới; vẫn extractive — không sinh lời giảng (boundary §2).

## Bối cảnh — bằng chứng (2026-10-19, ORCHESTRATOR, đọc read-only dữ liệu thật)

Playlist `PLOynZc0cJJfA6C9mATbfggiF7ATJmwSJa`, `theme_index.json`: 106 favorite, 37 indexed (`tc1-v2`), `theme_proposals.json` (`tc2-v3`).

- **Synopsis ngắn do thiết kế, không phải do model.** `validate_metadata` lưu đúng **một** segment Whisper (`synopsis[0]`). Segment evidence: 2638 segment, trung vị 5,5 từ, tối đa 14. Synopsis 37 clip: 0–10 từ (1 rỗng, 7 clip ≤ 5 từ; ví dụ "Là một thể", "Đây chẳng phải là", "Mấu chốt là ở hai chữ này"). Câu prompt "tránh mẩu < 6 từ" không thể thỏa khi segment luôn ngắn.
- **Metadata nghèo:** 5/37 topic `null`, 23/37 subtopic `null`; topic gần như mỗi clip một nhãn riêng.
- **Gom theo tập:** 5 proposal, mỗi proposal chỉ 1–2 tập (3/5, 3/4, 3/4, 2+2, 3/3 clip cùng tập); chỉ 20/37 clip được dùng. `propose()` gửi clip theo thứ tự record (liền nhau theo tập) kèm `episode_id`; tín hiệu nội dung mỗi clip chỉ là topic + synopsis ≤ 10 từ + 5 key message ≈ 5 từ → model bám theo tập.
- **Tốc độ:** qwen3:30b `think=true` ≈ 1–2 phút / clip (current-state). Ngoài scope task này.

## Goal

Re-index playlist thật cho synopsis là một **trích đoạn liền mạch đủ ý** (đa số 20–80 từ) thay vì mẩu 5 từ, và proposal TC2 gom clip theo **nội dung** — nhiều theme có clip từ ≥ 3 tập khi dữ liệu cho phép — mà vẫn chỉ trích nguyên văn transcript.

## Scope

- In scope:
  - TC1: synopsis = dãy evidence **liên tiếp** (AI chọn id đầu + id cuối, hoặc danh sách id liên tiếp); code kiểm liên tiếp theo thứ tự evidence, nối text nguyên văn, bảo đảm ngưỡng từ (mở rộng tất định sang segment kề khi quá ngắn, cắt ở giới hạn trên); prompt yêu cầu topic khi có evidence; bump `PROMPT_VERSION` → `tc1-v3`; validator cache theo shape mới.
  - TC2: payload gửi AI không còn `episode_id`, thứ tự clip tất định nhưng **không** theo tập (ví dụ sort theo hash id); gửi synopsis mới + tối đa 8 key message; prompt nêu rõ gom theo ý dạy, không theo tập; bump `tc2-v4`. Proposal thêm trường đếm số tập (`episode_count`) để HUMAN LEAD thấy độ trộn.
  - UI preview TC1: hiển thị synopsis nhiều segment đúng (id đầu–cuối + text).
- Out of scope: model / `think` / tốc độ AI; tóm tắt abstractive (AI tự viết) — chạm boundary §2 "no synthetic speech"; embedding / vector DB / dependency; đổi eligibility, fingerprint ngoài prompt / schema; TC3 renderer; route / API mới; sửa plan đã duyệt hoặc MP4 đã render.

## Authority / key decisions

- Boundary TC1–TC3 §2–§4; `docs/tasks/TC1-theme-index.md` (extractive, fail closed, cache invalidation), `docs/tasks/TC2-theme-compilation-planner.md`.
- Local S1: synopsis lưu dạng `{"evidence_id": <id đầu>, "evidence_ids": [...], "text": <nối nguyên văn>}` — consumer hiện tại (`theme_plan._snapshot`, `propose`, `theme_index.js`) chỉ đọc `evidence_id` / `text` nên vẫn chạy; ngưỡng từ là hằng số trong module (đề xuất min 20, max 80; IMPLEMENTER chỉnh nếu test dữ liệu thật cho thấy cần).
- **D1 (HUMAN LEAD — ACCEPTED 2026-10-19):** bump prompt version đổi `input_fingerprint` của mọi clip → 2 plan đã duyệt (`d6a874b50e91` "Từ bi là nền tảng của nhân quả", `bddcede7d89d` "Tu hành không phải là hình thức") hiện **stale** trên UI, cần duyệt lại nếu muốn render lại; MP4 đã render giữ nguyên. Re-index thật ≈ 37 clip × 1–2 phút ≈ 40–70 phút GPU Ollama. Đề xuất: chấp nhận.

## Implementation approach

1. TC1: đổi schema AI `synopsis` thành danh sách id liên tiếp (maxItems ~12); `validate_metadata` kiểm id có thật, không lặp, liên tiếp theo vị trí trong `evidence`; không liên tiếp → lấy đoạn liên tiếp dài nhất chứa id đầu + ghi `uncertainty` (không bịa). Nếu < min từ: mở rộng sang segment kề (sau rồi trước) tới ngưỡng; > max: cắt bớt đuôi. `_validate_cached_metadata` kiểm lại đúng text nối từ evidence hiện hành.
2. TC2: build payload không `episode_id`, sort tất định không theo tập; prompt thêm quy tắc nội dung; `_build_proposal` thêm `episode_count`.
3. JS: `ref` hiển thị `evidence_ids` dạng `s12–s15` khi có.
4. Tests fake-Ollama cho mọi nhánh mới; ORCHESTRATOR chạy full suite + re-index thật sau D1.

## Phải giữ nguyên

- Extractive: mọi text synopsis / key message là nguyên văn evidence trong final ranges; output lạ / id bịa → bỏ + `missing_metadata`, không sửa hộ.
- Eligibility, ineligible reason, fail closed stale source / render, cache reuse khi input không đổi.
- Shape đọc của consumer: `metadata.synopsis.evidence_id`, `.text`; `key_messages[]` `{evidence_id, text}`; plan snapshot / stale logic TC2; tiêu đề TC2.2 (`titles`, style A/B, validator).
- Không gọi AI thật trong tests.

## Code bị thay / xóa

- Nhánh "chỉ giữ `synopsis[0]`" trong `validate_metadata` và kiểm `set(ref) == {"evidence_id","text"}` cho synopsis trong `_validate_cached_metadata`.
- Câu prompt "Avoid fragments shorter than 6 words…" (thay bằng quy tắc span).
- Trường `episode_id` trong payload AI của `propose()` (vẫn giữ trong proposal / snapshot).
- Tests khẳng định `prompt_version == 'tc1-v2'` / `'tc2-v3'` và synopsis một segment — cập nhật theo hành vi mới, không xóa phủ test.

## Acceptance Criteria

1. Synopsis là dãy evidence liên tiếp, text = nối nguyên văn; id không có / lặp / không liên tiếp không lọt qua; quá ngắn được mở rộng tất định, quá dài được cắt; clip có ≥ min từ evidence thì synopsis ≥ min từ.
2. Cache `tc1-v2` không được reuse (fingerprint đổi); cache `tc1-v3` hợp lệ được reuse; cache synopsis bị sửa text / id → không tin.
3. Payload TC2 gửi AI không chứa `episode_id`, thứ tự không nhóm theo tập và tất định; prompt mới có quy tắc nội dung; proposal có `episode_count` đúng.
4. UI preview hiển thị synopsis nhiều segment; record cũ một segment vẫn hiển thị.
5. Tests targeted + full suite PASS; framework-check, `git diff --check` PASS; inventory ⊆ Owned paths.
6. Chạy thật (ORCHESTRATOR, sau D1): re-index playlist trên — báo phân bố số từ synopsis (kỳ vọng trung vị ≥ 20, không clip < 10 từ khi có đủ evidence), số topic `null`, và proposal mới: số tập / theme, số clip được dùng. Đây là bằng chứng cho HUMAN LEAD chấm, không phải ngưỡng PASS tự động về ngữ nghĩa.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_index.py tests/test_theme_plan.py tests/test_web_theme_index.py -x --tb=short` — AC1–4.
- Cùng prefix `-m pytest -q -n auto` — full suite (ORCHESTRATOR, ngoài sandbox).
- `node scripts/framework-check.mjs`; `git diff --check` — AC5.
- Re-index + propose thật trên 8080 pin vào commit branch — AC6.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract; manual test sau automated verification là điểm danh.

- [ ] Trang preview chỉ mục chủ đề: đọc 5–10 synopsis — có thành câu đủ ý, đúng nội dung clip?
- [ ] "Đề xuất chủ đề" mới: chủ đề có hợp lý, có trộn nhiều tập, tiêu đề còn ổn?
- [ ] 2 plan cũ hiện stale như D1 dự kiến; MP4 cũ vẫn tải được.

## Result

- Main changes:
- Tests:
- Diff + / − (app, test):
- Helper mới (đã tìm, lý do không tái dùng):
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
