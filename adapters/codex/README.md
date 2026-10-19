# Adapter Codex — ORCHESTRATOR / IMPLEMENTER

> **Trạng thái kiểm chứng (2026-10-18/19, một adopted project trên Linux, Codex CLI 0.163.0, model `gpt-6.1-sol`):**
> - **IMPLEMENTER qua `codex exec`** (Claude Code là ORCHESTRATOR): **đã pilot** — 1 tính năng lớn, 1 phần web, 5 vòng sửa / task nhỏ, tất cả review ACCEPTED; xem mục "Cách chạy" và "Số đo pilot".
> - **Reviewer read-only** (`codex exec review`): đã chạy thử.
> - **ORCHESTRATOR** (Codex điều phối, Claude / native worker viết): đã dùng trong cùng project nhưng chưa có checklist pilot riêng của kit.
> - Tool thay đổi nhanh: kiểm lại cờ CLI và model trên máy của bạn trước khi dùng.

## Mặc định: native dual-agent (built-in worker)

Khi project mở bằng Codex, session chính đề xuất mình là ORCHESTRATOR (chỉ khi adapter `codex` được bật, không có `agents.orchestrator` cố định sang tool khác, và policy task cho phép) và giao việc cho **built-in native worker** của Codex. Không gọi CLI của provider khác; Phase 1 không có `.codex/config.toml` hay `.codex/agents/*.toml` (ADR-003 D2). Worker ban đầu kế thừa model của session chính; không hard-code model ID.

> **Chưa pilot (P3).** Codex built-in worker và model routing chưa được kiểm chứng trên CLI/version của bạn. Chỉ coi là chạy được sau khi có evidence: thread worker (vd `/subagents`), model và version thực tế, permission, và ORCHESTRATOR tự chạy lại verification. Thiếu worker/model/permission → BLOCKED hoặc xin duyệt phương án khác, không tự hạ xuống `single-agent`.

Delegation prompt gọn cho built-in worker (chỉ là prompt, không phải sandbox):

```text
Dùng built-in worker làm IMPLEMENTER duy nhất cho task <ID>.
Task contract (APPROVED hoặc trong boundary đã duyệt): docs/tasks/<ID>.md
Branch: <branch>   Base: <sha>
Xác minh branch/HEAD/working tree trước khi sửa; lệch thì BLOCKED.
Chỉ sửa trong Owned paths; không commit, push, tạo PR; không gọi CLI khác.
Chạy required verification, trả READY report (thay đổi chính, verification + exit code, finding ngoài scope, giới hạn).
```

ORCHESTRATOR vẫn review độc lập (contract → diff gồm untracked → AC → tự chạy lại verification). Mọi mục bên dưới là **tùy chọn / thay thế**, không phải mặc định.

---

Adapter hỗ trợ hai vai trò (descriptor `adapter.json`: `orchestrator`, `implementer`). Descriptor chỉ khai capability fact, không cấp authorization; authority nằm ở workflow, project policy và task contract.

- **IMPLEMENTER** (tùy chọn, `codex exec`; mục "Cách chạy" và "Mẫu delegation prompt"): thực hiện vai trò IMPLEMENTER của profile `dual-agent` (`core/docs/ai/execution-profiles.md`) bằng Codex CLI chạy **local** trong worktree của task. ORCHESTRATOR (agent khác) vẫn review diff.
- **ORCHESTRATOR** (tùy chọn, handoff thủ công sang Claude Code; mục "Vai trò ORCHESTRATOR"): Codex điều phối và review; IMPLEMENTER là agent khác (tài liệu hóa cho Claude Code Sonnet). Gọi `claude -p` lồng từ Codex (hoặc ngược lại) là route thử nghiệm, **không mặc định** và ADR-003 không đưa vào production.

## Vai trò ORCHESTRATOR (tùy chọn: handoff thủ công sang Claude Code)

Codex làm ORCHESTRATOR của profile `dual-agent` (`core/docs/ai/execution-profiles.md`); contract vai trò ở `core/docs/ai/agent-adapter-contract.md`. Chưa pilot, nên HUMAN LEAD vẫn là gate cho mọi decision gate.

