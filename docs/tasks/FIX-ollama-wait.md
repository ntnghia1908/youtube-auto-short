# Task: FIX-ollama-wait — Đợi GPU (Ollama) thay vì báo lỗi

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; task chạm job runner nhiều thread, cần review diff riêng.
- Base commit / branch: `2c5027d` (`origin/main` 2026-09-30, gồm CP8.16 PR #37 `d0c1517` và CP8.17 PR #38) / `fix/ollama-wait` (worktree `../youtube-auto-short-ollama-wait`). Phụ thuộc CP8.16 (`web/jobs.py`: khóa `<id>#post`, `on_finished`, `PostComposeTarget.followup`) đã thỏa: branch đã rebase lên `2c5027d`.
- Human Lead approval: accepted (HUMAN LEAD 2026-09-30: APPROVE O1–O8 theo đề xuất)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì đổi quyết định đã duyệt: CP8.3 W4 (503 lúc gửi link), W5 (job model: trạng thái đợi GPU, `PREFETCH_LIMIT`), W7 (field API mới), CP5 B5 / CP6 G6 / CP8.15 P3 (retry khi lỗi kết nối), CP8.15 P1 / P9 (503 soạn bài), CP8 E8 (phân loại lỗi preflight). Không thêm dependency, không đổi schema artifact, không đổi `config_hash` stage nào.

## Bối cảnh

Yêu cầu HUMAN LEAD 2026-09-30. Ollama chạy trên máy GPU, tới máy này qua tunnel `127.0.0.1:11437`; tunnel / máy GPU có lúc sập. Hiện trạng (`bddc0f9`):

- `POST /api/episodes` (cả nút "Xử lý" của bộ kinh) preflight Ollama trong request → 503, không nhận link (W4). Soạn bài (CP8.15 P1) cũng 503.
- Ở làn `ai`, preflight lỗi → job `failed` `ollama preflight: …`; phải gửi lại link bằng tay (W4, CP8.10).
- Ollama sập giữa selection / titling / soạn bài: mỗi lần gọi `OllamaClient.chat` timeout 600 s, stage thử lại `1 + retries` = 3 lần (CP5 B5, CP6 G6, CP8.15 P3) → tới ~30 phút mới báo lỗi; soạn bài hết lượt còn ghi bài `raw` (sai: không phải lỗi của AI).
- `PREFETCH_LIMIT = 2`: làn `prepare` dừng khi 2 job đã chuẩn bị đợi làn `ai` → khi GPU sập, tải / transcript / analysis cũng đứng.

Ràng buộc HUMAN LEAD: **không chạy Ollama trên CPU** — không fallback sang Ollama cục bộ / host khác, chỉ đợi GPU có lại. Tunnel tự nối lại là việc bên máy GPU (ngoài repo).

## Goal

Khi GPU / Ollama mất kết nối: web vẫn nhận link và soạn bài; job chạy hết phần không cần GPU (ingest / transcript / analysis) rồi **đợi GPU** ở làn `ai` thay vì `failed`; làn `ai` tự kiểm lại Ollama mỗi ~60 s và tự chạy tiếp khi có lại, không cần bấm gì. Lỗi kết nối không bị thử lại 3 × 600 s. UI cho thấy đang đợi GPU.

## Quyết định (HUMAN LEAD 2026-09-30: APPROVE O1–O8 theo đề xuất)

- **O1. Hai loại lỗi Ollama.**
  - *Mất kết nối* (`unavailable`): không kết nối được / bị ngắt (`URLError`, `ConnectionError`, `RemoteDisconnected`, `OSError` khác của socket), HTTP 502 / 503 / 504, và timeout **khi kiểm lại `GET /api/tags` (10 s) cũng không được** (O3). → đợi GPU (web) / dừng ngay không retry.
  - *Lỗi khác*: thiếu model, HTTP khác, response không hợp lệ, AI trả sai schema / không khớp. → như hiện nay (retry theo stage, job `failed`). Đợi không sửa được lỗi cấu hình.
  - Code: `ChatUnavailable(ChatError)` trong `selection/client.py`; `OllamaUnavailable(PreflightError)` trong `pipeline.py`, `ollama_preflight` và `post.stage.preflight` raise nó cho lỗi kết nối. Là subclass → CLI và mọi chỗ bắt `ChatError` / `PreflightError` giữ hành vi (exit 1, message cũ).
- **O2. Không retry lỗi mất kết nối** (sửa CP5 B5, CP6 G6, CP8.15 P3, và title AI của Short thêm tay CP9 C6): gặp `ChatUnavailable` → dừng stage / job ngay, không backoff, không lượt tiếp:
  - selection: `SelectionError` như hiện nay (window lỗi), chỉ không thử lại.
  - titling: dừng **cả stage** (`failed`) — không đánh clip `untitled` rồi đi tiếp clip sau (G6 "mixed retry" không áp cho mất kết nối).
  - soạn bài: dừng job, **không ghi bài `raw`**, bài đang có giữ nguyên.
  - Short thêm tay (CP9): như lỗi preflight hiện có — Short `untitled`, vẫn render, job `failed` "gõ tiêu đề tay" (không đổi hành vi, chỉ bỏ retry).
  - Áp cho cả CLI (`auto-short run`, lệnh lẻ): lỗi kết nối báo nhanh hơn, exit code / message không đổi. Các lỗi khác retry như cũ. `learning/` (CL1) không đổi (bắt `ChatError`, subclass tương thích).
- **O3. Timeout.** `OllamaClient.chat` timeout (600 s, không đổi) → kiểm ngay `GET <host>/api/tags` (10 s): không được → `ChatUnavailable`; được → `ChatError` timeout thường (model chậm thật, retry như cũ). Tunnel treo: tối đa ~610 s thay vì ~1830 s.
- **O4. Gửi việc không còn 503.** `POST /api/episodes` (tập lẻ, "Xử lý" / "Chạy tiếp" bộ kinh) và `POST /api/episodes/{id}/posts` (tay + tự động CP8.16) **không preflight trong request**: luôn xếp job (202), trừ các lỗi khác đã có (422 / 409 / 507). Model thiếu (lỗi cấu hình) báo ở làn `ai` (job `failed`). **Không đổi:** "Thêm Short" CP9 (`POST /api/episodes/{id}/shorts`) vẫn preflight + 503 — người dùng đang thao tác, có đường gõ tiêu đề tay.
- **O5. Làn `ai` đợi GPU** (`queue_mode = "lanes"`):
  - Trước khi chạy một job `pipeline` / `post`, làn `ai` chạy preflight của job đó (như hiện nay). `OllamaUnavailable` → làn vào trạng thái **`gpu_down`**: job trả về **đầu** hàng `ai` (vẫn `running` + `waiting`, W5), không `failed`.
  - Stage / job ở làn `ai` lỗi giữa chừng (selection / titling / soạn bài) → làn kiểm preflight một lần: `unavailable` → như trên (job về đầu hàng, lần sau chạy lại từ stage lỗi — selection làm lại từ đầu stage, CP8 E3); preflight được → lỗi thật, job `failed` như cũ.
  - Trong `gpu_down`: làn ngủ ~60 s (hằng `GPU_RETRY_SECONDS = 60` trong code, không phải config; ngủ bằng `Condition.wait` nên dừng server không phải đợi), rồi preflight job đầu hàng; được → log `web: ollama is back`, làn về `ok`, chạy tiếp FIFO; không → ngủ tiếp. Không giới hạn thời gian đợi.
  - Job `add` (CP9) trong hàng `ai` khi `gpu_down`: không đợi — được lấy ra chạy ngay (preflight lỗi → Short `untitled` + render, như CP9), để không giữ khóa episode (409 sửa Short) vô hạn.
  - **Sửa đổi FIX-post-doc-no-gpu (HUMAN LEAD 2026-10-02, F1–F4; `docs/tasks/FIX-post-doc-no-gpu.md`):** job `post` không còn preflight ở đầu job: `compose_posts` gọi preflight trễ (`before_ai`, đúng một lần, ngay trước Short đầu tiên cần AI), nên bài lấy từ văn bản gốc (CP8.19, không gọi AI) soạn được khi GPU tắt. Trong hàng `ai` khi `gpu_down`, job `post` **chưa chạy lượt nào** cũng được lấy ra chạy ngay (sau job `add`, FIFO); job `post` đã về hàng do `GpuUnavailable` đợi như mọi job khác. `serial`: cùng preflight trễ. Các dòng khác của O5 không đổi.
  - Dừng server khi làn đang `gpu_down`: job đang đợi → `interrupted` `"interrupted while waiting for GPU"` (như W5 đợi giữa hai làn).
  - `queue_mode = "serial"`: không đợi (job `failed` `ollama preflight: …` như cũ) — serial là chế độ dự phòng; chỉ O2–O4 áp dụng.
- **O6. Bỏ `PREFETCH_LIMIT` khi `gpu_down`:** làn `prepare` chuẩn bị hết các job trong hàng khi làn `ai` đang `gpu_down`; giới hạn 2 áp lại khi GPU có lại (job đã chuẩn bị không bị bỏ). Ngưỡng ổ W9 trước ingest vẫn áp.
- **O7. API + UI.**
  - Job thêm `gpu_wait: bool` (true khi job đang đợi ở làn `ai` trong lúc `gpu_down`, kể cả job đầu hàng).
  - `GET /api/episodes`, `GET /api/episodes/{id}`, `GET /api/playlists/{pid}` thêm `gpu: {state: "ok" | "down", since, error, next_check}` (`since` / `next_check` UTC ISO, `null` khi `ok`). Server không tự dò Ollama khi làn rảnh: `state` phản ánh lần kiểm gần nhất của làn `ai` (mới khởi động = `ok`).
  - UI (trang chủ, trang tập, trang bộ kinh, tab Bài đăng): khi `gpu.state = "down"` hiện dải cảnh báo "Mất kết nối GPU (Ollama) từ HH:MM — tập vẫn được tải / chuẩn bị, phần AI tự chạy tiếp khi GPU có lại (kiểm lại mỗi 60 s)". Nhãn job `gpu_wait` = "đợi GPU (mất kết nối)" (nhãn "đợi GPU" hiện có cho hàng đợi bình thường giữ nguyên). Form gửi link không còn hiển thị lỗi 503.
- **O8. Không làm:** fallback Ollama CPU / host khác; tự nối lại tunnel; tự chạy lại job đã `failed` trước đây; đổi timeout 600 s / `retries` / backoff của lỗi khác; lưu hàng đợi qua restart; đợi GPU cho CLI `run`.

## Scope

- In scope: `src/auto_short/selection/client.py` (`ChatUnavailable`, timeout → kiểm `/api/tags`), `src/auto_short/pipeline.py` (`OllamaUnavailable`, phân loại trong `ollama_preflight`), `src/auto_short/post/stage.py` (`preflight` phân loại; `ChatUnavailable` dừng job, không `raw`), `src/auto_short/selection/stage.py`, `src/auto_short/titling/stage.py`, `src/auto_short/titling/added.py` (không retry `ChatUnavailable`), `src/auto_short/web/jobs.py` (trạng thái `gpu_down`, đợi / kiểm lại, `PREFETCH_LIMIT`, `gpu_wait`, dừng server), `src/auto_short/web/app.py` (bỏ preflight 503 ở O4, field `gpu`), `src/auto_short/web/static/` (dải cảnh báo, nhãn), tests, docs (Documentation impact).
- Out of scope: O8; `learning/`; CLI mới; config key mới; "Thêm Short" 503 (O4); manual test của CP8.15 / CP8.16.

## Authority / key decisions

- `docs/decisions/CP8-pipeline-contract.md` E4, E8; `docs/decisions/CP8.3-web-contract.md` W4, W5, W7; `docs/decisions/CP5-selection-contract.md` B5; `docs/decisions/CP6-titling-contract.md` G6; `docs/decisions/CP8.15-community-post-contract.md` P1, P3, P9; `docs/tasks/CP8.16-post-tab-auto.md` R2–R3 (job `post` tự động, khóa `#post`); job `add` CP9: CP8.3 W5 + `docs/tasks/CP9-clip-review.md` C6.
- Quyết định task: O1–O8 ở trên (sau khi HUMAN LEAD duyệt).

## Implementation approach

- Phân loại lỗi ở tầng client / preflight (subclass), stage chỉ thêm nhánh `except ChatUnavailable: raise` trước nhánh retry.
- `JobRunner` giữ `self._gpu` (state, since, error, next_check) dưới `self._lock`. Vòng làn `ai`: nếu `gpu_down` và job đầu hàng không phải `add` → `wait(timeout)` tới `next_check`, rồi thử preflight job đầu hàng. Việc "đặt job về đầu hàng" và "phân loại lỗi giữa chừng" nằm trong `_loop` / target `ai` (target raise một exception riêng, vd `GpuUnavailable`, để runner phân biệt với `JobFailed`). Preflight inject được để test không cần Ollama thật; thời gian ngủ inject được (test không đợi 60 s).
- `_can_start(PREPARE)`: bỏ điều kiện `PREFETCH_LIMIT` khi `gpu_down`.
- Tương thích CP8.16: job `post` tự động (`on_finished`) xếp bình thường, đợi như job `post` tay; `followup()` không chạy khi job kết thúc do dừng server.

## Acceptance Criteria

1. O1–O3: `OllamaClient.chat` với host không kết nối được / reset / HTTP 503 → `ChatUnavailable`; timeout + `/api/tags` lỗi → `ChatUnavailable`; timeout + `/api/tags` được → `ChatError` thường; HTTP 400 / envelope sai → `ChatError` thường. `ollama_preflight` / `post.stage.preflight`: lỗi kết nối → `OllamaUnavailable`, thiếu model → `PreflightError` thường; CLI `run` exit 1 + message như cũ.
2. O2: selection / titling / soạn bài / title Short thêm tay gặp `ChatUnavailable` gọi AI đúng **1** lần (không retry, không sleep backoff); titling → stage `failed` (không clip `untitled` mới); soạn bài → `posts.json` không đổi (không `raw`). Lỗi khác (sai schema, timeout khi `/api/tags` được) vẫn retry như cũ.
3. O4: `POST /api/episodes` và `POST …/posts` khi preflight sẽ lỗi → 202 + job (không 503); "Thêm Short" vẫn 503.
4. O5: Ollama tắt → job `pipeline` chạy xong làn `prepare`, ở làn `ai` thành `running` + `waiting` + `gpu_wait: true`, không `failed`; bật lại (preflight giả chuyển sang được) → job tự chạy tiếp tới `done`, không gửi lại. Ollama sập giữa selection → job về đầu hàng đợi GPU, không `failed`; lỗi selection thật (preflight được) → `failed`. Nhiều job đợi: chạy lại đúng thứ tự FIFO. Job `post` (tay + tự động CP8.16) đợi như vậy. Job `add` khi `gpu_down` không đợi (Short `untitled`, render, `failed`). Thiếu model → `failed` (không đợi).
5. O5: dừng server khi làn `gpu_down` → job đợi `interrupted` `"interrupted while waiting for GPU"`, `stop()` trả về không đợi hết 60 s. `serial`: preflight lỗi → `failed` như cũ.
6. O6: khi `gpu_down`, 4 job gửi liền → cả 4 xong làn `prepare` (không dừng ở 2); GPU có lại → giới hạn 2 áp lại cho job mới.
7. O7: `gpu` có trong ba API ở O7 (`down` + `since` khi đang đợi, `ok` sau khi có lại); job có `gpu_wait`; UI hiện dải cảnh báo + nhãn "đợi GPU (mất kết nối)" (kiểm bằng manual test).
8. Không regression: toàn bộ suite PASS; test hiện có về 503 lúc gửi link / soạn bài được sửa theo O4 (ghi rõ trong Result, không sửa test để che lỗi).

## Required verification

- `conda run -n auto-short python -m pytest -q -n auto` — toàn bộ PASS (AC 1–8), theo Test policy `docs/ai/project-profile.md` §8.
- Test mới (unit, không cần Ollama thật): client phân loại lỗi qua HTTP server stdlib cục bộ / opener giả (AC1); stage không retry (AC2); route 202 (AC3); runner đợi / chạy tiếp / FIFO / `add` / thiếu model / dừng / prefetch với preflight giả + thời gian ngủ inject (AC4–AC6); field API (AC7).
- `node scripts/framework-check.mjs` PASS.
- Chạy thật trên server test 8081 (dữ liệu bản sao, `OLLAMA_HOST` trỏ tới cổng đóng rồi đổi về 11437 bằng proxy TCP cục bộ tắt / bật được — không đụng tunnel thật): một tập mới đi hết `prepare`, đợi GPU, tự chạy tiếp khi proxy bật lại; ghi thời gian vào Result.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API contract (W4 bỏ 503, field `gpu` / `gpu_wait`) và job model → manual test là gate trước integration. Không chạm database / security model. Server test 8081, dữ liệu bản sao.

- [ ] Tắt đường tới Ollama (proxy test), gửi link tập mới → nhận ngay, tập tải + transcript + analysis, rồi hiện "đợi GPU (mất kết nối)" + dải cảnh báo ở trang chủ / trang tập / trang bộ kinh.
- [ ] Bấm "Xử lý" vài tập trong bộ kinh lúc GPU tắt → tất cả được chuẩn bị (không kẹt ở 2).
- [ ] Bật lại → trong ~60 s dải cảnh báo mất, các tập tự chạy AI → render, bài đăng tự soạn (CP8.16).
- [ ] Tắt GPU giữa lúc selection đang chạy → job không lỗi, về đợi GPU, bật lại chạy tiếp.
- [ ] "Thêm Short" lúc GPU tắt → vẫn báo 503 như trước.

## Documentation impact

- `docs/decisions/CP8.3-web-contract.md` W4 (bỏ 503 lúc gửi link), W5 (đợi GPU, `PREFETCH_LIMIT`, `add`, dừng server), W6 / W7 (`gpu`, `gpu_wait`, dải cảnh báo, nhãn) — "Sửa đổi FIX-ollama-wait".
- `docs/decisions/CP8-pipeline-contract.md` E8 (hai loại lỗi preflight; CLI không đổi).
- `docs/decisions/CP5-selection-contract.md` B5, `docs/decisions/CP6-titling-contract.md` G6, `docs/decisions/CP8.15-community-post-contract.md` P1 / P3 / P9 — pointer tới task này cho luật không retry mất kết nối, O3 timeout, bỏ 503 soạn bài.
- `docs/ai/project-profile.md` §2: thêm task này vào danh sách sửa đổi nếu cần pointer; `docs/workflow/current-state.md`: trạng thái task.

## Result

- Main changes: `ChatUnavailable` / `OllamaUnavailable` (client, `ollama_preflight`, `post.stage.preflight`; timeout → `/api/tags` re-check); selection / titling / soạn bài / `added` không retry lỗi mất kết nối (soạn bài không ghi `raw`); route gửi link + soạn bài không còn 503 (giữ 503 "Thêm Short"); `JobRunner` trạng thái `gpu_down` (đợi 60 s bằng `Condition.wait`, job về đầu hàng `ai`, `add` không đợi, bỏ `PREFETCH_LIMIT` khi down, dừng server → `interrupted while waiting for GPU`); field `gpu` + `gpu_wait`; dải cảnh báo + nhãn UI; docs CP8.3 / CP8 E8 / CP5 B5 / CP6 G6 / CP8.15.
- Tests: mới `tests/test_ollama_wait_client.py` (AC1–AC2), `tests/test_ollama_wait_runner.py` (AC3–AC7). Sửa theo O4 (kỳ vọng 503 lúc gửi link / soạn bài đổi thành 202 + job): `test_web_app.py::test_submit_preflight_error_no_job` (đổi tên `…_still_queues_job`), `test_web_khaithi_cp89.py::test_submit_preflight_and_disk` (khối 503 → 202, hai job `failed`), `test_web_post_cp815.py::test_compose_preflight_failure_503` (đổi tên `…_queues_job`, cả `lanes` / `serial`). Toàn bộ suite `python -m pytest -q -n auto` (ORCHESTRATOR chạy lại trên `80135cb`): 1199 passed, 1 skipped. `node scripts/framework-check.mjs` PASS (IMPLEMENTER).
- Chạy thật 8081 (2026-09-30, giờ UTC; dữ liệu riêng `~/.cache/auto-short-ollama-wait-test/`, `OLLAMA_HOST=127.0.0.1:11438` = proxy TCP test tới 11437, tunnel thật không đụng; tập mới `4oOZz2CBz3g`, chỉ Short): proxy tắt, gửi link 12:45:43 → 202; `prepare` xong (ingest 52 s, transcript Whisper 1720 s, analysis 143 s) → 13:17:38 job `running` + `waiting` + `gpu_wait`, `gpu.state = down`; bật proxy 13:18:02 → `web: ollama is back` 13:18:38 (lần kiểm 60 s kế tiếp), selection chạy; tắt proxy giữa selection 13:19:23 → ~2 s sau job về đợi GPU (không `failed`, không retry); một lần kiểm lại còn lỗi 13:20:23; bật proxy 13:20:40 → tự chạy tiếp, selection làm lại từ đầu (237 s), titling 25 s, render 243 s → `done` 13:29:48, 9/9 Shorts, `gpu.state = ok`; job `post` tự động (CP8.16) xếp ngay sau đó và chạy. Không bấm gì sau khi gửi link.
- Review: round 1 ACCEPTED (ORCHESTRATOR, diff `2b98ca6..80135cb` theo AC 1–8), không blocking finding. Note: (1) `submit()` gộp yêu cầu soạn bài mới vào job `post` đang đợi GPU (thay vì `again`) — trong scope O5, tránh soạn hai lượt; (2) dừng server đúng lúc job làn `ai` vừa nhận lỗi mất kết nối có thể ghi `failed` thay vì `interrupted` (cửa sổ rất hẹp, gửi lại là chạy tiếp).
- Important findings / decisions: base là `2c5027d` (gồm cả CP8.17) thay vì merge commit CP8.16. Manual test checklist: **không chạy** — HUMAN LEAD 2026-09-30 bỏ qua gate manual test, duyệt push + PR ("không cần test"); các ô checklist để trống. "Thêm Short" 503 lúc GPU tắt và O6 (4 job) chỉ kiểm bằng test tự động, chưa chạy thật.
- Known limitations: `job.stages` của lần chạy làn `ai` bị hủy (đợi GPU) được xóa trước khi chạy lại làn; mất kết nối giữa chừng làm lại stage lỗi từ đầu (selection: E3); trạng thái `gpu` chỉ cập nhật khi làn `ai` chạy / kiểm lại (không tự dò khi rảnh).
- PR: #39 (https://github.com/ntnghia1908/youtube-auto-short/pull/39)
