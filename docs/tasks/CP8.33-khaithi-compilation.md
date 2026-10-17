# Task: CP8.33 — Khai thị yêu thích + ghép thành video dài / lặp / tự ghép theo thời lượng

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `185ba20` (`main`) / `feature/cp8.33-khaithi-compilation` (worktree `../youtube-auto-short-cp833`); PR #85 (CP8.32, cũng sửa trang bộ kinh) còn mở: làm trên `main` hiện tại, rebase khi #85 merge (UI ghép nằm ở trang mới nên xung đột dự kiến nhỏ).
- Human Lead approval: APPROVED 2026-10-17 ("Tôi đồng ý … nhưng thêm một chi tiết là thêm một chức năng tích các bài yêu thích với icon hình trái tim … đưa vào một danh sách yêu thích ở trong một trang khác … để lựa chọn ghép hoặc lặp lại video … cũng nên có chức năng tự động ghép video yêu thích"; câu hỏi cùng ngày: yêu thích **riêng từng bộ kinh**, tự động = **tự ghép theo thời lượng**) → G1–G8 duyệt, G6 sửa theo G9, thêm G9–G10. Amendment 1 (HUMAN LEAD 2026-10-17): "Tạm thời khi dọn dẹp sẽ không xóa các video trong mục yêu thích", làm rõ: "Ý tôi không phải là video nguồn mà là khi xóa Khai Thị thì giữ lại các Khai Thị được yêu thích" → thêm G11 (nguồn / gợi ý dọn W9 không đổi). Amendment 2 (HUMAN LEAD 2026-10-17, APPROVED): "Thêm nút thích trái tim vào trong shot luôn. Cách hoạt động y như Khai Thị không khác gì" → Short thường có tim / yêu thích / ghép y như khai thị (sửa G1, G6, G7, G9, G10, G11, AC5; thêm AC 13).
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: thêm loại output mới (video ghép, namespace `output/_compilations/`), job kind mới và route web mới (CP8.3 web contract). Không đổi dependency (chỉ `ffmpeg` đã có), security model, schema artifact của tập.

## Bối cảnh (2026-10-17, ORCHESTRATOR)

- HUMAN LEAD: "ghép nhiều video Khai Thị thành một video dài hơn hoặc có thể ghép một video lặp lại nhiều lần thành một video dài". Trả lời câu hỏi cùng ngày: phạm vi = trong **một bộ kinh**; chỗ nối = **nối liền**; mục đích = **đăng YouTube video dọc dài** (giữ khung 9:16, header + tiêu đề từng đoạn); lặp = chỉ định **tổng thời lượng**.
- Khai thị đã render: `output/<id>.kt/shorts/kNN.mp4` (CP8.9, CP7), 1080×1920, h264 High yuv420p 30000/1001, AAC LC 48 kHz stereo, ≈ 1,8–2,1 Mbit/s (đo 4 file 2026-10-17) → 60 phút ≈ 0,8 GB.

## Goal

HUMAN LEAD đánh dấu khai thị yêu thích (icon trái tim) rồi, trên trang Yêu thích của bộ kinh, (a) tick nhiều khai thị yêu thích rồi bấm "Ghép" → một file mp4 dọc nối liền các khai thị theo thứ tự tập; hoặc (b) chọn một khai thị, nhập tổng thời lượng (phút) → một file mp4 lặp khai thị đó đủ thời lượng; hoặc (c) nhập tổng thời lượng → tự ghép các khai thị yêu thích (lặp vòng nếu thiếu). File tải về được, xóa được, kèm mô tả có mốc thời gian (chapter YouTube) để copy.

## Quyết định (G1–G10, APPROVED 2026-10-17)

- **G1 Nguồn.** Chỉ khai thị (tập có `khaithi.json`) thuộc **một** bộ kinh, đã render, không bị xóa (`rejected`, CP8.5). Short thường không dùng. Thứ tự trong video ghép = thứ tự tập trong bộ kinh rồi số `KT`; sắp xếp tay: out of scope. **Amendment 2:** nguồn là Short HOẶC khai thị (tập `<id>` không có `khaithi.json` / tập `<id>.kt`) của cùng một bộ kinh, đã render, không `rejected`; được trộn trong một video ghép (cùng định dạng CP7, đo 2026-10-17: 1080×1920 h264 30000/1001 AAC 48 kHz stereo → nhánh copy). Thứ tự: số tập, trong một tập Short trước khai thị, rồi số clip. Loại mục suy từ id tập (`.kt` = khai thị), không lưu trong `favorites.json`; `cid` không đổi (cid cũ của khai thị giữ nguyên).
- **G2 Hai chế độ.** `concat`: ≥ 2 khai thị được tick. `loop`: 1 khai thị + tổng thời lượng `T` phút (số nguyên); số lần lặp `n = ceil(60·T / d)` (`d` = thời lượng khai thị) → video ≥ T phút; giao diện hiện trước "n lần ≈ X phút" khi nhập. Cả hai: tổng thời lượng ≤ `[compilation] max_minutes` (mặc định 720 = giới hạn 12 h của YouTube); vượt → từ chối (400) trước khi xếp job.
- **G3 Nối liền, không encode lại.** ffmpeg concat demuxer `-c copy` (nhanh, không giảm chất lượng). Trước khi ghép `ffprobe` mọi input: khác codec / kích thước / fps / sample rate / channels → encode lại một lần theo thông số encode CP7 (chậm hơn, vẫn nối liền). Chỗ nối có thể có tiếng "tách" rất nhỏ do AAC → kiểm bằng tai ở manual test; nếu nghe thấy thì sửa đổi contract (vd encode lại riêng audio).
- **G4 Lưu trữ.** `output/_compilations/<playlist_id>/<cid>.mp4` + `<cid>.json` (`schema_version`, `mode`, `items` = danh sách `{episode_id, clip}` theo thứ tự đã mở rộng lần lặp, `repeat`, `duration`, `chapters`, `created_at`, `status`). `cid` = 12 ký tự đầu sha256 của spec (mode + items + repeat) → cùng yêu cầu thì dùng lại file đã có, không ghép lại. Ghi atomic (file tạm rồi rename). Không thuộc workspace tập nào: xóa tập / dọn nguồn (CP8.6) không xóa video ghép; video ghép không tính vào "Xong" của bộ kinh.
- **G5 Job.** Kind mới `compilation`, làn `render`, key `compilation:<playlist_id>:<cid>`; lưu qua khởi động lại như các job khác (CP8.22); job lỗi → `status = "failed"` + thông báo, file tạm bị xóa. Hủy job đang chạy: out of scope (xóa sau khi xong).
- **G6 Web (sửa theo G9).** Trang **Yêu thích** của bộ kinh (G9), không phải trang bộ kinh: danh sách khai thị **yêu thích** đã render (tập, `KT`, title, thời lượng) có ô tick + tổng thời lượng các mục đã tick; nút "Ghép (n đoạn, X phút)"; mỗi dòng có nút "Lặp" → ô nhập tổng phút + xem trước số lần lặp → "Tạo"; ô "Tự ghép theo thời lượng" (G10). Danh sách video ghép của bộ: chế độ, số đoạn / số lần lặp, thời lượng, trạng thái (đang chờ / đang ghép / xong / lỗi), "Tải", "Copy mô tả", "Xóa" (xác nhận). Route (cùng auth / cookie như route bộ kinh): **Amendment 2:** trang Yêu thích có bộ lọc "Tất cả | Short | Khai thị" (mặc định Tất cả, nhớ trong `localStorage`, bọc try/catch); tick / Ghép / Lặp dùng cho mọi mục; mỗi dòng ghi mã `T<tập>_S<NN>` / `T<tập>_KT<NN>`; mục có thêm field `kind`.
  - `GET /api/playlists/{pid}/compilations` — khai thị yêu thích (kèm cờ dùng được) + video ghép đã có;
  - `POST /api/playlists/{pid}/compilations` — body `{"mode": "concat", "items": [...]}`, `{"mode": "loop", "item": {...}, "minutes": T}` hoặc `{"mode": "auto", "minutes": T}` (G10); trả `cid` (đã có → trả luôn, không xếp job);
  - `DELETE /api/playlists/{pid}/compilations/{cid}`;
  - `GET /files/playlists/{pid}/compilations/{cid}.mp4` — tải về.
- **G7 Tên file tải về + mô tả.** `concat`: `<Tên bộ kinh> - Khai thị T<a>-T<b> (<n> đoạn).mp4` (cùng một tập: `… Khai thị T<a> (<n> đoạn).mp4`, sửa 2026-10-17); `loop`: `<Tên bộ kinh> - T<tập>_KT<NN> lặp <n> lần.mp4` (dùng quy ước tên của `review/names.py`, CP8.21). "Copy mô tả": `concat` → mỗi dòng `MM:SS <title khai thị>` (từ `00:00`, giờ thì `H:MM:SS`) + hashtag của bộ kinh (CP8.8); `loop` → title khai thị + hashtag (không chapter). **Amendment 2:** `concat` → `<Tên bộ kinh> - <Short|Khai thị|Short + Khai thị> T<a>[-T<b>] (<n> đoạn).mp4` (chữ theo loại có mặt); `loop` Short → `<Tên bộ kinh> - T<tập>_S<NN> lặp <n> lần.mp4`; chapter / mô tả dùng title Short như khai thị.
- **G9 Yêu thích (riêng từng bộ kinh).** Icon trái tim (bật / tắt, không cần xác nhận) trên mỗi khai thị ở trang tập và trang bộ kinh (danh sách tập / khai thị của bộ). Lưu `output/_compilations/<playlist_id>/favorites.json` (`schema_version`, `items` = `{episode_id, clip}` sắp theo G1; ghi atomic). Khai thị của tập không thuộc bộ → 400. Trang bộ kinh có link "Yêu thích (n)" → trang mới `/playlists/{pid}/favorites` (cùng auth). Khai thị yêu thích sau đó bị xóa (`rejected`) / chưa render / render lại thành ít khai thị hơn: vẫn hiện trên trang Yêu thích nhưng mờ, không tick được, không dùng cho G10; bỏ tim được. Video ghép đã tạo không đổi khi danh sách yêu thích đổi. Route: `POST /api/playlists/{pid}/favorites` body `{"episode_id", "clip", "favorite": true|false}` (idempotent). Xóa tập / bộ kinh không bắt buộc dọn `favorites.json` (mục mồ côi hiện mờ). **Amendment 2:** trái tim cũng có trên mỗi Short ở trang tập Short, cùng nút / cùng hành vi; mục `{episode_id, clip}` (loại suy từ id); "Yêu thích (n)" đếm cả hai loại. Trái tim vẫn không có trên trang bộ kinh (HUMAN LEAD 2026-10-17: không cần).
- **G10 Tự ghép theo thời lượng (`auto`).** Nhập tổng `T` phút (cùng giới hạn G2) → lấy các khai thị yêu thích dùng được theo thứ tự G1, nối lần lượt, hết danh sách thì lặp vòng từ đầu, dừng khi tổng ≥ `60·T` (không cắt dở khai thị cuối). Xem trước "n đoạn (k vòng) ≈ X phút" trước khi tạo. Kết quả mở rộng thành spec `concat` (cùng `cid`, metadata, tên file G7 dạng concat, mô tả có chapter G7); `mode` ghi `auto` trong `<cid>.json`. Không có yêu thích dùng được → 400. **Amendment 2:** body nhận `"kinds"` (tập con của `["short","khaithi"]`, mặc định cả hai; rỗng / giá trị khác → 400); chỉ dùng yêu thích dùng được thuộc các loại đó; UI gửi loại của bộ lọc đang chọn.
- **G11 Giữ khai thị yêu thích khi xóa tập (Amendment 1).** Dọn video nguồn (W9 S3 / S5) và gợi ý (S2) không đổi. **Amendment 2:** áp dụng y hệt cho tập Short `<id>` (Short yêu thích đang `rendered` được giữ vào `kept/<episode_id>/<clip>.mp4` + snapshot); xóa tay một Short yêu thích bỏ luôn tim; hộp xác nhận ghi "Short" / "khai thị" theo loại; xóa cả hai phần của một video thì từng phần được xử lý riêng.
  (a) `DELETE /api/episodes/{id}` (trang tập hoặc gợi ý Bộ nhớ) của tập khai thị `<id>.kt`: TRƯỚC khi xóa, mỗi clip là yêu thích (trong `favorites.json` của bất kỳ bộ kinh nào) và đang `rendered` được chuyển (rename; khác ổ đĩa → copy + kiểm kích thước rồi xóa nguồn) sang `output/_compilations/<playlist_id>/kept/<episode_id>/<clip>.mp4` (nhiều bộ kinh cùng yêu thích → mỗi bộ một bản); mục yêu thích nhận snapshot `kept` = `{path (tương đối với thư mục bộ kinh), title, duration, episode_number (tập), clip_number (KT), clip_total (độ rộng NN, bổ sung), saved_at}`; `favorites.json` ghi atomic. Lỗi lúc giữ, hoặc xóa tập thất bại sau đó → hoàn tác, trả 500, không xóa gì.
  (b) Mục yêu thích "dùng được" nếu clip của tập đang `rendered` HOẶC có file `kept` còn tồn tại; có `kept` thì luôn dùng file `kept` (kể cả khi tập được gửi lại và render lại, (e)). Trang Yêu thích, concat / loop / auto, chapters, tên file, hashtag dùng snapshot; mục đã giữ hiện "đã lưu" (không có nút "Xem").
  (c) Bỏ tim mục đã giữ → xóa file `kept` (xác nhận "Khai thị này đã bị xóa khỏi tập, bỏ tim sẽ xóa hẳn"). Xóa tay một khai thị (CP8.5 reject) đang yêu thích → bỏ luôn tim, không giữ bản nào (hộp xác nhận nói rõ).
  (d) Hộp xác nhận xóa tập `.kt` có yêu thích: "n khai thị yêu thích sẽ được giữ lại trong mục Yêu thích" (`favorites_count` của `GET /api/episodes/{id}`). Số byte "giải phóng" ở Bộ nhớ không đổi (Known limitation: ước tính cao hơn thực tế bằng dung lượng file giữ lại).
- **G8 Config.** Section mới `[compilation]`: `max_minutes` (int, 1–720, mặc định 720). Không key nào khác.

## Scope

- In scope: G1–G10; module `src/auto_short/compilation/` (spec, ghép ffmpeg, metadata, tên file, mô tả) — web chỉ gọi; job kind + route + UI trang bộ kinh; README mục ngắn; cập nhật `docs/ai/project-profile.md` §3 (module map) và pointer trong `docs/decisions/CP8.3-web-contract.md`.
- Out of scope: CLI; ghép khác bộ kinh; sắp xếp tay; khoảng lặng / dissolve / intro / outro; thumbnail; tick "Đã đăng" cho video ghép; endpoint xem trước file `kept`; tự ghép lại khi danh sách yêu thích đổi; sắp tay danh sách yêu thích; tab Bộ nhớ đếm dung lượng video ghép (ghi Known limitation); hủy job đang chạy.

## Authority / key decisions

- G1–G10 ở trên (khi APPROVED là canonical owner của video ghép cho tới khi tách decision record riêng nếu mở rộng).
- CP8.9 (khai thị, tên `KT`), CP7 (thông số encode), CP8.3 + CP8.10 + CP8.22 (auth, route, làn, lưu hàng đợi), CP8.7 / CP8.8 / CP8.11 (bộ kinh, hashtag, "Tên bộ kinh"), CP8.21 (tên file).

## Implementation approach

- `compilation/`: `build_spec(...)` (validate, tính `n`, `cid`), `probe_compatible(paths)`, `assemble(spec, out)` (viết list file concat với đường dẫn tuyệt đối đã escape, `ffmpeg -f concat -safe 0 -i list -c copy -movflags +faststart`; fallback encode lại), `chapters(...)`, `download_name(...)`. Loop: list file lặp lại cùng đường dẫn `n` lần (không copy file nguồn).
- Web: tách logic route sang module nhỏ như `web/prepared.py` / `web/reading.py`; UI trong `web/static/` theo style trang bộ kinh hiện có.
- Test dùng clip ffmpeg tổng hợp ngắn (vài giây, `lavfi`), không dùng dữ liệu thật.

## Acceptance Criteria

1. `concat` 3 khai thị → mp4 có thời lượng = tổng ± 0,1 s, cùng codec / kích thước / fps với input, thứ tự đúng thứ tự tập (kiểm bằng ffprobe + frame đầu từng đoạn).
2. `loop` với `T` phút → `n = ceil(60·T/d)`, thời lượng ≈ `n·d` ± 0,1 s; vượt `max_minutes` hoặc `T < 1` → 400, không job nào được xếp.
3. Input khác thông số → nhánh encode lại chạy và kết quả hợp lệ (thông số CP7).
4. Cùng spec gửi lại → cùng `cid`, không xếp job mới; spec khác → `cid` khác.
5. Chỉ chấp nhận khai thị của đúng bộ kinh, đã render, không `rejected`; mục ngoài bộ / tập không thuộc bộ kinh / `cid` hay `pid` không hợp lệ → 400 / 404; route không có cookie → 401 như route khác.
6. Job `compilation` chạy ở làn `render`, sống qua khởi động lại; lỗi ffmpeg → `status = failed`, không còn file tạm.
7. Tên file tải về và "Copy mô tả" đúng G7 (chapter bắt đầu `00:00`, mốc = tổng thời lượng các đoạn trước).
8. Xóa video ghép xóa `.mp4` + `.json`; xóa tập / dọn nguồn không đụng `output/_compilations/`.
9. Trái tim bật / tắt ghi đúng `favorites.json` (idempotent, thứ tự G1); khai thị ngoài bộ → 400; mục không còn dùng được hiện mờ, không vào `auto`; trang `/playlists/{pid}/favorites` và route yêu thích không có cookie → 401 / chuyển hướng đăng nhập như trang khác.
10. `auto` với `T` phút: thứ tự + lặp vòng + dừng khi ≥ T đúng G10 (kiểm cả danh sách 1 mục và danh sách dài hơn T); không yêu thích dùng được → 400.
11. Tập Short, khai thị, bộ kinh hiện có: artifact và route cũ không đổi (full suite PASS).
12. G11: xóa tập `.kt` có 2 clip yêu thích trong 3 clip → 2 file `kept` + snapshot, tập biến mất, trang Yêu thích liệt kê, concat / loop / auto dùng được file `kept`; bỏ tim mục đã giữ → file bị xóa; xóa tay một clip yêu thích → tim bị bỏ; tập không có yêu thích xóa y như trước; lỗi lúc giữ / lúc xóa → không mất gì.
13. Amendment 2: tim bật / tắt trên Short; concat trộn Short + khai thị (thứ tự + tên); loop một Short (tên `T<tập>_S<NN>`); auto với bộ lọc chỉ Short / chỉ khai thị / cả hai (+ `kinds` sai → 400); xóa tập Short giữ Short yêu thích, xóa tay một Short yêu thích bỏ tim; test khai thị cũ không đổi.

## Required verification

- `python -m pytest -q -n auto` — toàn bộ suite, PASS (AC 1–11 có test mới trong `tests/test_compilation*.py`).
- `node scripts/framework-check.mjs` — PASS.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Chạm public API (route web mới, cùng auth hiện có); không chạm database, security model. Manual test trên 8080 (ghim commit nhánh) là điểm danh trước integration.

- [x] Bấm tim vài khai thị ở trang tập + trang bộ kinh → hiện trên trang Yêu thích; bỏ tim → mất.
- [x] Bộ Địa Tạng: ghép 3–4 khai thị → tải về, xem trên điện thoại: thứ tự đúng, chỗ nối không giật / không tiếng tách.
- [x] Lặp một khai thị 30 phút → số lần lặp đúng như xem trước, tải về xem được.
- [x] Tự ghép 60 phút từ yêu thích → số đoạn / vòng đúng như xem trước.
- [x] "Copy mô tả" dán vào YouTube Studio → chapter nhận đúng.
- [x] Bấm tim vài Short ở trang tập Short; trang Yêu thích lọc Tất cả / Short / Khai thị; ghép trộn Short + khai thị, tự ghép chỉ Short → tên file / chapter đúng.
- [x] Xóa một tập khai thị có clip yêu thích (xác nhận nói "được giữ lại") → vẫn thấy ở trang Yêu thích ("đã lưu"), ghép / lặp được; bỏ tim → mất hẳn.
- [x] Gửi lại cùng lựa chọn → không ghép lại; xóa → biến mất khỏi danh sách và đĩa.

## Result

- Main changes: package `src/auto_short/compilation/` (spec, probe, assemble, meta, store); `web/compilations.py` + job kind `compilation` (`web/jobs.py`); routes / favourites / G11 keep-on-delete in `web/app.py`; UI `favorites.html` + `favorites.js`, heart in `app.js`, link on the bộ kinh page; config `[compilation]`; README, project profile §3, CP8.3 pointers.
- Tests: `tests/test_compilation.py`, `tests/test_web_compilation.py` (AC 1–12).
- Review: ORCHESTRATOR review ACCEPTED 2026-10-17 (code + real-data smoke: 3 khai thị → 740,86 s = tổng, `-c copy`, 1,6 s; suite 1831 passed / 1 skipped). Manual test HUMAN LEAD trên 8080 (local merge với #85): đạt 2026-10-17 ("CP8.33 test ok").
- Important findings / decisions: `<cid>.json` also carries `download_name`, `title`, `duration_estimate`, `size`, `reencoded`, `error`, `finished_at`; `cid` of `auto` = `cid` of the equal `concat`; the heart on a khai thị lives on the episode page and the Yêu thích page (the bộ kinh page lists episodes, not clips: it carries the "Yêu thích (n)" link); kept snapshot has an extra `clip_total`.
- Amendment 2 (Shorts like khai thị): kind derived from the episode id (`.kt`), no `kind` stored; `Clip.rank` is `(episode position, 0 Short / 1 khai thị, clip number)` so khai thị-only `cid`s are unchanged; `kinds` filter on `auto`; tests `test_web_compilation.py` (AC13).
- Review fix 1 (HUMAN LEAD 2026-10-17): concat name uses `T<a>` when first == last episode; hearts on the bộ kinh page confirmed not needed (Deviation 1 accepted).
- Known limitations: a re-rendered clip with the same clip id reuses the old compilation (cid is of ids, not file hashes); Bộ nhớ "giải phóng" overstated by kept files; compilations not counted in the Bộ nhớ tab; no cancel of a running job; kept files have no preview link.
- PR: #86