Trách nhiệm:

1. **Kiểm authority / base / branch**: xác nhận remote, branch, HEAD khớp base ghi trong contract; working tree sạch (cả untracked). Lệch hoặc có thay đổi chưa rõ ownership → BLOCKED, không reset / checkout đè / xóa file.
2. **Chuẩn bị contract / plan**: viết task contract theo `docs/tasks/_template.md` (kit: `templates/docs/tasks/_template.md`): Execution profile `dual-agent`, `Orchestrator: codex`, `Implementer: claude-code — <Sonnet, một writer>`, Authorization mode / source, Owned paths, AC, Required verification. Chỉ ghi `Implementation authorized: YES` khi có authorization hợp lệ (task approval hoặc boundary); decision gate vẫn do HUMAN LEAD quyết.
3. **Delegation thủ công**: HUMAN LEAD (hoặc người vận hành) mở session Claude Code trong worktree của task và dán delegation prompt (mẫu bên dưới). Không có helper script, gateway, scheduler hay tự chuyển provider/model. Mỗi task một writer; không chạy hai Sonnet đồng thời trừ khi governance và project config cho phép.
4. **Review** theo thứ tự `task contract → diff → AC → verification evidence` (`core/docs/ai/workflow.md` §7). Tự chạy lại verification khi môi trường cho phép; nếu không thì ghi rõ, không claim PASS.
5. **Bounded fix**: chỉ micro-fix cục bộ, hiển nhiên, không đổi behavior / contract / architecture / security / business logic. Lớn hơn thì trả IMPLEMENTER. Cùng một blocker sau hai vòng fix → BLOCKED.
6. **READY / BLOCKED**: kết luận READY khi AC đạt, required verification PASS, không còn blocking finding; ngược lại BLOCKED kèm evidence. Push / PR / merge theo integration policy của project, không do ORCHESTRATOR tự quyết.

### Mẫu delegation prompt sang Claude Code Sonnet

```text
Bạn là IMPLEMENTER duy nhất cho task <ID>. Codex là ORCHESTRATOR bên ngoài và sẽ review sau.

Task contract (APPROVED): <đường dẫn tới docs/tasks/<ID>.md>
Repository: <repo>   Worktree: <đường dẫn>   Branch: <branch>   Base: <sha>
Implementation authorized: YES
Plan ngắn:
1. ...
2. ...

Xác minh remote / branch / HEAD / working tree trước khi sửa; lệch thì BLOCKED.
Chỉ sửa trong Owned paths. Không gọi agent khác, không commit, không push, không tạo PR.
Chạy required verification và dừng ở READY report: thay đổi chính, verification
(lệnh + exit code + kết quả), finding ngoài scope, giới hạn.
```

### Project config mẫu (tùy chọn: binding cố định, adopted project)

Chỉ dùng khi HUMAN LEAD chủ ý ràng buộc cố định ORCHESTRATOR; project mới từ kit không đặt `agents.orchestrator`.

```json
{
  "adapters": ["codex", "claude-code"],
  "agents": {
    "orchestrator": "codex"
  }
}
```

`agents.orchestrator = "codex"` yêu cầu `codex` có trong `adapters` và descriptor khai role `orchestrator`. IMPLEMENTER không nằm trong `agents`: ghi ở task contract (`Implementer: claude-code — Sonnet`). Capabilities trong descriptor không cấp authorization.

### Starter-kit root và adopted project

Starter-kit root (repo kit) **không** phải adopted project: không có `AGENTS.md`, `framework.config.json`, `docs/ai/project-profile.md`, `docs/workflow/current-state.md` hay subagent Claude đã đăng ký. Làm việc ở kit thì dùng `core/`, `templates/`, ADR trong `docs/decisions/` và task contract. Ở adopted project, chỉ đọc các entry point thực sự tồn tại (`AGENTS.md`, project profile, current-state, `framework.config.json`).

## Sự kiện đã tra (2026-09-29)

- Codex CLI đọc `AGENTS.md` và có `codex exec` chạy non-interactive. Nguồn: https://learn.chatgpt.com/docs/codex/cli
- Codex CLI có từ gói Plus trở lên, hoặc dùng API key tính theo token. Nguồn: https://learn.chatgpt.com/docs/pricing
- Cài theo trang CLI ở trên: `curl -fsSL https://chatgpt.com/codex/install.sh | sh`. Ngoài ra trên registry npm có gói `@openai/codex` (`npm view @openai/codex version` trả 0.159.0 lúc tra); đây là thông tin tham khảo, không bắt buộc và chưa cài thử.
- Cờ sandbox / approval của `codex exec`: **chưa xác minh được từ nguồn chính thức** → cần xác minh khi pilot (`codex exec --help`). Không đoán tên cờ.

## Cài đặt vào project

Phần này áp dụng cho vai trò IMPLEMENTER; ORCHESTRATOR xem mục trên. Không cần file adapter riêng: Codex đọc `AGENTS.md` (đã luôn bắt buộc). Thêm `"codex"` vào `adapters` trong `framework.config.json` và khai adapter trong Danh sách IMPLEMENTER (`docs/ai/project-profile.md` §7).

## Cách chạy (tùy chọn: `codex exec` làm IMPLEMENTER)

### Chuẩn bị máy (một lần)

- Linux: sandbox `workspace-write` dùng bubblewrap. Ubuntu 24.04 bật `kernel.apparmor_restrict_unprivileged_userns = 1` → bwrap đóng gói của Codex lỗi `bwrap: loopback: Failed RTM_NEWADDR` / `bwrap: setting up uid map: Permission denied` và Codex trả BLOCKED. Sửa (sudo, chạy trong terminal thật): `apt install bubblewrap`; tạo `/etc/apparmor.d/bwrap` với `abi <abi/4.0>, include <tunables/global> profile bwrap /usr/bin/bwrap flags=(unconfined) { userns, }`; `apparmor_parser -r /etc/apparmor.d/bwrap`. Kiểm: `codex exec --skip-git-repo-check -s workspace-write "echo sandbox-ok"`.
- Không chạy `danger-full-access` thay cho sửa sandbox (ORCHESTRATOR của Claude Code cũng bị chặn khi tạo agent không sandbox).
- Ghi model và effort mặc định thực tế: trên máy pilot, `codex exec` mặc định reasoning effort `none` — luôn đặt rõ.

### Giao việc

1. ORCHESTRATOR tạo worktree / branch, viết task contract (`Implementer: codex — <lý do>`, `Implementation authorized: YES`), kiểm quota (mục "Quota").
2. Chạy nền trong worktree, prompt từ file (mẫu bên dưới):

   ```text
   codex exec -C <worktree> -s workspace-write -m <model> -c model_reasoning_effort='"high"' -o <tmp>/codex.out - < <prompt.md> > <tmp>/codex.log 2>&1
   ```

   `high` cho module / tính năng mới, `medium` cho sửa nhỏ. `-o` ghi READY report; `tokens used` và `session id:` nằm trong log.
3. Giới hạn sandbox `workspace-write`: **không mạng, không socket loopback** → test HTTP / server và full suite có thể treo hoặc lỗi trong sandbox. Prompt yêu cầu Codex chỉ chạy test targeted không cần socket và ghi rõ lệnh nào không chạy được; **ORCHESTRATOR chạy test web, full suite và mọi lần chạy với dịch vụ thật** (AI, mạng) ngoài sandbox trước READY. Pilot: Codex tự báo BLOCKED / "chưa PASS" đúng sự thật khi không chạy được, không claim PASS.
4. Sau khi chạy: `git status` / `git diff --stat` (pilot: Codex không commit / push, không sửa ngoài Owned paths), review theo `core/docs/ai/workflow.md` §7.
5. Vòng sửa cùng context: `codex exec resume <session id> -c sandbox_mode='"workspace-write"' -c model_reasoning_effort='"high"' -o … - < <finding.md>` (`resume` nhận cấu hình qua `-c`).
6. Reviewer thứ hai (tùy chọn, read-only): `codex exec review --commit <sha> -c sandbox_mode='"read-only"' -o <tmp>/review.out` (`review` không nhận `-s`; `--uncommitted` cho diff chưa commit). Finding là thông tin để ORCHESTRATOR kiểm.

### Quota

Gói Codex có cửa sổ giới hạn ngắn (pilot: 5 giờ) và tuần; `codex exec` không in mức dùng. `scripts/codex-usage.py` (có trong project này) đọc `rate_limits` mới nhất trong `~/.codex/sessions`. Gợi ý: cửa sổ ngắn ≥ 85 % hoặc tuần ≥ 80 % → giao IMPLEMENTER dự phòng trong Danh sách IMPLEMENTER; Codex hết quota giữa chừng → ORCHESTRATOR kiểm diff dở rồi giao tiếp cho dự phòng, ghi vào Result.

### Số đo pilot (tham khảo, không phải cam kết)

| Việc | Thời gian | Tokens | Kết quả review |
|---|---|---|---|
| Module render mới (~330 dòng + 25 test, ffmpeg) | ≈ 13 phút | 147k | 0 blocking |
| Phần web (routes + UI + tests) | — | 159k | 1 blocking (hiệu năng) → 1 vòng sửa 236k |
| Sửa prompt / validation AI, retry, tiêu đề, kho nguồn | 2–6 phút | 47–120k | 0 blocking |
| Review read-only một commit | ≈ 1 phút | ≈ 2 % cửa sổ 5 giờ | khớp review ORCHESTRATOR |

Ba lượt implement lớn liên tiếp dùng ≈ 84 % cửa sổ 5 giờ, ≈ 14 % tuần. Cùng giai đoạn, subagent Sonnet: 33–78k tokens / task, 0 blocking. Phân vai gợi ý: Codex cho việc tự chứa, spec rõ (tiết kiệm hạn mức của ORCHESTRATOR) và reviewer thứ hai; IMPLEMENTER native của ORCHESTRATOR làm dự phòng và cho việc cần chạy server / socket trong vòng lặp.

## Mẫu delegation prompt sang Claude Code Sonnet

```text
Bạn là IMPLEMENTER duy nhất cho task <ID>. Codex là ORCHESTRATOR bên ngoài và sẽ review sau.

Task contract (APPROVED): <đường dẫn tới docs/tasks/<ID>.md>
Repository: <repo>   Worktree: <đường dẫn>   Branch: <branch>   Base: <sha>
Implementation authorized: YES
Plan ngắn:
1. ...
2. ...

Xác minh remote / branch / HEAD / working tree trước khi sửa; lệch thì BLOCKED.
Chỉ sửa trong Owned paths. Không gọi agent khác, không commit, không push, không tạo PR.
Chạy required verification và dừng ở READY report: thay đổi chính, verification
(lệnh + exit code + kết quả), finding ngoài scope, giới hạn.
```

### Project config mẫu (tùy chọn: binding cố định, adopted project)

Chỉ dùng khi HUMAN LEAD chủ ý ràng buộc cố định ORCHESTRATOR; project mới từ kit không đặt `agents.orchestrator`.

```json
{
  "adapters": ["codex", "claude-code"],
  "agents": {
    "orchestrator": "codex"
  }
}
```

`agents.orchestrator = "codex"` yêu cầu `codex` có trong `adapters` và descriptor khai role `orchestrator`. IMPLEMENTER không nằm trong `agents`: ghi ở task contract (`Implementer: claude-code — Sonnet`). Capabilities trong descriptor không cấp authorization.

### Starter-kit root và adopted project

Starter-kit root (repo kit) **không** phải adopted project: không có `AGENTS.md`, `framework.config.json`, `docs/ai/project-profile.md`, `docs/workflow/current-state.md` hay subagent Claude đã đăng ký. Làm việc ở kit thì dùng `core/`, `templates/`, ADR trong `docs/decisions/` và task contract. Ở adopted project, chỉ đọc các entry point thực sự tồn tại (`AGENTS.md`, project profile, current-state, `framework.config.json`).

## Sự kiện đã tra (2026-09-29)

- Codex CLI đọc `AGENTS.md` và có `codex exec` chạy non-interactive. Nguồn: https://learn.chatgpt.com/docs/codex/cli
- Codex CLI có từ gói Plus trở lên, hoặc dùng API key tính theo token. Nguồn: https://learn.chatgpt.com/docs/pricing
- Cài theo trang CLI ở trên: `curl -fsSL https://chatgpt.com/codex/install.sh | sh`. Ngoài ra trên registry npm có gói `@openai/codex` (`npm view @openai/codex version` trả 0.159.0 lúc tra); đây là thông tin tham khảo, không bắt buộc và chưa cài thử.
- Cờ sandbox / approval của `codex exec`: **chưa xác minh được từ nguồn chính thức** → cần xác minh khi pilot (`codex exec --help`). Không đoán tên cờ.

## Cài đặt vào project

Phần này áp dụng cho vai trò IMPLEMENTER; ORCHESTRATOR xem mục trên. Không cần file adapter riêng: Codex đọc `AGENTS.md` (đã luôn bắt buộc). Thêm `"codex"` vào `adapters` trong `framework.config.json` và khai adapter trong Danh sách IMPLEMENTER (`docs/ai/project-profile.md` §7).

## Cách chạy (tùy chọn: `codex exec` làm IMPLEMENTER)

1. ORCHESTRATOR tạo worktree / branch, viết task contract (`Implementer: codex — <lý do>`, `Implementation authorized: YES`).
2. Chạy `codex exec` trong worktree với delegation prompt (mẫu dưới). Yêu cầu khi chọn cờ (cần xác minh cờ cụ thể): được ghi file trong worktree; không commit / push / tạo PR; không truy cập mạng nếu task không cần.
3. Codex chạy required verification, trả READY report.
4. ORCHESTRATOR review diff trên cùng branch (`core/docs/ai/workflow.md` §7).

Chặn commit / push không chỉ bằng prompt: dùng cơ chế sandbox / approval của Codex khi đã xác minh, hoặc kiểm `git status` / `git log` sau khi chạy.

## Mẫu delegation prompt

```text
Bạn là IMPLEMENTER cho task <ID>.

Task contract (APPROVED): <đường dẫn tới docs/tasks/<ID>.md>
Base commit: <sha>   Branch: <branch>   Worktree: <đường dẫn>
Implementation authorized: YES
Plan ngắn:
1. ...
2. ...

Làm theo AGENTS.md và task contract. Chạy required verification theo Test policy.
Không commit, không push, không tạo PR. Dừng ở READY và trả READY report:
thay đổi chính, verification (lệnh + kết quả), finding ngoài scope, giới hạn.
```

## Checklist pilot

Chạy trên một task S1 nhỏ, ít rủi ro.

- [x] Xác minh cờ sandbox / approval của `codex exec`; ghi vào README này (mục "Cách chạy").
- [ ] Codex đọc `AGENTS.md`, project profile, current-state và task contract trước khi sửa.
- [ ] Dừng BLOCKED khi prompt thiếu contract / base / `Implementation authorized: YES`.
- [x] Không commit / push / tạo PR; không sửa ngoài scope.
- [x] Chạy required verification và báo kết quả thật.
- [x] READY report đủ 4 mục.
- [x] Số blocking finding ở review không cao bất thường.
- [ ] ORCHESTRATOR: pilot một task S1 nhỏ theo mục "Vai trò ORCHESTRATOR" (kiểm base, delegation thủ công sang Claude, review, READY/BLOCKED) và ghi evidence.
- [x] Ghi số đo (thời gian, chi phí / hạn mức) và cập nhật tiêu chí trong Danh sách IMPLEMENTER; gỡ nhãn "CHƯA KIỂM CHỨNG" cho vai trò IMPLEMENTER (mục "Số đo pilot").
