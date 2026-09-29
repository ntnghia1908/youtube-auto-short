# Task: FW-implementer-speed — Test song song, test policy, IMPLEMENTER dùng Sonnet và làm việc gọn hơn

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `f39c86e` (`main`) / `feature/fw-implementer-speed` (worktree `../youtube-auto-short-fw`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-29: APPROVE TASK; D1–D4 như đề xuất; IMPLEMENTER task này chạy override `sonnet` theo D3)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm dependency (dev), tạo project-wide convention (test policy), đổi adapter Claude Code (model + cách làm việc của IMPLEMENTER). Không đổi Framework Core (`docs/ai/workflow.md`, `docs/ai/execution-profiles.md`), code pipeline, security model hay public API.

## Vấn đề (số liệu 2026-09-29)

Đo trên 22 lần chạy IMPLEMENTER (transcript subagent 2026-09-26 → 29) và 1 lần chạy lại test suite:

| Task | Tổng | Thời gian chạy lệnh | Turn | Số lần chạy pytest | Token đọc từ cache |
|---|---|---|---|---|---|
| CP8.9 | 204 phút | 55 phút | 583 | 24 | 199 M |
| CP8.10 | 196 phút | 184 phút (render / GPU) | 207 | 19 (≈ 25 phút) | 29 M |
| CP8.5 | 100 phút | 38 phút | 355 | 32 (≈ 28 phút) | 94 M |
| CP9 | 140 phút | 37 phút | 278 | 22 (≈ 19 phút) | 87 M |
| CP8.14 | 20 phút | 11 phút | 140 | 11 | 16 M |

- Toàn bộ suite: **898 test, 3 phút 30 giây**, chạy tuần tự (máy 48 core, chưa có `pytest-xdist`). Mỗi task chạy toàn bộ 10–32 lần.
- Phần lớn thời gian còn lại là model sinh turn: IMPLEMENTER đọc file bằng `sed -n` / `cat` qua Bash, mỗi turn một lệnh.
- Chi phí token ≈ độ dài context × số turn (token đọc từ cache chiếm gần hết; output chỉ 1 k–100 k).
- IMPLEMENTER được thiết kế dùng **Sonnet** (HUMAN LEAD 2026-09-29), nhưng `.claude/agents/implementer.md` không khai `model`, nên subagent kế thừa model của session chính (transcript: `claude-opus-5-5` ở mọi lần chạy).

## Goal

IMPLEMENTER hoàn thành cùng loại task nhanh hơn và tốn ít token hơn, mà không nới required verification: toàn bộ suite chạy song song, trong vòng sửa chỉ chạy test liên quan, IMPLEMENTER chạy Sonnet và dùng ít turn hơn.

## Scope

- In scope:
  - `pyproject.toml`: thêm `pytest-xdist` vào extra `dev`.
  - `docs/decisions/CP1-product-contract.md` §10: thêm dòng `pytest-xdist` (dev only) + ghi sửa đổi HUMAN LEAD.
  - `docs/ai/project-profile.md` §8: mục **Test policy** (canonical owner của D2).
  - `.claude/agents/implementer.md`: `model: sonnet` (D3); hướng dẫn làm việc gọn (D4), pointer tới Test policy.
  - `README.md`: lệnh chạy test song song (1–2 dòng).
  - `docs/ai/framework-history.md`: entry dưới `## v4.1` (adapter + project policy; không đổi Core nên không tăng version).
  - `docs/workflow/current-state.md`, Result.
  - Sửa test **chỉ khi** chạy song song lộ ra lỗi cô lập thật (dùng chung đường dẫn / cwd / port / global state); sửa ở tầng fixture để test độc lập, không đổi assert; ghi từng ca ở Result.
- Out of scope:
  - `docs/ai/workflow.md`, `docs/ai/execution-profiles.md` (Framework Core).
  - Marker `slow` / chia nhóm test; tối ưu từng test chậm.
  - Rút gọn `docs/workflow/current-state.md`, rút gọn task contract (S0 / việc riêng).
  - Adapter Copilot làm IMPLEMENTER (task riêng khi có tài khoản).
  - Code pipeline / web.

## Authority / key decisions

- Authority: `docs/ai/workflow.md` §3 (dependency gate), §5, §7; `docs/ai/execution-profiles.md` (profile không nới workflow; adapter quyết cách tool thực hiện profile); `docs/ai/project-profile.md` §4 (không tên model trong Core), §8; CP1 §10.
- Quyết định (đề xuất — HUMAN LEAD duyệt / sửa trước APPROVE):
  - **D1 Dependency `pytest-xdist`:**

    ```text
    Library: pytest-xdist (không pin, như pytest)
    Purpose: chạy toàn bộ suite song song (`-n auto`)
    Why current stack is insufficient: suite tuần tự 3 phút 30 giây, chạy 10–32 lần mỗi task
    Alternative: marker slow + chạy tập con (giảm ít hơn, phải bảo trì marker); giữ nguyên
    Impact: dev only, không vào runtime / extra `[web]`; test phải độc lập giữa các process
    ```

  - **D2 Test policy** (project-wide, `docs/ai/project-profile.md` §8, áp dụng cho mọi IMPLEMENTER bất kể tool):
    - Trong vòng sửa: chạy test liên quan tới thay đổi (file / `-k`), nên dùng `-x --tb=short`.
    - Toàn bộ suite: **một lần** trước khi báo READY và **một lần** sau mỗi vòng fix review; không chạy toàn bộ sau từng lần sửa.
    - Lệnh chuẩn: `python -m pytest -q -n auto`; chạy tuần tự (không `-n`) vẫn hợp lệ.
    - Không nới workflow §7: required verification trong task contract vẫn phải chạy và PASS trước READY.
  - **D3 Model IMPLEMENTER (adapter Claude Code):** `.claude/agents/implementer.md` khai `model: sonnet`. ORCHESTRATOR giữ model của session chính. Task muốn IMPLEMENTER dùng model khác phải ghi trong task contract (HUMAN LEAD duyệt); ORCHESTRATOR khi đó truyền override lúc delegate. Tên model chỉ nằm ở adapter, không vào Core (project-profile §4).
  - **D4 Cách làm việc của IMPLEMENTER (adapter):**
    - Đọc nhiều file / đoạn độc lập trong **cùng một lượt** (tool call song song).
    - Tìm bằng Grep, đọc bằng Read (offset / limit) thay cho `cat` / `sed -n` qua Bash; không đọc lại file chưa đổi.
    - Gom các sửa đổi cùng file vào ít Edit.
    - Lệnh có output dài thì lọc (`| tail -n 20`, `-q`); khi test fail chỉ lấy phần traceback cần thiết.
    - Chạy test theo Test policy (pointer, không chép rule).
    - READY report ngắn: thay đổi chính, verification (lệnh + kết quả), finding ngoài scope, giới hạn.

