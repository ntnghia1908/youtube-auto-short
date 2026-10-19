# Task: AUDIT-code-growth — Audit code phình do agent và đề xuất quy tắc

## Status / Approval

- Status: IN_PROGRESS
- Type: DOC
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: claude-code — subagent `implementer` (Sonnet) quét rộng (trùng lặp, code chết, test) trên Claude Code cloud; Codex không có trên cloud
- Authorization mode: task
- Authorization source: HUMAN LEAD yêu cầu audit 2026-10-19 (phiên FW-TOKEN-01); cần duyệt contract trước khi làm
- Parallel group: —
- Owned paths:
  - `docs/audit/` (báo cáo mới; không sửa `code-growth-evidence.md`, `code-growth-prs.tsv` trừ bổ sung cột khớp task)
  - `docs/tasks/AUDIT-code-growth.md`
- Dependencies: FW-TOKEN-01 (ai-dev-framework PR #10) đã merge — để đề xuất bám quy tắc mới
- Base commit / branch: `39f6c80` / `claude/vigilant-faraday-y4vgxc` (phiên cloud chỉ được push nhánh này; HUMAN LEAD duyệt 2026-10-19)
- Human Lead approval: APPROVED 2026-10-19 — PR đào sâu: #10, #82, #35, #98, #57 (app+ lớn nhất) + CHANGE #74, #78, #72 (#73 / #51 / #55 bỏ vì chủ yếu script bench); cài tạm `vulture` (`pip install --user`), `jscpd` qua `npx`
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

## Goal

HUMAN LEAD biết code thêm vào mỗi task có phần nào thừa (trùng lặp, code chết, test trùng, abstraction không dùng), nguyên nhân nằm ở hành vi agent hay ở yêu cầu task, và nhận đề xuất quy tắc cụ thể để quyết định có cập nhật framework (ai-dev-framework) hay không.

## Scope

- In scope:
  1. Đọc `docs/audit/code-growth-evidence.md` + `code-growth-prs.tsv` (số đo sẵn, gồm số liệu transcript chỉ có trên VM).
  2. Đo trên `src/` + `tests/` + web: code trùng lặp (khối giống nhau, helper viết lại thay vì dùng lại), code chết (hàm / route / tham số không ai gọi), test trùng hoặc test chi tiết implementation, abstraction một lần dùng. Công cụ không cần cài thêm vào dự án nếu chạy được tạm (`pip install --user` / `npx` trong phiên): `vulture`, `jscpd` hoặc script AST nhỏ. Không thêm dependency vào repo.
  3. Đào sâu 5 PR phình nhất (theo `code-growth-prs.tsv`) và 3 PR CHANGE: diff từng PR → phần nào cần thiết, phần nào thừa, nguyên nhân (prompt thiếu chỉ dẫn, contract mở, agent tự thêm phòng hờ, test sinh dư).
  4. Phân loại nguyên nhân: hành vi IMPLEMENTER / prompt delegation / task contract / review của ORCHESTRATOR.
  5. Đề xuất: (a) quy tắc cho framework (canonical owner dự kiến trong `core/docs/ai/workflow.md`, ví dụ ngân sách diff, "xóa code bị thay", tái dùng trước khi viết mới, giới hạn test theo AC); (b) danh sách refactor / xóa cụ thể trong dự án, ước số dòng giảm — chỉ là đề xuất.
- Out of scope: sửa code / test của dự án; sửa ai-dev-framework (task riêng sau khi HUMAN LEAD chọn đề xuất); chạy test cần GPU / Ollama / YouTube.

## Authority / key decisions

- `docs/ai/workflow.md`, `docs/ai/project-profile.md` (module boundary), task contract của các PR được đào sâu.
- Quy tắc token FW-TOKEN-01: `workflow.md` §10 của kit (tra cứu bằng grep / script, không nạp file lớn).

## Implementation approach

- ORCHESTRATOR: đọc evidence, chọn PR đào sâu, giao IMPLEMENTER từng lượt quét có đầu ra số liệu ngắn; tự đọc diff PR được chọn bằng `git show --stat` rồi từng file cần thiết.
- IMPLEMENTER: chạy công cụ quét, trả bảng tổng hợp (file, dòng, loại), không dán output thô dài.
- Báo cáo: `docs/audit/code-growth-report.md` — tóm tắt 1 trang đầu (kết luận, top nguyên nhân, đề xuất xếp theo lợi ích / chi phí), phụ lục số liệu.
- Ngân sách: phiên cloud, tổng chi phí mục tiêu ≤ ~$30; handoff khi context ≥ 250k.

## Phải giữ nguyên

- Toàn bộ code / test / config của dự án (audit chỉ đọc).
- File evidence hiện có (chỉ bổ sung).

## Acceptance Criteria

1. Báo cáo có số đo trùng lặp, code chết, test trùng (công cụ + lệnh chạy lại được) cho `src/`, `tests/`, web.
2. 5 PR phình nhất + 3 PR CHANGE có phân tích cần thiết / thừa và nguyên nhân.
3. Mỗi nguyên nhân gán vào một nhóm (IMPLEMENTER / prompt / contract / review) có dẫn chứng.
4. Đề xuất quy tắc framework có canonical owner dự kiến, cách đo hiệu quả (vd. tỉ lệ xóa / thêm, dòng viết / dòng thay trong `code-growth-evidence.md`), và đề xuất refactor dự án có ước lượng.
5. Không file ngoài Owned paths bị sửa; `node scripts/framework-check.mjs` PASS.

## Required verification

- `node scripts/framework-check.mjs` — AC5.
- `git diff --stat main...` chỉ trong Owned paths — AC5.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract.

- [ ] HUMAN LEAD đọc tóm tắt, chọn đề xuất framework / refactor nào thành task tiếp.

## Result

- PR:
