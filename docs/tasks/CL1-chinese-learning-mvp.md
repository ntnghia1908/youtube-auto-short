# Task: CL1 — Chinese Learning MVP (experiment)

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Human Lead: HUMAN LEAD
- Base commit / branch: `eab3134` / `feature/cl1-chinese-learning` (worktree `../youtube-auto-short-cl1`, tạo 2026-09-27)
- Human Lead approval: kiến trúc duyệt về nguyên tắc 2026-09-27; chỉ CL1.1 APPROVED (`docs/tasks/CL1.1-chinese-captions-media.md`); CL1.2–CL1.4 pending; G4, G6 tạm
- Implementation authorized: NO

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm ứng dụng thứ hai vào host repository và quy ước host/application (G1, G11); namespace artifact mới `work/_learning/`; public route/API web và CLI mới; mở rộng shared abstraction `run_stage` (CP2 D6). Không thêm dependency.

Revision R2 (2026-09-27): Chinese Learning là **ứng dụng riêng** dùng chung hạ tầng, không phải feature/stage của Auto Short. Thay R1 (`work/<id>/learning/`, route trong `web/`).

## Goal

Dán một URL video YouTube tiếng Trung vào web → sau vài phút có bài học cho **5 phút đầu**: câu chữ Hán + Pinyin + nghĩa tiếng Việt đồng bộ với video; bấm câu để nghe lại, lặp câu, ẩn/hiện Pinyin/nghĩa; tiến độ nhớ trên trình duyệt. Auto Short giữ nguyên behavior.

## Scope

- In scope:
  - Package ứng dụng `src/auto_short/learning/` (contract C3 NEW): stage `subtitle`, `media`, `lesson`; orchestrator `run_learning`; preflight; CLI handler; router web + static.
  - Namespace `work/_learning/<id>/` bằng `Workspace` nguyên trạng (C4).
  - Tham số `downstream` cho `run_stage` / `mark_downstream_stale` (G3), mặc định giữ CP2 D6.
  - Config `[learning]` (additive), subparser `learn`, mount router trong `create_app`, allow-list kind trong `api_list`, một link ở `index.html`.
  - Tests (fetcher/Ollama/yt-dlp giả), số đo thật, docs.
- Out of scope:
  - Whisper tiếng Trung; file local, playlist, channel; phần sau 5 phút.
  - Sửa `pipeline.py`, `ingest/`, `transcript/`, `analysis/`, `selection/`, `titling/`, `render/`, `review/`, `web/jobs.py`, `web/episodes.py`, `web/playlists.py`, `web/storage.py`, `web/auth.py`, `web/urls.py`.
  - Tách/di chuyển hạ tầng loại C (caption fetcher, Ollama client/preflight, JobRunner) sang module chung; đổi tên package `auto_short`; lớp shared source giữa hai ứng dụng; bài học trong tab Bộ nhớ.
  - Giản ↔ phồn thể, tách từ, từ điển, chấm phát âm, Anki/SRS, gamification, TTS, AI tutor, tài khoản, database, React, app mobile, đồng bộ tiến độ.
  - Dependency mới (`pypinyin`, `opencc`…); sửa `pyproject.toml`.

## Authority / key decisions

- `docs/decisions/CL1-chinese-learning-contract.md` (PROPOSED R2; C0–C12, G1–G11) — canonical owner khi ACCEPTED.
- `docs/decisions/CP2-workspace-contract.md` D3, D5–D8; `CP3-transcript-contract.md` T2, T5 #2, T6; `CP8.3-web-contract.md` W2, W5, W7, W9 S4; `CP1-product-contract.md` §10, §11.
- Gate HUMAN LEAD: **G1** ứng dụng thứ hai; **G2** `work/_learning/<id>/` + xóa độc lập; **G3** orchestrator riêng + `run_stage(downstream=…)`; **G4** thứ tự track; **G5** clip cục bộ; **G6** AI + `[learning]`; **G7** router thuộc app + job kind; **G8** CLI `learn`; **G9** không dependency; **G10** profile/branch/worktree; **G11** quy ước host/application.

## Implementation approach

Bốn task con tuần tự trên cùng branch (một writer); mỗi task có review diff-first + verification riêng trước khi sang task sau; READY toàn CL1 sau CL1.4.

Protected cho **mọi** task con (không sửa): danh sách MUST NOT MODIFY ở contract C3, cộng mọi test hiện có.

### CL1.1 — Chinese caption acquisition + 5-minute media artifact

**APPROVED 2026-09-27** (HUMAN LEAD: "APPROVE ONLY CL1.1"). Contract riêng, canonical cho task con này: `docs/tasks/CL1.1-chinese-captions-media.md` (gồm cả stage `media` lấy clip 0–300 s, trước đây ở CL1.3).

