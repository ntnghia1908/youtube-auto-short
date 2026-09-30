# Task: CP8.16 — Tab "Bài đăng" + tự soạn bài đăng cộng đồng

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; task nhiều UI + job runner, cần review diff riêng.
- Base commit / branch: `bddc0f9` (`origin/main`) / `feature/cp8.16-post-tab-auto` (implement trong worktree `../youtube-auto-short-cp816`)
- Human Lead approval: accepted (HUMAN LEAD 2026-09-30: APPROVE — R1–R5 theo đề xuất, gồm R3 job soạn bài khóa riêng và R4 loại bài `manual` khỏi tự soạn lại)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (a) đảo quyết định đã duyệt CP8.15 Q3 / P1 (soạn theo yêu cầu → tự soạn); (b) đổi job model CP8.3 W5 (job soạn bài không còn chiếm khóa "một job mỗi episode", R3); (c) đổi public API web (giá trị `clips: "auto"`, route trang mới, field mới trong `GET /api/episodes/{id}`); (d) đổi UI canonical CP8.15 P9 / CP8.12 U1 (thanh chuyển). Không thêm dependency, không đổi schema `posts.json`, không đổi stage CP2–CP9.

## Bối cảnh

Góp ý HUMAN LEAD 2026-09-30 khi dùng CP8.15 trên 8080 (current-state, CP8.16 PROPOSED):

1. "Bài đăng" thành tab riêng trên trang tập, cùng hàng với switch [Shorts | Khai thị] (CP8.12), thay khu "Bài đăng cộng đồng" trên thẻ Short.
2. Tự soạn bài cho mọi Short và khai thị (đảo Q3 / P1 "theo yêu cầu").
3. Dòng nguồn bài đăng ghi "HT. Tịnh Không" (có dấu cách), chỉ trong bài đăng, không đổi header video.

Hiện trạng (code `bddc0f9`): khu bài đăng là `postPanel(s)` trong thẻ mỗi Short (`web/static/app.js`), đầu danh sách có `#posts-head` ("Soạn bài cho mọi Short" + đếm); job `post` chạy dưới episode id (`runner.submit(episode_id, KIND_POST, …)`) nên chiếm khóa một-job-mỗi-episode (`_busy` → 409 cho sửa title / cut / thêm / xóa Short); dòng nguồn = `post/logic.header_line` từ `titles.json` `header.fields.speaker` (`[titling] speaker = "HT.Tịnh Không"`).

## Goal

Trang tập có thanh [Shorts | Khai thị | Bài đăng]. Tab "Bài đăng" liệt kê bài đăng cộng đồng của mọi Short + video khai thị của video đó, luôn có sẵn bài mà không cần bấm "Soạn bài": bài được AI soạn tự động ngay sau khi Short dựng xong (và soạn lại khi text nguồn đổi, nếu chưa đăng), không khóa việc sửa Short. Dòng nguồn trong bài ghi "HT. Tịnh Không".

## Quyết định (HUMAN LEAD 2026-09-30: APPROVE theo đề xuất)

- **R1. Tab "Bài đăng" là một view của cả video, gộp Short + khai thị.**
  - URL trang mới `GET /episodes/{id}/posts` (`id` = tập Short `<vid>` hoặc tập khai thị `<vid>.kt`, cùng HTML); thanh chuyển [Shorts | Khai thị | Bài đăng] ở cả ba view, luật mờ / disabled / link của hai nút đầu giữ nguyên CP8.12 U1–U4; nút "Bài đăng" link tới `/episodes/<id đang xem>/posts`.
  - Nội dung: nhóm "Shorts" (bài của tập `<vid>`, nếu tập tồn tại) rồi nhóm "Khai thị" (bài của `<vid>.kt`, nếu có); mỗi nhóm theo thứ tự `render_manifest.json`. Mỗi bài: title Short đang dùng + clip id, link "Xem Short" (mở file mp4 như thẻ Short, không nhúng video), và editor CP8.15 P9 hiện có (nhãn, textarea đoạn + "Lưu đoạn", ảnh + "Đổi ảnh" + "Tải ảnh", ô link + "Lưu link", số ký tự, "Sao chép bài", "Soạn lại", tick "Đã đăng bài") — mở sẵn, không thu gọn.
  - Đầu tab: đếm "Đã đăng x / y" (gộp hai nhóm), trạng thái job soạn bài (đợi / đang soạn / lỗi + thông báo) của từng tập, nút "Soạn bài còn thiếu" (R4 `auto`). Hộp thoại "Thư viện ảnh" chuyển sang trang này (không đổi hành vi).
  - Thẻ Short ở view Shorts / Khai thị: **bỏ** khu "Bài đăng cộng đồng" và `#posts-head`; không thêm badge bài đăng (giữ thẻ gọn).
  - Phương án khác (không đề xuất): tab chỉ hiện bài của tập đang xem — phải chuyển Short ↔ Khai thị rồi mới vào Bài đăng, nút thứ ba trên thanh không rõ nghĩa.
- **R2. Lúc tự soạn** (đảo CP8.15 Q3 / P1):
  - (a) Sau mỗi job của episode có chạy bước render — `pipeline` (tập Short + khai thị), `render` (sửa title / cut / xóa / khôi phục Short), `add` (CP9) — kết thúc (`done` hoặc `failed`), server tự xếp job soạn bài `auto` (R4) của episode đó; tập hợp rỗng → không xếp job.
  - (b) Mở tab Bài đăng (tập cũ, hoặc sau khi server khởi động lại làm mất hàng đợi): trang tự gửi `POST …/posts {clips: "auto"}` một lần mỗi lần tải trang cho mỗi tập có bài thiếu / cần soạn lại, khi tập đó không có job soạn bài đang đợi / chạy.
  - Không tự thử lại bài `raw` (AI không chắc) hay khi Ollama lỗi: job `failed`, tab hiện lỗi + "Soạn bài còn thiếu" / "Soạn lại" bấm tay.
  - Chỉ web (CP8.15 P10): `auto-short run` CLI không tự soạn.
- **R3. Job soạn bài không khóa episode.** Job `post` (tự động và bấm tay) chạy dưới khóa riêng `<episode_id>#post` trong job runner (như `_post_images` CP8.15 P5b), vẫn làn `ai`:
  - Sửa title / cut / thêm / xóa / khôi phục Short **không** bị 409 vì job soạn bài đang đợi / chạy (khác CP8.15 P1). Lý do: ở chế độ `lanes`, job soạn bài có thể phải đợi selection của tập khác trong làn `ai` vài phút; khóa episode suốt lúc đó chặn việc sửa Short ngay sau khi tập vừa dựng xong.
  - Tối đa một job soạn bài đợi / chạy mỗi episode. Gửi soạn bài (tay hoặc tự động) khi đã có job soạn bài **đang đợi** → trả job đó (tập hợp bài được tính lúc job bắt đầu chạy, không lúc xếp). Khi job soạn bài **đang chạy** mà có trigger R2a mới (Short vừa đổi) → job chạy thêm một lượt `auto` ngay sau lượt hiện tại (không mất trigger).
  - Gửi soạn bài bấm tay khi episode đang có job `pipeline` đợi / chạy → 409 (như cũ; text nguồn đang có thể đổi). Trigger tự động chỉ xảy ra khi job episode kết thúc nên không gặp trường hợp này.
  - Xóa tập (CP8.5 X3) khi có job soạn bài đợi / chạy → 409 như job episode; `forget` xóa cả job soạn bài của tập.
  - Soạn bài đọc artifact trong lúc Short có thể đang render lại: kết quả ghi với `source_sha256` đã đọc → nếu text đổi giữa chừng, bài hiện `stale` và được R2a của job render đó soạn lại. Ghi `posts.json` vẫn qua `post_lock` (CP8.15 P7).
  - `GET /api/episodes/{id}` thêm `post_job` (view job như `job`, hoặc `null`); `job` giữ nguyên nghĩa (job episode). Trang tập (view Shorts / Khai thị) không hiện job soạn bài trong khung 6 bước.
- **R4. Tập bài được soạn tự động — `clips: "auto"`** (hàm thuần trong `post/`, canonical cho cả R2a, R2b và nút "Soạn bài còn thiếu"): mọi Short `rendered` chưa xóa mà (i) chưa có bài, hoặc (ii) bài `stale` **và** chưa tick "Đã đăng bài" **và** `origin` khác `manual`.
  - Bài đã tick mà `stale`: giữ, hiện nhãn (đã đăng rồi, không tự đổi).
  - Bài `manual` mà `stale`: giữ chữ sửa tay, hiện nhãn "Text nguồn đã đổi — soạn lại" (tự soạn lại sẽ mất chữ HUMAN LEAD đã sửa); bấm "Soạn lại" nếu muốn. **Điểm cần duyệt:** góp ý gốc là "bài stale chưa tick tự soạn lại"; loại `manual` ra là đề xuất thêm để không mất sửa tay.
  - `clips: "all"` (CP8.15) giữ nguyên nghĩa cho API, UI không còn dùng; `clips: [id…]` ("Soạn lại" một bài) giữ nguyên.
- **R5. Dòng nguồn "HT. Tịnh Không".** Chỉ trong bài đăng (`post/logic.header_line`, P4): trong `speaker`, một dấu `.` đứng ngay trước chữ cái (không có khoảng trắng) được chèn một dấu cách (`HT.Tịnh Không` → `HT. Tịnh Không`; `HT. Tịnh Không` giữ nguyên). Không đổi `titles.json`, `[titling] speaker`, header video, `render_key`. Text sao chép tính lúc đọc API → áp ngay cho mọi bài có sẵn, không cần soạn lại, không đổi `source_sha256` / `stale`.
  - Phương án khác (không đề xuất): `[post] speaker` riêng — thêm config, sai khi có speaker khác trong `title_patterns`.

## Scope

- In scope: `src/auto_short/post/` (hàm tập `auto` R4, `header_line` R5, lượt chạy thêm R3), `src/auto_short/web/jobs.py` (khóa `#post`, trigger sau job render, lượt thêm), `src/auto_short/web/app.py` (route trang `/episodes/{id}/posts`, `clips: "auto"`, `post_job`, 409 / xóa / forget theo R3), `src/auto_short/web/static/` (thanh 3 nút, trang Bài đăng, bỏ khu bài đăng trên thẻ Short), tests, docs (Documentation impact).
- Out of scope: đổi prompt / chiếu / validate P3, schema `posts.json`, thư viện ảnh P5–P5b, bố cục P4 (ngoài R5); CLI; tự soạn trong `auto-short run`; tự thử lại bài `raw`; badge bài đăng trên thẻ Short; "Xong" / gợi ý dọn / `publish.json`; header video; chạy manual test CP8.15 (ghi riêng vào Result CP8.15 khi HUMAN LEAD báo).

## Documentation impact

- `docs/decisions/CP8.15-community-post-contract.md`: P1 (R2, R3, R4), P4 (R5), P9 (R1, route mới, `clips: "auto"`, `post_job`) — ghi "Sửa đổi CP8.16", giữ canonical tại file này.
- `docs/decisions/CP8.3-web-contract.md` W5 (job `post` khóa riêng, trigger sau job render), W6 (thanh 3 nút, trang Bài đăng), W7 (route trang + `post_job`) — chỉ pointer tới CP8.15.
- `docs/tasks/CP8.12-episode-ui.md`: không sửa (lịch sử); CP8.3 W6 trỏ sửa đổi.
- `docs/ai/project-profile.md` dòng module `web/` (thêm "tab Bài đăng + tự soạn — CP8.16"); `AUTO_SHORT_CHECKPOINT_PLAN.md`; `docs/workflow/current-state.md`.

## Implementation approach

- `post/stage.py`: hàm thuần `auto_clips(ep, doc, order)` theo R4; `compose_posts(..., clips="auto")` dùng nó (đọc `posts.json` hỏng → như `all`: coi rỗng, nhưng không ghi đè — theo P7 hiện hành).
- `post/logic.header_line`: chuẩn hóa `speaker` theo R5 (regex `\.(?=[^\W\d_])` → `". "`).
- `web/jobs.py`: helper khóa `post_key(episode_id)`; `PostComposeTarget` có cờ `again` (đặt dưới lock của runner) → chạy thêm một lượt `auto`; callback "job episode kết thúc" (tiêm từ `app.py`, không để `jobs.py` import route) gọi submit job `auto` sau job `pipeline` / `render` / `add` có bước render đã chạy. Chế độ `serial` hoạt động tương tự (một worker).
- `web/app.py`: `/episodes/{id}/posts` phục vụ `posts.html` (static mới); `_busy` cho sửa Short chỉ xét job episode; compose route xét job episode (`pipeline` → 409) + job `#post` (trả job đang đợi); xóa tập xét cả hai khóa.
- `web/static/`: `posts.html` mới (thanh chuyển, hai nhóm, hộp thoại thư viện ảnh chuyển từ `episode.html`), `renderKindBar` thêm nút thứ ba, `postPanel` → editor mở sẵn dùng trên trang mới; gỡ `postPanel` / `#posts-head` khỏi thẻ Short.
- IMPLEMENTER tự quyết chi tiết bên trong các điểm trên; lệch quyết định R1–R5 → dừng, báo ORCHESTRATOR.

## Acceptance Criteria

1. R4: `auto` chọn đúng Short chưa có bài + bài `stale` chưa tick, không `manual`; bỏ qua bài tick / `manual` / còn hợp lệ / Short `rejected`; `all` và danh sách clip giữ hành vi CP8.15.
2. R2a: sau job `pipeline` (tập Short và khai thị), `render` (sửa cut → bài `stale` được soạn lại; sửa title → không có bài nào cần soạn → không xếp job), `add` → job `post` `auto` được xếp ở làn `ai`; tập hợp rỗng → không có job; job episode `failed` giữa chừng mà có Short đã dựng → vẫn xếp.
3. R3: khi job soạn bài đợi / chạy, sửa title / cut / thêm / xóa / khôi phục Short không bị 409; soạn bài tay khi có job `pipeline` đợi / chạy → 409; hai lần gửi soạn bài khi job đang đợi → một job; trigger khi job đang chạy → thêm đúng một lượt; xóa tập khi job soạn bài đợi / chạy → 409; `GET /api/episodes/{id}` có `post_job`.
4. R5: dòng nguồn "— HT. Tịnh Không, <series> tập <N>" từ header `HT.Tịnh Không`; speaker đã có dấu cách giữ nguyên; `titles.json` / header render không đổi.
5. R1: `GET /episodes/{id}/posts` 200 (có cookie) cho tập Short và tập khai thị, 404 id sai, redirect đăng nhập khi không cookie (như `/episodes/{id}`); trang hiện thanh 3 nút, hai nhóm; view Shorts / Khai thị không còn khu bài đăng; R2b tự gửi `auto` một lần khi có bài thiếu. (Test route + test JS thuần nếu có sẵn khung; phần giao diện kiểm bằng manual test.)
6. Toàn bộ test suite PASS; test CP8.15 được sửa **chỉ** ở chỗ hành vi đổi theo R1–R4 (mỗi chỗ ghi lý do trong Result), không nới assertion khác.

## Required verification

- `conda run -n auto-short python -m pytest -q -n auto` — toàn bộ PASS (AC 1–6), theo Test policy `docs/ai/project-profile.md` §8.
- `node scripts/framework-check.mjs` — exit 0.
- Chạy thật trên bản sao dữ liệu (không ghi `work/` / `output/` chính), server test 8081 `queue_mode = "lanes"`, Ollama `qwen3:14b`: gửi 1 video mới (Short + khai thị) → ghi vào Result: thời điểm render xong / job `post` bắt đầu / xong, số bài `ai` / `raw`; trong lúc job `post` đợi, sửa title một Short thành công (không 409); sửa cut một Short đã có bài → bài được soạn lại tự động; mở tab Bài đăng của một tập cũ chưa có bài → tự soạn.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API contract (route trang mới, `clips: "auto"`, `post_job`) và job model → manual test là gate trước integration. Server test 8081, dữ liệu bản sao.

HUMAN LEAD 2026-09-30: manual test làm trên 8080 (dữ liệu thật, worktree web ghim `0eaf1a8`), kết quả chung: "đã ổn" (không báo từng mục; ô dưới không tick riêng). Góp ý mới → CP8.17 PROPOSED (`docs/workflow/current-state.md`).

- [ ] Điện thoại: thanh [Shorts | Khai thị | Bài đăng] ở cả ba view; chuyển qua lại đúng tập.
- [ ] Gửi một video mới: không bấm gì, bài đăng của mọi Short + khai thị có sẵn sau khi dựng xong; trong lúc đợi soạn, sửa title một Short được.
- [ ] Tab Bài đăng: sửa đoạn, đổi ảnh, dán link, "Sao chép bài" (dòng nguồn "HT. Tịnh Không"), tick "Đã đăng bài".
- [ ] Sửa đầu/cuối một Short: bài chưa tick được soạn lại tự động; bài đã tick / đã sửa tay giữ nguyên + nhãn "Text nguồn đã đổi".
- [ ] Tập cũ chưa có bài: mở tab Bài đăng → tự soạn.

## Result

Implementer: Sonnet (dual-agent). Base `bddc0f9` + contract `7eb90cf`.

### Main changes

- `post/stage.py`: `auto_clips(ep, doc, order)` (R4, pure) + `compose_posts(..., clips="auto")` (broken `posts.json` reads as empty like `all`, never overwritten). `post/logic.header_line`: R5 (`\.(?=[^\W\d_])` -> `". "`, post line only; `titles.json` / header video / `render_key` untouched).
- `web/jobs.py`: `post_key()` (`<id>#post`), `Job.key` / `Job.again`, `JobRunner.submit(..., rerun=)`, `latest_post()`, `forget()` and `on_finished` hook (called after `pipeline` / `render` / `add` ends `done` or `failed`, before the lane is released so `wait_idle` never sees a gap); `PostComposeTarget.followup()` = the one extra `auto` pass when a trigger arrived while the job ran (queued as a new job right after the running one; not for `interrupted` / stopping).
- `web/app.py`: page route `GET /episodes/{id}/posts`; `clips: "auto"`; `post_job` in `GET /api/episodes/{id}`; manual compose 409 only for a `pipeline` job (a waiting `post` job is returned, 202); `_busy` / title / cut / add / delete / restore use only the episode's own job; delete-episode also checks the `#post` job; `_auto_post` hook (R2a, empty R4 set or unreadable source -> no job).
- `web/static/`: new `posts.html` (3-button bar, two groups Shorts / Khai thị, editors always open, "Xem Short", "Sao chép bài", "Tải ảnh", head with `Đã đăng x / y`, per-episode compose job status, "Soạn bài còn thiếu", image library dialog moved here); `app.js` `initPosts()` (R2b: one `auto` per page load per episode that lacks / needs posts, only when no `post` job is active and no `pipeline` job runs), `renderKindBar` 3 buttons; removed `postPanel`, `#posts-head`, `#posts-msg`, image dialog from `episode.html` / Short card; CSS for `.post-card`.
- Docs: CP8.15 decision record (amendment notes at P1, P4, P9), CP8.3 W5 / W6 / W7 pointers, `docs/ai/project-profile.md` web/ row, `AUTO_SHORT_CHECKPOINT_PLAN.md` (CP8.16 section). `docs/workflow/current-state.md` not touched (ORCHESTRATOR).

### Tests

- New: `tests/test_post_auto_cp816.py` (AC1, AC4), `tests/test_web_post_cp816.py` (AC2, AC3, AC5; lanes + serial).
- CP8.15 tests changed only where behaviour changed (AC6):
  - `tests/test_post_backend.py::test_header_line`, `::test_compose_copy_text_full`: speaker line now `HT. Tịnh Không` (R5); added cases for already-spaced speaker and a dot before a digit.
  - `tests/test_web_post_cp815.py::test_compose_one_clip_then_get`: assertion `— HT. Tịnh Không, ...` (R5).
  - `tests/test_web_post_cp815.py::test_compose_409_while_job_active` -> `test_compose_returns_waiting_job_while_job_active`: second submit while a post job is active now returns that job (202, same id) instead of 409 (R3).
  - `tests/test_web_post_cp815.py::FakeComposeAI`: supports `clips == "auto"` via `post_stage.auto_clips` (test double only, R4).
- Full suite: `PYTHONPATH=$PWD/src conda run -n auto-short python -m pytest -q -n auto` -> 1144 passed, 1 skipped (serial-mode skip of a lanes-only race test), 0 failed (one run; `test_lanes_artifacts_identical_to_serial` did not flake). `node scripts/framework-check.mjs` -> exit 0 (all PASS).
- JS: no browser / JS test framework in the repo; `node --check app.js` OK, plus a throw-away fake-DOM harness (not committed) running `initPosts()` against the live 8081 server: kind bar links, 2 groups, 10 / 25 cards, failed-job text, R2b auto request. Real layout / touch behaviour = manual test.

### Real run (scratch data, server 8081, `queue_mode = "lanes"`, Ollama `qwen3:14b`)

Data: `~/.cache/auto-short-cp816-test/` (config.toml, work/, output/, images/, server.log; copies of `E4QhRRXFbIM` + `.kt` and `tHtxw6ykUmM` + `.kt` from the main repo, no write to main `work/` / `output/`; server stopped; 8080 untouched). Login password `cp816test` was env-only.

Substitution (contract allows): sending a brand-new video was not attempted (55 min source download + Whisper); instead `E4QhRRXFbIM` (+ `.kt`) had no output and its manifest `render` stage removed, then the URL was submitted through the normal `POST /api/episodes` (both kinds): ingest / transcript / analysis / selection / titling up to date, render ran for real.

- Short episode `E4QhRRXFbIM`: pipeline job 3 done 01:10:44 (10/10 Shorts) -> post job 5 auto-queued and started immediately (lane ai idle), done 01:11:17 in 32.9 s: 10 `ai`, 0 `raw`, every call valid on first attempt.
- Edit during post job: at 01:10:54, with post job 5 running, `POST .../shorts/k01/title` -> 202 (CP8.15 answered 409). That title render (job 6) ended without any post job (nothing stale) as required.
- Khai thị `E4QhRRXFbIM.kt`: pipeline job 4 done ~01:19:45 (5/5, 770 s) -> post job 9 auto-queued but waiting behind post job 8 (`tHtxw6ykUmM.kt`, same ai lane); while it was `queued` (position 1) `POST .../shorts/k01/title` -> 202. A later render (job 10) trigger returned job 9 ("đã có"): one job.
- Old episode without posts: opened the Bài đăng page of `tHtxw6ykUmM` (harness) -> R2b sent `auto` for Short + khai thị: job 7 done in 55.2 s (20 `ai`, 0 `raw`), job 8 (khai thị) composed k01-k04 `ai` (2 calls each valid).
- Cut edit of `E4QhRRXFbIM` k02 (01:20:06, 202) -> render job 11 done -> post job 12 auto-queued (`tự soạn bài ... sau job 11 -> job 12`). NOT verified end-to-end: from ~01:18 the remote Ollama at 127.0.0.1:11437 (a tunnel not owned by this session) stopped answering (k05 of `tHtxw6ykUmM.kt` hit the 600 s timeout 3 times, then connection refused, still down at 02:03). Job 9 and job 12 ended `failed` with `ollama preflight: cannot reach Ollama ...` (correct R2 behaviour: no auto retry, page shows the error and "Soạn bài còn thiếu"); the "stale post recomposed after a cut" outcome is covered only by `test_stale_post_recomposed_after_cut_render` (fake compose). The scratch data is left so the manual test can redo it when Ollama is back (k02 of `E4QhRRXFbIM` is stale; k05 of `tHtxw6ykUmM.kt` has no post).
- Required verification therefore is NOT fully PASS for the one live check "sửa cut -> bài soạn lại" (blocked by the Ollama outage); everything else in the list ran.

### Decisions when implementing

- `Job.episode_id` of a `post` job stays the real episode id (so lists / storage `active` set / logs behave as before); only the runner key differs (`Job.key`). `forget` removes both keys.
- The extra pass (R3) is a follow-up `post` job created by the runner when the running job ends with `again` set (not a loop inside the target), so it is visible in `post_job` and cannot lose a trigger to a finish race. Manual submits (no `rerun`) while running return the running job, as before.
- R2b "needs compose" is decided in JS from `GET .../posts` fields (missing post, or `stale` && !`posted` && origin != `manual`); the server's `auto` set (`auto_clips`, R4) remains canonical, so over-asking only yields an empty job. No extra field was added to `GET .../posts` (keeps the CP8.15 response shape).
- `Đã đăng x / y`: y = number of `rendered` Shorts of both episodes (a Short without a post counts as not posted).
- Manual compose is refused with 409 only for a `pipeline` job (per R3); with `render` / `add` running it is accepted (the following R2a trigger fixes staleness).
- In `serial` mode the single worker runs a compose job like any other job, so edit jobs queue behind it (still no 409 from the compose job itself).

### Known limitations / findings outside scope

- The compose job holds the ai lane while Ollama is slow / down: each hung chunk waits `[post] timeout` = 600 s x (retries + 1) (seen live: ~30 min for one Short), delaying `selection` of other videos. Not changed (CP8.15 P11 config). Consider a shorter default `[post] timeout` or aborting the whole job after the first connection failure.
- Queue is in memory: a restart loses waiting post jobs (R2b recovers them on the next visit of the tab).
- Manual test checklist above: not run (HUMAN LEAD, scratch server data kept).

### Round 2 (review round 1: B1)

B1: a manual compose request (`clips: [ids]` / `"all"`) that met an active `post` job was dropped (the returned job runs `auto`, which skips valid / ticked / `manual` posts). Fix, keeping R3 ("return that job", at most one `post` job per episode):

