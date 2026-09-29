# Task: FW-starter-kit — Tách Framework v4.2 thành starter kit (repo riêng) + tài liệu cơ chế + adapter Copilot IMPLEMENTER

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `bb0824b` (`origin/main`, sau PR #33 v4.2) / `feature/fw-starter-kit` (worktree `../youtube-auto-short-fw-kit`); repo kit: xem D1
- Human Lead approval: accepted (HUMAN LEAD 2026-09-29: APPROVE TASK; D1 = repo riêng `ntnghia1908/ai-dev-framework`, ORCHESTRATOR tự tạo repo, tạo private trong lúc dựng; HUMAN LEAD cho phép chuyển **public** khi kiểm không còn thông tin riêng của `dang-vu-spring` (kiểm ở review, trước READY); D2 = C, sửa đổi cùng ngày: **A + pilot ngay với Copilot Free** ("Pilot bản free luôn để có pro thì sài luôn"); D3–D7 như đề xuất; D8 = A; D9 như đề xuất; D10 (sửa đổi cùng ngày): Copilot là IMPLEMENTER thứ hai, ORCHESTRATOR chọn IMPLEMENTER theo từng task — "Tôi đồng ý. Nhưng nếu có bản pro thì nhắc tôi đo lại cho chính xác"; D11 (sửa đổi cùng ngày): adapter Codex dạng template chưa kiểm chứng — "Đồng ý D11")
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

**Sửa đổi HUMAN LEAD 2026-09-29: pilot ngay với Copilot Free** — phương án A, pilot trong task này:

- Copilot CLI (`@github/copilot`, npm global, cần Node ≥ 22; mọi gói kể cả Free có CLI — nguồn docs.github.com/en/copilot/get-started/plans, tra 2026-09-29). Cài CLI là tool máy dev, không phải dependency của project. Đăng nhập (`/login` hoặc token "Copilot Requests") do HUMAN LEAD làm.
- **Pilot = phần 2 (dogfood trong repo này)**: IMPLEMENTER của phần 2 là Copilot CLI với custom agent `implementer` (`.github/agents/implementer.agent.md` từ kit). ORCHESTRATOR (Claude Code) chạy `copilot -p "<delegation prompt>" --agent implementer` trong worktree `../youtube-auto-short-fw-kit` với tool được phép giới hạn (đọc/sửa file, `node`, `git diff/status`); chặn `git commit`, `git push`, `gh`. Execution profile task vẫn `dual-agent`; IMPLEMENTER phần 1 = adapter Claude Code, phần 2 = adapter Copilot (HUMAN LEAD duyệt ở đây).
- Fallback (duyệt trước): nếu Copilot không chạy được (auth, hạn mức Free, lỗi tool) hoặc chạm circuit breaker → ghi lý do ở Result, phần 2 giao lại IMPLEMENTER Claude Code; pilot ghi FAIL / PARTIAL, không che.
- Đo pilot (ghi Result): số lần chạy, thời gian, số lần ORCHESTRATOR phải trả lại, blocking finding, READY report có đúng mẫu, có vi phạm boundary (commit/push/file ngoài scope) không, hạn mức Free tiêu tốn (nếu xem được).
- Adapter kit bỏ nhãn "chưa kiểm chứng" nếu pilot PASS; ghi "kiểm chứng: Copilot Free, <ngày>, task FW-starter-kit phần 2".

Thiết kế ban đầu (giữ làm nền):

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

### D10 — Nhiều IMPLEMENTER, ORCHESTRATOR chọn theo task (HUMAN LEAD 2026-09-29: đồng ý)

- Core không đổi: `dual-agent` vẫn là ORCHESTRATOR + IMPLEMENTER; tool nào làm IMPLEMENTER là việc của adapter / project.
- **Danh sách IMPLEMENTER** là project policy, khai ở `docs/ai/project-profile.md` §7 (canonical owner), HUMAN LEAD duyệt: mỗi dòng = adapter, điểm mạnh, giới hạn (vd hạn mức gói), tiêu chí dùng, dự phòng.
- ORCHESTRATOR chọn IMPLEMENTER lúc viết contract, ghi field `- Implementer: <adapter> — <lý do một dòng>` (task `dual-agent`); `APPROVE TASK` duyệt luôn lựa chọn này. Gọi tool / AI CLI của IMPLEMENTER đã được duyệt không vi phạm "không gọi AI CLI ngoài execution profile".
- Không đổi IMPLEMENTER giữa task (một writer / branch), trừ dự phòng khai trong danh sách (hạn mức, auth, lỗi tool, circuit breaker) → ghi Result.
- Hai IMPLEMENTER song song chỉ khi tập file không giao nhau, mỗi người một branch (`workflow.md` §5).
- Tên model / vendor chỉ ở adapter và project-profile, không vào Core.
- Tiêu chí ban đầu viết từ số đo pilot (D2); **khi HUMAN LEAD có Copilot Pro: đo lại và cập nhật tiêu chí** (manual checklist).
- Phạm vi trong task này:
  - Kit: template project-profile §7 thêm mục "Danh sách IMPLEMENTER" (FILL + ví dụ trung tính); `_template.md` thêm field `Implementer` (tùy chọn, chỉ `dual-agent`); adapter Claude Code (`execution.md`) ghi ORCHESTRATOR chọn theo §7 và truyền override / gọi adapter tương ứng; adapter Copilot README ghi cách ORCHESTRATOR gọi non-interactive; `mechanism.md` §4 giải thích.
  - Repo này: `_template.md` thêm field `Implementer` (giống kit). Danh sách IMPLEMENTER của repo này trong `project-profile.md` §7 → **follow-up sau khi CP8.15 merge** (file ngoài scope).
  - Checker: không bắt buộc field `Implementer` (contract cũ không có); chưa kiểm giá trị.

### D11 — Adapter Codex dạng template (HUMAN LEAD 2026-09-29: đồng ý)

- HUMAN LEAD chưa có gói Codex trả phí → không pilot; adapter ghi **CHƯA KIỂM CHỨNG**.
- Sự kiện đã tra (2026-09-29): Codex CLI đọc `AGENTS.md`; có `codex exec` non-interactive (https://learn.chatgpt.com/docs/codex/cli); Codex CLI có từ gói Plus trở lên, hoặc dùng API key tính theo token (https://learn.chatgpt.com/docs/pricing). Cờ sandbox / approval của `codex exec` phải lấy từ tài liệu chính thức lúc viết, không đoán; chưa xác minh được thì ghi "cần xác minh".
- Kit: `adapters/codex/` (README: điều kiện gói, cách ORCHESTRATOR giao việc qua `codex exec` trong worktree, chặn commit / push, mẫu delegation prompt, checklist pilot); checker nhận adapter `codex` (kiểm `AGENTS.md` — đã luôn bắt buộc — nên adapter không thêm file bắt buộc, trừ khi tài liệu Codex yêu cầu file riêng); ví dụ trong Danh sách IMPLEMENTER mẫu và `mechanism.md` §4.
- Repo này: không bật `codex` trong `framework.config.json`, không đưa vào Danh sách IMPLEMENTER tới khi pilot đạt.

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
8. Adapter Copilot: template IMPLEMENTER + delegation prompt + checklist pilot, nguồn tài liệu GitHub được ghi; pilot phần 2 đã chạy với Copilot Free, kết quả + số đo ghi ở Result (PASS / PARTIAL / FAIL + fallback nếu có); nhãn adapter khớp kết quả pilot.
9. Repo này: `framework-history.md` có entry dưới `## v4.2`; `FRAMEWORK_ADOPTION.md` ghi repo kit + tag + commit.
10. Không file Out of scope nào của repo này bị sửa.
11. D10: kit có mục Danh sách IMPLEMENTER (template §7), field `Implementer` ở `_template.md` (kit + repo này, giống nhau), adapter Claude Code / Copilot và `mechanism.md` §4 mô tả cơ chế chọn; không đổi Core.
12. D11: kit có `adapters/codex/` (CHƯA KIỂM CHỨNG, nguồn + ngày), checker chấp nhận adapter `codex` (có test), repo này không bật `codex`.

## Required verification

- Repo kit: `node --test` → PASS — AC3.
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
- [ ] Khi có Copilot Pro: **đo lại** (chạy lại một task S1 nhỏ bằng adapter Copilot, cùng số đo như pilot Free) và cập nhật tiêu chí trong Danh sách IMPLEMENTER.
- [ ] Sau khi CP8.15 merge: follow-up khai Danh sách IMPLEMENTER của repo này ở `docs/ai/project-profile.md` §7.
- [ ] Sau merge: S0 cập nhật `docs/workflow/current-state.md` (khi CP8.15 không còn sửa file này).

## Result

- Main changes:
  - Repo kit `ntnghia1908/ai-dev-framework` (branch `feature/v4.2-kit`, `e667b60` + `855944d`): Core v4.2, templates Project Layer (FILL; project-profile §7 có Danh sách IMPLEMENTER, §8 có Test policy mẫu), adapter `claude-code` / `copilot` (đã kiểm chứng trên Free) / `codex` (CHƯA KIỂM CHỨNG), checker dùng chung + 28 test `node --test`, `docs/mechanism.md`, hướng dẫn cài (project mới / có sẵn / nâng version), CHANGELOG.
  - Repo này: Core bỏ 2 đoạn project-specific (D4, giống byte-for-byte kit); checker = bản sao kit; `framework.config.json` (adapters `claude-code`, `copilot`; kiểm riêng cũ qua `requiredFiles` / `requiredTokens`); `.github/agents/implementer.agent.md`; field `Implementer` trong `_template.md`; `FRAMEWORK_ADOPTION.md` mục Starter kit; history entry dưới `## v4.2`.
- Tests: kit `node --test` → 28 pass / 0 fail. Cài thử vào thư mục tạm (bật 3 adapter): chưa điền FILL → FAIL, điền đủ → exit 0, trả lại 1 FILL → FAIL đúng file. Repo này `node scripts/framework-check.mjs` → exit 0; so với checker `bb0824b`: mọi PASS cũ còn, thêm `PASS: framework.config.json`, `PASS: .github/agents/implementer.agent.md`. `cmp` Core / checker / `_template.md` với kit → giống. `git diff --stat bb0824b` trên `project-profile.md`, `README.md`, `current-state.md`, `src/`, `tests/` → rỗng. Grep riêng tư trong kit (`dang-vu|spring|mysql|react|/home/|@gmail|ntnghia`) → 0 hit.
- Review: ORCHESTRATOR review diff-first 3 lượt (kit vòng 1, dogfood, kit vòng 2): ACCEPTED, 0 blocking, không micro-fix.
- Pilot Copilot (D2, phần 2 dogfood): **PASS**. Copilot CLI 1.0.89, gói Free, model tự chọn `gpt-6-luna`, 134 s, 1 premium request, 37 tool call (19 view, 17 bash, 1 apply_patch), 7 file đúng plan, 0 vi phạm boundary (không commit / push, không file ngoài scope), READY report đủ 4 mục, verification tự chạy đúng. Vấn đề: 3 lệnh chỉ-đọc (`find`, `cmp`, `sha256sum` / `test`) bị chặn do allowlist thiếu → đã đưa vào khuyến nghị allowlist ở adapter. So sánh: IMPLEMENTER Claude (Sonnet) phần 1 ≈ 4 phút / 21 tool call, vòng 2 ≈ 1,2 phút.
- Important findings / decisions:
  - v4.2 khác v4.1 chỉ ở adapter + project policy; Core nội dung = v4.1.
  - Core của repo này là bản rút gọn của framework v4 gốc; lỗ hổng (class A/B không định nghĩa, thiếu danh sách đóng S0, rule IMPLEMENTER không commit / push, mẫu READY report, duyệt theo chuỗi…) ghi ở `docs/mechanism.md` §11 của kit, dự kiến v4.3 (D8 = A).
  - Lệnh đúng trên Node 24 là `node --test` (không `node --test tests/`).
- Known limitations:
  - Repo này chưa có Danh sách IMPLEMENTER (`project-profile.md` §7) và chưa đồng bộ `.claude/rules/execution.md` với adapter kit (mục "Chọn IMPLEMENTER") → follow-up sau khi CP8.15 merge (cùng lúc, để pointer không trỏ vào mục chưa có).
  - Adapter Codex chưa kiểm chứng (cần gói Plus hoặc API key); cờ sandbox / approval của `codex exec` chưa xác minh.
  - Số đo Copilot là của gói Free, một task nhỏ; đo lại khi có Pro (manual checklist).
  - Tag `v4.2` của kit gắn sau khi PR kit merge; repo kit đang private, chuyển public chờ HUMAN LEAD xác nhận ở READY.
- PR: #34 (repo này); kit: ntnghia1908/ai-dev-framework#1
