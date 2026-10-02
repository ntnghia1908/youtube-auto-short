# Task: CP8.19 — Bài đăng lấy từ văn bản gốc bài giảng

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; task có tải từ mạng + gióng văn bản + route + UI, cần review diff riêng.
- Base commit / branch: `cecc920` (`origin/main`, sau merge CP8.18 PR #47; ban đầu xếp chồng trên `028ef8f`) / `feature/cp8.19-post-doc-source` (worktree `../youtube-auto-short-cp819`)
- Human Lead approval: accepted (HUMAN LEAD 2026-10-02: Q1–Q4; APPROVE CP8.19 — D1–D8, Q3 theo cách hiểu ghi dưới; manual test thẳng trên 8080)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: (a) đổi luật canonical `docs/decisions/CP8.15-community-post-contract.md` P2/P3 (bài không còn là chữ transcript + dấu câu AI, mà có thể là đoạn văn bản gốc đã biên tập), P7 (`origin` mới `doc`), P1/R4 (soạn lại bài có sẵn); (b) tải dữ liệu từ site ngoài (security, như P13); (c) thêm field + route bộ kinh (`docs/decisions/CP8.3-web-contract.md` W7, W10). Không thêm dependency, không đổi stage CP2–CP9, title, render.

## Bối cảnh

HUMAN LEAD 2026-10-02: lời giảng có sẵn văn bản đã biên tập trên `ph.tinhtong.vn`, ví dụ `https://ph.tinhtong.vn/Home/KinhVoLuongTho10?d=KinhVoLuongTho10_001.html`.

ORCHESTRATOR đo 2026-10-02 (transcript trong `work/` so với văn bản, token chuẩn hóa, `difflib`):

| Trang | Tập | Transcript | Token transcript khớp văn bản |
|---|---|---|---|
| `KinhVoLuongTho10` | `Bi7kVGbnPfE` (tập 1) | caption YouTube | 0.88 |
| `KinhThapThienNghiep` | `7axON1RpRjo` (tập 7) | caption YouTube | 0.90 |
| `CamUngThien` | `4oOZz2CBz3g` (tập 1) | Whisper | 0.81 |
| `ThaiThuongCamUngThien` (bản giảng khác) | `4oOZz2CBz3g` | Whisper | 0.02 |

Cả 11 Short của `Bi7kVGbnPfE` tìm được đoạn tương ứng, độ giống 0.81–0.95; văn bản đúng chính tả ("rốt cuộc", "hủy báng", "Phật Đà Da" — transcript: "suốt cuộc", "hủy bán", "Phật Đại gia") và có dấu câu do người biên tập. Văn bản là bản **đã biên tập**: đôi chỗ khác lời nói, câu lặp đã bỏ.

Cấu trúc trang (2026-10-02): `<div id="bodytext">` chứa các `<p>` phần đầu (đầu trang: `<p class="text-center">` tên kinh / người giảng / "Tập N", tiêu đề mục toàn `<b>`); phần còn lại ở link `/html-end/<Code>/<Code>_<NNN>.gz.z?v=…` (gzip, các `<p>` tiếp theo). Số tập có độ rộng khác nhau theo bộ (`_001`, `_07`, `_1`).

## Goal

Bộ kinh có gắn văn bản gốc → bài đăng của mỗi Short (tập Short và khai thị) là đúng đoạn văn bản gốc tương ứng, mở rộng ra trọn câu, giữ chia đoạn của văn bản — không cần AI, không còn lỗi chính tả / dấu câu của transcript. Không có văn bản hoặc khớp kém → cách cũ (AI + từ điển CP8.18).

## Scope

- In scope:
  - Field "Văn bản gốc" của bộ kinh + route + UI trang bộ kinh (D1).
  - Tải + đọc văn bản một tập, lưu cache trong workspace tập (D2, D3).
  - Gióng một Short vào văn bản, chọn đoạn, mở rộng trọn câu, dọn khoảng trắng trong ngoặc kép (D4, D5).
  - `compose_posts` dùng văn bản khi có, `origin: doc`, dự phòng cách cũ (D6).
  - Soạn lại bài chưa đăng có sẵn khi gắn văn bản (D7).
  - UI tab Bài đăng: nhãn nguồn bài (D8).
  - Tài liệu: CP8.15 (P15 mới + ghi chú P1, P2, P3, P7, P9), CP8.3 W7/W10 pointer, `README.md`, `AUTO_SHORT_CHECKPOINT_PLAN.md`, `docs/ai/project-profile.md` (dòng `post/`).
- Out of scope:
  - Dùng văn bản cho title, transcript, phụ đề, chọn clip.
  - Site khác ngoài `ph.tinhtong.vn`; tải `.docx` / PDF.
  - Tập lẻ không thuộc bộ kinh; tập không nhận dạng được số tập (CP8.11).
  - Áp từ điển CP8.18 lên bài `doc`.

## Quyết định

Q1–Q4: HUMAN LEAD 2026-10-02 "Approve Q1–Q4". D1–D8: HUMAN LEAD 2026-10-02 APPROVE CP8.19.

- **Q1 (a).** Đoạn được mở rộng ra trọn câu ở hai đầu (D5).
- **Q2.** Chấp nhận bài dùng lời đã biên tập của văn bản (có thể khác lời trong video đôi chỗ).
- **Q3.** Gắn văn bản cho một bộ kinh → các bài **chưa đăng**, `origin` `ai` / `raw`, của các tập trong bộ đó được soạn lại từ văn bản (D7). Bài `manual` và bài đã tick "Đã đăng bài" không đổi. (xác nhận khi APPROVE CP8.19)
- **Q4.** Áp cho cả tập khai thị (`<vid>.kt`, cùng video, cùng văn bản).

- **D1. Gắn văn bản cho bộ kinh.** Trang bộ kinh có ô "Văn bản gốc (link một tập bất kỳ)" + "Lưu" / "Xóa". `PUT /api/playlists/{pid}/doc {url | null}`:
  - Chỉ nhận `https://ph.tinhtong.vn/Home/<Code>?d=<Code>_<số>.html` (`<Code>` chữ / số, `<số>` chữ số). Khác → 422.
  - Lưu field `doc_url` (đúng link đã dán, đã chuẩn hóa) trong `<workspace>/_playlists/<pid>.json` cạnh `hashtags` / `series` (giữ khi "Làm mới" bộ kinh như hai field kia). `null` = xóa.
  - Link tập N = thay `<số>` bằng N, giữ độ rộng đệm số 0 của link đã dán (`_001` → `_007`; `_1` → `_7`; `_07` → `_12`).
  - Response: `{doc_url, check}` — `check` = kết quả kiểm thử tập đầu tiên của bộ kinh đã có transcript (D3: `{episode_id, episode, match, ok}`), `null` khi chưa có tập nào. UI hiện "Khớp 88% — đúng bản giảng" / "Khớp 2% — có thể sai bản giảng" (vẫn lưu; tập khớp kém tự dùng cách cũ).
  - `GET /api/playlists/{pid}` thêm `doc_url`.
  - Tập thuộc nhiều bộ kinh có `doc_url` → bộ có `playlist_id` nhỏ nhất (như CP8.8 H4).

- **D2. Tải + đọc văn bản.** `post/doc.py` (không import `web/`; đọc file bộ kinh trực tiếp như `titling.playlist`):
  - Tải trang bằng `post.fetch.fetch` (luật P13: chỉ host công khai, kiểm lại sau redirect, timeout, ≤ 5 MB, không cookie). Redirect sang host khác `ph.tinhtong.vn` → lỗi.
  - Lấy `<p>` trong `<div id="bodytext">` (`html.parser`); bỏ `<p class="text-center">` và `<p>` mà toàn bộ chữ nằm trong `<b>` (tiêu đề). Nếu trang có link `/html-end/…gz.z` cùng host: tải (≤ 5 MB), giải gzip giới hạn 5 MB sau giải nén (dư → lỗi), lấy `<p>` theo cùng luật, nối sau phần đầu.
  - Mỗi đoạn: unescape HTML, gộp khoảng trắng, bỏ đoạn rỗng.
  - Không đọc được / 0 đoạn → lỗi (log), tập dùng cách cũ.

- **D3. Cache + kiểm khớp tập.** `work/<id>/doc.json` (ghi atomic):
  ```json
  {"schema_version": 1, "url": "…", "fetched_at": "…", "paragraphs": ["…"], "match": 0.88}
  ```
  - `match` = số token transcript (`transcript.json` `segments[].text`, chuẩn hóa `normalize_word`) nằm trong khối khớp `SequenceMatcher(autojunk=False)` với token văn bản / tổng token transcript.
  - `match < 0.6` → tập **không** dùng văn bản (sai bản giảng / sai số tập); vẫn lưu cache để không tải lại.
  - Cache dùng lại khi `url` trùng; `doc_url` của bộ kinh đổi → tải lại. Lỗi tải không ghi cache (lần soạn sau thử lại).
  - Tập `.kt` dùng cùng link (số tập của video); cache riêng trong workspace của nó.

- **D4. Gióng một Short.** Token chữ nguồn P2 của Short (chưa áp từ điển) gióng vào token văn bản (`SequenceMatcher`, `autojunk=False`), chỉ dùng khối khớp ≥ 4 token; chọn cụm khối liên tiếp dày nhất (khoảng cách văn bản giữa hai khối kề ≤ 30 token) làm vùng; điểm đầu / cuối vùng = vị trí văn bản ứng với token nguồn đầu / cuối (bù phần chưa khớp ở hai đầu theo số token).
  - `ratio` = `SequenceMatcher(nguồn, vùng).ratio()`; `ratio < 0.6` → Short này dùng cách cũ.

- **D5. Đoạn bài (Q1 a).**
  - Mở rộng điểm đầu về đầu câu chứa nó (sau dấu `. ? ! …` gần nhất phía trước, kể cả khi theo sau là ngoặc đóng, hoặc đầu đoạn văn); điểm cuối ra cuối câu chứa nó (tới dấu kết câu kế tiếp, kèm ngoặc đóng ngay sau, hoặc cuối đoạn văn).
  - Mỗi phía mở rộng tối đa 60 token; vượt → dừng ở điểm gióng, phía đầu thêm `…` trước chữ đầu, phía cuối thêm `…` sau chữ cuối.
  - Giữ ngắt đoạn của văn bản bên trong vùng.
  - Dọn ngoặc kép: bỏ khoảng trắng ngay sau `“` và ngay trước `”` (`“ Hành ”` → `“Hành”`). Không sửa gì khác.
  - Viết hoa chữ đầu bài (chữ đầu câu trong văn bản vốn đã hoa).

- **D6. Soạn bài.** Trong `compose_posts`, trước nhánh AI: nếu tập có văn bản dùng được (D3) và Short gióng được (D4) → `paragraphs` = D5, `origin: doc`, không gọi AI; `source_sha256` vẫn trên chữ nguồn P2 (stale như cũ). Không → nhánh cũ (từ điển CP8.18 + AI / `raw`).
  - `posts.json`: `origin` thêm giá trị `doc` (`store.ORIGINS`); không đổi `schema_version`.
  - `post_log.json` entry `doc` ghi: `origin: doc`, `doc_url`, `doc_match`, `ratio`, khoảng token văn bản `[start, end)`, `expanded: {head, tail}`; không có `ai_calls`.
  - Soạn lại một bài (`auto` R4, "Soạn lại") theo cùng thứ tự ưu tiên; bài `doc` `stale` được `auto` soạn lại như `ai`.
  - Lỗi tải văn bản không làm job thất bại: cả tập đi nhánh cũ, log cảnh báo.

- **D7. Soạn lại bài có sẵn (Q3).** Sau khi `PUT …/doc` lưu link mới (khác `null`): với mỗi tập (Short + `.kt`) của bộ kinh đã có `posts.json`, xếp job `post` với danh sách clip = bài `origin` `ai` / `raw`, `posted_at` `null` (dùng cơ chế job `post` CP8.16: khóa `<id>#post`, gộp khi đang đợi). Clip đó không gióng được → nhánh cũ soạn lại như bình thường. Response `PUT` thêm `queued: <số tập đã xếp>`.

- **D8. UI tab Bài đăng.** Nhãn nguồn mỗi bài: "Văn bản gốc" (`doc`) cạnh các nhãn hiện có (`raw`, `stale`, …); bài `doc` không hiện nhãn "ít dấu câu". Sửa tay bài `doc` → `manual` như mọi bài (học từ điển CP8.18 vẫn chạy).

## Implementation approach

- `src/auto_short/post/doc.py` (mới): link → template (D1), đọc file bộ kinh tìm `doc_url` của video, tải + parse (D2), cache + `match` (D3), gióng + đoạn (D4, D5). Hàm thuần tách khỏi IO để test bằng HTML / text tổng hợp (không gọi mạng trong test; `opener` giả như test `post/fetch`).
- `post/stage.py`: nhánh `doc` trước AI (D6).
- `post/store.py`: `ORIGINS` thêm `doc`.
- `web/playlists.py` + `web/app.py`: field + route D1, xếp job D7.
- `web/static/`: ô "Văn bản gốc" trang bộ kinh, nhãn D8.

## Acceptance Criteria

1. `PUT …/doc` nhận đúng dạng link, suy ra link tập N giữ độ rộng số (`_001`/`_1`/`_07`); 422 cho host / dạng khác; `null` xóa; "Làm mới" bộ kinh không mất `doc_url`; `GET` bộ kinh trả `doc_url`.
2. Parse: lấy đúng `<p>` của `#bodytext`, bỏ tiêu đề / `text-center`, nối phần gzip; gzip vượt giới hạn hoặc host khác → lỗi, không ghi cache.
3. Fetch tuân P13 (host nội bộ / redirect sang host nội bộ bị chặn) — test với resolver / opener giả.
4. `doc.json` tạo đúng; `match < 0.6` → tập dùng nhánh cũ; cache dùng lại khi `url` trùng, tải lại khi `doc_url` đổi.
5. Gióng: Short nằm giữa văn bản (có nhiễu ASR và câu lặp như dữ liệu thật) → đúng vùng; mở rộng trọn câu hai đầu; vượt 60 token → `…`; ngắt đoạn văn bản giữ nguyên; `“ X ”` → `“X”`.
6. `compose_posts` với văn bản dùng được → `origin: doc`, không gọi AI (client giả không bị gọi), `source_sha256` như cũ; Short gióng kém hoặc tập không có văn bản → nhánh AI cũ (kể cả từ điển CP8.18).
7. `PUT …/doc` → xếp job soạn lại đúng các bài `ai`/`raw` chưa đăng của các tập trong bộ (Short + `.kt`); bài `manual` / đã đăng không đổi.
8. Tập `.kt` của video trong bộ kinh dùng văn bản như tập Short.
9. Hành vi CP8.15–CP8.18 khác không đổi: toàn bộ suite PASS.
10. Đo trên dữ liệu thật (bản sao `work/`, ORCHESTRATOR chạy, ghi vào Result): với các tập `Bi7kVGbnPfE`, `7axON1RpRjo`, `4oOZz2CBz3g` và bộ kinh gắn link tương ứng, ≥ 90% Short có `origin: doc`; ORCHESTRATOR đọc đối chiếu ≥ 5 bài với video.

## Required verification

- `python -m pytest -q -n auto tests/test_post_doc.py tests/test_web_post_doc_cp819.py` — AC 1–8.
- `python -m pytest -q -n auto` — AC 9.
- `node scripts/framework-check.mjs`.
- AC 10: script đo một lần trên bản sao dữ liệu (`~/.cache/auto-short-cp819-test/`), không ghi vào `work/` chính.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Task chạm public API web và tải dữ liệu từ mạng (dùng lại luật security P13, không đổi security model), không chạm database. Manual test là điểm danh sau automated verification, **trên 8080 với dữ liệu thật** (HUMAN LEAD 2026-10-02): ORCHESTRATOR ghim 8080 lên commit READY của branch trước khi HUMAN LEAD test; gắn văn bản sẽ soạn lại bài chưa đăng ở `work/` chính (D7).

- [ ] Trang bộ kinh Vô Lượng Thọ: dán link tập 1 → "Khớp …% — đúng bản giảng".
- [ ] Tab Bài đăng của một tập: bài hiện nhãn "Văn bản gốc", đọc đúng đoạn trong video, trọn câu.
- [ ] Bài đã đăng / bài sửa tay không đổi.
- [ ] Dán link sai bản giảng (`ThaiThuongCamUngThien`) cho bộ Cảm Ứng Thiên → cảnh báo khớp thấp, bài vẫn theo cách cũ.
- [ ] Tập khai thị dùng được văn bản.

## Result

- Main changes: `post/doc.py` mới (D1 link + template, tra `doc_url` từ `_playlists/*.json`, tải qua `post.fetch` + chặn redirect khác host, parse `#bodytext` + phần gzip giới hạn, cache `doc.json` + `match`, gióng + mở rộng trọn câu + dọn ngoặc kép); `post/stage.py` nhánh `doc` trước AI; `store.ORIGINS` + `doc`; `web/playlists.py` field `doc_url` (giữ khi làm mới); `PUT /api/playlists/{pid}/doc` (`check`, `queued`, xếp job soạn lại D7); UI ô "Văn bản gốc" trang bộ kinh + nhãn "Văn bản gốc" tab Bài đăng. Tài liệu: CP8.15 P15 + ghi chú P1/P2/P3/P7/P9, CP8.3 W7/W10, README, checkpoint plan, project profile.
- Tests: `tests/test_post_doc.py` (48), `tests/test_web_post_doc_cp819.py` (15) — 63 passed; toàn bộ `python -m pytest -q -n auto` 1318 passed, 1 skipped (ORCHESTRATOR chạy lại); `node scripts/framework-check.mjs` PASS.
- AC 10 (ORCHESTRATOR 2026-10-02, bản sao `~/.cache/auto-short-cp819-test/`, link: `KinhVoLuongTho10_001`, `CamUngThien_001`, `KinhThapThienNghiep_01`; client AI giả): 17 tập (Short + `.kt`) của 3 bộ kinh có bài → **148/150 Short (99%) `origin: doc`**; `match` tập 0.67–0.92; mỗi tập ~0.5 s gồm tải. Đọc đối chiếu 6 bài (`Bi7kVGbnPfE` k03, `4oOZz2CBz3g` k01, `X8ao0_7ufto` k05, `yzR1eCK_iV0` k02, `By0ZVJTPW3Y.kt` k01, `VlLxSpVCcws.kt` k02) với chữ nguồn: đúng đoạn, trọn câu, chính tả / dấu câu đúng ("xuất thế gian pháp", "hết thảy"); mở rộng lớn nhất 41 token đầu / 40 token cuối.
- Review: round 1 ACCEPTED, không có blocking finding.
- Important findings / decisions (IMPLEMENTER, contract không nói): link gzip tìm bằng regex trên HTML (trang thật dùng `<link rel="preload">`); `check` có `error` khi tải lỗi (link vẫn lưu); `queued` bỏ qua tập đang có job `pipeline`; `…` dính chữ, có `…` đầu thì không viết hoa; `match` tính trên segment `speech`; cache không theo transcript hash (chỉ tải lại khi đổi link).
- Known limitations: job soạn bài vẫn chạy preflight Ollama (làn `ai`) kể cả khi mọi Short lấy từ văn bản — GPU tắt thì bài `doc` cũng đợi GPU; bài có thể thừa vài câu không có trong video (Q1 a, ≤ 60 token mỗi phía). Manual test trên 8080 (HUMAN LEAD 2026-10-02): "Test quá ok" — tập 1 Vô Lượng Thọ (`Bi7kVGbnPfE` + `.kt`) soạn lại 17/17 bài `doc`.
- PR: #48