- `post/stage.py`: `merge_clips` (union of two `clips` specs) and `resolve_todo` (spec -> clip ids in `render_manifest` order: `"all"` = CP8.15 rule, `"auto"` = R4, explicit id composed even when its post is valid). `compose_posts` accepts a list mixing tokens and ids (e.g. `["auto", "k03"]`).
- `web/jobs.py`: `submit` on an active `post` job: while `queued` the new request is merged into that job's target (resolved when it starts); while `running` it sets `again` and is kept in `pending`, so the runner's follow-up pass is `auto` + those clips / `"all"`. The existing job is returned (202). The `rerun` parameter is gone (an automatic trigger is just a merged `"auto"`).
- Unknown clip id: chosen = dropped with a log warning when the request carries `auto` / `all` (merged), so one bad id never fails the whole job; a pure explicit list keeps the CP8.15 `PostComposeError` ("không có Short đã dựng").
- Tests (lanes + serial): `test_manual_clip_merged_into_waiting_auto_job` (waiting auto job + POST `[k02]` -> same job id, one compose call with `["auto", "k02"]`), `test_manual_clip_while_running_gets_one_extra_pass` (running job + POST `[k02]` -> exactly one extra job, whose pass is `["auto", "k02"]` and composes k02), `test_merge_clips_and_resolve_todo_pure`, `test_merged_unknown_clip_is_dropped_not_fatal`. `FakeComposeAI` (CP8.15 test double) now resolves token lists through `post_stage.resolve_todo`.
- Full suite once after the fix: 1151 passed, 1 skipped; `framework-check` unaffected (docs only). No live re-run for B1 (scratch data / 8081 unchanged).
- Non-blocking noted: `on_finished` also fires for a `pipeline` job that failed before render; harmless, unchanged.

### Review (ORCHESTRATOR)

- Round 1 (diff `9f708c5`): 1 blocking — B1: yêu cầu soạn bài bấm tay (`clips: [id]`) gặp job `post` đang đợi / chạy chỉ nhận lại job đó, clip được yêu cầu không được soạn nếu không nằm trong tập `auto`. Nguyên nhân gốc: câu R3 "gửi (tay hoặc tự động) khi đang đợi → trả job đó" chỉ đúng với `auto`. Non-blocking: hook `on_finished` cũng chạy khi job `pipeline` fail trước bước render (vô hại, chỉ soạn Short đã dựng từ trước). Không có ghi nhận duyệt tự bịa trong code / docs.
- Round 2 (diff `61bc2aa`): **ACCEPTED**. B1 sửa đúng chữ R3 (trả job đang có; đang đợi → gộp clip vào job; đang chạy → lượt thêm `auto` ∪ clip); merge / `again` đều dưới lock của runner. ORCHESTRATOR chạy lại `pytest -q -n auto` → 1151 passed, 1 skipped; `framework-check` exit 0.
- Chưa kiểm trên server thật (Ollama sập lúc chạy): "sửa đầu/cuối → bài tự soạn lại" — thuộc manual test checklist.
- Chạy thật bổ sung (ORCHESTRATOR 2026-09-30 10:03–10:05, sau khi GPU/Ollama `11437` lên lại; server 8081, cùng dữ liệu bản sao, `qwen3:14b`): tập `E4QhRRXFbIM`, trước: k02 `stale` chưa tick. Tick "Đã đăng bài" k04; sửa tay đoạn k05 (→ `manual`). Sửa cut k03 (bớt một dòng cuối) → job `render` 34 s → job `post` `auto` tự xếp, soạn **k02 + k03** (2 `ai`, 0 `raw`). Sửa cut k04 (đã tick) và k05 (`manual`) → render xong, **không** xếp job `post` mới; sau cùng k04 `stale` + giữ tick, k05 `manual` + `stale`, giữ chữ sửa tay; mọi bài khác không `stale`. Khớp R2a / R4. Dữ liệu bản sao giữ các thay đổi này (tick k04, k05 sửa tay, cut k03–k05) cho manual test. Ghi chú: `tHtxw6ykUmM.kt` k05 là `raw` (soạn lúc Ollama chập chờn) — theo R2 không tự thử lại, bấm "Soạn lại" tay.
- Manual test: HUMAN LEAD 2026-09-30 trên 8080 (dữ liệu thật, `0eaf1a8`): "đã ổn". Góp ý ngoài scope CP8.16 (→ CP8.17 PROPOSED): tự tick "Đã đăng bài" sau khi sao chép bài + tải ảnh; tải zip cả tập không tự tick "Đã đăng"; tên zip rõ Short / khai thị của tập nào hoặc nút tải cả hai (hai thư mục).
