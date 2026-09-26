# CP5 — AI Clip Selection Contract

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | — (B1–B10 duyệt cùng APPROVE TASK 2026-09-26; Sửa B3 (v2), chốt C2, Sửa B5 (backoff), port 11437, Thay B11 (head cut) + prompt v3 HUMAN LEAD 2026-09-26; review ACCEPTED; HUMAN LEAD nghe điểm cắt: ổn, `head_cut_pad` 0.1 giữ nguyên; segment không có word timing: để nguyên, không nội suy) |
| Checkpoint | CP5 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP5 |
| Task contract | `docs/tasks/CP5-selection.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §3, §5, §8, §10, §11; `docs/decisions/CP2-workspace-contract.md` D1–D8; `docs/decisions/CP4-analysis-contract.md` A7–A10 |

File này là **canonical owner** của window, prompt + versioning, map đề xuất AI về candidate, cắt từ nối đầu clip (head cut), chọn cuối, validation và schema `clips.json` / `selection_log.json` mà CP6 (title), CP7 (render), CP9 (review) dùng lại. Nơi khác chỉ trỏ tới đây. Stage framework (manifest v1, skip/stale, config hash, CLI exit code) giữ nguyên theo `docs/decisions/CP2-workspace-contract.md`; `candidates.json` theo `docs/decisions/CP4-analysis-contract.md`. Thay đổi cần decision gate mới với HUMAN LEAD.

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

## B3. Prompt (version `prompt_version`, mặc định `"v3"`)

- Prompt là hằng trong `selection/prompt.py` (`PROMPTS[version] = (system, user template)`); nội dung đầy đủ ghi ở `selection_log.json`. **Đổi bất kỳ chữ nào của prompt phải thêm version mới**; `prompt_sha256` = sha256(`system + "\n\0\n" + template`) nằm trong `config_hash` (B9) nên prompt sửa không bị skip nhầm. `prompt_version` không có trong code → lỗi (exit 1, manifest không đổi).
- Version trong code: `v1` (bản đầu, giữ nguyên văn để so sánh; `prompt_sha256` `0ff963d1…4bf4d7c`) , `v2` (Sửa B3 HUMAN LEAD 2026-09-26 sau đo v1; `95c13065…8b5c15a`) và `v3` (mặc định; cùng B11 head cut). v1, v2 giữ nguyên văn để so sánh. Mô tả dưới là v1; khác biệt của v2/v3 ở mục **B3 v2**, **B3 v3**.
- System prompt v1 (tiếng Việt): nhiệm vụ đề xuất Short độc lập; mỗi đề xuất là dãy unit `first_unit`–`last_unit`; thời lượng = tổng thời lượng unit + ~1 s mỗi ranh giới giữa hai unit, bắt buộc 30–180 s, mục tiêu 60–90 s; **trọn một ý** (câu đầu tự đứng được, không mở bằng từ nối/từ chỉ ngược; câu cuối kết thúc ý; thà không đề xuất còn hơn cụt ý); caption không dấu câu, có thể sai chính tả, mép danh sách có thể rơi giữa ý; được phép chồng lấn; tối đa 12 đề xuất; trường output và cách chấm.
- User message mỗi window: `Video: <metadata.title | (không rõ)>`; dòng tóm tắt window (số unit, khoảng thời gian gốc, ranh giới trước/sau); mỗi unit một dòng `id | thời lượng s | ranh giới trước | text`:
  - thời lượng = thời lượng unit sau rút khoảng lặng, tính **đúng như CP4 A8**: `end − start − Σ trims` với `trims = plan_trims(start, end, silences, max_pause)` (cùng hàm, `silences.json`, `params.max_pause`), 1 chữ số thập phân. Vì unit bắt đầu/kết thúc đúng mép khoảng lặng ranh giới nên con số này cộng với ranh giới rút còn `max_pause` và 2 × `boundary_pad` cho `duration` candidate sai lệch ≤ 0.35 s (đo trên 1484 candidate video test);
  - ranh giới trước: `lặng x.x s` | `ngắt cứng (nhạc/nhãn hoặc lặng dài[ x.x s])` | `đầu nội dung`; unit đầu window con có thêm `(đầu danh sách)`.
- **B3 v2** (chỉ đổi text prompt + format dòng unit; map/chọn/schema không đổi):
  - Dòng unit: `id | từ X | đến Y | ranh giới trước | text`. `X`, `Y` là mốc trên "đồng hồ Short" tính từ unit đầu window (window con: từ unit đầu của nó): với unit thứ `i`, `X_i = Σ_{k<i} (d_k + min(gap_k, max_pause))`, `Y_i = X_i + d_i + 2·boundary_pad` (`d` = thời lượng unit sau trim như v1, `gap_k` = `break_after.seconds` của unit `k`; `max_pause`, `boundary_pad` từ `candidates.json` `params`). Khi đó `Y_b − X_a` = ước lượng `estimate_seconds` của đoạn `[a..b]` (B4), lệch `duration` candidate ≤ 0.35 s. Chọn dạng "từ/đến" thay cho một cột cộng dồn để model chỉ cần một phép trừ, không phải tra unit `a−1`.
  - System prompt v2: giải thích cách tính "thời lượng = đến(last_unit) − từ(first_unit)" kèm ví dụ, yêu cầu tính trước khi đề xuất, nhắc nối nhiều unit cho đủ 30 s; quy tắc câu đầu nghiêm hơn: first_unit mở bằng từ nối/từ chỉ ngược (danh sách mở rộng: "cho nên", "vì vậy", "thế nên", "thế là", "do đó", "còn", "và", "nhưng", "mà", "rồi", "thì", "cái này", "điều đó", "việc này", "như vậy", "ở đây") hoặc giữa câu thì `start_complete` **phải** false và nên chọn unit sớm hơn; tương tự cho câu cuối; `topic` bằng tiếng Việt; `reason` ghi thời lượng đã tính.
- **B3 v3** (HUMAN LEAD 2026-09-26, cùng Thay B11): user message và format dòng unit như v2. System prompt như v2 nhưng thêm đoạn "TỰ ĐỘNG CẮT TỪ NỐI Ở ĐẦU": các từ nối thuần ở đầu `first_unit` — liệt kê từ `[selection] head_cut_words` (điền vào chỗ `<<HEAD_CUT_WORDS>>`; rỗng → "(không có)") — sẽ được hệ thống tự cắt, kể cả nhiều từ liên tiếp; AI đánh giá `start_complete` trên câu đầu **sau khi bỏ** các từ đó và không cần tránh `first_unit` vì chúng. Bỏ quy tắc ép `start_complete = false` theo danh sách từ của v2; giữ yêu cầu chung câu đầu tự đứng được (ví dụ chỉ ngược "cái này", "điều đó", "như vậy" không rõ chỉ gì → false). `prompt_sha256` tính trên template (có chỗ trống); danh sách `head_cut_words` nằm trong `config_hash` nên text đã render được định danh đầy đủ; `system_prompt` trong log là bản đã render.
- Output: JSON theo `RESPONSE_SCHEMA` qua `format` của `/api/chat`: `{"clips": [{first_unit, last_unit, topic, reason, start_complete, end_complete, score}]}` (thứ tự property = thứ tự sinh: nhận xét trước điểm), `score` integer 1–10.
- Request: `POST <host>/api/chat`, `stream: false`, `think` theo config, `options = {temperature, seed, num_ctx}`.
- Client: Protocol `ChatClient.chat(model, messages, format, options, think) -> ChatResult`; implementation `OllamaClient` dùng `urllib.request` (CP1 §10). Host: env `OLLAMA_HOST` > config `[selection] ollama_host`; thiếu scheme thì thêm `http://`.

