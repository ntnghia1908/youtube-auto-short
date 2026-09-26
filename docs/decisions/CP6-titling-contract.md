# CP6 — AI Title / Hook Generation Contract

| Metadata | Value |
|---|---|
| Status | PROPOSED |
| Accepted by | — (G1–G10, P1–P4 duyệt cùng APPROVE TASK 2026-09-26; chờ review) |
| Checkpoint | CP6 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP6 |
| Task contract | `docs/tasks/CP6-titling.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §1, §4, §6, §8, §10, §11; `docs/decisions/CP2-workspace-contract.md` D1–D8; `docs/decisions/CP5-selection-contract.md` B3, B5, B7, B11 |

File này là **canonical owner** của header deterministic, text clip, prompt titling + versioning, validation title, chọn title và schema `titles.json` / `titling_log.json` mà CP7 (render) và CP9 (review) dùng lại. Nơi khác chỉ trỏ tới đây. Stage framework (manifest v1, skip/stale, config hash, CLI exit code) giữ nguyên theo `docs/decisions/CP2-workspace-contract.md`; `clips.json` theo `docs/decisions/CP5-selection-contract.md`, `candidates.json` theo `docs/decisions/CP4-analysis-contract.md`. Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/titling/` (`prompt.py`, `logic.py`, `stage.py`); client Ollama dùng lại `src/auto_short/selection/client.py`. Dữ kiện đo lúc soạn và tham số P1–P4: `docs/tasks/CP6-titling.md`.

## G1. Stage / artifact

- Stage `titling` (CP1 §8), subpackage `src/auto_short/titling/`.
- Artifact `work/<id>/titles.json` (trusted, qua validation G8) và `titling_log.json` (log AI: prompt, response thô, mọi option và lý do loại). Ghi atomic; `titles.json` không chứa timestamp (provenance ở manifest, CP2 D5). `titling_log.json` có thời gian gọi (không byte-stable).

## G2. Header (deterministic, không AI)

- Trường `speaker`, `series`, `episode`. Mỗi trường resolve theo thứ tự: CLI flag (`--speaker` / `--series` / `--episode`) > `[titling.header]` (chuỗi không rỗng) > named group cùng tên của regex `title_pattern` (`re.search` trên `metadata.title`, NFC). Giá trị được chuẩn hóa NFC + gộp khoảng trắng; flag/config rỗng sau chuẩn hóa = không đặt. Nguồn từng trường ghi ở `header.sources` (`cli | config | metadata`, `null` khi không resolve); `header.fields` là giá trị (`null` khi không resolve).
- Dòng header = template `[titling.header] lines` (`str.format` với `{speaker}`, `{series}`, `{episode}`), mặc định `["{speaker}", "{series} (tập {episode})"]`; 1–3 dòng (CP1 §4); dòng render ra rỗng (sau gộp khoảng trắng) → `failed`. Template chỉ được dùng ba trường trên (kiểm lúc đọc config: `{}` / `{title}` / `{speaker.x}` / cú pháp hỏng → lỗi config).
- Trường template cần mà không resolve được → stage `failed`, `error` nêu trường + flag/config cần đặt (vd `header field(s) not resolved: series (pass --series or set [titling.header] series), …`). Trường không dùng trong template được phép không resolve.
- Mặc định: `speaker = "HT.Tịnh Không"` (theo ảnh mẫu CP1 §4), `series = ""`, `episode = ""`, `title_pattern = ^(?:Phật Thuyết\s+)?(?P<series>.+?)\s+tập\s+(?P<episode>\d+)\b` (rỗng = tắt). Video test → `["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"]`.
- CP6 không ngắt dòng; "dòng" là dòng logic. Ngắt dòng hiển thị và kiểm ≤ 3 dòng hiển thị là của CP7.
- `header.lines` đã resolve vào `config_hash`. CLI flag không được lưu: chạy lại không flag mà giá trị resolve khác → chạy lại stage (giá trị ổn định nên đặt trong config); resolve thất bại → `failed`.

## G3. Text clip

- Text = nối (một khoảng trắng) `text` các unit từ `unit_ids[0]` tới `unit_ids[1]` của `candidates.json`, rồi tách token theo khoảng trắng.
- Clip có `head_cut` (CP5 B11): bỏ `len(head_cut.words.split())` token đầu nếu chúng khớp `head_cut.words` sau chuẩn hóa như B11 (`selection.logic.normalize_word`: NFC, lowercase, bỏ dấu câu hai đầu); không khớp → `failed` (dữ liệu không nhất quán, chạy lại selection).
- `clips.json.candidates_sha256` phải bằng sha256 canonical JSON của `candidates.json` đã đọc, nếu không → `failed`. `unit_ids` không có trong `candidates.json` → `failed`.
- `clips: []` → `titles: []`, stage `done`, không gọi AI.

## G4. Prompt (version `prompt_version`, mặc định `"v2"` — Sửa G4)

- Prompt là hằng trong `titling/prompt.py` (`PROMPTS[version] = (system, user template)`). **Đổi bất kỳ chữ nào phải thêm version mới**; `prompt_sha256` = sha256(`system + "\n\0\n" + template`) (template có chỗ trống) nằm trong `config_hash`. `prompt_version` không có trong code → lỗi (exit 1, manifest không đổi). Version trong code: `v1` (bản đầu, giữ nguyên văn để so sánh; `prompt_sha256` `8fe349ed…069037e4`) và `v2` (mặc định, **Sửa G4**; `0cc8abbf…d78c8359`). Mô tả dưới là v1; khác biệt của v2 ở mục **G4 v2**.
- System prompt v1 (tiếng Việt): biên tập viên kênh Phật pháp đặt tiêu đề cho Short cắt từ bài giảng; dữ liệu vào là caption tự động (không dấu câu, viết hoa lộn xộn, có thể sai chính tả); tiêu đề nêu đúng ý chính **của chính đoạn này**; tiếng Việt, một dòng, tối đa `<<MAX_CHARS>>` ký tự; viết hoa chữ đầu câu và danh từ riêng (ví dụ "Các bậc thang tu học Phật pháp"); chỉ dùng thông tin trong đoạn, không thêm tên người giảng/tên kinh/số tập; không emoji, hashtag, dấu chấm than, ngoặc kép bao ngoài, không viết hoa toàn bộ, không giật tít/phóng đại; được sửa chính tả hiển nhiên nhưng không đổi ý; đúng `<<N_OPTIONS>>` phương án, tốt nhất trước; `evidence` trích **nguyên văn** 3–25 từ liên tiếp, chép đúng như caption (giữ cả lỗi chính tả, không thêm dấu câu). `<<MAX_CHARS>>`, `<<N_OPTIONS>>` điền từ config (cả hai trong `config_hash`); `system_prompt` trong log là bản đã render.
- **G4 v2** (Sửa G4, HUMAN LEAD 2026-09-26, sau đọc title v1: v1 quá cao siêu — thuật ngữ Hán Việt, văn giảng kinh). User message, `RESPONSE_SCHEMA`, validation G5 và evidence (P2) **không đổi**; chỉ đổi system prompt:
  - Kênh dành cho người học Phật tại gia và người bình dân; title là câu "móc" (hook) YouTube: đọc vào hiểu ngay, lời lẽ đời thường, gần gũi, gợi một chút tò mò (có thể nêu câu hỏi / vấn đề đời sống mà đoạn trả lời).
  - Tránh thuật ngữ khó (Hán Việt, thuật ngữ kinh luận) khi có cách nói đời thường tương đương; nếu phải giữ thì đặt trong ý dễ hiểu.
  - Vẫn đúng ý chính của chính đoạn, chỉ thông tin trong đoạn, không thêm tên người giảng/tên kinh/số tập; không giật tít (không hứa hẹn, phóng đại, không "sốc", "bí mật", "không thể tin", "chấn động"); không emoji, hashtag, dấu chấm than, ngoặc kép bao ngoài, viết hoa toàn bộ; **được dùng dấu hỏi**; viết hoa kiểu câu (chỉ chữ đầu câu và danh từ riêng).
  - Ví dụ minh họa **không lấy từ video test**: đoạn giảng về giữ bình tĩnh khi bị nói xấu — tốt: "Bị người khác nói xấu, nên làm gì?", "Vì sao bị nói xấu mà không cần cãi lại"; không tốt: "Tu nhẫn nhục ba la mật trước nghịch duyên" (thuật ngữ khó), "Bí mật khiến kẻ nói xấu bạn phải hối hận" (giật tít).
  - Hướng dẫn `evidence` như v1, thêm "không ghép các chỗ khác nhau" (quyết định khi implement: đo v1 có evidence ghép hai chỗ không liền nhau, `k12`).
- User message mỗi clip: `Video: <metadata.title | (không rõ)>`, `Thời lượng Short: <clip.duration, 1 chữ số> giây`, dòng trống, `Lời nói của đoạn:` + text G3. Không đưa `topic`/`reason` của CP5 (P4).
- Output JSON theo `RESPONSE_SCHEMA` qua `format`: `{"options": [{"evidence": string, "title": string}]}` (thứ tự property = thứ tự sinh: căn cứ trước title). Schema không ràng buộc số phần tử; số option kiểm ở G6.
- Mỗi clip một lời gọi: `POST <host>/api/chat`, `stream: false`, `think`, `options = {temperature, seed, num_ctx}` (như CP5 B3).

## G5. Validate option (deterministic) và chọn title

- Chuẩn hóa title và evidence để lưu: NFC, bỏ khoảng trắng hai đầu, gộp khoảng trắng. Không sửa/cắt nội dung title của AI.
- Luật, kiểm theo thứ tự; option đầu tiên trượt luật nào thì `invalid` với `reject_reason` tương ứng:
  1. có ký tự xuống dòng (`\n \r \v \f \x1c–\x1e \x85 U+2028 U+2029`) bên trong (sau bỏ khoảng trắng hai đầu) → `multi-line title` (title lưu nguyên văn);
  2. rỗng → `empty title`;
  3. số code point NFC < `min_chars` → `too short (n < min chars)`; > `max_chars` → `too long (n > max chars)`;
  4. emoji/pictograph → `emoji/pictograph`: ký tự trong U+1F000–1FAFF, U+2190–21FF (mũi tên), U+2300–23FF, U+2600–27BF, U+2B00–2BFF, U+FE0F, U+200D, U+20E3, U+3030, U+303D, U+3297, U+3299, U+E0020–E007F;
  5. `#` → `hashtag`; `@` → `@ mention`; `!` hoặc `！` → `exclamation mark`;
  6. URL (`http(s)://`, `www.`, hoặc `<từ>.<com|net|org|vn|info|io|me|tv|ly>`) → `URL`;
  7. bao bởi cặp ngoặc kép (`"…"`, `“…”`, `'…'`, `‘…’`, `«…»`, `„…“`, `「…」`, `『…』`) → `wrapped in quotes`;
  8. viết HOA toàn bộ (có chữ có hoa/thường và `upper() == title`) → `all caps`;
  9. evidence sau chuẩn hóa so khớp (NFC, lowercase, ký tự không phải chữ/số thay bằng khoảng trắng, gộp khoảng trắng) có < 3 từ → `evidence too short (n < 3 words)`;
  10. evidence chuẩn hóa không phải chuỗi con **trọn từ** của text clip chuẩn hóa (so `" ev "` trong `" text "`) → `evidence not in clip text` (P2: chặn).
- Title = option `valid` đầu tiên theo thứ tự AI; các option `valid` còn lại → `alternatives` (`[{title, evidence}]`, cho CP9).
- Clickbait/sai nội dung ở mức ý nghĩa không kiểm được bằng code: dựa vào prompt + HUMAN LEAD đọc + CP9.
- Sửa title bằng tay (chọn từ `alternatives` hoặc gõ tay) thuộc **CP9** review (`review.json`, không gọi lại AI); CP7 render dùng title đã duyệt, không đọc thẳng `titles.json` (HUMAN LEAD 2026-09-26, `docs/tasks/CP6-titling.md`).

## G6. Response lỗi, retry, untitled

- Mỗi clip tối đa `1 + retries` lần gọi (mặc định `retries = 2`), backoff như CP5 B5 (`retry_backoff` mặc định `[5, 15]`, lặp giá trị cuối, hàm `selection.stage.backoff_before` import lại; sleep inject được).
- Lỗi được thử lại: HTTP lỗi, timeout, không kết nối, envelope Ollama sai, content không phải JSON, sai schema (không có mảng `options`, số option ≠ `n_options`, phần tử không phải object, `evidence`/`title` thiếu hoặc không phải chuỗi) — và response đúng schema nhưng **không option nào valid** (`error = "no valid option"`, option vẫn ghi log).
- Hết lượt:
  - nếu **ít nhất một** lần gọi trả response đúng schema (tức mọi lần thất bại còn lại là "no valid option" hoặc lỗi tạm thời xen giữa) → clip `untitled` (`title`/`evidence` = `null`, `alternatives` = `[]`) + cảnh báo stderr, stage vẫn `done` (P3). CP7 không render clip `untitled` cho tới khi CP9 sửa;
  - nếu **không lần nào** có response đúng schema → stage `failed`, `error` = `clip <kNN>: <lỗi cuối> (after N attempts)`, xóa cả hai artifact.
- Retry dùng cùng request (seed cố định).

## G7. Schema v1

Thứ tự key cố định:

```json
// titles.json
{"schema_version": 1, "episode_id": "rbjfCfFq3Dk",
 "clips_sha256": "<sha256 canonical JSON clips.json>",
 "candidates_sha256": "<sha256 canonical JSON candidates.json (= clips.json.candidates_sha256)>",
 "header": {"lines": ["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"],
            "fields": {"speaker": "HT.Tịnh Không", "series": "Thập Thiện Nghiệp Đạo Kinh", "episode": "9"},
            "sources": {"speaker": "config", "series": "metadata", "episode": "metadata"}},
 "model": {"provider": "ollama", "name": "qwen3:14b", "think": false,
           "options": {"temperature": 0, "seed": 42, "num_ctx": 16384}},
 "prompt_version": "v2", "prompt_sha256": "<G4>",
 "params": {"n_options": 3, "min_chars": 10, "max_chars": 60, "retries": 2},
 "stats": {"clips": 13, "ai_calls": 13, "titled": 13, "untitled": 0},
 "titles": [{"clip_id": "k09", "candidate_id": "c00723", "title": "Tướng và môi trường sống tùy tâm chuyển",
             "evidence": "…", "alternatives": [{"title": "…", "evidence": "…"}], "status": "titled"}]}
```

- `titles` cùng thứ tự và cùng số phần tử với `clips.json.clips`; `status` = `titled | untitled`.
- `stats.ai_calls` = tổng số lần gọi kể cả retry.

```json
// titling_log.json
{"schema_version": 1, "episode_id": "…", "clips_sha256": "…", "model": {…}, "prompt_version": "v1",
 "prompt_sha256": "…", "system_prompt": "<toàn văn đã render>", "response_format": {<RESPONSE_SCHEMA>},
 "header": {<như titles.json>}, "stats": {<như titles.json>},
 "clips": [{"clip_id": "k01", "candidate_id": "c00003", "text": "<text G3 gửi AI>",
            "ai_calls": [{"attempt": 1, "backoff_seconds": 0.0, "seconds": 44.8,
                          "request": {"model": "…", "messages": [system, user], "format": {…},
                                      "options": {…}, "think": true, "stream": false},
                          "response": {"content": "<raw>", "thinking": "…", "eval_count": 7000,
                                       "prompt_eval_count": 650, "total_duration": 44800000000,
                                       "done_reason": "stop"},
                          "error": null | "<lỗi G6>" | "no valid option",
                          "options": [{"title": "…", "evidence": "…", "status": "valid | invalid",
                                       "reject_reason": null | "<G5>"}]}]}]}
```

`response` là `null` khi lỗi xảy ra trước khi có response; `options` rỗng khi response sai schema.

## G8. Validation trước khi ghi (vi phạm → `failed`, lỗi code)

Mỗi clip của `clips.json` có đúng một entry, cùng thứ tự, `clip_id`/`candidate_id` khớp; entry `titled`: `title` và mọi `alternatives` qua lại luật G5 trên text G3 (gồm evidence là chuỗi con trọn từ); entry `untitled`: `title`/`evidence` `null`, `alternatives` rỗng; `status` chỉ `titled | untitled`; header 1–3 dòng không rỗng; `clips_sha256`, `candidates_sha256` khớp input đã đọc.

## G9. Stage / resume / CLI

Dùng `run_stage` của CP2 nguyên trạng:

- Yêu cầu `selection` = `done` và `clips.json`, `candidates.json`, `metadata.json` tồn tại; không có manifest → lỗi; chưa done → stage `failed` + `error`, không artifact, không gọi AI. Header (G2) resolve trước khi kiểm skip (vì nằm trong hash); resolve lỗi → `failed`.
- `inputs` = `clips.json`, `candidates.json`, `metadata.json` (relative + sha256).
- `config_hash` = `[titling]` `model`, `think`, `temperature`, `seed`, `num_ctx`, `prompt_version`, `n_options`, `min_chars`, `max_chars`, `retries` + `prompt_sha256` + `header.lines` đã resolve. **Không** gồm `ollama_host`, `timeout`, `retry_backoff`, và các giá trị `[titling.header]` thô (chỉ kết quả resolve). Đổi config stage khác không chạy lại titling.
- Host: env `OLLAMA_HOST` > `[titling] ollama_host` (mặc định `http://127.0.0.1:11437`).
- `artifacts` = `titles.json`, `titling_log.json`; lỗi → cả hai bị xóa. Chạy lại titling → downstream stale; selection chạy lại → titling stale (D6).
- CLI `auto-short titling <episode_id> [--force] [--config PATH] [--speaker S] [--series S] [--episode N]` — stdout `<episode_id>\t<titled (<n>/<m> clips)|skipped (up to date)>\t<path titles.json>` (`n` = số `titled`); stderr: model/host, header + nguồn, mỗi clip (title chọn, số option valid, số lần gọi, thời gian), tổng, cảnh báo retry/untitled; exit code CP2 D8.

## G10. Model / client

- `[titling]` là section riêng (CP1 §11). **Mặc định chốt (HUMAN LEAD 2026-09-26, sau đọc title v1/v2 hai model):** `qwen3:14b`, `think = false`, prompt `v2`; `temperature 0`, `seed 42`, `num_ctx 16384`, `timeout 600` s. Lý do: title v2 của `14b` tự nhiên, đúng kiểu viết hoa câu và đa dạng (9/13 câu hỏi), trong khi `30b` think on ép 13/13 thành câu hỏi, có câu gượng/lệch ý; `14b` think off nhanh ≈ 15× (≈ 35 s so với ≈ 540 s cho 13 clip). Title lệch ý hoặc bám lỗi nhận dạng caption (vd `k11` "trẻ 6 tuổi") xử lý ở CP9 (review/sửa title). Lúc soạn contract mặc định là `qwen3:30b` think on (số đo hai cấu hình ở dưới).
- `ChatClient`, `OllamaClient`, `ChatError`, `resolve_host` import từ `auto_short.selection.client`; `backoff_before` import từ `auto_short.selection.stage`; không sửa code CP5.

## Config `[titling]`

Xem `config.example.toml`: `model`, `think`, `temperature` (0–2), `seed` (≥ 0), `num_ctx` (≥ 512), `prompt_version` (`v1` | `v2`, mặc định `v2`), `n_options` (1–10), `min_chars` (≥ 1), `max_chars` (≥ `min_chars`), `retries` (≥ 0) — trong hash; `ollama_host`, `timeout` (> 0), `retry_backoff` (list số 0–3600) — thực thi. `[titling.header]`: `speaker`, `series`, `episode` (chuỗi; `episode` nhận cả số nguyên TOML; rỗng = không đặt), `title_pattern` (regex hợp lệ; rỗng = tắt), `lines` (1–3 chuỗi không rỗng, chỉ trường `{speaker}` `{series}` `{episode}`).

## Quyết định khi implement (không có trong task contract)

- Mixed retry (G6): `untitled` khi có ít nhất một response đúng schema, dù lần cuối là lỗi HTTP; `failed` chỉ khi mọi lần gọi lỗi G6. Lý do: P3 nói về "không có title hợp lệ" — model đã trả lời; lỗi tạm thời cuối không nên làm hỏng cả stage.
- Evidence so khớp **trọn từ** (chặt hơn "chuỗi con" thuần): tránh khớp nửa từ (`"ướng tùy tâm"`). Dấu câu thay bằng khoảng trắng (không xóa) để `"tâm,chuyển"` khớp `"tâm chuyển"`.
- Danh sách emoji/pictograph là các dải Unicode ở G5 (gồm mũi tên U+2190–21FF và ký hiệu kỹ thuật U+2300–23FF); không dùng category `So` để không loại nhầm `°`, `©`.
- `！` (fullwidth) cũng tính là dấu chấm than. URL nhận diện thêm tên miền trần với TLD phổ biến.
- Luật kiểm theo thứ tự cố định, ghi lý do đầu tiên trượt.
- Chuẩn hóa header: NFC + gộp khoảng trắng cho giá trị trường và dòng render.
- `RESPONSE_SCHEMA` không có `minItems`/`maxItems` (hằng, không phụ thuộc config); số option kiểm trong code.
- `prompt_sha256` tính trên template có chỗ trống `<<MAX_CHARS>>`/`<<N_OPTIONS>>` (như CP5 v3 với `<<HEAD_CUT_WORDS>>`).

## Đo thực tế — prompt v1 (2026-09-26, video test `rbjfCfFq3Dk`, Ollama 0.34.4, port 11437)

`clips.json` 13 clip (2 `head_cut`), prompt v1, `temperature 0`, `seed 42`, `num_ctx 16384`, `n_options 3`, `max_chars 60`. Không lần gọi nào lỗi/retry; không clip `untitled`. Header: `["HT.Tịnh Không", "Thập Thiện Nghiệp Đạo Kinh (tập 9)"]` (speaker từ config, series/episode từ metadata).

| Cấu hình | Wall (CLI) | Σ gọi AI | Gọi / clip | Token sinh | Prompt lớn nhất | Tổng token lớn nhất / gọi | Option valid | Invalid (lý do) | Titled |
|---|---|---|---|---|---|---|---|---|---|
| `qwen3:14b` think off | 34.2 s | 34.0 s | 1.8–6.4 s | 2.2k | 698 | 902 | 38/39 | 1 `too long` (62) | 13/13 |
| `qwen3:30b` think on (mặc định) | 543.3 s | 543.1 s | 29.2–55.0 s | 91.6k | 692 | 9838 (60 % `num_ctx`) | 36/39 | 3 `evidence not in clip text` | 13/13 |
| `qwen3:30b` think on, `--force` | 552.4 s | 552.1 s | 29.3–54.9 s | 94.0k | 692 | 9838 | 35/39 | 4 `evidence not in clip text` | 13/13 |