### CL1.2 — AI enrichment + `lesson.json`

- Scope: `learning/prompt.py`, `learning/enrich.py`, `learning/lesson.py`, `learning/preflight.py`; `[learning]` đủ key C7; `learn` chạy `subtitle → lesson`.
- Acceptance Criteria:
  1. Payload Ollama chỉ chứa `id` + `zh` (không `start`/`end`/số giây).
  2. AI giả trả `start`/`end`/`zh` khác → `lesson.json` vẫn mang giá trị từ subtitle; `lines_sha256` khớp tính trực tiếp.
  3. Thiếu/thừa/trùng `id`, `pinyin`/`vi` rỗng, pinyin có chữ Hán → retry; hết retry → `failed` + batch + lý do; artifact bị xóa; khi thành công `lesson_log.json` có request/response thô + lý do reject mọi lần thử.
  4. `lesson.json` đúng C8, thứ tự key cố định, không có thời điểm tạo; chạy lại với AI giả deterministic → byte-identical; skip khi up to date; đổi `prompt_version`/`model` → chạy lại.
  5. Preflight lỗi (không tới được / thiếu model) → lỗi rõ trước khi gọi AI.
- Required verification: `pytest -q`; `pytest -q tests/test_learning_lesson.py tests/test_learning_enrich.py`; chạy thật 2 video CL1.1 với `qwen3:14b` (think off) + 1 model so sánh → thời gian, số retry, 20 dòng mẫu vào § Đo thực tế; HUMAN LEAD chốt model (G6).
- Files allowed: `src/auto_short/learning/{prompt,enrich,lesson,preflight,run,cli}.py`, `src/auto_short/config.py` + `config.example.toml` (`[learning]`), tests learning mới, contract § Đo thực tế.
- Files protected: C3 MUST NOT MODIFY (đặc biệt `selection/client.py`, `pipeline.py`); `workspace.py`; `web/`.

### CL1.3 — Media + web backend

- Scope: (lấy clip đã chuyển sang CL1.1) `learning/web.py` (router, job target `learning:<id>`, xóa có guard, route clip); `web/app.py` mount router + allow-list kind trong `api_list`.
- Acceptance Criteria:
  1. Mọi route learning: chưa đăng nhập → 401 JSON (API/file) hoặc 303 login (trang); không thêm public path.
  2. `POST /api/learning`: video → 202 + job; trùng active → 200 cùng job; playlist/không phải YouTube → 422; preflight lỗi → 503; ổ dưới ngưỡng CP8.6 → 507.
  3. Job learning và Auto Short chung một worker (không đồng thời); job learning không xuất hiện trong `GET /api/episodes`; job Auto Short cùng video id vẫn submit được khi job learning active và ngược lại.
  4. `GET /api/learning/{id}` trả lesson + stage + job; id sai → 404; `DELETE` xóa đúng `work/_learning/<id>/` (fixture `work/<id>/` + `output/<id>/` cùng id còn nguyên), 409 khi job active; "Xóa tập" Auto Short cùng id không chạm `work/_learning/<id>/`.
  5. Route clip (`clip.mp4` do CL1.1 tạo) trả 206 với `Range`; path không lấy từ client.
  6. Mọi test web hiện có PASS không sửa.
- Required verification: `pytest -q`; `pytest -q tests/test_web_learning.py` (TestClient, runner/pipeline/learning giả); 
- Files allowed: `src/auto_short/learning/{web,run,cli}.py`, `src/auto_short/web/app.py` (chỉ mount + allow-list kind), `src/auto_short/config.py` + `config.example.toml` (`media_format`), tests mới, contract § Đo thực tế.
- Files protected: C3 MUST NOT MODIFY (đặc biệt `web/jobs.py`, `web/episodes.py`, `web/storage.py`, `review/delete.py`); `workspace.py`.

### CL1.4 — Web UI học + tiến độ + docs

- Scope: `learning/static/learn.html`, `lesson.html`, `learn.js` (player, danh sách câu, highlight, bấm → seek, lặp câu, tốc độ 0.75/1, ẩn/hiện Pinyin/nghĩa, "đã thuộc"); localStorage C11; layout ≤ 640 px; một link ở `web/static/index.html`; docs.
- Acceptance Criteria:
  1. Bấm câu → video tới `start`; câu đang phát highlight theo `currentTime ∈ [start, end)`.
  2. Lặp câu phát lại `[start, end)` tới khi tắt.
  3. Ẩn/hiện Pinyin và nghĩa độc lập, giữ sau tải lại.
  4. Tiến độ giữ sau tải lại, riêng theo `episode_id`, key `auto-short.learn.v1.<id>`; storage lỗi → trang vẫn chạy; không request nào gửi tiến độ.
  5. Không thư viện JS ngoài, không build step (test: mọi `<script src=` trỏ path same-origin); 360 px không cuộn ngang.
  6. Trang Auto Short không đổi hành vi (ngoài link mới).
  7. Docs: contract CL1 → ACCEPTED + số đo; `project-profile.md` mục Applications, module map `learning/`, authority; pointer CP2 D6, CP3 (reuse parser/normalize), CP8.3 (router learning, allow-list kind); README (`learn`, `/learn`); `config.example.toml`.