## B4. Map về candidate

- Đề xuất hợp lệ (`valid`) ⇔ `first_unit`, `last_unit` thuộc window, `first_unit` không sau `last_unit`, và tồn tại candidate nằm trong window có `unit_ids = [first_unit, last_unit]` (duy nhất theo CP4 A8; trùng → `failed`).
- Không map được → `rejected` với `reject_reason`: `unit not in window <w>: <ids>` | `last_unit before first_unit` | `no candidate with unit_ids [a, b] (~X s; must be 30-180 s after trims and pass the shot guard)` (X = ước lượng như B3). Không sửa/nới đề xuất, không sinh timestamp mới.
- Trùng `candidate_id` (trong một window hoặc giữa window con): giữ đề xuất `score` cao nhất, bằng nhau giữ cái đầu; cái còn lại `rejected` (`duplicate of proposal in <w>`).

## B5. Response lỗi

- **Backoff (Sửa B5, HUMAN LEAD 2026-09-26):** chờ `retry_backoff[0]` = 5 s trước lần thử 2, `retry_backoff[1]` = 15 s trước lần thử 3; lần sau nữa (khi `retries` > 2) lặp giá trị cuối; không chờ trước lần đầu, không chờ sau lần cuối. `retry_backoff` là tham số thực thi `[selection]` (list số 0–3600 s, rỗng = thử lại ngay), **không** vào `config_hash`. Thời gian chờ ghi ở `ai_calls[].backoff_seconds`; hàm sleep inject được (test không chờ thật).
- Mỗi window tối đa `1 + retries` lần gọi (mặc định `retries = 2`). Lỗi được thử lại: HTTP lỗi, timeout, không kết nối được, envelope Ollama sai, content không phải JSON, sai schema (thiếu/sai kiểu trường, `score` ngoài 1–10, `clips` không phải mảng). Retry dùng **cùng** request (seed cố định) — hữu ích cho lỗi tạm thời; lỗi do model lặp lại sẽ lặp lại.
- Hết lượt → stage `failed`, `error` = `window <w>: <lỗi> (after N attempts)`; không để artifact (xóa cả hai file).

