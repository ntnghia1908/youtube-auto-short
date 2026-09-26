# CP5 — AI Clip Selection Contract

| Metadata | Value |
|---|---|
| Status | PROPOSED |
| Accepted by | — (B1–B10 duyệt cùng APPROVE TASK 2026-09-26; chờ review) |
| Checkpoint | CP5 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP5 |
| Task contract | `docs/tasks/CP5-selection.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §3, §5, §8, §10, §11; `docs/decisions/CP2-workspace-contract.md` D1–D8; `docs/decisions/CP4-analysis-contract.md` A7–A10 |

File này là **canonical owner** của window, prompt + versioning, map đề xuất AI về candidate, chọn cuối, validation và schema `clips.json` / `selection_log.json` mà CP6 (title), CP7 (render), CP9 (review) dùng lại. Nơi khác chỉ trỏ tới đây. Stage framework (manifest v1, skip/stale, config hash, CLI exit code) giữ nguyên theo `docs/decisions/CP2-workspace-contract.md`; `candidates.json` theo `docs/decisions/CP4-analysis-contract.md`. Thay đổi cần decision gate mới với HUMAN LEAD.

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

## B3. Prompt (version `prompt_version`, mặc định `"v1"`)

- Prompt là hằng trong `selection/prompt.py` (`PROMPTS[version] = (system, user template)`); nội dung đầy đủ ghi ở `selection_log.json`. **Đổi bất kỳ chữ nào của prompt phải thêm version mới**; `prompt_sha256` = sha256(`system + "\n\0\n" + template`) nằm trong `config_hash` (B9) nên prompt sửa không bị skip nhầm. `prompt_version` không có trong code → lỗi (exit 1, manifest không đổi).
- System prompt (tiếng Việt): nhiệm vụ đề xuất Short độc lập; mỗi đề xuất là dãy unit `first_unit`–`last_unit`; thời lượng = tổng thời lượng unit + ~1 s mỗi ranh giới giữa hai unit, bắt buộc 30–180 s, mục tiêu 60–90 s; **trọn một ý** (câu đầu tự đứng được, không mở bằng từ nối/từ chỉ ngược; câu cuối kết thúc ý; thà không đề xuất còn hơn cụt ý); caption không dấu câu, có thể sai chính tả, mép danh sách có thể rơi giữa ý; được phép chồng lấn; tối đa 12 đề xuất; trường output và cách chấm.
- User message mỗi window: `Video: <metadata.title | (không rõ)>`; dòng tóm tắt window (số unit, khoảng thời gian gốc, ranh giới trước/sau); mỗi unit một dòng `id | thời lượng s | ranh giới trước | text`:
  - thời lượng = thời lượng unit sau rút khoảng lặng, tính **đúng như CP4 A8**: `end − start − Σ trims` với `trims = plan_trims(start, end, silences, max_pause)` (cùng hàm, `silences.json`, `params.max_pause`), 1 chữ số thập phân. Vì unit bắt đầu/kết thúc đúng mép khoảng lặng ranh giới nên con số này cộng với ranh giới rút còn `max_pause` và 2 × `boundary_pad` cho `duration` candidate sai lệch ≤ 0.35 s (đo trên 1484 candidate video test);
  - ranh giới trước: `lặng x.x s` | `ngắt cứng (nhạc/nhãn hoặc lặng dài[ x.x s])` | `đầu nội dung`; unit đầu window con có thêm `(đầu danh sách)`.
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
 "params": {"max_clips": 25, "min_score": 7, "max_window_words": 2500, "retries": 2},
 "stats": {"windows": 11, "ai_calls": 10, "proposals": 82, "valid": 39, "eligible": 27, "selected": 25,
           "selected_seconds": 1058.53},
 "clips": [{"id": "k01", "candidate_id": "c00003", "source_start": 77.372, "source_end": 129.793,
            "source_duration": 52.421, "duration": 38.379, "in_target": false,
            "unit_ids": ["u0003", "u0006"], "segment_ids": ["s00016", "s00026"],
            "score": 9, "start_complete": true, "end_complete": true,
            "topic": "…", "reason": "…", "window": "w02"}]}
```

- `stats`: `windows` = số window gốc (không đếm window con); `ai_calls` = tổng số lần gọi kể cả retry; `proposals` = số đề xuất parse được; `valid` = map được candidate (sau gộp trùng); `eligible` = qua B6 (`selected` + `overlapped` + `over_limit`); `selected_seconds` = Σ `duration` clip.
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

