# Task: CP1 — Product Contract & Architecture Baseline

## Status / Approval

- Status: DRAFT
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `0798a67` / `feature/cp1-product-contract`
- Human Lead approval: pending
- Implementation authorized: NO

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Chốt và ghi lại product contract + architecture baseline của Auto Short (roadmap CP1) thành decision record ACCEPTED, đủ để CP2–CP8 implement mà không phải tự quyết lại.

## Scope

- In scope:
  - `docs/decisions/CP1-product-contract.md`: chuyển từ PROPOSED sang ACCEPTED theo quyết định HUMAN LEAD; ảnh mẫu layout `docs/decisions/assets/cp1-layout-reference.jpg`.
  - `docs/ai/project-profile.md`: cập nhật authority order (trỏ tới decision record), module map theo artifact model, setup/tools theo dependency đã duyệt.
  - `docs/workflow/current-state.md`: focus/open decisions/blockers.
  - `scripts/framework-check.mjs`: kiểm decision record tồn tại và có Status hợp lệ.
- Out of scope:
  - Mọi code pipeline, `pyproject.toml`, cài dependency, config file mẫu (thuộc CP2+).
  - Cài `ffmpeg`/Ollama trên máy.
  - Pixel-level design vượt quá mẫu HUMAN LEAD cung cấp.

## Authority / key decisions

- `AUTO_SHORT_CHECKPOINT_PLAN.md` §3 (core principles), §4 CP1, §5 invariants.
- Mọi quyết định trong `docs/decisions/CP1-product-contract.md` do HUMAN LEAD chốt (pha DECIDE); agent không tự chốt mục "Cần HUMAN LEAD".

## Implementation approach

- DISCUSS: bản đề xuất PROPOSED + open questions.
- DECIDE: HUMAN LEAD trả lời open questions và chấp nhận/sửa từng đề xuất.
- DOCUMENT: ghi quyết định cuối vào decision record, đổi Status ACCEPTED; đồng bộ project profile.

## Acceptance Criteria

1. Decision record có Status `ACCEPTED` và mỗi mục trong roadmap CP1 (input/output contract, duration, 9:16, clip boundaries, title/header, yellow panel, subtitle, artifact model, pipeline boundaries, execution profile, dependency policy, GPU/Ollama) có quyết định cuối, không còn "Cần HUMAN LEAD".
2. Dependency được duyệt nằm trong một danh sách duy nhất (canonical owner = decision record); project profile chỉ trỏ tới.
3. Project profile authority order tham chiếu decision record.
4. `node scripts/framework-check.mjs` PASS và FAIL khi decision record thiếu hoặc Status không hợp lệ.
5. Không có code pipeline hoặc file dependency (`pyproject.toml`, `requirements*.txt`) được thêm.

## Required verification

- `node scripts/framework-check.mjs` → exit 0 (AC4).
- Negative test trên bản copy tạm: xóa decision record / đổi Status sang giá trị lạ → exit 1 (AC4).
- `grep -n "Cần HUMAN LEAD" docs/decisions/CP1-product-contract.md` → không còn kết quả (AC1).
- `git diff --stat main...HEAD` + tree inspection → chỉ file docs/checker trong scope (AC5).
- Diff review theo contract + checklist roadmap CP1 (AC1–AC3).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract. Task là S2 architecture/product decision; manual review là HUMAN LEAD đọc decision record trước integration.

- [ ] Đọc `docs/decisions/CP1-product-contract.md` → mọi mục đúng ý HUMAN LEAD.
- [ ] Chạy `node scripts/framework-check.mjs` → PASS.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