- Required verification: `pytest -q`; `node scripts/framework-check.mjs`; manual test HUMAN LEAD (checklist) trên desktop + điện thoại trong LAN.
- Files allowed: `src/auto_short/learning/static/*`, `src/auto_short/learning/web.py` (phục vụ trang), `src/auto_short/web/static/index.html` (một link), tests mới, docs liệt kê ở AC7.
- Files protected: C3 MUST NOT MODIFY (mọi `web/static/*` khác, `app.js`, `style.css`); `docs/workflow/current-state.md` (do HUMAN LEAD / session điều phối cập nhật).

## Acceptance Criteria

1. CL1.1–CL1.4: mọi AC từng task con đạt.
2. Auto Short không đổi behavior: toàn bộ test hiện có PASS không sửa; `git diff <base> -- src/auto_short/pipeline.py src/auto_short/ingest src/auto_short/transcript src/auto_short/analysis src/auto_short/selection src/auto_short/titling src/auto_short/render src/auto_short/review src/auto_short/web/jobs.py src/auto_short/web/episodes.py src/auto_short/web/playlists.py src/auto_short/web/storage.py src/auto_short/web/auth.py src/auto_short/web/urls.py` rỗng.
3. Ownership: learning chỉ ghi trong `work/_learning/`; hai chiều xóa độc lập (CL1.3 AC4).
4. Timestamp bất biến (CL1.2 AC2).
5. Không dependency mới (`git diff <base> -- pyproject.toml` rỗng).
6. Docs theo CL1.4 AC7.

## Required verification

- `pytest -q` — PASS cuối mỗi task con và trước READY.
- Test riêng từng task con như trên.
- Các lệnh `git diff` ở AC2, AC5 rỗng.
- `node scripts/framework-check.mjs` PASS.
- Số đo thật CL1.1–CL1.3 trong contract (chốt G4, G5, G6).

Tất cả phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task **chạm public API contract** (route/API/CLI mới) và **security surface** (route mới sau auth hiện có; route file mới). Không chạm database. Manual test là **gate trước integration**.

- [ ] Chưa đăng nhập mở `/learn`, `/learn/<id>`, `/api/learning`, `/files/learning/<id>/clip.mp4` → login / 401.
- [ ] URL có phụ đề Trung manual → bài 5 phút đầu, câu khớp video.
- [ ] URL chỉ có auto caption Trung → chạy được, `source.json` `auto: true`.
- [ ] URL không có phụ đề Trung → lỗi rõ trên web.
- [ ] Bấm câu, lặp câu, đổi tốc độ, ẩn/hiện Pinyin/nghĩa trên desktop và điện thoại.
- [ ] Tải lại → tiến độ còn; trình duyệt khác → trống (đúng thiết kế).
- [ ] Đọc ≥ 20 dòng Pinyin/nghĩa: chấp nhận model (G6).
- [ ] Trang chủ Auto Short: tập, job, bộ kinh, Bộ nhớ như trước; không thấy bài học/job learning.
- [ ] Cùng một video ở cả hai: xóa bài học → tập Auto Short còn; xóa tập Auto Short → bài học còn.

## Integration

- Session Auto Short song song dùng working tree chính. CL1 làm trong **worktree riêng** trên `feature/cl1-chinese-learning` (tạo khi APPROVE từ `main` mới nhất); không `git add -A`; không sửa `docs/workflow/current-state.md`.
- Điểm dễ xung đột với nhánh Auto Short: `workspace.py` (1 hàm), `config.py` / `config.example.toml` (section mới), `cli.py` (subparser), `web/app.py` (mount + 1 điều kiện), `web/static/index.html` (1 link), docs dùng chung (CL1.4). Rebase lên `main` trước READY nếu `main` đã đổi.
- Commit cục bộ sau APPROVE; push/PR sau READY + HUMAN LEAD approval; merge do HUMAN LEAD.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations: (dự kiến) bài học không hiện trong tab Bộ nhớ; job learning chờ sau job Auto Short (một worker); Pinyin do LLM có thể sai thanh/đa âm; không Whisper fallback; phụ đề/clip tải riêng dù Auto Short đã có cùng video; video id bắt đầu bằng `-`/`_` bị từ chối (giới hạn sẵn có của `validate_episode_id`, chung với Auto Short — finding ngoài scope đã báo HUMAN LEAD).
- PR:
