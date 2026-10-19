# Task: FW-token-audit — Script đo token và mốc so sánh

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: single-agent
- Orchestrator: claude-code
- Human Lead: ntnghia1908
- Authorization mode: task
- Authorization source: HUMAN LEAD duyệt trong phiên 2026-10-19 ("Duyệt hết", chọn phương án (a): script nằm trong repo)
- Parallel group: —
- Owned paths: `scripts/token-audit.py`, `docs/tasks/FW-token-audit.md`, `docs/tasks/CHG-current-state-trim.md` (DRAFT)
- Dependencies: none
- Base commit / branch: `91ef68d` / `chore/token-audit`
- Human Lead approval: accepted (2026-10-19)
- Implementation authorized: YES

## Goal

Đo lại được chi phí token của Claude Code theo cùng định nghĩa với đợt đo 2026-10-19, để ngày 2026-10-29 so sánh hiệu quả các quy tắc tiết kiệm đã duyệt.

## Scope

- In scope: `scripts/token-audit.py` (chỉ đọc transcript `~/.claude/projects`, `~/.codex/sessions`, `git log`; in số tổng hợp); mốc số liệu; contract DRAFT rút gọn `current-state.md`.
- Out of scope: sửa `current-state.md` (contract riêng), quy tắc trong kit `ai-dev-framework` (contract FW-TOKEN-01 ở kit), cấu hình Claude Code.

## Authority / key decisions

- single-agent: script đo nhỏ, đã viết và chạy trong phiên phân tích token; giao lại cho IMPLEMENTER tốn token hơn chính thay đổi.
- Chi phí = giá API niêm yết quy đổi (Opus 5.5 $4/$20, Sonnet 5.5 $2/$10, đọc cache $0,20; ghi cache 1h = 2×, 5m = 1,25× input), không phải hóa đơn thuê bao.
- "Cache-expired rewrite" = một lượt ghi cache > 50k token mà đọc cache ít hơn phần ghi.

## Acceptance Criteria

1. `python3 scripts/token-audit.py --since 2026-09-26 --until 2026-10-19` tái tạo mốc bên dưới.
2. Script không in nội dung transcript, chỉ số tổng hợp; không cần dependency mới.

## Mốc (2026-09-26 .. 2026-10-19)

| Chỉ số | Mốc |
|---|---|
| Tổng (giá API quy đổi) | $824 |
| Tỷ lệ subagent | 42 % |
| Đầu vào phiên chính trên 150k / 250k context | 41 % / 23 % |
| Context đỉnh phiên chính (trung vị / p90) | 173k / 347k |
| Ghi lại context do cache hết hạn: phiên chính / subagent | 43 (9,7M) / 190 (34,1M) |
| $/PR merge | 7,8 (cả kỳ); 4,6 (18–19/10, Codex làm IMPLEMENTER) |
| Context cố định đầu phiên (`/context`) | ≈ 38k; `current-state.md` 4,4k |

Đo lại 2026-10-29: `python3 scripts/token-audit.py --since 2026-10-20 --until 2026-10-29`.

## Required verification

- Lệnh ở AC1 — đã chạy, khớp mốc.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract.

- [ ] Chạy lệnh đo lại vào 2026-10-29.

## Result

- Main changes: `scripts/token-audit.py`; contract DRAFT `CHG-current-state-trim.md`.
- Tests: AC1 chạy thật, số khớp đợt đo trong phiên.
- Known limitations: chỉ transcript trên máy này (không gồm claude.ai / thiết bị khác); quota thuê bao không quy được từ giá API.
- PR:
