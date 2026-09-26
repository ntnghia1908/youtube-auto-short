# Project Profile — YouTube Auto Short

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Project stage | CP5 — AI clip selection |

## 1. Project

- Mục tiêu: tự động biến video tiếng Việt dạng bài giảng thành danh sách YouTube Shorts có đoạn cắt phù hợp, tiêu đề/tựa tự động và layout 9:16 theo template đã duyệt.
- Project mới, greenfield. Không phải fork của `youtube-vietnamese-dubber`.
- `youtube-vietnamese-dubber` là reference implementation để học pattern xử lý media/transcription/rendering; không phải source of truth của project này.
- Framework v4 được adopt từ `ntnghia1908/dang-vu-spring` snapshot `main` commit `c5092ce`.

## 2. Authority order

1. HUMAN LEAD decisions / approved task contracts và accepted decision records trong `docs/decisions/` (hiện có `docs/decisions/CP1-product-contract.md` — product contract & architecture baseline; `docs/decisions/CP2-workspace-contract.md` — workspace/manifest/stage convention; `docs/decisions/CP3-transcript-contract.md` — transcript provider/validation/normalization và schema `transcript.json`; `docs/decisions/CP4-analysis-contract.md` — shot/silence detection, content window, điểm cắt, candidate và schema `shots.json`/`silences.json`/`candidates.json`; `docs/decisions/CP5-selection-contract.md` — AI clip selection: window, prompt/versioning, map về candidate, chọn cuối và schema `clips.json`/`selection_log.json`);
2. `docs/ai/workflow.md`, `docs/ai/execution-profiles.md` và file này cho workflow/policy;
3. source code và tests hiện hành cho implementation state;
4. `docs/workflow/current-state.md` chỉ là operational state, không phải authority;
5. `README.md` và tài liệu onboarding chỉ mô tả/cross-link, không tạo policy mới.

Không có database, security hay public API authority ở CP0/CP1. Nếu những boundary này xuất hiện trong feature sau, phải tạo authority tương ứng trước khi implementation.

## 3. Module map

Các boundary dưới đây là **planned module boundaries**, chưa phải implemented modules, trừ mục ghi *implemented*. Stage và artifact tương ứng theo `docs/decisions/CP1-product-contract.md` §8; package layout, manifest và stage convention theo `docs/decisions/CP2-workspace-contract.md`:

| Path | Stage / vai trò | Rule riêng |
|---|---|---|
| `src/auto_short/` (`workspace.py`, `hashing.py`, `config.py`, `cli.py`) | stage framework dùng chung, config, CLI — *implemented* (CP2) | `docs/decisions/CP2-workspace-contract.md` |
| `src/auto_short/ingest/` | ingest: input/download/metadata — *implemented* (CP2) | `docs/decisions/CP2-workspace-contract.md` |
| `src/auto_short/transcript/` | transcript: caption YouTube / subtitle local / Whisper + timestamps — *implemented* (CP3) | `docs/decisions/CP3-transcript-contract.md` |
| `src/auto_short/analysis/` | analysis: shot/silence detection + candidate generation (deterministic) — *implemented* (CP4) | `docs/decisions/CP4-analysis-contract.md` |
| `src/auto_short/selection/` | selection: AI (Ollama) chọn clip trong candidates + validate — *implemented* (CP5) | `docs/decisions/CP5-selection-contract.md` |
| `src/auto_short/titling/` | titling: AI sinh title/hook + validate | chưa có module rule |
| `src/auto_short/review/` | review: human approve/reject/edit | chưa có module rule |
| `src/auto_short/render/` | render: composition 9:16 theo template + export | chưa có module rule |
| `tests/` | automated verification | project workflow applies |
| `docs/` | authority, tasks, decisions, workflow | authority by section |
| `scripts/` | development/check tooling | project workflow applies |

Chỉ tạo `<module>/AGENTS.md` khi module có convention riêng đủ rõ.

## 4. Project policy

- Core framework rules không chứa tên model/vendor, media path hay project-specific implementation detail.
- Tên module/file kỹ thuật dùng English; trao đổi và tài liệu nội bộ dùng tiếng Việt trừ tên kỹ thuật/canonical terms.
- Ưu tiên explicit, readable, testable và deterministic pipeline artifacts.
- Artifact trung gian phải được thiết kế để có thể rerun từng stage mà không chạy lại stage trước nếu input artifact vẫn hợp lệ.
- AI selection/title generation phải có artifact có timestamp/input reference để review được quyết định.
- Không tự thêm dependency; dependency là decision gate.
- Không biến `youtube-vietnamese-dubber` thành runtime dependency của project.

## 5. Integration mechanism

- Branch: `feature/<scope>` hoặc `fix/<scope>`.
- Commit cục bộ được phép sau khi task được approve/authorized.
- Push và Pull Request chỉ sau READY + HUMAN LEAD approval.
- Merge do HUMAN LEAD quyết.
- `main` là target integration branch và source of truth.

## 6. Ownership

HUMAN LEAD giữ scope, architecture, dependency, project-wide conventions, integration và milestone decisions. Agent chỉ tự thực thi bên trong boundary đã approve.

## 7. Execution profiles

- Được phép: `single-agent`, `dual-agent`.
- Profile của từng task là source of truth; không suy đoán profile từ tool/model.

## 8. Setup / tools

Runtime, packaging, dependency được duyệt và giả định GPU/Ollama: xem `docs/decisions/CP1-product-contract.md` §10 (canonical owner của danh sách dependency) và §11. Không thêm dependency ngoài danh sách đó khi chưa qua dependency proposal.

Cài đặt môi trường (conda env `auto-short`, `pip install -e ".[dev]"`, `config.toml`, `ffmpeg`) và cách chạy CLI: xem `README.md` (Setup / Usage).

Framework checker: `node scripts/framework-check.mjs`.
