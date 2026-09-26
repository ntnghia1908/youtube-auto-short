# CP5 — AI Clip Selection Contract

| Metadata | Value |
|---|---|
| Status | PROPOSED |
| Accepted by | — (B1–B10 duyệt cùng APPROVE TASK 2026-09-26; Sửa B3 (v2), chốt C2 và B11 HUMAN LEAD 2026-09-26; chờ review) |
| Checkpoint | CP5 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP5 |
| Task contract | `docs/tasks/CP5-selection.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §3, §5, §8, §10, §11; `docs/decisions/CP2-workspace-contract.md` D1–D8; `docs/decisions/CP4-analysis-contract.md` A7–A10 |

File này là **canonical owner** của window, prompt + versioning, map đề xuất AI về candidate, lọc từ nối câu đầu, chọn cuối, validation và schema `clips.json` / `selection_log.json` mà CP6 (title), CP7 (render), CP9 (review) dùng lại. Nơi khác chỉ trỏ tới đây. Stage framework (manifest v1, skip/stale, config hash, CLI exit code) giữ nguyên theo `docs/decisions/CP2-workspace-contract.md`; `candidates.json` theo `docs/decisions/CP4-analysis-contract.md`. Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/selection/` (`client.py`, `prompt.py`, `logic.py`, `stage.py`). Dữ kiện đo lúc soạn và tham số P1–P3: `docs/tasks/CP5-selection.md`.

## B1. Stage / artifact

- Stage `selection` (CP1 §8), subpackage `src/auto_short/selection/`.
- Artifact `work/<id>/clips.json` (trusted, qua validation B8) và `selection_log.json` (log AI: prompt, response thô, trạng thái từng đề xuất). Ghi atomic; `clips.json` không chứa timestamp tạo file (provenance ở manifest, CP2 D5). `selection_log.json` có thời gian gọi (không byte-stable).
- Số giây chép nguyên từ `candidates.json` (3 chữ số, CP4 A1).

## B2. Window

- Window = dãy unit liên tiếp giữa hai ranh giới không phải `silence` (hard break / content edge, CP4 A6–A7) — đúng miền candidate CP4 có thể nằm (A8). Id `w01`… theo thời gian.
- Window không có candidate → không gọi AI (vẫn ghi trong log với `ai_calls: []`).
- Window có tổng `words` > `max_window_words` (mặc định 2500) → chia thành window con `wNN.1`, `wNN.2`… chồng lấn: window con bắt đầu từ unit `s`, kéo dài tối đa sao cho ≤ `max_window_words`; window con kế tiếp bắt đầu tại unit đầu nhỏ nhất của các candidate chưa nằm trọn trong window con trước (không còn thì unit kế tiếp) → mọi candidate nằm trọn trong ít nhất một window con. Candidate nhiều từ hơn `max_window_words` → stage `failed`.
- Candidate của một window (con) = candidate nằm trọn trong nó; đề xuất trùng `candidate_id` gộp theo B4.

## B3. Prompt (version `prompt_version`, mặc định `"v2"`)

- Prompt là hằng trong `selection/prompt.py` (`PROMPTS[version] = (system, user template)`); nội dung đầy đủ ghi ở `selection_log.json`. **Đổi bất kỳ chữ nào của prompt phải thêm version mới**; `prompt_sha256` = sha256(`system + "\n\0\n" + template`) nằm trong `config_hash` (B9) nên prompt sửa không bị skip nhầm. `prompt_version` không có trong code → lỗi (exit 1, manifest không đổi).
- Version trong code: `v1` (bản đầu, giữ nguyên văn để so sánh; `prompt_sha256` `0ff963d1…4bf4d7c`) và `v2` (mặc định; Sửa B3 HUMAN LEAD 2026-09-26 sau đo v1). Mô tả dưới là v1; khác biệt của v2 ở mục **B3 v2**.
- System prompt v1 (tiếng Việt): nhiệm vụ đề xuất Short độc lập; mỗi đề xuất là dãy unit `first_unit`–`last_unit`; thời lượng = tổng thời lượng unit + ~1 s mỗi ranh giới giữa hai unit, bắt buộc 30–180 s, mục tiêu 60–90 s; **trọn một ý** (câu đầu tự đứng được, không mở bằng từ nối/từ chỉ ngược; câu cuối kết thúc ý; thà không đề xuất còn hơn cụt ý); caption không dấu câu, có thể sai chính tả, mép danh sách có thể rơi giữa ý; được phép chồng lấn; tối đa 12 đề xuất; trường output và cách chấm.
- User message mỗi window: `Video: <metadata.title | (không rõ)>`; dòng tóm tắt window (số unit, khoảng thời gian gốc, ranh giới trước/sau); mỗi unit một dòng `id | thời lượng s | ranh giới trước | text`:
  - thời lượng = thời lượng unit sau rút khoảng lặng, tính **đúng như CP4 A8**: `end − start − Σ trims` với `trims = plan_trims(start, end, silences, max_pause)` (cùng hàm, `silences.json`, `params.max_pause`), 1 chữ số thập phân. Vì unit bắt đầu/kết thúc đúng mép khoảng lặng ranh giới nên con số này cộng với ranh giới rút còn `max_pause` và 2 × `boundary_pad` cho `duration` candidate sai lệch ≤ 0.35 s (đo trên 1484 candidate video test);
  - ranh giới trước: `lặng x.x s` | `ngắt cứng (nhạc/nhãn hoặc lặng dài[ x.x s])` | `đầu nội dung`; unit đầu window con có thêm `(đầu danh sách)`.
- **B3 v2** (chỉ đổi text prompt + format dòng unit; map/chọn/schema không đổi):
  - Dòng unit: `id | từ X | đến Y | ranh giới trước | text`. `X`, `Y` là mốc trên "đồng hồ Short" tính từ unit đầu window (window con: từ unit đầu của nó): với unit thứ `i`, `X_i = Σ_{k<i} (d_k + min(gap_k, max_pause))`, `Y_i = X_i + d_i + 2·boundary_pad` (`d` = thời lượng unit sau trim như v1, `gap_k` = `break_after.seconds` của unit `k`; `max_pause`, `boundary_pad` từ `candidates.json` `params`). Khi đó `Y_b − X_a` = ước lượng `estimate_seconds` của đoạn `[a..b]` (B4), lệch `duration` candidate ≤ 0.35 s. Chọn dạng "từ/đến" thay cho một cột cộng dồn để model chỉ cần một phép trừ, không phải tra unit `a−1`.
  - System prompt v2: giải thích cách tính "thời lượng = đến(last_unit) − từ(first_unit)" kèm ví dụ, yêu cầu tính trước khi đề xuất, nhắc nối nhiều unit cho đủ 30 s; quy tắc câu đầu nghiêm hơn: first_unit mở bằng từ nối/từ chỉ ngược (danh sách mở rộng: "cho nên", "vì vậy", "thế nên", "thế là", "do đó", "còn", "và", "nhưng", "mà", "rồi", "thì", "cái này", "điều đó", "việc này", "như vậy", "ở đây") hoặc giữa câu thì `start_complete` **phải** false và nên chọn unit sớm hơn; tương tự cho câu cuối; `topic` bằng tiếng Việt; `reason` ghi thời lượng đã tính.
- Output: JSON theo `RESPONSE_SCHEMA` qua `format` của `/api/chat`: `{"clips": [{first_unit, last_unit, topic, reason, start_complete, end_complete, score}]}` (thứ tự property = thứ tự sinh: nhận xét trước điểm), `score` integer 1–10.
- Request: `POST <host>/api/chat`, `stream: false`, `think` theo config, `options = {temperature, seed, num_ctx}`.
- Client: Protocol `ChatClient.chat(model, messages, format, options, think) -> ChatResult`; implementation `OllamaClient` dùng `urllib.request` (CP1 §10). Host: env `OLLAMA_HOST` > config `[selection] ollama_host`; thiếu scheme thì thêm `http://`.

## B4. Map về candidate

- Đề xuất hợp lệ (`valid`) ⇔ `first_unit`, `last_unit` thuộc window, `first_unit` không sau `last_unit`, và tồn tại candidate nằm trong window có `unit_ids = [first_unit, last_unit]` (duy nhất theo CP4 A8; trùng → `failed`).
- Không map được → `rejected` với `reject_reason`: `unit not in window <w>: <ids>` | `last_unit before first_unit` | `no candidate with unit_ids [a, b] (~X s; must be 30-180 s after trims and pass the shot guard)` (X = ước lượng như B3). Không sửa/nới đề xuất, không sinh timestamp mới.
- Trùng `candidate_id` (trong một window hoặc giữa window con): giữ đề xuất `score` cao nhất, bằng nhau giữ cái đầu; cái còn lại `rejected` (`duplicate of proposal in <w>`).

## B5. Response lỗi

- Mỗi window tối đa `1 + retries` lần gọi (mặc định `retries = 2`). Lỗi được thử lại: HTTP lỗi, timeout, không kết nối được, envelope Ollama sai, content không phải JSON, sai schema (thiếu/sai kiểu trường, `score` ngoài 1–10, `clips` không phải mảng). Retry dùng **cùng** request (seed cố định) — hữu ích cho lỗi tạm thời; lỗi do model lặp lại sẽ lặp lại.
- Hết lượt → stage `failed`, `error` = `window <w>: <lỗi> (after N attempts)`; không để artifact (xóa cả hai file).

## B6. Chọn cuối (deterministic)

- Trước bước này chạy B11 (đề xuất bị lọc đã là `ineligible`).
- `eligible` = `valid` ∧ `start_complete` ∧ `end_complete` ∧ `score ≥ min_score` (mặc định 7); còn lại `ineligible` (lý do: `start not complete`, `end not complete`, `score < N`).
- Sắp: `score` giảm, `in_target` true trước, `source_start` tăng (rồi `source_end`, `candidate_id`); greedy nhận nếu không chồng lấn clip đã nhận (giao `[source_start, source_end]` > 0; chạm mép không tính); đủ `max_clips` (mặc định **25**) thì phần còn lại `over_limit`; chồng lấn → `overlapped` (`overlaps selected <candidate_id>`); nhận → `selected` (+ `clip_id` trong log).
- Clip sắp theo `source_start`, id `k01`… theo thứ tự đó (tên render CP7 `shorts/<clip_id>.mp4`, CP1 §2).
- Không có clip → stage `done`, `clips: []`, cảnh báo stderr (P3).

## B7. Schema v1

Thứ tự key cố định:

```json
// clips.json
{"schema_version": 1, "episode_id": "rbjfCfFq3Dk",
 "candidates_sha256": "<sha256 canonical JSON candidates.json>",
 "model": {"provider": "ollama", "name": "qwen3:14b", "think": false,
           "options": {"temperature": 0, "seed": 42, "num_ctx": 16384}},
 "prompt_version": "v1", "prompt_sha256": "<B3>",
 "params": {"max_clips": 25, "min_score": 7, "max_window_words": 2500, "retries": 2,
            "start_blocklist": ["cho nên", "vì vậy", …]},
 "stats": {"windows": 11, "ai_calls": 10, "proposals": 82, "valid": 39, "filtered_start": 3, "eligible": 27, "selected": 25,
           "selected_seconds": 1058.53},
 "clips": [{"id": "k01", "candidate_id": "c00003", "source_start": 77.372, "source_end": 129.793,
            "source_duration": 52.421, "duration": 38.379, "in_target": false,
            "unit_ids": ["u0003", "u0006"], "segment_ids": ["s00016", "s00026"],
            "score": 9, "start_complete": true, "end_complete": true,
            "topic": "…", "reason": "…", "window": "w02"}]}
```

- `stats`: `windows` = số window gốc (không đếm window con); `ai_calls` = tổng số lần gọi kể cả retry; `proposals` = số đề xuất parse được; `valid` = map được candidate (sau gộp trùng); `filtered_start` = số đề xuất valid bị B11 lọc; `eligible` = qua B6 (`selected` + `overlapped` + `over_limit`); `selected_seconds` = Σ `duration` clip.
- Clip chép `source_start`, `source_end`, `source_duration`, `duration`, `in_target`, `unit_ids`, `segment_ids` của candidate; `trims`/`text` không chép (CP7/CP9 tra `candidates.json` theo `candidate_id`/`unit_ids`). `window` = window (con) của đề xuất được giữ.

```json
// selection_log.json
{"schema_version": 1, "episode_id": "…", "candidates_sha256": "…", "model": {…}, "prompt_version": "v1",
 "prompt_sha256": "…", "system_prompt": "<toàn văn>", "response_format": {<RESPONSE_SCHEMA>},
 "stats": {<như clips.json>}, "unit_seconds": {"u0001": 2.925, …},
 "windows": [{"id": "w03", "parent": "w03", "unit_ids": ["u0007", "u0025"], "units": 19, "words": 464,
              "candidates": 140,
              "ai_calls": [{"attempt": 1, "seconds": 16.6,
                            "request": {"model": "…", "messages": [system, user], "format": {…},
                                        "options": {…}, "think": false, "stream": false},
                            "response": {"content": "<raw>", "thinking": null, "eval_count": 812,
                                         "prompt_eval_count": 1588, "total_duration": 16500000000,
                                         "done_reason": "stop"},
                            "error": null}],
              "proposals": [{"first_unit": "u0008", "last_unit": "u0009", "topic": "…", "reason": "…",
                             "start_complete": true, "end_complete": true, "score": 9, "window": "w03",
                             "status": "valid | rejected | ineligible | selected | overlapped | over_limit",
                             "candidate_id": "c00018", "reject_reason": null, "clip_id": "k02"}]}]}
```

`response` là `null` khi lỗi xảy ra trước khi có response (HTTP/timeout). Status `valid` chỉ là trạng thái trung gian; trong file đã ghi mọi đề xuất valid đều thành `ineligible` / `selected` / `overlapped` / `over_limit`.

## B11. Lọc từ nối câu đầu (HUMAN LEAD 2026-09-26, thêm trong CP5)

- Deterministic, trong code (`logic.filter_start`), chạy **sau** B4 (map + gộp trùng), **trước** B6.
- Với mỗi đề xuất `valid`: lấy `text` của unit đầu candidate (`unit_ids[0]`), chuẩn hóa NFC + lowercase + gộp khoảng trắng; nếu bắt đầu bằng một cụm trong `start_blocklist` (cụm cũng chuẩn hóa như vậy) **khớp trọn từ** — sau cụm là hết chuỗi hoặc ký tự không phải chữ/số (`(?!\w)` Unicode; vd "còn" không khớp "cồn", "conn"; "mà" không khớp "màu") — thì `ineligible`, `reject_reason = "start connector: <cụm>"` (nhiều cụm khớp → ghi cụm dài nhất). Không sửa/nới đề xuất, không đổi prompt.
- `start_blocklist` là config `[selection]` (list chuỗi không rỗng, vào `config_hash`, ghi ở `clips.json` `params`); mặc định = danh sách từ nối của prompt v2: "cho nên", "vì vậy", "thế nên", "thế là", "do đó", "còn", "và", "nhưng", "mà", "rồi", "thì", "cái này", "điều đó", "việc này", "như vậy", "ở đây". Danh sách rỗng → tắt lọc.
- Log stderr mỗi đề xuất bị lọc; `stats.filtered_start` đếm số bị lọc.
- Giới hạn đã biết: không bắt được câu mở giữa câu không có từ nối (vd "là lấy Hiếu thân…"), và cụm không có trong danh sách (vd "tại vì sao…").

## B8. Validation trước khi ghi (vi phạm → `failed`, lỗi code)

Số clip ≤ `max_clips`; id `k01`… liên tục theo thứ tự; `candidate_id` tồn tại và 7 trường chép khớp candidate; `duration` trong `[params.min_duration, params.max_duration]` của `candidates.json`; `unit_ids` tồn tại; `start_complete` ∧ `end_complete` ∧ `min_score ≤ score ≤ 10`; sắp theo `source_start`, không chồng lấn. `silences.json` phải khớp `candidates.json.silences_sha256` (nếu không → `failed`, chạy lại analysis). `candidates_sha256` tính từ chính input đã đọc.

## B9. Stage / resume / CLI

Dùng `run_stage` của CP2 nguyên trạng:

- Yêu cầu `analysis` = `done` và `candidates.json`, `silences.json`, `metadata.json` tồn tại; không có manifest → lỗi; analysis chưa done → stage `failed` + `error`, không artifact, không gọi AI.
- `inputs` = `candidates.json`, `metadata.json` (relative + sha256). `silences.json` không nằm trong `inputs` vì nó được khóa qua `candidates.json.silences_sha256` (kiểm ở B8).
- `config_hash` = `[selection]` `model`, `think`, `temperature`, `seed`, `num_ctx`, `prompt_version`, `max_clips`, `min_score`, `max_window_words`, `retries` + `prompt_sha256`. **Không** gồm `ollama_host`, `timeout` (thực thi). Đổi config stage khác không chạy lại selection.
- `artifacts` = `clips.json`, `selection_log.json`; lỗi → cả hai bị xóa.
- Chạy lại selection → downstream stale; analysis chạy lại → selection stale.
- CLI `auto-short selection <episode_id> [--force] [--config PATH]` — stdout `<episode_id>\t<selected (<n> clips)|skipped (up to date)>\t<path clips.json>`; stderr: model/host, mỗi window (số unit, từ, candidate, đề xuất, valid, thời gian), tổng `windows/ai_calls/proposals/valid/eligible/selected/selected_seconds`, cảnh báo retry/không clip; exit code theo CP2 D8.

## B10. Model / reproducibility

- **Mặc định C2** (HUMAN LEAD 2026-09-26, sau nghe mẫu v1/v2; CP1 §11): `qwen3:30b`, `think = true`, `prompt_version = "v2"`, `temperature 0`, `seed 42`, `num_ctx 32768`, `timeout 600` s/request. `num_ctx` nâng từ 16384 vì 30b-think dùng tới 14.9k token/lần gọi (prompt ~3k + suy luận ~9–12k) — 91 % của 16384; 32768 cho dư. Lần gọi lâu nhất đo được 81 s ≪ `timeout`.
- Chạy lại cùng config với `--force` → so sánh `clips.json` (kết quả đo bên dưới). Model/`think` chốt ghi ở CP1 §11.

## Config `[selection]`

Xem `config.example.toml`: `model`, `think`, `prompt_version` (`v1` | `v2`, mặc định `v2`), `temperature` (0–2), `seed` (≥ 0), `num_ctx` (≥ 512), `max_clips` (1–99), `min_score` (1–10), `max_window_words` (≥ 1), `retries` (≥ 0), `start_blocklist` (list chuỗi không rỗng; rỗng = tắt B11) — trong hash; `ollama_host`, `timeout` (> 0) — thực thi.

## Đo thực tế (2026-09-26, video test `rbjfCfFq3Dk`, Ollama 0.34.4 máy GPU)

Cùng `candidates.json` (195 unit, 1484 candidate, 11 window — đúng số unit `2, 4, 19, 40, 4, 2, 13, 27, 9, 26, 49`; w06 không có candidate → 10 lần gọi; không window nào bị chia ở `max_window_words = 2500`). `temperature 0`, `seed 42`, `num_ctx 16384`; prompt lớn nhất ~3.1k token. Không lần gọi nào lỗi/retry.

Wall = tổng thời gian các lần gọi AI. "Không có candidate" = đề xuất bị loại vì không map được (đều do ước lượng < 30 s). Median kèm (min–max).

| Cấu hình | Prompt | Wall | Token sinh | Đề xuất | Không có candidate | Valid | Eligible | Selected | Tổng thời lượng | `in_target` | Median clip |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `qwen3:14b` think off | v1 | 120 s | 8.4k | 82 | 43 | 39 | 27 | **25** (chạm max) | 1058.5 s | 1 | 39.2 s (30.2–61.4) |
| `qwen3:14b` think off (mặc định) | **v2** | 113 s | 7.7k | 72 | 25 | 47 | 42 | **25** (chạm max) | 1407.4 s | 9 | 50.4 s (30.3–111.5) |
| `qwen3:14b` think on | v1 | 305 s | 22.2k | 31 | 5 | 26 | 26 | 24 | 1206.2 s | 6 | 41.3 s (30.2–102.1) |
| `qwen3:14b` think on | v2 | 405 s | 29.3k | 33 | 0 | 33 | 24 | 17 | 918.8 s | 2 | 54.0 s (30.4–111.6) |
| `qwen3:30b` think off | v1 | 18 s | 0.07k | 0 | 0 | 0 | 0 | 0 | 0 | — | — |
| `qwen3:30b` think on | v1 | 564 s | 91.1k | 14 | 0 | 14 | 14 | 13 | 779.7 s | 6 | 57.9 s (34.2–85.0) |
| `qwen3:30b` think on | v2 | 450 s | 72.0k | 20 | 0 | 20 | 20 | 19 | 1111.0 s | 10 | 61.4 s (31.3–83.6) |

- v2 so với v1: `14b` think off giảm đề xuất quá ngắn 43 → 25, clip dài hơn (median 39 → 50 s, `in_target` 1 → 9), vẫn chạm 25 clip; `14b` think on hết đề xuất quá ngắn nhưng tự đánh giá khắt khe hơn (6 `start not complete`) → 17 clip; `30b` think on nhiều đề xuất hơn (14 → 20), 19 clip, median 61 s. `qwen3:30b` think off không đo lại ở v2 (không dùng được, xem dưới).
- Câu mở đầu (kiểm từ vựng: unit đầu của clip được chọn bắt đầu bằng từ nối/từ chỉ ngược; không bắt được trường hợp mở giữa câu không có từ nối): v1 — `14b` off 3/25, `14b` on 3/24, `30b` on 1/13; v2 — `14b` off 2/25, `14b` on 3/17, `30b` on 2/19. v2 **không** giảm rõ lỗi này; ví dụ `c01293`/`c01292` ("cho nên điều thứ nhất…") được chọn ở 5/6 lần đo. Ngoài ra có clip mở giữa câu không có từ nối (vd v2 `14b` off `c01212` "là lấy Hiếu thân Tôn Sư…").
- Lý do loại chính (v1) của `14b` think off: 43/82 đề xuất không có candidate vì quá ngắn (ước lượng < 30 s — model hay đề xuất 1–2 unit); 12 `ineligible` (tự đánh giá cụt đầu/cuối hoặc score < 7). Think on: 5 quá ngắn, 2 chồng lấn. `30b` think on: mọi đề xuất hợp lệ, 1 chồng lấn.
- `qwen3:30b` trên máy GPU là bản chỉ-suy-luận: với `think: false` model vẫn viết suy luận vào `content` (thử không `format`: ~10k token suy luận); khi có `format` JSON schema, grammar ép trả ngay `{"clips": []}` cho mọi window → cấu hình này không dùng được.
- Script kiểm độc lập (map candidate, 7 trường chép khớp, không chồng lấn, ≤ 25, 30–180 s, không vượt hard break, log khớp `clips.json`): PASS cả bảy lần đo.
- Reproducibility (`14b` think off): lần chạy đầu và lần chạy lại sau khi đổi config (model được nạp lại) cho `clips.json` **byte-identical**; chạy lại không đổi → skip 0.14 s, sha256 không đổi, không gọi AI. Hai lần `--force` liền sau (model đã nạp, cache prompt còn) giống nhau byte-identical nhưng **khác** hai lần đầu: 22/25 clip chung (16 cùng score/topic), 6 window có response khác, request giống hệt. Suy đoán: Ollama tái dùng KV cache của tiền tố prompt làm đổi số học → cùng seed/temperature 0 chưa đảm bảo tất định tuyệt đối giữa các trạng thái server. Ghi nhận, không che. v2 `14b` think off: lần đo và lần chạy mặc định sau đổi config (model nạp lại) byte-identical; chạy lại → skip.
- Render thô (không phải CP7) mẫu mỗi cấu hình có áp `trims`: thời lượng file lệch `duration` +0.00–0.15 s.
- Chất lượng trọn ý: HUMAN LEAD nghe mẫu để chốt model + `think` (P1). Quan sát máy: `14b` think off đánh `start_complete = true` cho cả đoạn mở bằng "luôn luôn … cho nên" (`c00087`); `14b` think on có một `topic` tiếng Anh.

### B11 — áp lại offline trên response đã lưu (không gọi AI)

Chạy lại B4 → B11 → B6 bằng code hiện hành trên response thô trong `selection_log.json` của các lần đo trên (cùng đề xuất AI, chỉ thêm bộ lọc). Mọi clip được chọn trước đây mở bằng cụm trong danh sách đều bị loại; không có kết quả lọc sai (kiểm tay các cụm khớp).

| Lần đo | Bị lọc (valid) | Selected trước → sau | Tổng thời lượng sau | Bị bỏ khỏi kết quả | Thêm vào |
|---|---|---|---|---|---|
| `30b` think on v2 (C2) | 1: `c00445` "cho nên" | 19 → 18 | 1069.9 s (median 61.7, `in_target` 10) | `c00445` | — |
| `14b` think off v2 | 5 ("cho nên" ×5) | 25 → 25 | 1385.5 s | `c00445`, `c01293` | `c00454`, `c00877` |
| `14b` think on v2 | 6 ("cho nên" ×4, "thế là" ×2) | 17 → 15 | 797.6 s | `c00497`, `c00936`, `c01293` | `c00504` |
| `30b` think on v1 | 1: `c01293` "cho nên" | 13 → 12 | 713.8 s | `c01293` | — |

Còn lọt (ngoài danh sách / không có từ nối): C2 `c01308` "Tại vì sao có hiện tượng này…"; `14b` v2 `c01212` "là lấy Hiếu thân Tôn Sư…".

Lần đầu chạy C2 + B11 (2026-09-26 ~14:00Z) Ollama `127.0.0.1:11435` reset mọi kết nối (> 10 phút); stage ghi `failed` đúng B5 (3 lần thử, không artifact). Chạy lại sau khi Ollama lên lại:

### C2 + B11 — đo thật (mặc định hiện hành: `qwen3:30b`, think on, v2, `num_ctx 32768`, `start_blocklist` mặc định)

| Lần | Wall | Token sinh | Đề xuất | Valid | Lọc B11 | Eligible | Selected | Tổng thời lượng | `in_target` | Median |
|---|---|---|---|---|---|---|---|---|---|---|
| C2 v2 không lọc (`num_ctx 16384`, bảng trên) | 450 s | 72.0k | 20 | 20 | — | 20 | 19 | 1111.0 s | 10 | 61.4 s (31.3–83.6) |
| C2 + B11, lần 1 | 447 s (7 m 27 s) | 72.0k | 20 | 20 | 1 | 19 | 18 | 1069.9 s | 10 | 61.7 s (31.3–83.6) |
| C2 + B11, `--force` ngay sau | 460 s (7 m 40 s) | 68.0k | 17 | 17 | 0 | 17 | 16 | 1090.7 s | 9 | 66.5 s |

- Lần 1: response **trùng từng token** với lần đo C2 không lọc (cùng `eval_count` mọi window, cùng đề xuất/score) dù `num_ctx` đổi 16384 → 32768; B11 lọc đúng `c00445` (u0059–u0061, "cho nên ở trong đây nói là…") như dự đoán offline, không clip nào khác đổi. `prompt_eval_count` lớn nhất 3806; tổng token lớn nhất một lần gọi 14732 (45 % của 32768); thời gian từng lần gọi (w01…w11, bỏ w06): 38, 21, 50, 46, 19, 56, 45, 33, 78, 61 s.
- Script kiểm độc lập: PASS cả hai lần. Kiểm câu mở đầu (danh sách từ nối mở rộng của script, rộng hơn `start_blocklist`): lần 1 còn 1/18 (`c01308` "Tại vì sao có hiện tượng này…" — "tại vì" không có trong `start_blocklist`); `--force` còn 2/16 (`c01308`, `c00279` "Tại vì sao phải tu thiện nghiệp…"). Không clip nào mở bằng cụm trong `start_blocklist`.
- Chạy lại không đổi → skip 0.14 s, sha256 `clips.json` không đổi, không gọi AI.
- **Tất định:** `--force` ngay sau (model đã nạp) cho response khác ở 7/10 window (request giống hệt): chỉ 9/18 clip chung (6 cùng score/topic); 17 đề xuất, 16 clip. Với 30b-think mức khác biệt giữa các lần chạy lớn hơn nhiều so với `14b` think off (22/25 chung) — chuỗi suy luận dài khuếch đại khác biệt số học. Hai lần chạy có trạng thái server tương tự (model vừa nạp lại) cho kết quả trùng (C2 không lọc và C2 + B11 lần 1). Ghi nhận, không che: `clips.json` của C2 **không tái lập được** giữa các lần `--force`; review (CP9) nên xem `clips.json` hiện có là một mẫu, không phải kết quả duy nhất.
- Workspace cuối là kết quả lần `--force` (mặc định hiện hành, `selection done`).
