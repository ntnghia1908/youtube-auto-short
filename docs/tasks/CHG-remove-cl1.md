# Task: CHG-remove-cl1 — Gỡ ứng dụng Chinese Learning (CL1) khỏi repository

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — việc xóa tự chứa, danh sách file rõ; quota 2026-10-19: 5 giờ 31 %, tuần 24 % (dưới ngưỡng)
- Authorization mode: task
- Authorization source: HUMAN LEAD 2026-10-19 (session này): "gỡ hẳn CL1 (Chinese Learning) khỏi repo"
- Parallel group: —
- Owned paths: `src/auto_short/learning/` (xóa), `src/auto_short/cli.py`, `src/auto_short/config.py`, `src/auto_short/workspace.py`, `tests/test_learning_*.py`, `tests/learning_helpers.py`, `tests/fixtures/learning/` (xóa), `tests/test_config.py`, `tests/test_workspace.py`, `config.example.toml`, `README.md`, `docs/ai/project-profile.md`, `docs/decisions/CL1-chinese-learning-contract.md`, `docs/decisions/CP2-workspace-contract.md`, `docs/tasks/CL1*.md`, `docs/tasks/CHG-remove-cl1.md`, `docs/workflow/current-state.md`
- Dependencies: none (PR #106 chỉ sửa `docs/workflow/current-state.md`; nếu merge trước thì rebase)
- Base commit / branch: `main` `1cdce32` → `chore/remove-cl1`
- Human Lead approval: accepted 2026-10-19 (session)
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

Repository không còn ứng dụng Chinese Learning: không còn package `learning`, lệnh `auto-short learn`, section config `[learning]`, test learning, và tài liệu ghi rõ HUMAN LEAD đã bỏ CL1 / G6A / G6B. Auto Short, Đọc Kinh, Khai thị, ghép theo chủ đề không đổi behavior. Các nhánh CL1 / G6A (local + GitHub, gồm commit local `d430152`) bị xóa.

## Scope

- In scope:
  - Xóa `src/auto_short/learning/`, `tests/test_learning_*.py`, `tests/learning_helpers.py`, `tests/fixtures/learning/`.
  - `cli.py`: bỏ import `cmd_learn`, subparser `learn`, nhánh dispatch.
  - `config.py`: bỏ `LearningConfig`, field `Config.learning`, `_learning`. File config cũ còn `[learning]` vẫn load được (section lạ bị bỏ qua như hiện nay).
  - `workspace.py`: bỏ tham số `downstream` của `run_stage` / `mark_downstream_stale` (chỉ learning dùng); trở về đúng CP2 D6. `tests/test_workspace.py`: bỏ test `downstream`; `tests/test_config.py`: bỏ `test_learning_config` + case `[learning]`.
  - `config.example.toml`: bỏ `[learning]`. `README.md`: bỏ mục "Chinese Learning".
  - Docs: `CL1-chinese-learning-contract.md` → Status `ACCEPTED (chỉ C0, C1 …) — phần ứng dụng WITHDRAWN` (checker chỉ nhận PROPOSED / ACCEPTED / SUPERSEDED); **C0 và C1 (quy ước host / application) giữ hiệu lực** vì SR1 / SR2 dựa vào; phần còn lại (C2–C12, gate G4/G6) là lịch sử. `CL1-*.md` / `CL1.*.md` trong `docs/tasks/` (gồm roadmap, G6A / G6B) → giữ Status (checker chỉ nhận DRAFT / APPROVED / IN_PROGRESS / READY), thêm banner `ABANDONED — HUMAN LEAD bỏ CL1 2026-10-19`. `CP2-workspace-contract.md`: sửa đổi CL1.1 (`downstream`) ghi "đã gỡ bởi CHG-remove-cl1". `project-profile.md`: bỏ Chinese Learning khỏi mô tả host, dòng module `learning/`, mục CL1 trong danh sách authority (trỏ C1 còn hiệu lực).
  - Nhánh: xóa local `feature/cl1-chinese-learning`, `docs/cl1-post-cl12-state`, `docs/g6a-evidence-profile`, `docs/g6a-experiment-design` (chứa `d430152`, chưa push); xóa remote `feature/cl1-chinese-learning`, `feature/cl1.2-lesson`, `docs/cl1-roadmap`, `docs/cl1-post-cl12-state`, `docs/g6a-evidence-profile`, `fix/cl1-roadmap-framework-check`. Trước khi xóa: `git bundle` toàn bộ các nhánh này vào `~/.local/share/auto-short/cl1-branches-2026-10-19.bundle` (ngoài repo, khôi phục được). Xóa nhánh chỉ sau khi PR gỡ CL1 đã merge.
  - `docs/workflow/current-state.md`: dòng CL1 → đã gỡ.
- Out of scope:
  - Tên thư mục hệ thống `_learning` trong luật id (CP2 / `tests/test_youtube_id_dash.py`): giữ nguyên — vô hại, tránh đụng luật id.
  - `framework.config.json` (danh sách task legacy): file CL1 vẫn còn nên giữ nguyên.
  - Task doc lịch sử khác nhắc CL1 (`FIX-ollama-wait`, `SR1.1`, `CP8.12`, `FIX-youtube-id-dash`), `docs/decisions/assets/cl12-sample-20.md`: không sửa (lịch sử).
  - Dữ liệu runtime `work/_learning/` (hiện không tồn tại), model Ollama, dependency (CL1 không thêm dependency).

## Authority / key decisions

- HUMAN LEAD 2026-10-19: bỏ CL1, gỡ code + nhánh.
- Quyết định cục bộ S1 (đề xuất, HUMAN LEAD duyệt cùng contract): (a) giữ CL1 C0/C1 làm canonical owner quy ước host / application; (b) gỡ `downstream`; (c) bundle sao lưu nhánh trước khi xóa.
- Config hash các stage Auto Short tính trên `used_config` từng stage → bỏ `[learning]` không làm stage nào chạy lại.

## Implementation approach

- IMPLEMENTER (Codex, effort medium) làm phần code + test + `config.example.toml` / `README.md` trong worktree `../youtube-auto-short-cl1rm`; ORCHESTRATOR sửa docs, chạy full suite, review, bundle + xóa nhánh sau merge.

## Acceptance Criteria

1. `src/auto_short/learning/`, test / fixture / helper learning không còn; `grep -rn "learning" src tests` chỉ còn `_learning` trong luật id và chuỗi không liên quan.
2. `auto-short --help` không còn lệnh `learn`; `auto-short learn x` báo lỗi argparse.
3. `config.from_dict({"learning": {...}})` không lỗi; `Config` không còn field `learning`.
4. `run_stage` / `mark_downstream_stale` không còn tham số `downstream`; behavior CP2 D6 không đổi.
5. Docs theo Scope; `node scripts/framework-check.mjs` đạt.
6. Full suite đạt; 8080 khởi động lại được với code mới (sau khi HUMAN LEAD đồng ý restart).
7. Bundle sao lưu tồn tại và `git bundle verify` đạt trước khi xóa nhánh; sau đó `git branch -a` không còn nhánh CL1 / G6A.

## Required verification

- `python -m pytest -q -n auto` — AC1, 3, 4, 6.
- `auto-short --help`, `auto-short learn x` — AC2.
- `grep -rn -i "learning" src tests` — AC1.
- `node scripts/framework-check.mjs` — AC5.
- `git bundle verify …`, `git branch -a` — AC7.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API web (chỉ bỏ một lệnh CLI chưa có trên web). Manual test là điểm danh.

- [ ] 8080 sau restart: danh sách tập, một trang bộ kinh, `/sutras` mở bình thường.

## Result

- Main changes: xóa `src/auto_short/learning/` (9 module), 6 test learning + helper + fixture; bỏ lệnh `learn`, `LearningConfig` / `[learning]`, tham số `downstream`; README / `config.example.toml` / docs theo Scope (≈ 2 800 dòng xóa).
- Tests: `python -m pytest -q -n auto` 2166 passed, 1 skipped (96,7 s, ngoài sandbox); `auto-short learn x` → argparse exit 2, `--help` không còn `learn`; `grep -rn -i learning src tests` chỉ còn `_learning` (luật id) + test tương thích config cũ; `node scripts/framework-check.mjs` PASS.
- Review: ORCHESTRATOR review diff Codex, 0 finding. Không chạy reviewer thứ hai (S1, chỉ xóa).
- Important findings / decisions: Codex (gpt-6.1-sol, effort medium) ≈ 50k tokens, 1 vòng, 0 sửa; Codex không chạy được 3 test web trong sandbox (loopback) như dự kiến. Status CL1 contract / task docs theo enum của checker (xem Scope). Config hash stage Auto Short không đổi (`used_config` từng stage).
- Known limitations: bundle + xóa nhánh CL1 / G6A làm sau merge (AC7); restart 8080 cần HUMAN LEAD đồng ý (AC6).
- PR: #107
