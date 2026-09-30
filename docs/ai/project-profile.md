# Project Profile — YouTube Auto Short

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Project stage | CP8 — End-to-end Auto Short MVP (`auto-short run`) |

## 1. Project

- Mục tiêu: tự động biến video tiếng Việt dạng bài giảng thành danh sách YouTube Shorts có đoạn cắt phù hợp, tiêu đề/tựa tự động và layout 9:16 theo template đã duyệt.
- Project mới, greenfield. Không phải fork của `youtube-vietnamese-dubber`.
- `youtube-vietnamese-dubber` là reference implementation để học pattern xử lý media/transcription/rendering; không phải source of truth của project này.
- Framework v4 được adopt từ `ntnghia1908/dang-vu-spring` snapshot `main` commit `c5092ce`.
- Repository là **host** của hai ứng dụng (HUMAN LEAD 2026-09-27, CL1 G1/G11): **Auto Short** (mục tiêu trên; `work/<id>/`, `output/<id>/`) và **Chinese Learning** (experiment CL1: bài học tiếng Trung từ 5 phút đầu một video YouTube; `src/auto_short/learning/`, namespace `work/_learning/<video_id>/`). Quy ước host/application (package app, namespace `_<app>/`, hướng import, router, job kind): `docs/decisions/CL1-chinese-learning-contract.md` C1.

## 2. Authority order

1. HUMAN LEAD decisions / approved task contracts và accepted decision records trong `docs/decisions/` (hiện có `docs/decisions/CP1-product-contract.md` — product contract & architecture baseline; `docs/decisions/CP2-workspace-contract.md` — workspace/manifest/stage convention; `docs/decisions/CP3-transcript-contract.md` — transcript provider/validation/normalization và schema `transcript.json`; `docs/decisions/CP4-analysis-contract.md` — shot/silence detection, content window, điểm cắt, candidate và schema `shots.json`/`silences.json`/`candidates.json`; `docs/decisions/CP5-selection-contract.md` — AI clip selection: window, prompt/versioning, map về candidate, chọn cuối và schema `clips.json`/`selection_log.json`; `docs/decisions/CP6-titling-contract.md` — header deterministic (CP8.11: danh sách `title_patterns`, "Tên bộ kinh" dự phòng), prompt/versioning titling, validation title và schema `titles.json`/`titling_log.json`; `docs/decisions/CP7-render-contract.md` — layout pixel, font, đo chữ/ngắt dòng/fit, render ffmpeg và schema `render_manifest.json`; `docs/decisions/CP8-pipeline-contract.md` — lệnh `run`, thứ tự stage của pipeline, resume, dừng khi lỗi, `--force-from`, preflight Ollama và exit code; `docs/decisions/CP8.2-title-override-contract.md` — `review.json` title override, validate title tay, `render_key` + tái dùng từng Short, CLI `title`; CP9: điểm cắt tay `cuts`, Short thêm tay `added`, luật đoạn tay T8; `docs/decisions/CP8.3-web-contract.md` — web boundary: lệnh `web`, auth mật khẩu + cookie, input URL, job model, API, phục vụ file; CP8.5: tên file tải về, xóa tập, `publish.json`; CP8.6: tab Bộ nhớ, dọn video nguồn, luật episode archived; CP8.7: bộ kinh, "Xong", tải về = đã đăng; CP8.8: hashtag riêng từng bộ kinh; CP8.11: "Tên bộ kinh" (W7, W10); `docs/decisions/CP8.9-khai-thi-contract.md` — video khai thị (tập `<id>.kt`, `khaithi.json`, thời lượng theo phút, prompt `kt1`, dùng lại nguồn / transcript, CLI `--khai-thi`, web `kinds`, bộ kinh gộp Short + khai thị); `docs/decisions/CP8.15-community-post-contract.md` — bài đăng cộng đồng YouTube từ một Short: text nguồn, prompt AI `post` `v1` (chỉ thêm dấu câu / chia đoạn) + validate token, schema `posts.json` / `post_log.json`, thư viện ảnh + upload + tìm ảnh từ link, config `[post]`, route web + job, security tải ảnh từ link; `docs/decisions/CL1-chinese-learning-contract.md` — ứng dụng Chinese Learning và quy ước host/application: PROPOSED, kiến trúc duyệt về nguyên tắc, task `docs/tasks/CL1.1-chinese-captions-media.md` READY);
2. `docs/ai/workflow.md`, `docs/ai/execution-profiles.md` và file này cho workflow/policy;
3. source code và tests hiện hành cho implementation state;
4. `docs/workflow/current-state.md` chỉ là operational state, không phải authority;
5. `README.md` và tài liệu onboarding chỉ mô tả/cross-link, không tạo policy mới.

Không có database, security hay public API authority ở CP0/CP1. Nếu những boundary này xuất hiện trong feature sau, phải tạo authority tương ứng trước khi implementation. Web MVP (CP8.3) là boundary security + HTTP API đầu tiên; authority: `docs/decisions/CP8.3-web-contract.md`.

## 3. Module map

Các boundary dưới đây là **planned module boundaries**, chưa phải implemented modules, trừ mục ghi *implemented*. Stage và artifact tương ứng theo `docs/decisions/CP1-product-contract.md` §8; package layout, manifest và stage convention theo `docs/decisions/CP2-workspace-contract.md`:

| Path | Stage / vai trò | Rule riêng |
|---|---|---|
| `src/auto_short/` (`workspace.py`, `hashing.py`, `config.py`, `cli.py`) | stage framework dùng chung, config, CLI — *implemented* (CP2) | `docs/decisions/CP2-workspace-contract.md` |
| `src/auto_short/khaithi.py` | tập khai thị: `khaithi.json` + tham số hiệu lực analysis / selection, dùng chung stage, CLI, web — *implemented* (CP8.9) | `docs/decisions/CP8.9-khai-thi-contract.md` |
| `src/auto_short/post/` | bài đăng cộng đồng của một Short: text nguồn, AI thêm dấu câu / chia đoạn (Ollama) + validate, `posts.json` / `post_log.json`, thư viện ảnh + tìm ảnh từ link — *implemented* (CP8.15); web chỉ gọi | `docs/decisions/CP8.15-community-post-contract.md` |
| `src/auto_short/pipeline.py` | điều phối end-to-end `ingest → … → render` + preflight Ollama (lệnh `run` trong `cli.py`) — *implemented* (CP8) | `docs/decisions/CP8-pipeline-contract.md` |
| `src/auto_short/ingest/` | ingest: input/download/metadata — *implemented* (CP2) | `docs/decisions/CP2-workspace-contract.md` |
| `src/auto_short/transcript/` | transcript: caption YouTube / subtitle local / Whisper + timestamps — *implemented* (CP3) | `docs/decisions/CP3-transcript-contract.md` |
| `src/auto_short/analysis/` | analysis: shot/silence detection + candidate generation (deterministic) — *implemented* (CP4) | `docs/decisions/CP4-analysis-contract.md` |
| `src/auto_short/selection/` | selection: AI (Ollama) chọn clip trong candidates + validate — *implemented* (CP5) | `docs/decisions/CP5-selection-contract.md` |
| `src/auto_short/titling/` | titling: header deterministic + AI (Ollama) sinh title/hook + validate — *implemented* (CP6) | `docs/decisions/CP6-titling-contract.md` |
| `src/auto_short/review/` | review: human approve/reject/edit — *implemented, partial* (CP8.2: title tay `review.json`; CP8.5: xóa / khôi phục Short `rejected`, `publish.json` "Đã đăng", tên file tải về, xóa tập; CP8.6: dọn video nguồn, cờ archived `archive.json`; CP9: điểm cắt tay theo dòng caption + tinh chỉnh ±0.2 s, thêm Short từ đề xuất AI / transcript (`cuts.py`, `shorts.py`; title AI một Short `titling/added.py`); approve từng Short, sửa header: không làm) | `docs/decisions/CP8.2-title-override-contract.md`; CP8.5 phần web: `docs/decisions/CP8.3-web-contract.md` W8 |
| `src/auto_short/web/` | web MVP: `auto-short web` (FastAPI, extra `[web]`), đăng nhập mật khẩu, gửi URL YouTube, job nền chạy pipeline, tiến độ, xem/tải Short, sửa title một Short + render lại (qua `review`) — *implemented* (CP8.3); tên file tải về, xóa / khôi phục Short, xóa tập, "Đã đăng" + bộ lọc — *implemented* (CP8.5); tab Bộ nhớ, gợi ý dọn, cảnh báo ổ đầy — *implemented* (CP8.6); bộ kinh (playlist), "Xong" suy ra, tải về = đã đăng — *implemented* (CP8.7); hashtag riêng từng bộ kinh — *implemented* (CP8.8); "Tên bộ kinh" — *implemented* (CP8.11); video khai thị (gửi `kinds`, nhãn, link qua lại, bộ kinh gộp Short + khai thị) — *implemented* (CP8.9); hàng đợi theo làn prepare / ai / render (`[web] queue_mode`) — *implemented* (CP8.10); "Thêm Short" (đề xuất AI / transcript) + "Sửa đầu/cuối" + "Nghe thử" — *implemented* (CP9); bài đăng cộng đồng mỗi Short + thư viện ảnh (route/job, gọi `post/`) — *implemented* (CP8.15); tab Bài đăng + tự soạn (job `post` khóa riêng, `clips: "auto"`) — *implemented* (CP8.16) | `docs/decisions/CP8.3-web-contract.md` |
| `src/auto_short/render/` | render: composition 9:16 theo template (font OFL đóng gói) + export `output/<id>/` — *implemented* (CP7) | `docs/decisions/CP7-render-contract.md` |
| `src/auto_short/learning/` | ứng dụng Chinese Learning (`auto-short learn <url>`): orchestrator riêng `subtitle → media → lesson`, chọn phụ đề tiếng Trung gốc, clip 5 phút đầu tải một phần, AI Pinyin + nghĩa tiếng Việt → `lesson.json`, artifact trong `work/_learning/<id>/` — *implemented, partial* (CL1.1 subtitle/media; CL1.2 `lesson.json`; web thuộc CL1.3–CL1.4) | `docs/decisions/CL1-chinese-learning-contract.md` |
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

### Test policy

Canonical owner; áp dụng cho mọi IMPLEMENTER bất kể tool (HUMAN LEAD 2026-09-29, FW-implementer-speed D2).

- Trong vòng sửa: chạy test liên quan tới thay đổi (file hoặc `-k`), nên dùng `-x --tb=short`.
- Toàn bộ suite: một lần trước khi báo READY và một lần sau mỗi vòng fix review; không chạy toàn bộ sau từng lần sửa.
- Lệnh chuẩn: `python -m pytest -q -n auto` (cần `pytest-xdist`, extra `dev`); chạy tuần tự (không `-n`) vẫn hợp lệ.
- Không nới `docs/ai/workflow.md` §7: required verification trong task contract vẫn phải chạy và PASS trước READY.
