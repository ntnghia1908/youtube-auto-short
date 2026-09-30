# CP8 — End-to-End Pipeline Contract

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | — (E1–E8, P1–P4 duyệt cùng APPROVE TASK 2026-09-27; P4 sửa: có preflight Ollama; review ACCEPTED). Sửa đổi HUMAN LEAD 2026-09-28 (CP8.10, `docs/tasks/CP8.10-queue-lanes.md`): E7 tham số `stages`. Sửa đổi HUMAN LEAD 2026-09-30 (FIX-ollama-wait): E8 |
| Checkpoint | CP8 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP8 |
| Task contract | `docs/tasks/CP8-pipeline.md` |
| Builds on | `docs/decisions/CP1-product-contract.md` §8; `docs/decisions/CP2-workspace-contract.md` D6, D8; `docs/decisions/CP3-transcript-contract.md` … `docs/decisions/CP7-render-contract.md` (stage giữ nguyên; CP7 R2 `title_source = "titles"`) |

File này là **canonical owner** của lệnh `auto-short run`, thứ tự stage của pipeline, resume, dừng khi lỗi, `--force-from`, preflight Ollama và exit code của `run` mà CP8.3 (web) và CP9 (batch) dùng lại. Nơi khác chỉ trỏ tới đây. Skip/stale của từng stage: `docs/decisions/CP2-workspace-contract.md` D6; schema/rule từng stage: decision record CP3–CP7. Thay đổi cần decision gate mới với HUMAN LEAD.

Implementation tham chiếu: `src/auto_short/pipeline.py` (`run_pipeline`, `ollama_preflight`), `src/auto_short/cli.py` (`run`, `stage_line`).

## E1. Lệnh

- `auto-short run <url|path> [--episode-id ID] [--subtitle PATH] [--speaker S] [--series S] [--episode N] [--force-from STAGE] [--no-preflight] [--config PATH]`.
- Tham số truyền nguyên cho stage tương ứng: ingest `--episode-id`; transcript `--subtitle`; titling `--speaker` / `--series` / `--episode`. Episode id lấy từ kết quả ingest.
- Lệnh lẻ (`ingest` … `render`, `status`) giữ nguyên tham số, output và exit code (CP2 D8, CP3–CP7).

## E2. Thứ tự stage

- `ingest → transcript → analysis → selection → titling → render` (CP1 §8 bỏ `review`).
- Stage `review` **không chạy** (giữ `pending` trong manifest) tới CP9. Render dùng `[render] title_source = "titles"` = title AI được auto-approve (CP1 §8, CP7 R2); `run` log một dòng `run: stage review is not run; AI titles are auto-approved ([render] title_source = 'titles')`.

## E3. Resume

- Không có state / artifact mới của pipeline. Mỗi stage tự skip khi up to date (CP2 D6).
- Chạy lại cùng lệnh sau lỗi / ngắt: stage đã `done` + khớp input/config skip, pipeline chạy tiếp từ stage đầu tiên chưa up to date (`failed`, `stale`, `running` do bị kill cứng, chưa chạy). Chạy lại khi mọi thứ đã xong: 6 stage skip, không gọi Ollama, không render.

## E4. Lỗi

- Dừng ở stage lỗi đầu tiên (`<Stage>Error`); stage sau không chạy; stage trước giữ `done`. Stage lỗi ghi `failed` + `error` như lệnh lẻ.
- Exit `1`; stderr `auto-short: error: <message của stage>` + `auto-short: re-run the same command to resume from the failed stage`. Không retry thêm ngoài retry sẵn có của stage.

## E5. Force

- `--force-from STAGE`, STAGE ∈ 6 stage của E2: stage đó chạy với `force=True`; stage sau chạy lại vì bị đánh `stale` (CP2 D6), không force; stage trước theo rule skip.
- Không có `--force` trơn. Giá trị khác (kể cả `review`) → argparse exit `2`.

## E6. Output / exit code

- stdout, mỗi stage xong một dòng đúng định dạng lệnh lẻ tương ứng (`<episode_id>\t<state>\t<path>`, cùng hàm `stage_line`), cuối cùng `<episode_id>\tdone (<rendered>/<clips> Shorts)\t<output_dir>/<episode_id>` (đường dẫn thư mục chứa `render_manifest.json`; số lấy từ kết quả render, hoặc `render_manifest.json` `stats` khi render skip).
- stderr: log của các stage như lệnh lẻ + bảng tổng kết `run: summary [<episode_id>]`: mỗi stage `ran` / `skip` + giây (đo bằng đồng hồ monotonic), stage dừng `error` / `interrupted`, dòng `total`. Thời điểm chạy từng stage vẫn là `started_at` / `finished_at` trong `manifest.json`; không thêm artifact.
- Exit: `0` thành công (kể cả clip `untitled` bị bỏ qua — cảnh báo của render); `1` lỗi stage (E4), preflight (E8), config; `2` sai cú pháp; `130` khi Ctrl-C: stderr `auto-short: interrupted during <stage>; re-run the same command to resume`, không traceback. Stage đang chạy được `run_stage` ghi `failed` + `error: "interrupted"` và xóa artifact (CP2); `<stage>` là `preflight` nếu ngắt trước ingest.
- Bắt Ctrl-C → 130 chỉ áp dụng cho `run`; lệnh lẻ giữ hành vi cũ.

## E7. Code

- `run_pipeline(target, config, *, episode_id, subtitle, speaker, series, episode, force_from, preflight, deps, on_stage, stages) -> PipelineResult` trong `src/auto_short/pipeline.py`: gọi lần lượt `run_<stage>` hiện có, không sửa `workspace.run_stage` hay module stage.
- `PipelineResult`: `episode_id`, `stages` (mỗi stage: tên, `ran`, giây, `…Result` của stage), `failed_stage` + `error` (E4), `rendered` / `clips` / `output_dir`. Lỗi stage trả về trong kết quả (không raise); preflight lỗi raise `PreflightError`; Ctrl-C raise `PipelineInterrupted` (subclass `KeyboardInterrupt`, mang tên stage đang chạy + kết quả tới lúc đó).
- `preflight` = hàm kiểm trước ingest (mặc định `ollama_preflight`; `None` = bỏ qua). `deps` (`StageDeps`) = dependency injectable của stage (downloader, caption fetcher, Whisper backend, analyzer, client Ollama selection/titling, runner render) và thay hàm `run_<stage>` cho test. `on_stage` = callback sau mỗi stage xong (CLI in dòng stdout; web dùng để báo tiến độ).
- **Sửa đổi CP8.10:** `stages` (mặc định `None` = cả 6 stage) = tập con khác rỗng của thứ tự E2, đúng thứ tự, không trùng (sai → `PipelineError`, không stage nào chạy); không có `ingest` thì bắt buộc `episode_id` (stage đọc workspace có sẵn). `preflight` chạy trước stage đầu tiên của tập con. Chỉ web dùng (làn prepare / ai / render: `docs/decisions/CP8.3-web-contract.md` W5); CLI `run` không đổi.
- CLI chỉ parse + in.

## E8. Preflight Ollama

- Trước ingest: `GET <host>/api/tags` (stdlib `urllib`, timeout 10 s) cho host của `[selection]` và `[titling]` (`resolve_host`: env `OLLAMA_HOST` ghi đè config, như stage); cùng host chỉ gọi một lần. `[selection] model` và `[titling] model` phải có trong `models[].name` / `models[].model` (tên không có tag khớp `<tên>:latest`).
- Lỗi (không kết nối, timeout, HTTP lỗi, response không hợp lệ, thiếu model) → exit `1`, `auto-short: error: ollama preflight: <lý do>`, không stage nào chạy, manifest không đổi.
- `--no-preflight` bỏ qua (vd episode đã xong selection/titling khi Ollama tắt). Không preflight `node` / `ffmpeg` / Whisper. Không sửa `OllamaClient.chat`.
- **Sửa đổi FIX-ollama-wait (HUMAN LEAD 2026-09-30, O1):** lỗi preflight có hai loại: mất kết nối (không kết nối được, timeout, HTTP 502 / 503 / 504) → `OllamaUnavailable` (subclass của `PreflightError`); thiếu model, HTTP khác, response không hợp lệ → `PreflightError` thường. CLI không đổi (exit `1`, cùng message); chỉ web phân biệt để đợi GPU (CP8.3 W5). Canonical: `docs/tasks/FIX-ollama-wait.md`.

## Số đo (máy dev, `rbjfCfFq3Dk`, 13 Short)

| Lệnh | Kết quả |
|---|---|
| `auto-short run https://youtu.be/rbjfCfFq3Dk` (đã xong hết) | 6 stage skip, exit 0, 0.32 s (preflight gồm), sha256 13 mp4 + `manifest.json` không đổi |
| `… --force-from render`, SIGINT cả process group sau 60 s | exit 130, 2/13 clip đã render bị xóa, render `failed` `interrupted`, không traceback |
| chạy lại không `--force-from` | 5 stage skip, render 13/13 trong 301 s, mp4 byte-identical với trước |
| `OLLAMA_HOST=http://127.0.0.1:1 auto-short run …` | exit 1 trong 0.18 s, manifest không đổi |

## Giới hạn đã biết

- Pipeline tuần tự một video; batch / playlist / song song là CP9.
- Timeout preflight 10 s mỗi host là hằng số (không phải key config).
- Giây trong bảng tổng kết là thời gian gọi `run_<stage>` (gồm cả kiểm skip / hash), không gồm preflight.
