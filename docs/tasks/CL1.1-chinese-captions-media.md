# Task: CL1.1 — Chinese caption acquisition + 5-minute media artifact

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Human Lead: HUMAN LEAD
- Base commit / branch: `eab3134` (`main` = `origin/main`, 2026-09-27) / `feature/cl1-chinese-learning`, worktree `../youtube-auto-short-cl1`
- Human Lead approval: accepted 2026-09-27 — kiến trúc hai ứng dụng CL1 duyệt về nguyên tắc (G1, G2, G3, G5 phần lấy clip, G7, G8, G9, G10, G11); "APPROVE ONLY CL1.1"; G4, G6 tạm, chốt bằng số đo
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S2 vì: task đầu tiên của ứng dụng thứ hai (namespace `work/_learning/`, CLI mới), mở rộng shared abstraction `run_stage` (CP2 D6). Không thêm dependency. Task tổng: `docs/tasks/CL1-chinese-learning-mvp.md`.

## Goal

`auto-short learn <youtube-url>` tạo `work/_learning/<video_id>/` chứa phụ đề tiếng Trung gốc đã chọn (manual trước, ASR tiếng Trung sau, không bao giờ bản dịch máy), provenance việc chọn track, và clip 0–300 s của video lấy bằng tải một phần — không tải cả video. Auto Short giữ nguyên behavior.

## Scope

- In scope:
  - `workspace.py`: `run_stage(..., downstream=None)` + `mark_downstream_stale(manifest, stage, downstream=None)`; `None` = CP2 D6 nguyên trạng; khi có `downstream` chỉ đánh stale đúng các stage đó và stage không cần nằm trong `STAGES`.
  - `src/auto_short/learning/`: `__init__.py`, `tracks.py` (liệt kê + chọn track theo contract C5), `subtitle.py` (stage `subtitle`), `media.py` (stage `media`), `run.py` (`run_learning`, `LEARNING_DIR = "_learning"`, thứ tự `subtitle` → `media`, dừng ở stage lỗi đầu tiên), `cli.py` (handler lệnh `learn`).
  - Artifact trong `work/_learning/<id>/`: `manifest.json` (CP2 D5), `subtitle.json3`, `source.json`, `clip.mp4`, `media.json` (contract C4, C5, C10).
  - Validation phụ đề theo contract C6 (cửa sổ `[0, window_seconds)`, timestamp, tag `zh`, tỉ lệ Hán) — chỉ để quyết accept; CL1.1 **không** ghi artifact dòng/bài học.
  - Config `[learning]`: `window_seconds` (300.0), `min_han_ratio` (0.5), `media_format` (`bv*[height<=720]+ba/b[height<=720]`); `config.example.toml`.
  - `cli.py`: subparser `learn <url> [--force] [--config PATH]`.
  - Tests mới; số đo thật; docs trong boundary (dưới).
- Out of scope:
  - Pinyin, dịch tiếng Việt, LLM/Ollama, preflight, `lesson.json`, Whisper fallback, chấm phát âm, UI/web/router/job, localStorage, TTS, Anki/SRS, app mobile.
  - Sửa hành vi transcript tiếng Việt, `pipeline.py`, stage Auto Short; refactor repo sang `shared/`; tách caption fetcher/Ollama client.
  - Sửa lỗi video id bắt đầu `-`/`_` (finding đã báo, ngoài scope).
  - Dependency mới; sửa `pyproject.toml`.

## Authority / key decisions

- `docs/decisions/CL1-chinese-learning-contract.md` R3: C1 (quy ước host/app), C3 (NEW/MODIFY/IMPORT ONLY/MUST NOT MODIFY), C4 (namespace, ownership, artifact), C5 (chọn track — tạm, G4), C6 (cửa sổ + validation), C9 (orchestrator riêng + `downstream`), C10 (lấy clip, chỉ phần B lấy clip), C12 (CLI).
- `docs/decisions/CP2-workspace-contract.md` D3, D5–D8; `CP3-transcript-contract.md` T5 #2, T6.
- Quyết định cục bộ CL1.1 (trong boundary đã duyệt):
  - `subtitle`: `inputs = []`; `config_hash` = `{"learning.window_seconds", "learning.min_han_ratio", "learning.track_rule": "v1"}`; `downstream = ("lesson",)`.
  - `media`: `inputs = []`; `config_hash` = `{"learning.window_seconds", "learning.media_format"}`; `downstream = ()`; chỉ chạy khi `subtitle` done.
  - Manifest `source` = `{"kind": "youtube", "uri": "https://youtu.be/<id>", "path": null, "sha256": null, "size": null, "mtime_ns": null}`.
  - `source.json` (schema_version 1, không timestamp tạo file): `episode_id`, `video` {`id`, `title`, `channel`, `duration`, `webpage_url`}, `tracks` (mọi track liên quan zh: `key`, `auto`, `lang`, `kind`, `tlang`, `json3`), `selected` {`key`, `auto`, `lang`, `reason`}, `subtitle` {`path`, `sha256`}, `window` {`start`, `end`}, `stats` {`segments_in_window`, `han_ratio`, `first_start`, `last_end`}.
  - Clip: tải qua thư mục tạm `work/_learning/<id>/.media-tmp/`, probe bằng `ingest.probe.probe` (import only), đổi tên thành `clip.mp4` sau khi hợp lệ; dọn thư mục tạm mọi trường hợp.

## Implementation approach

- `tracks.py`: lớp con `YtDlpCaptionFetcher` thêm `listing(url)` đọc info đã cache (`title`, `channel`, `duration`, `webpage_url`) và mô tả track (`lang`/`kind`/`tlang` từ query URL json3); hàm thuần `pick_chinese_track(tracks) -> selection | None` + lý do; `download()` dùng nguyên trạng. Mọi truy cập mạng qua Protocol để test thay bằng fake.
- `subtitle.py`: `parse_json3` → `normalize` (import only) → lọc `kind = speech`, `start < window` (không kẹp `end`) → validate C6 → ghi `subtitle.json3` (bytes gốc), `source.json`.
- `media.py`: `yt_dlp` với `download_ranges=download_range_func(None, [(0, window)])`, `force_keyframes_at_cuts=True`, `format=media_format`, `merge_output_format="mp4"`, `noplaylist`, `js_runtimes` từ `[ingest]`; downloader injectable. Nếu bản pin không tải một phần được → dừng, báo BLOCKED kèm bằng chứng; **không** tự chuyển sang tải toàn bộ.
- `run.py`: `Workspace(<workspace.dir>/_learning, validate_episode_id(video_id))`; `run_stage` mỗi stage với `downstream` tường minh; kết quả `LearningResult(episode_id, workspace, stages: [(name, ran)])`.
- CLI: stdout mỗi stage một dòng `<episode_id>\t<stage>\t<ran|skipped (up to date)>`, dòng cuối `<episode_id>\tdone\t<workspace dir>`; log stderr; exit code CP2 D8 (`1` với `auto-short: error: …`).

## Acceptance Criteria

1. **Shared primitive:** `run_stage` / `mark_downstream_stale` không truyền `downstream` cho kết quả như trước — toàn bộ test hiện có PASS không sửa; `downstream=("lesson",)` chỉ đánh stale `lesson` (nếu có entry); `downstream=()` không đánh stale gì; stage ngoài `STAGES` chạy được khi có `downstream`.
2. **Chọn track (C5):** manual `zh-Hans` + manual `zh` → `zh-Hans`; manual `zh-CN` + `zh-Hant` → `zh-CN`; manual key có hậu tố id (`zh-Hans-abc123`, `lang=zh-Hans`) được nhận theo `lang`; không manual + auto `lang=zh&kind=asr` không `tlang` → auto; auto `zh-Hans` có `tlang` (bản dịch) → **không** nhận; track không có json3 → bỏ qua; manual + auto cùng có → manual.
3. **Không có phụ đề Trung:** không track hợp lệ → `subtitle` `failed`, `error` nêu lý do + tóm tắt track zh đã thấy; `media` không chạy; không còn artifact; exit 1.
4. **Phụ đề hỏng:** json3 không parse được / timestamp hỏng / tag không `zh` / tỉ lệ Hán < `min_han_ratio` / không segment speech trong cửa sổ → `failed` + lý do tương ứng; artifact stage bị xóa.
5. **Biên 0–300 s:** giữ đúng segment speech có `start < window_seconds` (segment `start = 299.999` giữ, `start = 300.0` bỏ, segment bắt đầu trước 300 và kết thúc sau 300 giữ nguyên `end`); video ngắn hơn cửa sổ → mọi segment.
6. **Timestamp giữ nguyên:** `start`/`end`/text các segment trong cửa sổ bằng đúng output `normalize(parse_json3(subtitle.json3))` (so trực tiếp, không làm tròn thêm, không sửa chữ); `stats.first_start`/`last_end` khớp.
7. **Schema artifact:** `subtitle.json3` byte-identical với bytes fetcher trả; `source.json`, `media.json`, `manifest.json` đúng schema ở § Authority/C4, thứ tự key cố định, không chứa thời điểm tạo (trừ `manifest.json` theo CP2 D5); chạy lại (`--force`) với fake deterministic → `source.json` byte-identical.
8. **Clip:** `clip.mp4` có video + audio, `duration` ∈ [min(window, duration video) − 2, window + 2] s; ngoài khoảng → `media` `failed`, clip bị xóa; `media.json` `sha256` khớp file.
9. **Rerun / skip:** chạy lại không đổi → cả hai stage `skip (up to date)`; đổi `window_seconds` → cả hai chạy lại; đổi `media_format` → chỉ `media` chạy lại; `--force` → chạy lại và `lesson` (nếu có entry) thành `stale`; xóa `clip.mp4` → chỉ `media` chạy lại.
10. **Dọn khi lỗi:** lỗi ở bất kỳ stage (kể cả Ctrl-C) → entry `failed`/`interrupted`, artifact của stage đó bị xóa, `.media-tmp/` không còn.
11. **Ownership:** chỉ `work/_learning/<id>/` được tạo/sửa; fixture `work/<id>/` + `output/<id>/` Auto Short cùng id byte-identical trước/sau; `iter_manifests(work/)` không trả `_learning`.
12. **Không tải cả video:** số đo thật cho thấy bytes tải về ≈ kích thước clip (không phải cả video) và thời gian tải không tỉ lệ với thời lượng video.
13. **Auto Short không đổi:** `git diff eab3134 -- src/auto_short/pipeline.py src/auto_short/ingest src/auto_short/transcript src/auto_short/analysis src/auto_short/selection src/auto_short/titling src/auto_short/render src/auto_short/review src/auto_short/web pyproject.toml` rỗng.

## Required verification

- `pytest -q` (toàn bộ) — AC1, AC13 (hồi quy).
- `pytest -q tests/test_workspace.py tests/test_learning_tracks.py tests/test_learning_subtitle.py tests/test_learning_media.py tests/test_learning_cli.py` — AC1–AC11 (fetcher/downloader giả; clip thật tổng hợp bằng ffmpeg lavfi như `tests/conftest.py`).
- Lệnh `git diff` ở AC13 rỗng.
- `node scripts/framework-check.mjs` PASS.
- Số đo thật `auto-short learn` trên ≥ 3 video (ít nhất: 1 manual zh, 1 nhiều manual zh cần thứ tự, 1 không có zh hợp lệ — vd video tiếng Việt chỉ có zh dịch máy hoặc video tiếng Trung không phụ đề; nếu tìm được video có ASR tiếng Trung gốc thì thêm): ghi vào contract § Đo thực tế / CL1.1 các cột track manual zh, track auto zh, `-orig` có/không, track chọn, hành vi rule, tên track bất thường, thời gian, kích thước clip, thời lượng clip (`ffprobe`), bytes tải (AC12). Chỉ sửa C5 trong boundary G4 nếu số đo bác bỏ rule.

Tất cả required verification phải chạy và PASS trước READY.

## Files

- Allowed to change:
  - `src/auto_short/workspace.py` (chỉ `run_stage`, `mark_downstream_stale`)
  - `src/auto_short/config.py`, `config.example.toml` (chỉ thêm `[learning]`)
  - `src/auto_short/cli.py` (chỉ thêm subparser + dispatch `learn`)
  - `src/auto_short/learning/` (file mới)
  - `tests/test_learning_*.py`, `tests/learning_helpers.py`, `tests/fixtures/learning/` (mới); `tests/test_workspace.py`, `tests/test_config.py` (chỉ thêm case, không sửa case cũ)
  - Docs: `docs/decisions/CL1-chinese-learning-contract.md` (§ Đo thực tế, C5 trong boundary G4, dòng implementation), `docs/decisions/CP2-workspace-contract.md` (ghi chú sửa đổi D6: `downstream`), `docs/ai/project-profile.md` (module map: `src/auto_short/learning/` — *implemented, partial* CL1.1; mục ứng dụng thứ hai + authority CL1), `README.md` (Usage `auto-short learn`), task này (§ Result)
- Protected (không sửa): `src/auto_short/pipeline.py`, `ingest/`, `transcript/`, `analysis/`, `selection/`, `titling/`, `render/`, `review/`, `web/`, `pyproject.toml`, mọi test hiện có (ngoài thêm case như trên), `docs/workflow/current-state.md`, các decision/task khác.

## Manual test checklist (Tech Lead)

Task chạm CLI công khai mới và shared abstraction; **không** chạm database, security model hay web API. Manual test sau automated verification là điểm danh.

- [ ] `auto-short learn <URL có manual zh>` → `work/_learning/<id>/` có đủ 5 file; mở `clip.mp4` nghe/xem ≈ 5 phút đầu; chữ trong `subtitle.json3` là tiếng Trung đúng video.
- [ ] Chạy lại → skip cả hai stage.
- [ ] URL tiếng Việt (chỉ có zh dịch máy) → lỗi rõ, không tải clip.
- [ ] Trang web Auto Short và `work/<id>/` không bị ảnh hưởng.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
