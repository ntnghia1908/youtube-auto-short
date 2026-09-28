# Task: CP8.9 — Video khai thị (thời lượng tùy chỉnh)

## Status / Approval

- Status: IN_PROGRESS
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Base commit / branch: `194c7f4` (`docs/cp8.4-skip`, trên `origin/main` `7274d8e`) / `feature/cp8.9-khai-thi`
- Human Lead approval: accepted (HUMAN LEAD 2026-09-28: APPROVE TASK, D1–D6 theo đề xuất; K1–K9 dưới đây là chi tiết hóa D1–D6, không thêm quyết định mới). Sửa đổi **A1** HUMAN LEAD 2026-09-28 (trong lúc IN_PROGRESS): "Xử lý" một tập tạo cả Short lẫn khai thị, mặc định 4–7 phút, "Xong" tính cả khai thị — xem § Sửa đổi A1; A1 thắng K6–K9 / AC nếu mâu thuẫn. Sửa đổi **A2**, **A3** HUMAN LEAD 2026-09-28 sau manual test lần 1 — xem § Sửa đổi A2, A3
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: sửa CP1 §2/§3 (loại output mới, thời lượng không cố định 30–180 s); thêm artifact theo episode và đổi config hash của analysis/selection (CP2 D7, CP4, CP5 B3/B9); thêm prompt selection mới; đổi HTTP API (CP8.3 W3, W7) và tên file tải về (W8). Không thêm dependency, không đổi security model, không đổi hành vi / hash của tập Short hiện có.

## Goal

Từ web (và CLI), người dùng gửi một video YouTube kèm lựa chọn **Khai thị** và khoảng thời lượng **min–max phút**. Pipeline tạo nhiều video khai thị 9:16 (cùng template, header, tiêu đề AI như Short), mỗi video trọn một ý, dài trong khoảng đã chọn (tính sau rút khoảng lặng), nằm trong một tập riêng không ghi đè các Short của cùng video. Xem, sửa tiêu đề, xóa, tải về, tick "Đã đăng" như Short.

## Scope

- In scope:
  - K1 tập khai thị riêng + artifact tham số `khaithi.json`; K2 thời lượng hiệu lực cho analysis/selection; K3 prompt selection `kt1`; K4 window lớn hơn; K5 dùng lại video nguồn + transcript của tập Short; K6 CLI; K7 web; K8 tên file / hashtag / bộ kinh; K9 config `[khaithi]`.
  - Titling, review (sửa title, xóa / khôi phục), render, `publish.json`, archive, xóa tập, tab Bộ nhớ chạy trên tập khai thị như tập thường (không code riêng nếu không cần).
  - Docs: decision record mới `docs/decisions/CP8.9-khai-thi-contract.md` (canonical owner của K1–K9); pointer ở CP1 §2/§3, CP2 D3, CP4 (params thời lượng), CP5 B3/B9, CP8.3 W3/W7/W8/W10; project profile (authority list, module map); README (usage); `AUTO_SHORT_CHECKPOINT_PLAN.md` (mục CP8.9); `config.example.toml`; `docs/workflow/current-state.md`; Result của contract này.
  - Tests + chạy thật trên scratch.
- Out of scope:
  - Khung ngang 16:9 (backlog), video > 15 phút, upload YouTube (CP8.4 đã bỏ).
  - Nút khai thị cho cả bộ kinh / xếp hàng hàng loạt; trạng thái "Xong" của bộ kinh tính khai thị (D6: chỉ tính Short).
  - Đổi prompt titling, layout render, luật title (≤ 60 ký tự giữ nguyên).
  - Khử trùng dung lượng hardlink trong tab Bộ nhớ (ghi vào Known limitations).
  - Sửa web đang chạy ở worktree `../youtube-auto-short-web` (HUMAN LEAD tự chuyển sau merge).

## Authority / key decisions

- Authority: CP1 §2–§5, §8; CP2 D3–D7; CP4 (candidates, `params`); CP5 B2, B3, B9; CP6; CP7; CP8 E2–E5; CP8.2 T1–T7; CP8.3 W3–W10 (+ CP8.5–CP8.8).
- Quyết định (D1–D6 HUMAN LEAD 2026-09-28, chi tiết hóa):
  - **K1 Tập khai thị (D1, D3):** loại output "khai thị" = video 9:16 cùng template CP7, dài hơn Short, đăng như video dọc thường (không phải YouTube Short khi > 3 phút). Mỗi nguồn có tối đa **một** tập khai thị, episode id `<base_id>.kt` (`base_id` = id CP2 D3 của nguồn; hợp lệ theo regex CP2 D3; video id YouTube không có `.` nên không trùng). Workspace `work/<base_id>.kt/`, output `output/<base_id>.kt/`. Loại tập xác định **chỉ** bởi file `work/<id>/khaithi.json` (không suy từ hậu tố):
    ```json
    {"schema_version": 1, "kind": "khaithi", "base_episode_id": "rbjfCfFq3Dk", "min_minutes": 5, "max_minutes": 10}
    ```
    Ghi atomic, thứ tự key cố định, không timestamp; viết bởi `run` (CLI / web) trước khi chạy stage; không phải stage (không entry trong manifest), như `review.json`. Sai schema / giá trị ngoài K2 → lỗi user-facing, stage không chạy, manifest không đổi.
  - **K2 Thời lượng (D2):** `min_minutes`, `max_minutes` nguyên, `1 ≤ min < max ≤ [khaithi] max_minutes_limit` (mặc định 15). Tính trên thời lượng thực tế sau rút khoảng lặng (như CP1 §3 sửa đổi 2026-09-26). Với tập khai thị, analysis dùng `min_duration = 60·min`, `max_duration = 60·max`, `target_min = min_duration`, `target_max = max_duration` thay cho giá trị `[analysis]`; các key `[analysis]` khác giữ nguyên. Giá trị hiệu lực nằm trong `used_config` (config hash) và `candidates.json` `params` → đổi min–max làm analysis và các stage sau stale (CP2 D6); đổi thời lượng Short trong `[analysis]` không làm tập khai thị stale. Tập Short: `used_config`, `params`, config hash **không đổi byte nào** (không Short nào stale sau khi nâng cấp).
  - **K3 Prompt (D4):** thêm prompt selection `kt1` (dựa trên v3, cùng B11 head cut, cùng format dòng unit / `RESPONSE_SCHEMA`): nhiệm vụ là "video khai thị ngắn độc lập"; thời lượng bắt buộc/lý tưởng lấy từ placeholder điền bằng giá trị hiệu lực K2 (phút và giây), ví dụ tính thời lượng đổi cho phù hợp độ dài. `prompt_sha256` tính trên template (có placeholder), giá trị điền nằm trong config hash (như `head_cut_words`). Tập khai thị dùng `[khaithi] prompt_version` (mặc định `kt1`); tập Short vẫn `[selection] prompt_version` (`v3`), prompt v1–v3 giữ nguyên văn. Chọn cuối (B6), validation (B8, dùng min/max hiệu lực), schema `clips.json` / `selection_log.json` không đổi; `max_clips`, `min_score` dùng chung `[selection]`.
  - **K4 Window:** tập khai thị dùng `max_window_words = max([selection] max_window_words, [khaithi] window_words_per_minute × max_minutes)` (mặc định `window_words_per_minute = 400`, ≈ 2 lần tốc độ nói, để window con chồng lấn chứa được candidate dài nhất); giá trị hiệu lực vào config hash + `params`. `num_ctx` dùng `[selection]`; chạy thật phải ghi `prompt_eval_count` lớn nhất so với `num_ctx` (vượt / sát → báo, không tự đổi `num_ctx`).
  - **K5 Dùng lại (D3):** ingest tập khai thị YouTube: nếu `work/<base_id>/` có ingest `done`, cùng video id, cùng `ingest.youtube_format`, file nguồn còn (không archived) và khớp sha256 trong manifest → hardlink (lỗi → copy) sang `work/<base_id>.kt/source.<ext>` thay vì tải; không thì tải như CP2 D4. Nguồn local: không copy (CP2 D4), chỉ ghi manifest. Transcript: nếu tập gốc có transcript `done`, cùng source sha256 và cùng `used_config` transcript → copy `transcript.json` (+ artifact phụ của stage, nếu có) và ghi manifest như stage đã chạy với provenance không đổi; không thì chạy CP3 bình thường. Không ghi / đổi gì trong `work/<base_id>/`. Tập gốc không bắt buộc phải có.
  - **K6 CLI (D5):** `auto-short run <source> --khai-thi --min-minutes N --max-minutes M` (thiếu min/max → `[khaithi] default_min_minutes` / `default_max_minutes` = 4 / 7, A1) → episode `<base_id>.kt` (`--episode-id X` đổi `base_id`); ghi / cập nhật `khaithi.json` rồi chạy pipeline CP8 như thường. `--min/--max-minutes` không có `--khai-thi` → lỗi. Lệnh từng stage (`analysis <id>.kt`, …) và `title`, `status` tự đọc `khaithi.json`. `status` hiện loại + min–max.
  - **K7 Web (D5):** `SubmitIn` thêm `kind: "short" | "khaithi"` (mặc định `"short"`), `min_minutes`, `max_minutes` (int; chỉ với `khaithi`; sai → 422 message tiếng Việt). `kind: "khaithi"` chỉ cho URL một video (playlist → 422). Luồng như W4 trên episode `<video_id>.kt` (job trùng → 200 `created: false`, archived → 409, ổ đầy → 507, preflight). Tập khai thị đã có với min–max khác → job cập nhật `khaithi.json` rồi pipeline tự chạy lại từ analysis; UI hỏi xác nhận trước ("thay toàn bộ video khai thị cũ, tick Đã đăng cũ thành bản cũ"). Form trang chủ: chọn "Short" / "Khai thị", khi chọn khai thị hiện hai ô phút (mặc định 4–7 theo A1, giới hạn 1–15). `GET /api/episodes` / `GET /api/episodes/{id}` thêm `kind` (`"short"` | `"khaithi"`), `min_minutes`, `max_minutes`, `base_episode_id` (null với Short) và `khaithi_episode_id` ở tập Short khi có tập khai thị. UI: nhãn "Khai thị m–n phút" ở danh sách và trang tập; link qua lại giữa trang tập Short và trang tập khai thị cùng video; trang tập Short có nút "Tạo video khai thị" (hai ô phút, cùng API).
  - **K8 Tên file, hashtag, bộ kinh (D5, D6):** tập khai thị tải về `Tập<episode>_KT<NN>_<title>.mp4`, zip `Tập<episode>_KhaiThị.zip` (`<episode>`, `<NN>`, làm sạch như W8; `<episode>` không có → `base_id`, không kèm `.kt`). Hashtag Copy: như tập gốc `base_id` (bộ kinh chứa `base_id` → danh sách của bộ kinh, CP8.8 H4). Bộ kinh: trạng thái / "Xong" / đếm của từng tập chỉ theo tập Short (không đổi); dòng tập có link "Khai thị" khi `work/<video_id>.kt/` tồn tại. Trang chủ mục "Tập lẻ": tập khai thị có `base_id` thuộc bộ kinh đã lưu không hiện ở đây (như tập Short của nó); còn lại hiện với nhãn. "Xong" (W10 L4) tính riêng cho tập khai thị ở trang tập của nó.
  - **K9 Config `[khaithi]`:** `default_min_minutes = 4`, `default_max_minutes = 7` (A1), `max_minutes_limit = 15`, `prompt_version = "kt1"`, `window_words_per_minute = 400`; validate khi load (như các section khác). Chỉ các giá trị hiệu lực (K2–K4) vào config hash; default và limit là execution-only.

## Sửa đổi A1 (HUMAN LEAD 2026-09-28)

Thay phần tương ứng của K7, K8 (bộ kinh) và D6. CLI (K6) giữ nguyên: `run` không có `--khai-thi` vẫn chỉ tạo Short.

- **A1.1 Một lần xử lý = hai tập:** `SubmitIn` dùng `kinds: list["short" | "khaithi"]` (không rỗng, không trùng) thay cho `kind`; **bỏ trống = `["short", "khaithi"]`**; `min_minutes` / `max_minutes` tùy chọn (bỏ trống = `[khaithi] default_*` = 4 / 7), chỉ hợp lệ khi có `"khaithi"`. Mỗi kind đi qua đúng luồng W4 của episode của nó (`<video_id>` / `<video_id>.kt`: job trùng, archived, ổ đầy; preflight một lần cho cả request). Job xếp hàng theo thứ tự **Short trước, khai thị sau** (để K5 dùng lại nguồn + transcript). Response: `{"kind": "video", "episodes": [{"kind", "episode_id", "created", "job"} …]}` và giữ `created` / `episode_id` / `job` của phần tử đầu (tương thích UI cũ). Một kind bị từ chối (vd archived) → phần tử đó có `"error"` + mã, kind kia vẫn chạy; tất cả bị từ chối → mã lỗi của phần tử đầu.
- **A1.2 Nút bộ kinh (W10 L3):** "Xử lý" (`new`) và "Xử lý lại" (`deleted`) gửi không kèm `kinds` → cả hai. "Chạy tiếp" (`failed` / `incomplete`) gửi `kinds` = Short (nếu Short chưa xong) + khai thị **chỉ khi** `work/<video_id>.kt/` đã tồn tại và chưa xong; không tự tạo khai thị cho tập đã có Short từ trước CP8.9 (tạo qua nút "Tạo video khai thị" ở trang tập, K7).
- **A1.3 Trang chủ:** hai ô chọn "Short" và "Khai thị", **mặc định tick cả hai**; ô khai thị kèm min–max phút (mặc định 4–7). Bỏ tick cả hai → không gửi được. Playlist URL: như cũ (bộ kinh), các ô không áp dụng.
- **A1.4 "Xong" và trạng thái dòng tập trong bộ kinh (thay D6 và câu "chỉ theo tập Short" của K8):** tập Xong ⇔ tập Short Xong (W10 L4) **và**, nếu `work/<video_id>.kt/` tồn tại, tập khai thị cũng Xong (cùng luật L4 trên render/publish của nó). Tập chưa có khai thị (xử lý trước CP8.9) → như cũ. `state` tổng hợp: có job đợi / chạy ở một trong hai → `queued` / `processing`; một trong hai `failed` → `failed` (`error` ghi rõ Short hay khai thị); cả hai render xong chưa Xong → `rendered`; còn lại như cũ. Dòng tập hiển thị số Short và số video khai thị riêng (vd "12 Short · 3 khai thị", đã đăng a/n cho từng loại); tóm tắt bộ kinh (xử lý / Xong / đang làm) theo `state` tổng hợp. Bia mộ (`_deleted/`) và gợi ý dọn (W9) giữ theo tập Short; ghi vào Known limitations nếu có lệch.
- **A1.5 Trang chủ "Tập lẻ" / danh sách:** tập khai thị có tập Short cùng video hiện gộp dưới tập Short (nhãn + link), không thành dòng riêng; không có tập Short → dòng riêng có nhãn.

## Sửa đổi A2, A3 (HUMAN LEAD 2026-09-28, sau manual test lần 1)

Bằng chứng (web test, dữ liệu thật): tập 20 (`X8ao0_7ufto`, 4–7 phút) chỉ ra 1 video khai thị: phụ đề YouTube tự động có 35 nhãn `[âm nhạc]` (34/35 dài 1,1–3,5 s) → 33 hard break (CP4 A4 a) → 34 đoạn vụn, chỉ 6 candidate. HUMAN LEAD nghe 3 mẫu tại các nhãn đó: **chỉ là chỗ ngừng, không có tiếng**. Mô phỏng bỏ hard break từ nhãn ≤ 5 s: tập 20 còn 4 hard break (đoạn liền dài nhất 1208 s, 839 s); tập 7, 8, `W2d-xS4ttTw` còn 1–2. Ngoài ra `kt1` chỉ ra đúng 1 đề xuất mỗi window (tập 7: 3 lần gọi → 3; tập 20: 1 → 1).

- **A3.1 Nhãn ngắn không là hard break (chỉ tập khai thị):** với tập khai thị, segment `non_speech` dài ≤ `[khaithi] soft_label_max_seconds` (mặc định **5.0** s) **không** tạo hard break (CP4 A4 a); ranh giới đó được xử lý như khoảng lặng thường (điểm cắt nếu thỏa luật `silence` CP4 A5, nằm trong được candidate; rút khoảng lặng khi render như CP7 vì audio là im lặng). Nhãn dài hơn và khoảng lặng ≥ `hard_break_silence` vẫn là hard break. Giá trị hiệu lực vào `used_config` / `params` của analysis tập khai thị (tập khai thị cũ trở thành stale — HUMAN LEAD đồng ý: video khai thị cũ xóa hay giữ đều được, chạy lại thì thay). Tập Short: **không đổi** (AC1 giữ nguyên).
- **A3.2 Prompt `kt2`:** như `kt1` nhưng yêu cầu rõ: đề xuất **mọi** đoạn đạt yêu cầu trong danh sách, các đoạn không chồng lấn nhau nếu có thể, không dừng ở một đề xuất khi danh sách còn dài (vẫn tối đa 12 đề xuất, vẫn "thà không đề xuất còn hơn cụt ý"). `[khaithi] prompt_version` mặc định → `kt2`; `kt1` giữ nguyên văn.
- **A2.1 Tab mặc định trang bộ kinh:** "Đang làm" (thay "Tất cả"); nhóm "Đang làm" rỗng → vẫn mở "Đang làm" (người dùng tự chuyển tab). Tab người dùng chọn có thể nhớ trong trình duyệt (localStorage, bọc try/catch).
- **A2.2 Chọn loại ở trang bộ kinh:** thanh ở đầu trang: "Khi bấm Xử lý tạo: ☑ Short ☑ Khai thị [4]–[7] phút" (mặc định theo `[khaithi]`, trình duyệt nhớ, bọc try/catch); áp cho nút "Xử lý" và "Xử lý lại" của mọi dòng (gửi `kinds` + phút theo A1.1); bỏ tick cả hai → nút tắt. "Chạy tiếp" giữ A1.2 (không theo thanh chọn).
- **A2.3 Nhãn nút ở tập khai thị:** mọi chữ "Short" trong UI của tập khai thị đổi thành "video" / "video khai thị" (vd "Xóa video", "Hiện video đã xóa", "Khôi phục", đếm "3 video khai thị"); tập Short giữ nguyên chữ.
- **A2.4 Plan:** thêm mục `CP8.10 — Tối ưu hàng đợi (planned, HUMAN LEAD 2026-09-28)` vào `AUTO_SHORT_CHECKPOINT_PLAN.md`: tải video + phụ đề trước cho job trong hàng đợi, AI (GPU) và render (CPU) chạy chồng giữa các video; decision gate riêng (CP8.3 W5), không làm trong CP8.9.