## Implementation approach

- Cài `pytest-xdist` vào env `auto-short` qua `pip install -e ".[dev]"` sau khi sửa `pyproject.toml`; ghi version cài được ở Result.
- Chạy `-n auto` nhiều lần; test nào fail / flaky chỉ khi song song → tìm nguyên nhân cô lập, sửa fixture (xem Scope).
- Viết D2 ở project-profile, D3 + D4 ở adapter; `framework-check` không cần đổi.

## Acceptance Criteria

1. `pip install -e ".[dev]"` cài `pytest-xdist`; CP1 §10 liệt kê nó (dev only) với ghi sửa đổi HUMAN LEAD.
2. `python -m pytest -q -n auto` PASS **3 lần liên tiếp** với cùng số test như chạy tuần tự, và nhanh hơn rõ rệt (ghi thời gian cả hai cách ở Result).
3. `docs/ai/project-profile.md` §8 có Test policy theo D2; adapter chỉ trỏ tới nó.
4. `.claude/agents/implementer.md` có `model: sonnet` và hướng dẫn D4; không chép rule workflow.
5. `docs/ai/workflow.md`, `docs/ai/execution-profiles.md` không đổi; `docs/ai/framework-history.md` có entry dưới `## v4.1`.
6. `node scripts/framework-check.mjs` PASS.

## Required verification

- `conda run -n auto-short pip install -e ".[dev]"` rồi `python -c "import xdist"` — AC1.
- `PYTHONPATH=<worktree>/src conda run -n auto-short python -m pytest -q` (tuần tự) → toàn bộ PASS, ghi số test + thời gian — AC2.
- `PYTHONPATH=<worktree>/src conda run -n auto-short python -m pytest -q -n auto` × 3 → toàn bộ PASS, cùng số test, ghi thời gian — AC2.
- `git diff main -- docs/ai/workflow.md docs/ai/execution-profiles.md` → rỗng — AC5.
- `node scripts/framework-check.mjs` → exit 0 — AC6.
- `git diff --stat main...HEAD` → chỉ file trong scope.
- Diff review theo contract (AC3, AC4).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract; manual test là điểm danh.

- [ ] Task S1/S2 kế tiếp: transcript IMPLEMENTER ghi model Sonnet (không phải Opus).
- [ ] Task kế tiếp: số lần chạy toàn bộ suite của IMPLEMENTER ≈ 2–3; số turn / thời gian giảm so với bảng ở trên.
- [ ] Chất lượng: ORCHESTRATOR review không tăng blocking finding bất thường; nếu tăng → cân nhắc lại D3.

## Result

- Main changes: `pytest-xdist` (dev, cài được 3.8.0, execnet 2.1.2) trong `pyproject.toml` + CP1 §10 (dòng bảng + sửa đổi HUMAN LEAD); Test policy ở `docs/ai/project-profile.md` §8; `.claude/agents/implementer.md` (`model: sonnet`, hướng dẫn gọn, pointer tới Test policy); README; entry `framework-history.md` dưới `## v4.1`.
- Tests: tuần tự `python -m pytest -q`: 898 passed, 183.7 s (3 phút 3 giây). Song song `-n auto` ×3: 898 passed mỗi lần, 61.9 s / 61.8 s / 60.8 s (≈ 3× nhanh hơn). Không có test nào fail riêng khi song song → không sửa test / fixture. `python -c "import xdist"` OK.
- Review: ORCHESTRATOR review diff-first (contract → diff → AC → evidence): ACCEPTED, không micro-fix. Chạy lại: `pytest -q -n auto` → 898 passed, 61.1 s; `node scripts/framework-check.mjs` exit 0 (kiểm exit thật, không qua pipe); `workflow.md` / `execution-profiles.md` không đổi; env `auto-short` import `auto_short` từ repo chính. IMPLEMENTER chạy override `sonnet` (transcript: `claude-sonnet-5-5`): 7 phút, 32 turn, ≈ 0.6 M token đọc từ cache, 4 lần chạy toàn bộ suite (đúng số required verification yêu cầu).
- Important findings / decisions: chạy `-n auto` có 48 warning (lặp `StarletteDeprecationWarning` mỗi worker, tuần tự là 1); không ảnh hưởng kết quả.
- Known limitations: D3 / D4 là hành vi agent, chỉ đánh giá được qua các task sau (manual checklist); `-n auto` in 48 warning thay vì 1.
- PR:
