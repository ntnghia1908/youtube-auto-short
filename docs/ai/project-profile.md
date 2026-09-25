# Project Profile — YouTube Auto Short

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Project stage | CP0 — Framework + project bootstrap |

## 1. Project

- Mục tiêu: tự động biến video tiếng Việt dạng bài giảng thành danh sách YouTube Shorts có đoạn cắt phù hợp, tiêu đề/tựa tự động và layout 9:16 theo template đã duyệt.
- Project mới, greenfield. Không phải fork của `youtube-vietnamese-dubber`.
- `youtube-vietnamese-dubber` là reference implementation để học pattern xử lý media/transcription/rendering; không phải source of truth của project này.
- Framework v4 được adopt từ `ntnghia1908/dang-vu-spring` snapshot `main` commit `c5092ce`.

## 2. Authority order

1. HUMAN LEAD decisions / approved task contracts và accepted project ADR/decision records trong repository;
2. `docs/ai/workflow.md`, `docs/ai/execution-profiles.md` và file này cho workflow/policy;
3. source code và tests hiện hành cho implementation state;
4. `docs/workflow/current-state.md` chỉ là operational state, không phải authority;
5. `README.md` và tài liệu onboarding chỉ mô tả/cross-link, không tạo policy mới.

Không có database, security hay public API authority ở CP0. Nếu những boundary này xuất hiện trong feature sau, phải tạo authority tương ứng trước khi implementation.

## 3. Module map

Các boundary dưới đây là **planned module boundaries**, chưa phải implemented modules:

| Path | Vai trò | Rule riêng |
|---|---|---|
| `src/ingestion/` | input/download/metadata | chưa có module rule |
| `src/transcription/` | speech-to-text + timestamps | chưa có module rule |
| `src/analysis/` | shot/segment/content analysis | chưa có module rule |
| `src/clipping/` | clip boundary selection | chưa có module rule |
| `src/titling/` | title/panel text generation | chưa có module rule |
| `src/composition/` | 9:16 composition/template | chưa có module rule |
| `src/export/` | final media/metadata export | chưa có module rule |
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

CP0 cố ý chưa khóa Python package manager, model, Whisper model, Ollama model, FFmpeg version hay runtime deployment. Những lựa chọn này sẽ được chốt ở task/decision gate tương ứng.

Framework checker: `node scripts/framework-check.mjs`.