Title chọn (số ký tự) — ~15 từ đầu text clip:

| Clip | `qwen3:14b` think off | `qwen3:30b` think on | Text clip (đầu) |
|---|---|---|---|
| k01 | Tự Tính Như Huyễn Là Khởi Dụng Trong Kinh Kim Cang (50) | Thế Tôn dùng bất khả tư nghị giải thích chân tướng (50) | tự tính như Huyễn là nói nó khởi dụng khi khởi tác dụng ở trong … |
| k02 | Chân Tướng Sự Thật Không Thể Nói Ra Hoặc Tư Duy (47) | Bất Khả tư nghị không mơ hồ (27) | chân tướng sự thật này tuyệt đối không phải ngôn ngữ có thể nói ra … |
| k03 | Tâm Thiện Lành Tạo Tướng Mạo Từ Bi (34) | Người có tâm địa thiện lương thì tướng mạo từ bi (48) | nếu như là niệm thiện thì hiện tượng bên ngoài Điền trở nên rất tốt … |
| k04 | Hành Là Sát Na Không Dừng Nghỉ (30) | Niệm niệm không dừng trong A lại da thức (40) | tương đối khó hiểu hành là sát na không dùng trụ ý nghĩa sinh diệt … (đã bỏ "thì") |
| k05 | Tâm Pháp Chỉ Nói Một Điều Trong Kinh (36) | Sắc pháp nói 11 điều Tâm pháp nói một điều (42) | sáu Trần là sắc Thanh Hương Vị xúc Pháp 6 căn là mất thời buổi … |
| k06 | Biết rồi thì Phàm phu thành Phật trong một niệm (47) | Phàm phu thành Phật chỉ trong một niệm (38) | đại sư chương gia nói cho tôi biết cái chân tướng sự thật này biết … |
| k07 | Biến Hóa Khôn Lường Trong Bản Thân Chúng Ta (43) | Biến hóa khôn lường trong sáu cõi (33) | cần phải học tập theo Phật Long Vương là đại biểu cho chúng sanh trong … |
| k08 | Tập tính thành tự nhiên là dấu hiệu của nghiệp lực sâu nặng (59) | Nguyên do nghiệp chướng sâu nặng tự mình không thể biết (55) | chứng tỏ điều gì chứng tỏ tập tính đã thành tự nhiên rồi tập quán … |
| k09 | Tướng Tùy Tâm Chuyển Là Sự Thật (31) | Tướng và môi trường sống tùy tâm chuyển (39) | chúng ta thường thường nói Tướng Tùy Tâm chuyển lời nói này không sai chút … |
| k10 | Một Móng Tay Có 900 Ý Niệm Theo Kinh Phật (41) | Một cái móng tay có 900 ý nghĩ (30) | chúng ta liền hiểu được chúng ta từ sớm đến tối có bao nhiêu ý … (đã bỏ "thế là") |
| k11 | Buông Xả Vọng Tưởng Là Buông Xả Tướng (37) | Chỉ buông xả ngọn mà không buông xả gốc rễ (42) | chúng sanh 6 tuổi có phước đức không thể bàn đến mức độ của đức … |
| k12 | Người khiêm tốn cung kính mới có thành tựu (42) | Người khiêm tốn cung kính thành tựu (35) | cổ đức thường nói nhưng quý tự tri Chi Minh tự Bình nhất định phải … |
| k13 | Khởi Tâm Động Niệm Đều Là Tội Lỗi (33) | Khởi tâm động niệm đều là tội lỗi (33) | cho nên điều thứ nhất trong tình nghiệp Tam Phước là vô cùng quan trọng … |

- Độ dài title chọn: `14b` 30–59 ký tự (median 41), `30b` 27–55 (median 39); chỉ 5/13 title mỗi cấu hình ≤ 36 ký tự (ước lượng sức chứa 2 dòng ở cỡ chữ mẫu) — đa số cần 3 dòng hoặc thu nhỏ chữ (P1, CP7).
- `qwen3:14b` think off viết Hoa Mỗi Chữ ở 10/13 title chọn (và phần lớn alternatives) dù prompt yêu cầu kiểu câu — không có luật code bắt lỗi này (G5 chỉ chặn viết hoa toàn bộ). `qwen3:30b` theo đúng kiểu câu, trừ `k02` "Bất Khả tư nghị" (hoa không đều) và giữ lỗi nhận dạng `k04` "A lại da thức" (đúng: A-lại-da thức).
- Evidence bị loại (`30b`): model ghép/diễn đạt lại khi trích — `k12` "người này khiêm tốn cung kính chắc chắn thi đỗ" ghép hai chỗ không liền nhau (text có "người khiêm tốn cung kính" và "người này chắc chắn thi đỗ"); `k02` "không nghĩ thì chân tướng sự thật liền hiện tiền ngay" (text: "không nghĩ không bạn thì chân tướng…"); `k01` (`--force`) "bất khả tư nghị giải thích" (text: "bất khả tư nghị để giải thích"). `k12` chỉ còn 1/3 option valid. P2 hoạt động đúng; tỉ lệ invalid do evidence 3–4/39 (≈ 8–10 %), không clip nào thành `untitled`.
- Script kiểm độc lập trên `titles.json` thật (không import `auto_short`: sha256 canonical `clips.json`/`candidates.json`, header, thứ tự entry, text G3 tự dựng lại kể cả head cut, luật G5 cho title + alternatives, evidence trọn từ trong text): PASS cả ba lần.
- Chạy lại không đổi → `skip (up to date)` 0.15 s, không gọi AI, sha256 `titles.json` không đổi (`a8e07373…41ce2b8c8e`, lần chạy mặc định đầu).
- **Tất định:** `--force` cùng config (model đã nạp) → 12/13 clip giống hệt (title + alternatives); `k01` khác: title "Thế Tôn dùng bất khả tư nghị giải thích chân tướng" → "Bất khả tư nghị giải thích chân tướng sự thật" (alternative cũ lên làm title; option thứ ba mới bị loại vì evidence). Như CP5: cùng seed/temperature 0 không bảo đảm tất định tuyệt đối giữa các trạng thái server. (Khi đó) workspace cuối là kết quả lần `--force` (`qwen3:30b` think on, v1).
- `status` → `titling done`.

## Đo thực tế — prompt v2 (Sửa G4, 2026-09-26, cùng video/clip, port 11437)

Cùng `clips.json`, `temperature 0`, `seed 42`, `num_ctx 16384`, `n_options 3`, `max_chars 60`. Không lần gọi nào lỗi/retry; không clip `untitled`. Header như v1. (Trước lần đo, Ollama `127.0.0.1:11437` trả "empty reply" ~5 phút; lần chạy `14b` đầu `failed` đúng G6 — 3 lần thử, backoff 5/15 s, không artifact; chạy lại khi server lên.)

| Cấu hình | Wall (CLI) | Σ gọi AI | Gọi / clip | Token sinh | Prompt lớn nhất | Tổng token lớn nhất / gọi | Option valid | Invalid (lý do) | Titled | Title dạng câu hỏi |
|---|---|---|---|---|---|---|---|---|---|---|
| `qwen3:14b` think off, v2 | 35.8 s | 35.5 s | 1.6–9.0 s | 2.1k | 1008 | 1170 | 38/39 | 1 `evidence not in clip text` | 13/13 | 9/13 |
| `qwen3:30b` think on, v2 (mặc định, workspace) | 537.3 s | 537.1 s | 23.2–54.3 s | 88.9k | 1002 | 9862 (60 % `num_ctx`) | 34/39 | 3 `evidence not in clip text`, 2 `too long` (61) | 13/13 | 13/13 |

Title chọn (số ký tự), đặt cạnh v1 `qwen3:30b` (lần đo v1 đầu):

| Clip | v1 `30b` think on | v2 `30b` think on | v2 `14b` think off |
|---|---|---|---|
| k01 | Thế Tôn dùng bất khả tư nghị giải thích chân tướng (50) | Tại sao nghe Phật nói về sự thật mà vẫn khó hiểu? (49) | Tại sao nói tự tính như huyễn như mộng như bèo bọt? (51) |
| k02 | Bất Khả tư nghị không mơ hồ (27) | Không nghĩ, sự thật hiện ra ngay? (33) | Chân tướng sự thật không thể nói ra hay tưởng tượng (51) |
| k03 | Người có tâm địa thiện lương thì tướng mạo từ bi (48) | Tướng mạo từ bi từ tâm tốt, đáng sợ vì tâm xấu? (47) | Tâm thiện thì tướng mạo cũng từ bi (34) |
| k04 | Niệm niệm không dừng trong A lại da thức (40) | Tại sao niệm niệm không dừng khiến tâm chứa hành động? (54) | Hành là gì? Vì sao không ngừng nghỉ (35) |
| k05 | Sắc pháp nói 11 điều Tâm pháp nói một điều (42) | Vì sao Phật nói nhiều khi người mê nặng? (40) | Tâm pháp chỉ có một điều, sao lại nói 11 pháp? (46) |
| k06 | Phàm phu thành Phật chỉ trong một niệm (38) | Bình thường thành Phật chỉ trong một niệm? (42) | Biết rồi thì thành Phật chỉ trong một niệm (42) |
| k07 | Biến hóa khôn lường trong sáu cõi (33) | Tại sao suy nghĩ ta thay đổi không ngừng? (41) | Tại sao con người lại biến hóa khó lường như vậy? (49) |
| k08 | Nguyên do nghiệp chướng sâu nặng tự mình không thể biết (55) | Tại sao nguyên do nghiệp chướng sâu nặng ta không thể biết? (59) | Tập tính thành tự nhiên là do đâu? (34) |
| k09 | Tướng và môi trường sống tùy tâm chuyển (39) | Vì sao môi trường sống và cơ thể thay đổi theo tâm? (51) | Tâm thay đổi, thế giới cũng thay đổi (36) |
| k10 | Một cái móng tay có 900 ý nghĩ (30) | Một giây có bao nhiêu suy nghĩ? (31) | Một ngày bạn có bao nhiêu suy nghĩ? (35) |
| k11 | Chỉ buông xả ngọn mà không buông xả gốc rễ (42) | Chỉ buông xả cái ngọn có đủ không? (34) | Tại sao trẻ 6 tuổi lại có phước đức lớn đến vậy? (48) |
| k12 | Người khiêm tốn cung kính thành tựu (35) | Người khiêm tốn chắc chắn thi đỗ, người kiêu căng rớt? (54) | Không hiểu bản thân, làm sao tu học được? (41) |
| k13 | Khởi tâm động niệm đều là tội lỗi (33) | Tại sao suy nghĩ vì mình lại là tội lỗi? (40) | Mỗi suy nghĩ đều là tội lỗi? (28) |

- Độ dài title chọn: v2 `30b` 31–59 (median 42, 3/13 ≤ 36 ký tự); v2 `14b` 28–51 (median 41, 6/13 ≤ 36); v1 `30b` 27–55 (median 39, 5/13).
- v2 bớt thuật ngữ rõ rệt ở cả hai model ("A lại da thức", "bất khả tư nghị", "sắc pháp/tâm pháp" biến mất khỏi title `30b`). `14b` think off ở v2 viết hoa kiểu câu đúng ở 13/13 (v1: Hoa Mỗi Chữ 10/13).
- `30b` v2 đặt **mọi** title (13/13, cả alternatives) thành câu hỏi, vài câu gượng hoặc lệch ý: `k06` "Bình thường thành Phật…" (đoạn nói "phàm phu"), `k12` "Người khiêm tốn chắc chắn thi đỗ, người kiêu căng rớt?" (sát ví dụ trong đoạn nhưng dễ đọc thành hứa hẹn), `k04` còn "niệm niệm", `k08` 59 ký tự.
- `14b` v2 có title bám lỗi nhận dạng caption: `k11` "Tại sao trẻ 6 tuổi lại có phước đức lớn đến vậy?" (caption "chúng sanh 6 tuổi…", nhiều khả năng nhận dạng sai) — code không bắt được (evidence nguyên văn vẫn đúng).
- Evidence bị loại vẫn do model ghép/cắt chữ (`30b` `k01` "mộng bèo bọt", `k10`, `k12`; `14b` `k07`); 2 option `30b` quá dài 61 ký tự. `k12` `30b` chỉ còn 1/3 option valid.
- Script kiểm độc lập (như v1): PASS cả hai lần. Chạy lại không đổi → skip, không gọi AI, sha256 `titles.json` không đổi (`b97cb33b…927c4247`). `status` → `titling done`. (Khi đó) workspace: v2 + `qwen3:30b` think on.
- Model + prompt titling **đã chốt** (HUMAN LEAD 2026-09-26): `qwen3:14b` think off + v2 (G10, CP1 §11).
- (Khi đó) workspace là v2 + `qwen3:30b`. Sau khi chốt, chạy mặc định mới (`qwen3:14b` think off, v2): `run (config changed)`, 32.2 s, 13/13 titled, 38/39 option valid (1 `evidence not in clip text`, `k07`), không retry. Mảng `titles` **giống hệt** lần đo v2 `14b` ở trên (0/13 clip khác, cả title lẫn alternatives). Chạy lại → skip, sha256 `titles.json` không đổi (`de157694…08a85600`); script kiểm độc lập PASS; `status` → `titling done`. Workspace cuối: cấu hình mặc định đã chốt.
