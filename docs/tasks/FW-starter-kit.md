# Task: FW-starter-kit — Tách Framework v4.2 thành starter kit (repo riêng) + tài liệu cơ chế + adapter Copilot IMPLEMENTER

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `bb0824b` (`origin/main`, sau PR #33 v4.2) / `feature/fw-starter-kit` (worktree `../youtube-auto-short-fw-kit`); repo kit: xem D1
- Human Lead approval: accepted (HUMAN LEAD 2026-09-29: APPROVE TASK; D1 = repo riêng `ntnghia1908/ai-dev-framework`, ORCHESTRATOR tự tạo repo, tạo **private**, chỉ cân nhắc public sau khi kiểm không còn thông tin riêng của `dang-vu-spring`; D2 = C (Copilot Free, pilot khi có Pro); D3–D7 như đề xuất; D8 = A; D9 như đề xuất)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: tạo artifact tái dùng xuyên project, tạo repository mới, đổi checker, thêm adapter cho một tool. Không đổi rule Framework Core (chỉ tách phần project-specific, D4), không chạm code pipeline, security model hay public API.

Chạy song song với CP8.15 (worktree `../youtube-auto-short-cp815`): task này **không** sửa `docs/ai/project-profile.md`, `README.md`, `docs/workflow/current-state.md`, `src/`, `tests/` của repo này. Cập nhật current-state sau merge là S0 riêng.

## Vấn đề

### So sánh bản sạch (v4 CP0 → v4.1 → v4.2)

Mốc: `8b3d39c` (CP0, adopt v4 sạch từ `dang-vu-spring` @ `c5092ce`), `5edeb1f` (v4.1, PR #4), `bb0824b` (v4.2, PR #33).

| File | v4 → v4.1 | v4.1 → v4.2 | Lớp |
|---|---|---|---|
| `docs/ai/workflow.md` | + §9 Session scope và handoff | chỉ metadata `Version` / `Accepted by` | Core |
| `docs/ai/execution-profiles.md` | không đổi | không đổi | Core (có 1 đoạn project-specific, xem dưới) |
| `docs/tasks/_template.md` | không đổi | không đổi | Project Layer template |
| `AGENTS.md` | + pointer `framework-history.md` | không đổi | Project Layer (bảng pointer generic + mục "Current project boundary" riêng project) |
| `.claude/rules/execution.md` | + "Kết thúc session" (`/clear` + handoff) | không đổi | Adapter Claude Code |
| `.claude/agents/implementer.md` | không đổi | + `model: sonnet` + "Cách làm việc gọn" | Adapter Claude Code |
| `docs/ai/project-profile.md` | nội dung project (CP1/CP2) | + Test policy (§8) + nội dung project | Project Layer: **Test policy là mẫu generic** (vòng sửa chạy test liên quan; toàn suite 1 lần trước READY + 1 lần sau mỗi vòng fix), chỉ lệnh `pytest -n auto` là riêng project |
| `scripts/framework-check.mjs` | + kiểm history ↔ `Version` (và task/decision ở CP0–CP1) | không đổi | Checker: phần generic lẫn hằng số riêng project |
| `docs/ai/framework-history.md` | tạo mới | + v4.2 | Project Layer (lịch sử adoption của từng project) |

Kết luận: v4.2 **khác v4.1 chỉ ở adapter + project policy**; Core nội dung = v4.1. Kit v4.2 = Core v4.1 (metadata 4.2) + adapter Claude Code v4.2 + mục Test policy dạng template.

### Phần project-specific còn nằm trong Core

- `workflow.md` §3: "…project này hiện không có database authority." (`project-profile.md` §2 đã giữ).
- `execution-profiles.md` "Project policy": "Project cho phép cả `single-agent` và `dual-agent`" (trùng `project-profile.md` §7 → hai owner cho một rule).

### Core của repo này rút gọn so với upstream v4

CP0 adopt một bản **rút gọn** Core của `dang-vu-spring` @ `c5092ce`. Một số rule generic của upstream không còn, trong đó có chỗ Core hiện tại tham chiếu mà không định nghĩa:

- `workflow.md` §2 dùng "tài liệu class B" nhưng không định nghĩa class A / class B (upstream có).
- Không còn: danh sách đóng S0; phân loại report (BUG / CHANGE REQUEST / UNCLEAR); "không phải decision gate" (naming, refactor cục bộ…); duyệt theo chuỗi; IMPLEMENTER không commit / push / tạo integration request; micro-fix ≈ ≤5 dòng; mẫu READY report; rule integration request (không review lại, cập nhật kết thúc gom trong cùng PR); thời điểm manual test (đang nằm ở template, không ở Core).
- Upstream cũng có chi tiết riêng project (backend/frontend, ADR-032, vai trò `dangvien`…) → không copy nguyên được.

Quyết định dùng bản nào làm Core kit: D8.

### Khác

- Checker hard-code danh sách file và kiểm riêng (`youtube-vietnamese-dubber`, `planned module boundaries`, `CP1-product-contract.md`) → không dùng lại được.
- Không có tài liệu giải thích **cơ chế** framework (vì sao ba lớp, authority, S-class, gate, lifecycle, vai trò / profile, canonical owner, state vs authority, session / handoff, checker). Upstream có lý do thiết kế trong ADR-032 (repo private, lẫn chi tiết project).
- Adapter Copilot chỉ là pointer đọc `AGENTS.md`; chưa có cách để Copilot làm IMPLEMENTER (hoãn ở `docs/tasks/FW-implementer-speed.md`).

## Goal

Có repo starter kit Framework v4.2 (tag `v4.2`) cài được vào project mới hoặc project có sẵn, gồm: Core nguyên văn (không còn chi tiết project), template Project Layer + adapter có chỗ trống, checker dùng chung đọc config, tài liệu cơ chế, hướng dẫn cài. Repo này chuyển sang dùng checker chung + config mà kết quả kiểm không đổi. Adapter Copilot IMPLEMENTER ở dạng template + checklist pilot, sẵn sàng pilot khi có Copilot Pro.

## Scope

- In scope:
  - **Repo kit** (D1), cấu trúc:

    ```text
    README.md                         kit là gì, cài nhanh, liên kết
    VERSION                           4.2
    CHANGELOG.md                      v4 → v4.1 → v4.2 (tóm tắt từ framework-history của repo này)
    docs/
      mechanism.md                    tài liệu cơ chế (D9), không normative
      install-new-project.md          D6
      install-existing-project.md     D6
      upgrade.md                      D6
    core/                             nguyên văn, project không sửa
      docs/ai/workflow.md
      docs/ai/execution-profiles.md
    templates/                        chỗ trống <!-- FILL: ... -->
      AGENTS.md
      CLAUDE.md
      FRAMEWORK_ADOPTION.md
      framework.config.json
      docs/ai/project-profile.md      (có sẵn: authority order, module map, policy, integration, execution profiles, Setup + Test policy)
      docs/ai/framework-history.md
      docs/workflow/current-state.md
      docs/tasks/_template.md
    adapters/
      claude-code/                    .claude/rules/execution.md, .claude/agents/implementer.md (v4.2)
      copilot/                        .github/copilot-instructions.md + IMPLEMENTER (D2)
    scripts/framework-check.mjs       checker dùng chung (D3)
    tests/                            node --test + fixture (D5)
    ```

  - **Repo này (dogfood):** `framework.config.json` ở root; `scripts/framework-check.mjs` = bản sao checker kit @ `v4.2`; Core bỏ hai đoạn project-specific (D4) để giống byte-for-byte Core kit; `FRAMEWORK_ADOPTION.md` ghi nguồn kit (repo + tag); `docs/ai/framework-history.md` entry dưới `## v4.2`; adapter Copilot theo D2; Result của file này.
- Out of scope:
  - `docs/ai/project-profile.md`, `README.md`, `docs/workflow/current-state.md`, `src/`, `tests/` của repo này. Việc cần sửa ở đó → ghi Result làm follow-up.
  - Thay đổi nội dung rule Core §1–§9, kể cả khôi phục rule từ upstream (D8 phương án B là task riêng, version mới).
  - Pilot Copilot IMPLEMENTER thật (chờ Copilot Pro; task S1 sau).
  - Áp kit vào một project khác thật (chỉ cài thử vào thư mục tạm).
  - Công cụ cài tự động (`npx`, script copy có tham số).
  - Adapter tool khác; dịch sang tiếng Anh.
  - Sửa `dang-vu-spring`.

## Authority / key decisions

- Authority: `docs/ai/workflow.md` §2–§4, §7–§9; `docs/ai/execution-profiles.md` ("Tool adapter quyết định cách một tool cụ thể thực hiện profile"); `docs/ai/project-profile.md` §4, §5, §7; `FRAMEWORK_ADOPTION.md` (ba lớp; thứ tự adoption greenfield); `docs/ai/framework-history.md` (quy ước version).

### D1 — Kit ở repo riêng (HUMAN LEAD 2026-09-29: chốt A)

- Còn chốt: tên repo (đề xuất `ntnghia1908/ai-dev-framework`) và visibility (đề xuất **private**: nội dung rút từ repo private `dang-vu-spring`; đổi public sau được).
- Tạo repo là outward-facing: HUMAN LEAD tạo repo trống, hoặc ghi trong approval cho phép ORCHESTRATOR chạy `gh repo create <tên> --private`.
- Integration của repo kit giống repo này: `main` + commit khởi tạo (README một dòng) → branch `feature/v4.2-kit` → PR → HUMAN LEAD merge → tag `v4.2` (tag sau merge, cũng cần HUMAN LEAD cho phép).
- Repo này **copy** Core + checker từ tag (không submodule, không dependency mới); `FRAMEWORK_ADOPTION.md` ghi repo + tag + commit.
- Thứ tự: PR kit merge + tag trước; PR repo này sau (trỏ tới tag).

### D2 — Adapter Copilot (HUMAN LEAD 2026-09-29: đang có Copilot Free, Pro sau)

- Task này: phương án **C** — viết adapter + delegation prompt template + checklist pilot, ghi rõ "chưa kiểm chứng". Hướng thiết kế là **A (local)**: Copilot chạy trong worktree của task như IMPLEMENTER; ORCHESTRATOR (Claude Code) sinh delegation prompt; HUMAN LEAD chuyển prompt cho Copilot; Copilot trả READY report; ORCHESTRATOR review diff trên cùng branch.
- Không dùng coding agent trên cloud (phương án B: tự tạo draft PR → lệch integration mechanism).
- Tên file / định dạng custom agent và giới hạn gói Free / Pro của Copilot được xác minh theo tài liệu GitHub hiện hành lúc implement, ghi nguồn; không đoán.
- Pilot: task S1 nhỏ sau khi có Pro (checklist trong adapter).

### D3 — Config checker (đề xuất)

`framework.config.json` ở root project (JSON → checker chỉ dùng Node stdlib):

```json
{
  "frameworkVersion": "4.2",
  "adapters": ["claude-code", "copilot"],
  "requiredFiles": ["README.md", "docs/decisions/CP1-product-contract.md"],
  "requiredTokens": { "docs/ai/project-profile.md": ["youtube-vietnamese-dubber", "planned module boundaries"] },
  "taskDir": "docs/tasks",
  "decisionDir": "docs/decisions"
}
```

- Luôn kiểm (không tắt được): file Core + Project Layer tồn tại; `Status` (Core / profile / history `CURRENT`, current-state `OPERATIONAL STATE — NOT AUTHORITY`); `Version` workflow = `frameworkVersion`; history có `## v<Version>`; task contract (field + section); decision record (Status); không còn `<!-- FILL:`.
- `adapters` bật kiểm riêng của adapter (`claude-code`: `CLAUDE.md` là bridge `@AGENTS.md`, `execution.md` import current-state, `implementer.md` tồn tại; `copilot`: file adapter tồn tại).
- `requiredFiles` / `requiredTokens` thay các kiểm hard-code của repo này.
- Config thiếu / sai kiểu → FAIL có thông báo rõ.

### D4 — Core nguyên văn (đề xuất)

- Core kit = Core v4.2 của repo này, bỏ: câu "…project này hiện không có database authority" (§3) và câu "Project cho phép cả…" (execution-profiles "Project policy"; giữ câu generic về vendor/model và adapter). Không đổi rule → không tăng version, entry dưới `## v4.2`.
- `Accepted by` Core thêm "FW-starter-kit".

### D5 — Test checker (đề xuất)

`node --test` (Node stdlib) với fixture: project tối thiểu PASS + ca FAIL (thiếu file, Status sai, Version lệch history, task thiếu field, `FILL` sót, config sai, adapter bật mà thiếu file). Test nằm trong repo kit.

### D6 — Hướng dẫn cài (đề xuất)

- **Project mới:** copy `core/` + `templates/` + adapter + checker → điền `FILL` theo thứ tự adoption (Core → Project Layer → module rules khi cần → execution profile → adapter → integration → checker → pilot S1) → checker PASS. Ví dụ tham chiếu: CP0 của repo này (`8b3d39c`).
- **Project có sẵn:** inventory tài liệu / quy ước đang có → map vào Project Layer (không chép vào Core) → `FRAMEWORK_ADOPTION.md` Adopted / Adapted / Not adopted → một task S0/S1 đầu tiên làm pilot; không đổi code / test trong lúc adopt.
- **Nâng version:** thay `core/` + checker theo tag mới, đọc CHANGELOG, cập nhật `frameworkVersion`, thêm entry history của project.

### D7 — Ngôn ngữ (đề xuất)

Tiếng Việt như Core hiện tại; tên file / field / thuật ngữ canonical giữ English.

### D8 — Core kit lấy bản nào? (HUMAN LEAD chốt)

| Phương án | Nội dung | Hệ quả |
|---|---|---|
| **A. v4.2 rút gọn của repo này** (khuyến nghị cho task này) | Đúng bản đã chạy thật qua CP0–CP9; chỉ bỏ 2 đoạn D4 | Giữ các lỗ hổng so với upstream (class A/B không định nghĩa…); `mechanism.md` liệt kê chúng; khôi phục là task riêng → v4.3 |
| **B. Gộp lại rule generic từ upstream** (class A/B, danh sách đóng S0, IMPLEMENTER không commit/push, mẫu READY report…) | Core đầy đủ hơn | Đổi rule Core → v4.3, phải review từng rule, task lớn hơn; nên tách task |

### D9 — Tài liệu cơ chế `docs/mechanism.md` (HUMAN LEAD yêu cầu; đề xuất nội dung)

Giải thích **vì sao** và **chạy thế nào**, không tạo rule mới — mỗi mục trỏ về canonical owner (Core / template), không chép rule:

1. Mục tiêu: repository là source of truth; agent tự chạy trong boundary do người duyệt.
2. Ba lớp Core → Project Layer → Tool Adapter; cái gì đặt ở lớp nào; vì sao Core không có tên model / vendor / chi tiết project.
3. Authority order và canonical owner; state (current-state) ≠ authority; file lịch sử không phải authority.
4. Vai trò HUMAN LEAD / ORCHESTRATOR / IMPLEMENTER và execution profile (`dual-agent` / `single-agent`); adapter hiện thực profile theo từng tool.
5. S0 / S1 / S2 và decision gate; sơ đồ luồng từ yêu cầu → phân loại → contract → approve → execute → review → READY → integration.
6. Task contract và lifecycle; `APPROVE TASK` authorize cả vòng tới READY.
7. Verification, review diff-first, blocking / non-blocking, circuit breaker, outside-scope finding.
8. Session scope + handoff; bootstrap từ repository.
9. Checker: kiểm gì, không kiểm gì (cấu trúc, không semantic).
10. Ví dụ đi hết một vòng S2 (lấy từ một task thật của repo này, rút gọn).
11. Giới hạn đã biết (D8) và lịch sử version.

## Implementation approach

- Tách Core trong repo này (D4) trước, rồi dựng kit từ đó; Core kit = Core repo, kiểm bằng `diff`.
- Checker chung viết từ checker hiện tại: hằng số riêng project → config; giữ định dạng PASS/FAIL.
- Dogfood: chạy checker cũ (`bb0824b`) và mới trên repo này, so output; làm hỏng có chủ đích ở bản sao tạm → cả hai FAIL cùng chỗ.
- Cài thử theo `install-new-project.md` vào thư mục tạm → điền FILL tối thiểu → checker PASS.
- `mechanism.md` dựa trên Core hiện hành + `FRAMEWORK_ADOPTION.md` + ý của ADR-032 upstream (viết lại, không copy chi tiết project private).
- Delegate IMPLEMENTER lần lượt: (1) repo kit trên branch của repo kit, (2) dogfood trên `feature/fw-starter-kit` — hai branch, hai writer tuần tự.

## Acceptance Criteria

1. Repo kit có đủ cấu trúc ở Scope; `VERSION` = `4.2`; PR kit đã tạo (merge + tag do HUMAN LEAD).
2. `core/docs/ai/workflow.md` và `core/docs/ai/execution-profiles.md` của kit giống byte-for-byte bản trong repo này; Core không còn hai đoạn project-specific (D4); nội dung rule §1–§9 không đổi.
3. Checker kit chỉ dùng Node stdlib, đọc `framework.config.json`, kiểm như D3; `node --test` trong kit PASS với đủ ca D5.
4. Repo này: `node scripts/framework-check.mjs` exit 0 với checker chung + config; danh sách PASS giống checker cũ; kiểm riêng cũ còn qua `requiredFiles` / `requiredTokens`.
5. Cài thử theo `install-new-project.md` vào thư mục tạm → checker PASS; bỏ điền một `FILL` → FAIL đúng file.
6. Kit có `install-new-project.md`, `install-existing-project.md`, `upgrade.md` theo D6.
7. `docs/mechanism.md` có đủ mục D9; không có rule mới (mọi câu normative đều là pointer tới Core / template).
8. Adapter Copilot: template IMPLEMENTER + delegation prompt + checklist pilot, ghi "chưa kiểm chứng"; nguồn tài liệu GitHub được ghi.
9. Repo này: `framework-history.md` có entry dưới `## v4.2`; `FRAMEWORK_ADOPTION.md` ghi repo kit + tag + commit.
10. Không file Out of scope nào của repo này bị sửa.

## Required verification

- Repo kit: `node --test tests/` → PASS — AC3.
- Repo kit: `node scripts/framework-check.mjs` chạy trên fixture PASS / FAIL như mong đợi — AC3.
- `diff <kit>/core/docs/ai/workflow.md docs/ai/workflow.md` và `execution-profiles.md` → rỗng — AC2.
- `git diff bb0824b -- docs/ai/workflow.md docs/ai/execution-profiles.md` → chỉ hai đoạn D4 + metadata — AC2.
- Repo này: `node scripts/framework-check.mjs` → exit 0 (kiểm exit thật, không qua pipe); so danh sách PASS với checker `bb0824b` — AC4.
- Cài thử theo hướng dẫn vào thư mục tạm, PASS rồi FAIL có chủ đích — AC5.
- `git diff --stat bb0824b...HEAD` → không có file Out of scope — AC10.
- Diff review theo contract (AC1, AC6–AC9).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract; manual test là điểm danh.

- [ ] Đọc `docs/mechanism.md`: hiểu được framework chạy thế nào mà không cần đọc Core trước.
- [ ] Đọc `install-new-project.md`: đủ để cài cho một project mới mà không cần hỏi thêm.
- [ ] Khi có Copilot Pro: pilot IMPLEMENTER theo checklist adapter trên một task S1 nhỏ.
- [ ] Sau merge: S0 cập nhật `docs/workflow/current-state.md` (khi CP8.15 không còn sửa file này).

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