## B6. Chọn cuối (deterministic)

- Trước bước này chạy B11 (head cut); B6 dùng thời gian **sau cắt** (`source_start`, `duration`, `in_target`) để sắp xếp và xét chồng lấn; đề xuất quá ngắn sau cắt đã là `ineligible`.
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
 "model": {"provider": "ollama", "name": "qwen3:30b", "think": true,
           "options": {"temperature": 0, "seed": 42, "num_ctx": 32768}},
 "prompt_version": "v3", "prompt_sha256": "<B3>",
 "params": {"max_clips": 25, "min_score": 7, "max_window_words": 2500, "retries": 2,
            "head_cut_words": ["cho nên", "vì vậy", …], "head_cut_pad": 0.1},
 "stats": {"windows": 11, "ai_calls": 10, "proposals": 14, "valid": 14, "eligible": 14, "selected": 13,
           "selected_seconds": 826.196, "head_cut": 2},
 "clips": [{"id": "k10", "candidate_id": "c00868", "source_start": 2531.06, "source_end": 2621.91,
            "source_duration": 90.85, "duration": 67.47, "in_target": true,
            "unit_ids": ["u0133", "u0136"], "segment_ids": ["s00571", "s00595"],
            "head_cut": {"words": "thế là", "original_start": 2530.19},
            "score": 9, "start_complete": true, "end_complete": true,
            "topic": "…", "reason": "…", "window": "w10"}]}
```

- `stats`: `windows` = số window gốc (không đếm window con); `ai_calls` = tổng số lần gọi kể cả retry; `proposals` = số đề xuất parse được; `valid` = map được candidate (sau gộp trùng); `eligible` = qua B6 (`selected` + `overlapped` + `over_limit`); `selected_seconds` = Σ `duration` clip (sau cắt); `head_cut` = số clip được chọn có head cut.
- Clip chép `source_start`, `source_end`, `source_duration`, `duration`, `in_target`, `unit_ids`, `segment_ids` của candidate — trừ khi có `head_cut` (B11): khi đó `source_start` là điểm cắt và `source_duration`, `duration`, `in_target` tính lại; `head_cut` = `null` hoặc `{"words", "original_start"}` (`original_start` = `source_start` của candidate); `trims`/`text` không chép (CP7/CP9 tra `candidates.json` theo `candidate_id`/`unit_ids`). `window` = window (con) của đề xuất được giữ.

```json
// selection_log.json
{"schema_version": 1, "episode_id": "…", "candidates_sha256": "…", "model": {…}, "prompt_version": "v1",
 "prompt_sha256": "…", "system_prompt": "<toàn văn>", "response_format": {<RESPONSE_SCHEMA>},
 "stats": {<như clips.json>}, "unit_seconds": {"u0001": 2.925, …},
 "windows": [{"id": "w03", "parent": "w03", "unit_ids": ["u0007", "u0025"], "units": 19, "words": 464,
              "candidates": 140,
              "ai_calls": [{"attempt": 1, "backoff_seconds": 0.0, "seconds": 16.6,
                            "request": {"model": "…", "messages": [system, user], "format": {…},
                                        "options": {…}, "think": false, "stream": false},
                            "response": {"content": "<raw>", "thinking": null, "eval_count": 812,
                                         "prompt_eval_count": 1588, "total_duration": 16500000000,
                                         "done_reason": "stop"},
                            "error": null}],
              "proposals": [{"first_unit": "u0008", "last_unit": "u0009", "topic": "…", "reason": "…",
                             "start_complete": true, "end_complete": true, "score": 9, "window": "w03",
                             "status": "valid | rejected | ineligible | selected | overlapped | over_limit",
                             "candidate_id": "c00018", "reject_reason": null,
                             "head_cut": null | {"words", "original_start", "source_start", "method": "silence | word",
                                                 "dropped_until": <start từ giữ lại đầu tiên>},
                             "head_cut_note": null | "<vì sao không cắt>", "clip_id": "k02"}]}]}
```

`response` là `null` khi lỗi xảy ra trước khi có response (HTTP/timeout). Status `valid` chỉ là trạng thái trung gian; trong file đã ghi mọi đề xuất valid đều thành `ineligible` / `selected` / `overlapped` / `over_limit`.

## B11. Head cut — cắt từ nối ở đầu clip (Thay B11, HUMAN LEAD 2026-09-26)

Thay bộ lọc loại đề xuất theo `start_blocklist` (bản trước, đã gỡ): B11 **không** loại đề xuất/candidate mà lùi đầu clip vào trong segment đầu để bỏ từ nối thuần (CP1 §5 sửa đổi CP5). Deterministic, trong code (`logic.head_cut`, `cut_candidate`, `apply_head_cuts`), chạy **sau** B4 (map + gộp trùng), **trước** B6.

- **Khớp:** lấy `words` (word timing, `transcript.json`) của segment đầu candidate (`segment_ids[0]`). Token chuẩn hóa NFC + lowercase, bỏ dấu câu hai đầu; cụm trong `head_cut_words` so khớp **trọn từ** theo token liên tiếp (cụm nhiều từ = nhiều token; "mà" không khớp "màu"); khớp xong lặp lại với token kế tiếp (vd "thế là còn" = "thế là" + "còn"), cụm dài trước. `head_cut_words` mặc định: "cho nên", "vì vậy", "thế nên", "thế là", "do đó", "và", "nhưng", "mà", "rồi", "còn", "thì". Cụm chỉ ngược / từ để hỏi ("cái này", "điều đó", "tại vì sao"…) không xử lý riêng — chỉ còn đánh giá của AI (B3 v3).
- **Không cắt (ghi `head_cut_note` + log):** segment không có word timing; mọi từ của segment đầu là từ nối; điểm cắt không sau `source_start` hoặc không trước `source_end` của candidate.
- **Điểm cắt:** gọi `w_d` = từ nối cuối cùng bị bỏ, `w_k` = từ giữ lại đầu tiên. Nếu có khoảng lặng (`silences.json`) giao `[w_d.start, w_k.start)` **và bắt đầu sau `source_start` của candidate** → cắt tại `max(silence.end − head_cut_pad, silence.start)` (lấy khoảng lặng muộn nhất), `method = "silence"`; không có → `w_k.start − head_cut_pad`, `method = "word"`. `head_cut_pad` mặc định 0.1 s. Khoảng lặng ranh giới của chính clip (bắt đầu trước `source_start`) bị loại vì timing caption của từ đầu thường sớm hơn âm thật, khiến khoảng lặng ấy giao `w_d` dù nằm **trước** từ nối (quyết định khi implement, đo thật `c00457`: nếu dùng nó thì cắt tại 1250.19 và vẫn giữ "thì").
- **Clip sau cắt:** giữ `candidate_id`, `source_end`, `unit_ids`, `segment_ids`; `source_start` = điểm cắt; `source_duration` = `source_end − source_start`; `duration` = `source_duration − Σ` phần của `trims` candidate nằm trong `[source_start, source_end]` (trim bị cắt ngang chỉ tính phần còn lại); `in_target` theo `params.target_min/max` của `candidates.json`; `head_cut = {"words": "<cụm đã bỏ>", "original_start": <source_start candidate>}`.
- `duration` sau cắt < `min_duration` → đề xuất `ineligible` (`too short after head cut (<x> s)`).
- **Cho CP7:** render đoạn `[clip.source_start, clip.source_end]` và các `trims` của candidate giao đoạn đó (cắt trim ở `source_start` nếu nó cắt ngang) — không dùng `source_start` của candidate khi `head_cut` khác `null`.
- Config `[selection]`: `head_cut_words` (list chuỗi không rỗng; rỗng → tắt), `head_cut_pad` (0–1 s) — cả hai vào `config_hash`, ghi ở `clips.json` `params`. `stats.head_cut` đếm clip có cắt. Log stderr mỗi head cut (`head cut <cand>: drop '<words>', <original> -> <cut> (<method>)`) và mỗi lần bỏ qua.
- Giới hạn đã biết: word timing của caption tự động là gần đúng (từ đầu segment thường dài ~1 s, bắt đầu sớm); segment không có word timing không được cắt (video test: `c01293`/`c01292` "cho nên điều thứ nhất…"); không bắt câu mở giữa câu không có từ nối. HUMAN LEAD nghe mẫu (2026-09-26): điểm cắt ổn, giữ `head_cut_pad` 0.1; segment không có word timing để nguyên (không nội suy timing theo ký tự).

## B8. Validation trước khi ghi (vi phạm → `failed`, lỗi code)

Số clip ≤ `max_clips`; id `k01`… liên tục theo thứ tự; `candidate_id` tồn tại và 7 trường chép khớp candidate (có `head_cut`: `original_start` = `source_start` candidate, `source_start` nằm trong `(candidate.source_start, source_end)`, các trường thời gian khớp giá trị tính lại theo B11); `duration` trong `[params.min_duration, params.max_duration]` của `candidates.json`; `unit_ids` tồn tại; `start_complete` ∧ `end_complete` ∧ `min_score ≤ score ≤ 10`; sắp theo `source_start`, không chồng lấn. `silences.json` phải khớp `candidates.json.silences_sha256` và `transcript.json` `transcript_sha256` khớp `candidates.json.transcript_sha256` (nếu không → `failed`, chạy lại analysis). `candidates_sha256` tính từ chính input đã đọc.

## B9. Stage / resume / CLI

Dùng `run_stage` của CP2 nguyên trạng:

- Yêu cầu `analysis` = `done` và `candidates.json`, `silences.json`, `metadata.json`, `transcript.json` tồn tại; không có manifest → lỗi; analysis chưa done → stage `failed` + `error`, không artifact, không gọi AI.
- `inputs` = `candidates.json`, `metadata.json`, `transcript.json` (word timing cho B11) (relative + sha256). `silences.json` không nằm trong `inputs` vì nó được khóa qua `candidates.json.silences_sha256` (kiểm ở B8).
- `config_hash` = `[selection]` `model`, `think`, `temperature`, `seed`, `num_ctx`, `prompt_version`, `max_clips`, `min_score`, `max_window_words`, `retries`, `head_cut_words`, `head_cut_pad` + `prompt_sha256`. **Không** gồm `ollama_host`, `retry_backoff`, `timeout` (thực thi). Đổi config stage khác không chạy lại selection.
- `artifacts` = `clips.json`, `selection_log.json`; lỗi → cả hai bị xóa.
- Chạy lại selection → downstream stale; analysis chạy lại → selection stale.
- CLI `auto-short selection <episode_id> [--force] [--config PATH]` — stdout `<episode_id>\t<selected (<n> clips)|skipped (up to date)>\t<path clips.json>`; stderr: model/host, mỗi window (số unit, từ, candidate, đề xuất, valid, thời gian), tổng `windows/ai_calls/proposals/valid/eligible/selected/selected_seconds`, cảnh báo retry/không clip; exit code theo CP2 D8.

## B10. Model / reproducibility

- **Mặc định C2** (HUMAN LEAD 2026-09-26, sau nghe mẫu v1/v2; CP1 §11): `qwen3:30b`, `think = true`, `prompt_version = "v3"` (v2 khi chốt C2; v3 thay khi Thay B11), `temperature 0`, `seed 42`, `num_ctx 32768`, `timeout 600` s/request. `num_ctx` nâng từ 16384 vì 30b-think dùng tới 14.9k token/lần gọi (prompt ~3k + suy luận ~9–12k) — 91 % của 16384; 32768 cho dư. Lần gọi lâu nhất đo được 81 s ≪ `timeout`.
- Chạy lại cùng config với `--force` → so sánh `clips.json` (kết quả đo bên dưới). Model/`think` chốt ghi ở CP1 §11.

## Config `[selection]`

Xem `config.example.toml`: `model`, `think`, `prompt_version` (`v1` | `v2` | `v3`, mặc định `v3`), `temperature` (0–2), `seed` (≥ 0), `num_ctx` (≥ 512), `max_clips` (1–99), `min_score` (1–10), `max_window_words` (≥ 1), `retries` (≥ 0), `head_cut_words` (list chuỗi không rỗng; rỗng = tắt B11), `head_cut_pad` (0–1) — trong hash; `ollama_host` (mặc định `http://127.0.0.1:11437`, Sửa đổi HUMAN LEAD 2026-09-26: trước là 11435), `timeout` (> 0), `retry_backoff` (list số 0–3600, mặc định `[5, 15]`) — thực thi.

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

### Lịch sử: B11 bản lọc (đã thay) — áp lại offline trên response đã lưu (không gọi AI)

Các mục "B11" dưới đây đo **bộ lọc loại đề xuất theo `start_blocklist`**, đã bị thay bằng head cut; giữ làm lịch sử.

Chạy lại B4 → B11 → B6 bằng code hiện hành trên response thô trong `selection_log.json` của các lần đo trên (cùng đề xuất AI, chỉ thêm bộ lọc). Mọi clip được chọn trước đây mở bằng cụm trong danh sách đều bị loại; không có kết quả lọc sai (kiểm tay các cụm khớp).

| Lần đo | Bị lọc (valid) | Selected trước → sau | Tổng thời lượng sau | Bị bỏ khỏi kết quả | Thêm vào |
|---|---|---|---|---|---|
| `30b` think on v2 (C2) | 1: `c00445` "cho nên" | 19 → 18 | 1069.9 s (median 61.7, `in_target` 10) | `c00445` | — |
| `14b` think off v2 | 5 ("cho nên" ×5) | 25 → 25 | 1385.5 s | `c00445`, `c01293` | `c00454`, `c00877` |
| `14b` think on v2 | 6 ("cho nên" ×4, "thế là" ×2) | 17 → 15 | 797.6 s | `c00497`, `c00936`, `c01293` | `c00504` |
| `30b` think on v1 | 1: `c01293` "cho nên" | 13 → 12 | 713.8 s | `c01293` | — |

Còn lọt (ngoài danh sách / không có từ nối): C2 `c01308` "Tại vì sao có hiện tượng này…"; `14b` v2 `c01212` "là lấy Hiếu thân Tôn Sư…".

Lần đầu chạy C2 + B11 (2026-09-26 ~14:00Z) Ollama `127.0.0.1:11435` reset mọi kết nối (> 10 phút); stage ghi `failed` đúng B5 (3 lần thử, không artifact). Chạy lại sau khi Ollama lên lại:

### Lịch sử: C2 + B11 bản lọc — đo thật (`qwen3:30b`, think on, v2, `num_ctx 32768`, `start_blocklist`)

| Lần | Wall | Token sinh | Đề xuất | Valid | Lọc B11 | Eligible | Selected | Tổng thời lượng | `in_target` | Median |
|---|---|---|---|---|---|---|---|---|---|---|
| C2 v2 không lọc (`num_ctx 16384`, bảng trên) | 450 s | 72.0k | 20 | 20 | — | 20 | 19 | 1111.0 s | 10 | 61.4 s (31.3–83.6) |
| C2 + B11, lần 1 | 447 s (7 m 27 s) | 72.0k | 20 | 20 | 1 | 19 | 18 | 1069.9 s | 10 | 61.7 s (31.3–83.6) |
| C2 + B11, `--force` ngay sau | 460 s (7 m 40 s) | 68.0k | 17 | 17 | 0 | 17 | 16 | 1090.7 s | 9 | 66.5 s |

- Lần 1: response **trùng từng token** với lần đo C2 không lọc (cùng `eval_count` mọi window, cùng đề xuất/score) dù `num_ctx` đổi 16384 → 32768; B11 lọc đúng `c00445` (u0059–u0061, "cho nên ở trong đây nói là…") như dự đoán offline, không clip nào khác đổi. `prompt_eval_count` lớn nhất 3806; tổng token lớn nhất một lần gọi 14732 (45 % của 32768); thời gian từng lần gọi (w01…w11, bỏ w06): 38, 21, 50, 46, 19, 56, 45, 33, 78, 61 s.
- Script kiểm độc lập: PASS cả hai lần. Kiểm câu mở đầu (danh sách từ nối mở rộng của script, rộng hơn `start_blocklist`): lần 1 còn 1/18 (`c01308` "Tại vì sao có hiện tượng này…" — "tại vì" không có trong `start_blocklist`); `--force` còn 2/16 (`c01308`, `c00279` "Tại vì sao phải tu thiện nghiệp…"). Không clip nào mở bằng cụm trong `start_blocklist`.
- Chạy lại không đổi → skip 0.14 s, sha256 `clips.json` không đổi, không gọi AI.
- **Tất định:** `--force` ngay sau (model đã nạp) cho response khác ở 7/10 window (request giống hệt): chỉ 9/18 clip chung (6 cùng score/topic); 17 đề xuất, 16 clip. Với 30b-think mức khác biệt giữa các lần chạy lớn hơn nhiều so với `14b` think off (22/25 chung) — chuỗi suy luận dài khuếch đại khác biệt số học. Hai lần chạy có trạng thái server tương tự (model vừa nạp lại) cho kết quả trùng (C2 không lọc và C2 + B11 lần 1). Ghi nhận, không che: `clips.json` của C2 **không tái lập được** giữa các lần `--force`; review (CP9) nên xem `clips.json` hiện có là một mẫu, không phải kết quả duy nhất.
- (Khi đó) workspace cuối là kết quả lần `--force`.
- Lần chạy thử với `start_blocklist` mở rộng (+ "tại vì", "tại vì sao", "vì sao"; port 11437): 20 đề xuất, lọc `c00445` ("cho nên") và `c01308` ("tại vì sao"), 17 clip / 1003.9 s. Dừng theo yêu cầu khi HUMAN LEAD làm rõ B11.

### Mặc định hiện hành — C2 + B11 head cut + prompt v3 (port 11437)

`qwen3:30b`, think on, v3, `num_ctx 32768`, `head_cut_words` mặc định, `head_cut_pad 0.1`, backoff `[5, 15]`. Không lần gọi nào lỗi/retry.

| Lần | Wall | Token sinh | Đề xuất | Valid | Eligible | Selected | Head cut | Tổng thời lượng | `in_target` | Median |
|---|---|---|---|---|---|---|---|---|---|---|
| C2 v2 (không head cut, bảng trên) | 450 s | 72.0k | 20 | 20 | 20 | 19 | — | 1111.0 s | 10 | 61.4 s (31.3–83.6) |
| v3 lần 1 (trước sửa điểm cắt) | 467 s (7 m 47 s) | 75.0k | 18 | 18 | 18 | 17 | 3 | 1047.8 s | 8 | 61.1 s (34.2–98.6) |
| **v3 `--force` sau sửa (workspace)** | 441 s (7 m 21 s) | 71.6k | 14 | 14 | 14 | 13 | 2 | 826.2 s | 7 | 65.9 s (31.3–98.6) |

- Head cut (bản workspace): `k04`/`c00457` bỏ "thì", 1249.99 → 1250.66 (`word`, từ giữ "tương" 1250.76); `k10`/`c00868` bỏ "thế là", 2530.19 → 2531.06 (`word`, "chúng" 2531.16). Bỏ qua: `c01293` "cho nên điều thứ nhất…" — segment `s00729` không có word timing. Lần 1 còn `c00562` bỏ "cho nên", 1791.6 → 1792.64 (`word`); `c00457` khi đó cắt 1250.19 (`silence`) do dùng khoảng lặng ranh giới → sửa quy tắc (xem B11), chạy lại `--force` (AI cho đề xuất khác: 14 thay vì 18 — không tất định như đã ghi).
- Trên toàn bộ 1484 candidate: 86 có head cut (63 `word`, 23 `silence` — trước sửa quy tắc), vài segment đầu không có word timing.
- Script kiểm độc lập (cập nhật cho `head_cut`: tính lại `source_duration`/`duration`/`in_target` từ candidate + trims cắt ngang): PASS cả hai lần. Kiểm câu mở đầu trên text **sau cắt** (danh sách từ nối mở rộng của script): 1/13 (`c01293`, không có word timing) — lần 1: 1/17 (cùng `c01293`); C2 v2 trước đó: 2/19.
- Chạy lại không đổi → skip, sha256 `clips.json` không đổi. `status` = `selection done`.
- Render thô mẫu có áp head cut (`[clip.source_start, source_end]` + trims giao đoạn đó): thời lượng file lệch +0.03–0.15 s; bản `-orig` 8 s từ `original_start` để so điểm cắt.