- Mặc định `qwen3:14b`, `think = false` (P1, tạm cho tới khi HUMAN LEAD chốt), `temperature 0`, `seed 42`, `num_ctx 16384`, `timeout 600` s/request.
- Chạy lại cùng config với `--force` → so sánh `clips.json` (kết quả đo bên dưới). Model/`think` chốt ghi ở CP1 §11.

## Config `[selection]`

Xem `config.example.toml`: `model`, `think`, `temperature` (0–2), `seed` (≥ 0), `num_ctx` (≥ 512), `prompt_version`, `max_clips` (1–99), `min_score` (1–10), `max_window_words` (≥ 1), `retries` (≥ 0) — trong hash; `ollama_host`, `timeout` (> 0) — thực thi.

## Đo thực tế (2026-09-26, video test `rbjfCfFq3Dk`, Ollama 0.34.4 máy GPU)

Cùng `candidates.json` (195 unit, 1484 candidate, 11 window — đúng số unit `2, 4, 19, 40, 4, 2, 13, 27, 9, 26, 49`; w06 không có candidate → 10 lần gọi; không window nào bị chia ở `max_window_words = 2500`). Prompt `v1`, `temperature 0`, `seed 42`, `num_ctx 16384`; prompt lớn nhất ~3.1k token. Không lần gọi nào lỗi/retry.

| Cấu hình | Wall | Token sinh | Đề xuất | Valid | Eligible | Selected | Tổng thời lượng | `in_target` | Median clip |
|---|---|---|---|---|---|---|---|---|---|
| `qwen3:14b` think off (mặc định) | 120 s | 8.4k | 82 | 39 | 27 | **25** (chạm `max_clips`) | 1058.5 s | 1 | 39.2 s (30.2–61.4) |
| `qwen3:14b` think on | 305 s | 22.2k | 31 | 26 | 26 | 24 | 1206.2 s | 6 | 43.5 s (30.2–102.1) |
| `qwen3:30b` think off | 18 s | 70 | 0 | 0 | 0 | 0 | 0 | — | — |
| `qwen3:30b` think on (đo thêm) | 564 s | 91.1k | 14 | 14 | 14 | 13 | 779.7 s | 6 | 57.9 s (34.2–85.0) |

- Lý do loại chính của `14b` think off: 43/82 đề xuất không có candidate vì quá ngắn (ước lượng < 30 s — model hay đề xuất 1–2 unit); 12 `ineligible` (tự đánh giá cụt đầu/cuối hoặc score < 7). Think on: 5 quá ngắn, 2 chồng lấn. `30b` think on: mọi đề xuất hợp lệ, 1 chồng lấn.
- `qwen3:30b` trên máy GPU là bản chỉ-suy-luận: với `think: false` model vẫn viết suy luận vào `content` (thử không `format`: ~10k token suy luận); khi có `format` JSON schema, grammar ép trả ngay `{"clips": []}` cho mọi window → cấu hình này không dùng được.
- Script kiểm độc lập (map candidate, 7 trường chép khớp, không chồng lấn, ≤ 25, 30–180 s, không vượt hard break, log khớp `clips.json`): PASS cả bốn cấu hình.
- Reproducibility (`14b` think off): lần chạy đầu và lần chạy lại sau khi đổi config (model được nạp lại) cho `clips.json` **byte-identical**; chạy lại không đổi → skip 0.14 s, sha256 không đổi, không gọi AI. Hai lần `--force` liền sau (model đã nạp, cache prompt còn) giống nhau byte-identical nhưng **khác** hai lần đầu: 22/25 clip chung (16 cùng score/topic), 6 window có response khác, request giống hệt. Suy đoán: Ollama tái dùng KV cache của tiền tố prompt làm đổi số học → cùng seed/temperature 0 chưa đảm bảo tất định tuyệt đối giữa các trạng thái server. Ghi nhận, không che.
- Render thô (không phải CP7) mẫu mỗi cấu hình có áp `trims`: thời lượng file lệch `duration` +0.00–0.15 s.
- Chất lượng trọn ý: HUMAN LEAD nghe mẫu để chốt model + `think` (P1). Quan sát máy: `14b` think off đánh `start_complete = true` cho cả đoạn mở bằng "luôn luôn … cho nên" (`c00087`); `14b` think on có một `topic` tiếng Anh.