## Implementation approach

- Hàm thuần đọc / kiểm `khaithi.json` và tính tham số hiệu lực (một chỗ, dùng chung analysis / selection / CLI / web); analysis và selection nhận config hiệu lực thay vì đọc `config.analysis` / `config.selection` trực tiếp cho các key K2–K4.
- Prompt `kt1` thêm vào `PROMPTS` như v3; render placeholder thời lượng trong `system_prompt`.
- Ingest / transcript: nhánh dùng lại K5 trước khi tải / lấy transcript; manifest vẫn theo CP2.
- Web: `api_submit` rẽ nhánh theo `kind`; `episodes.episode_view` / `list_episodes` / `names` / `playlists` nhận biết tập khai thị qua `khaithi.json`.
- Thứ tự gợi ý: config + tham số hiệu lực + analysis → selection `kt1` → ingest/transcript dùng lại → CLI → web API → UI → docs.

## Acceptance Criteria

1. Tập Short (không có `khaithi.json`): config hash, `used_config`, `candidates.json` `params`, prompt và kết quả mọi stage giống hệt trước; một workspace Short tạo bởi code cũ được skip toàn bộ (không stage nào stale). Test cũ vẫn pass.
2. `run --khai-thi --min-minutes 5 --max-minutes 10` tạo `work/<id>.kt/khaithi.json` đúng schema; mọi candidate và clip có `duration` trong [300, 600] s; `candidates.json` `params` ghi giá trị hiệu lực; `selection_log.json` ghi `prompt_version` `kt1` và system prompt đã điền 5–10 phút.
3. Đổi min–max của tập khai thị → analysis, selection, titling, render stale và chạy lại; chạy lại cùng min–max → skip toàn bộ. Đổi `[analysis] min_duration/max_duration` → tập khai thị không stale, tập Short stale như trước.
4. `min ≥ max`, `min < 1`, `max > max_minutes_limit`, không phải số nguyên, `khaithi.json` hỏng → lỗi rõ ràng (CLI exit ≠ 0 / web 422), không stage nào chạy, manifest không đổi.
5. K5: có tập Short cùng video đã ingest + transcript `done` → tập khai thị không gọi downloader, không gọi fetcher/Whisper; source là hardlink (cùng inode) hoặc bản copy cùng sha256; `transcript.json` giống hệt; `work/<id>/` không đổi file nào. Tập gốc archived / không có / khác format → tải bình thường.
6. K4: candidate dài nhất (`max_minutes`) luôn nằm trọn trong ít nhất một window; không có `SelectionError` "more than max_window_words" với max = 15 phút trên dữ liệu test.
7. Web: `POST /api/episodes` với `kind: "khaithi"` hợp lệ → 202, job trên `<video_id>.kt`; giá trị sai / kèm playlist → 422; job trùng → 200 `created: false`; archived → 409; chưa đăng nhập → 401. `GET` trả `kind`, `min_minutes`, `max_minutes`, `base_episode_id`, `khaithi_episode_id` đúng.
8. Tên file tải về / zip của tập khai thị theo K8; Copy dùng hashtag của bộ kinh chứa `base_id`; tập khai thị của video thuộc bộ kinh không hiện ở "Tập lẻ".
11. A1: `POST /api/episodes` không kèm `kinds` → hai job (Short rồi khai thị 4–7 phút); `kinds` chỉ một loại → một job; `kinds` rỗng / trùng / min–max kèm khi không có khai thị → 422; một kind archived → kind kia vẫn chạy. Nút bộ kinh gửi `kinds` đúng A1.2.
13. A3.1: tập khai thị với nhãn `non_speech` ≤ 5 s giữa hai unit → không hard break, candidate vắt qua được; nhãn > 5 s / lặng ≥ 10 s vẫn hard break; tập Short cùng transcript → hard break như cũ (AC1). A3.2: `kt2` là mặc định, `kt1` giữ nguyên `prompt_sha256`. Chạy thật tập 20 (`X8ao0_7ufto`, 4–7 phút) → số candidate và video khai thị ghi vào Result (kỳ vọng > 1; nếu vẫn ≤ 2 → báo, không tự đổi tham số khác).
14. A2: trang bộ kinh mở tab "Đang làm"; thanh chọn loại gửi đúng `kinds` / phút; tập khai thị không còn chữ "Short" trên nút / nhãn.
12. A1.4: "Xong" của tập có khai thị cần cả hai Xong; tập không có khai thị giữ kết quả cũ (test CP8.7 cũ pass); `state` tổng hợp và đếm Short / khai thị đúng.
9. Sửa title, xóa / khôi phục, tick "Đã đăng", xóa tập, archive hoạt động trên tập khai thị; xóa / archive tập Short không làm hỏng tập khai thị (và ngược lại).
10. `config.example.toml` có `[khaithi]` với giá trị K9; config sai → lỗi load rõ ràng.

## Required verification

- `pytest -q` — toàn bộ, gồm test mới cho AC1–AC10 (AC1 có test so sánh config hash / `params` tập Short với giá trị cố định trước thay đổi).
- `node scripts/framework-check.mjs` — PASS.
- Chạy thật trên scratch (config trỏ thư mục tạm; hardlink một tập đã có từ `work/` chính để kiểm K5; Ollama `127.0.0.1:11437`; không đụng `work/` / `output/` chính và web đang chạy): `run --khai-thi --min-minutes 5 --max-minutes 10` trên một video thật tới render. Ghi: số candidate / clip, thời lượng từng video, thời gian từng stage, số window và `prompt_eval_count` lớn nhất so với `num_ctx`, xác nhận downloader / Whisper không chạy (K5), sha256 `work/` chính không đổi. Web scratch (cổng khác 8080): gửi `kind: "khaithi"` qua curl, xem `GET` và tên file tải về.
- Bằng chứng cảm quan: gửi HUMAN LEAD 1–2 video khai thị mẫu để nghe / xem (trọn ý, điểm đầu / cuối).

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Lần 1 (HUMAN LEAD 2026-09-28, web test cổng 8091): phát hiện khai thị ra ít, tab mặc định, thiếu chọn loại ở bộ kinh, nhãn "Xóa Short" ở tập khai thị → A2, A3; đề xuất tối ưu hàng đợi → CP8.10.

Chạm public API contract (trường mới của `POST` / `GET /api/episodes`) — manual test là gate trước integration. Không chạm database, không đổi security model.

- [ ] Trang chủ: hai ô tick sẵn, khai thị 4–7 phút; gửi một video → hai job (Short rồi khai thị), xong có nhãn "Khai thị 4–7 phút", các video dài đúng khoảng.
- [ ] Bộ kinh: bấm "Xử lý" một tập mới → tạo cả Short và khai thị; dòng tập hiện số Short / khai thị; Xong chỉ khi đăng hết cả hai.
- [ ] Trang tập Short → "Tạo video khai thị"; link qua lại hai trang tập.
- [ ] Nghe / xem ít nhất 2 video khai thị: trọn ý, header + tiêu đề đúng; sửa tiêu đề + render lại một video.
- [ ] Tải về (tên `Tập<n>_KT<NN>_…`, zip), Copy tiêu đề (hashtag bộ kinh), tick Đã đăng; bộ kinh vẫn đếm như cũ.
- [ ] Gửi lại cùng video với min–max khác → hộp xác nhận → chạy lại từ analysis.

## Result

- Main changes: `src/auto_short/khaithi.py` (mới: `khaithi.json`, tham số hiệu lực K2–K4); `config.py` (`[khaithi]`, `SelectionConfig.duration_minutes`); `analysis/stage.py`, `selection/stage.py` + `selection/prompt.py` (`kt1`); `ingest/stage.py`, `transcript/stage.py` (K5); `pipeline.py` (kiểm `khaithi.json` trước mọi stage), `cli.py` (`--khai-thi`, `status`); web: `app.py` (`kinds`, A1.1), `episodes.py` (`kind_fields`, tên file), `playlists.py` (`combine_status`, `resume_kinds`, A1.4), `jobs.py`, `review/names.py`, `static/` (A1.3, A1.5, trang tập, bộ kinh); docs: `docs/decisions/CP8.9-khai-thi-contract.md` (canonical K1–K9 + A1) + pointer CP1 §2/§3, CP2 D3, CP4 config, CP5 B3/B9, CP8.3 W3/W7/W8/W10; project profile; README; plan; `config.example.toml`.
- Tests: `pytest -q` 817 passed (738 trước CP8.9). Mới: `tests/test_khaithi_ac1.py` (AC1: hash / params / prompt tập Short chốt từ code trước thay đổi), `tests/test_khaithi_cp89.py` (AC2–AC6, AC10, CLI, e2e `run --khai-thi` không mạng), `tests/test_web_khaithi_cp89.py` (AC7–AC9, AC11, AC12). Test cũ sửa theo A1 (mặc định hai kind): 4 test web gửi thêm `"kinds": ["short"]` vì chúng kiểm luồng W4 của riêng tập Short; helper `fake_pipeline` tôn trọng `episode_id`. `node scripts/framework-check.mjs` PASS.
- Chạy thật (scratch, video `7axON1RpRjo` "Thập Thiện Nghiệp Đạo Kinh tập 7", 56,6 phút, hardlink source từ `work/` chính, config riêng, Ollama 11437): tập Short code cũ → `ingest`…`titling` đều skip (AC1). `run --khai-thi --min-minutes 5 --max-minutes 10`: ingest 2,5 s (hardlink, không tải; cùng inode), transcript 0,0 s (copy, không provider; `transcript.json` giống hệt), analysis 83,7 s (90 unit, 29 candidate, tất cả 300,09–464,16 s), selection 148,5 s (14 window, 3 có candidate → 3 lời gọi `kt1`, `max_window_words` 4000, `prompt_eval_count` lớn nhất 2641 / `num_ctx` 32768, prompt + eval lớn nhất 12519 = 38 %), titling 15,0 s, render 331,8 s → 3 video 1080×1920: 300,8 s, 340,1 s, 300,1 s. Chạy lại cùng lệnh → 6 stage skip. Web scratch (cổng 8093): 401 chưa đăng nhập; 4 body sai → 422 tiếng Việt; POST mặc định → 202, job Short (1) rồi khai thị (2), gửi lại → 200 `created: false`; GET đủ `kind` / `min_minutes` / `max_minutes` / `base_episode_id` / `khaithi_episode_id`; tải về `Tập7_KT01_Tại sao dân chủ khiến mỗi người đều là chủ.mp4`, zip `Tập7_KhaiThị.zip`. sha256 76 file `work/` chính trước / sau: không đổi.
- Review: ORCHESTRATOR (dual-agent) review diff-first 2026-09-28 — ACCEPTED, không blocking finding; chạy lại `pytest -q` 817 passed, framework-check PASS. Non-blocking: (1) video thật 5–10 phút chỉ ra 3 video, sát mức tối thiểu (nhiều hard break); (2) k03 mở bằng "vậy thì…" và title viết thường đầu câu ("phật dạy ngắn gọn…") — để HUMAN LEAD nghe khi manual test; (3) chưa chạy thật với mặc định 4–7 phút. Manual test HUMAN LEAD: chờ.
- Important findings / decisions: (1) Video thật có nhiều hard break (nhạc / lặng ≥ 10 s): 11/14 window không có candidate 5–10 phút; 3 video, cả 3 gần mức tối thiểu. Fixture thật `rbjfCfFq3Dk` trong test chỉ cho candidate ở 2–5 phút (fixture thưa segment) nên test dùng 2–5 phút + dữ liệu tổng hợp cho 14–15 phút. (2) Quyết định khi implement (không đổi decision gate): `max_minutes_limit` bị chặn ≤ 15 khi load (video > 15 phút ngoài scope); response `created` / `episode_id` / `job` lấy từ phần tử đầu tiên không lỗi; prompt có placeholder thời lượng chỉ dùng cho tập khai thị (ngược lại → lỗi selection); link playlist bỏ qua `kinds`.
- Known limitations: xem `docs/decisions/CP8.9-khai-thi-contract.md` § Known limitations (hardlink đếm hai lần ở tab Bộ nhớ; bia mộ tập khai thị hiện ở "Đã xóa"; link về tập Short khi tập đó đã xóa; video ít đoạn nói liên tục → ít / không có video khai thị).
- PR: chưa (chờ READY review).
