# Task: CP8.16 — Tab "Bài đăng" + tự soạn bài đăng cộng đồng

## Status / Approval

- Status: APPROVED
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

- [ ] Điện thoại: thanh [Shorts | Khai thị | Bài đăng] ở cả ba view; chuyển qua lại đúng tập.
- [ ] Gửi một video mới: không bấm gì, bài đăng của mọi Short + khai thị có sẵn sau khi dựng xong; trong lúc đợi soạn, sửa title một Short được.
- [ ] Tab Bài đăng: sửa đoạn, đổi ảnh, dán link, "Sao chép bài" (dòng nguồn "HT. Tịnh Không"), tick "Đã đăng bài".
- [ ] Sửa đầu/cuối một Short: bài chưa tick được soạn lại tự động; bài đã tick / đã sửa tay giữ nguyên + nhãn "Text nguồn đã đổi".
- [ ] Tập cũ chưa có bài: mở tab Bài đăng → tự soạn.

## Result

(chưa thực hiện)
