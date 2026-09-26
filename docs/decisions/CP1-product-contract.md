# CP1 — Product Contract & Architecture Baseline

| Metadata | Value |
|---|---|
| Status | ACCEPTED |
| Accepted by | HUMAN LEAD, 2026-09-26 |
| Checkpoint | CP1 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP1 |
| Task contract | `docs/tasks/CP1-product-contract.md` |

Mỗi mục §1–§11 dưới đây là quyết định cuối. Thay đổi bất kỳ mục nào cần decision gate mới với HUMAN LEAD.

## 0. Dữ kiện môi trường (đo 2026-09-26)

| Mục | Kết quả |
|---|---|
| Máy chạy repo | VM VMware, 48 CPU, 125 GB RAM, **không có GPU** (`VMware SVGA II`, không có `/dev/nvidia*`) |
| Python | Miniconda 3, Python 3.14.7 (base env) |
| `ffmpeg` / `ffprobe` | `ffmpeg` 6.1.1 đã cài (`/usr/bin/ffmpeg`) |
| `yt-dlp` | 2026.08.19 cài dạng binary ở `~/.local/bin` (tool máy dùng chung để tải video test); việc dùng `yt-dlp` làm dependency Python của project theo §10 |
| Ollama | máy GPU riêng, truy cập qua `127.0.0.1:11435`; version 0.34.4; model có sẵn: `qwen3:30b`, `qwen3:14b`, `qwen3-embedding:8b`, `qwen3-embedding:4b`. Sửa đổi HUMAN LEAD 2026-09-26 (CP5): port **11437** (`127.0.0.1:11437`, có cơ chế giữ kết nối; 11435 hay reset kết nối) |
| Reference `youtube-vietnamese-dubber` | Python ≥3.11, `pyproject.toml` + hatchling, `yt-dlp`, `faster-whisper`, `pyyaml`; Ollama gọi bằng `urllib` stdlib; model đã kiểm chứng `gemma3:12b` cho tiếng Việt |

## 1. Input contract

- Một episode = một nguồn, một trong hai:
  1. YouTube URL (video đơn);
  2. file video local (`.mp4/.mkv/.webm`) + tùy chọn file phụ đề local (`.srt/.vtt`).
- Nguồn là tiếng Việt; không nhận/không tạo translation, TTS, dubbing.
- Playlist/batch: ngoài CP1–CP8, để CP9.
- Metadata tùy chọn cho header: `series`, `episode`, `speaker` qua config/CLI (xem §6).
- Video test chuẩn: `https://youtu.be/rbjfCfFq3Dk` ("Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập 9 - Lão Pháp Sư Tịnh Không", kênh PhapHanh), đã tải về local để test lặp lại:
  - `input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4` — H.264 1440×1080 (4:3), 29.97 fps, Opus audio, 3622 s, sha256 `7271326d…c3b77b`;
  - `rbjfCfFq3Dk.vi.json3` (= `vi-orig`) — caption YouTube tiếng Việt **auto-generated** (827 event, không dấu câu, có nhãn `[âm nhạc]`), không có phụ đề thủ công;
  - `rbjfCfFq3Dk.info.json` — metadata.
  - `input/` đã gitignore; file không commit. Tải lại: `yt-dlp -f "bv*+ba/b" --merge-output-format mp4 --write-info-json --write-auto-subs --sub-langs vi --sub-format json3 -o "input/%(id)s/%(id)s.%(ext)s" <url>`.
  - Sửa đổi HUMAN LEAD 2026-09-26 (sau review CP2): lệnh tải dùng chất lượng tốt nhất `bv*+ba/b` (bỏ `height<=1080`); với video test bản tốt nhất vẫn là 1440×1080.

## 2. Output contract

- Mỗi Short một file `output/<episode_id>/shorts/<clip_id>.mp4`:
  - 1080×1920 (9:16), H.264 (yuv420p), AAC 48 kHz, 30 fps (hoặc giữ fps nguồn nếu ≤ 30);
  - kèm `render_manifest.json` (clip, title, source hash, render config hash).
- Không tự upload YouTube (ngoài scope; nếu cần là quyết định riêng sau CP12).

## 3. Short duration policy

- Tối thiểu 30 s / mục tiêu 60–90 s / tối đa 180 s.
- Không cắt giữa câu.
- Sửa đổi HUMAN LEAD 2026-09-26 (chốt CP4): các mức 30 / 60–90 / 180 s tính trên **thời lượng Short thực tế** sau khi rút khoảng lặng (§5), không phải thời lượng đoạn nguồn.

## 4. Composition 9:16

Theo mẫu HUMAN LEAD cung cấp (ảnh chụp Short "HT.Tịnh Không / Thập Thiện Nghiệp Đạo Kinh (tập 14)" — "Các bậc thang tu học Phật pháp").

```text
┌──────────────────────────┐  nền đen
│  ┌────────────────────┐  │
│  │ HEADER (vàng)      │  │  deterministic: speaker / series / tập — không AI
│  └────────────────────┘  │
│ ┌──────────────────────┐ │
│ │                      │ │
│ │  VIDEO NGUỒN         │ │  full width, crop giữa
│ │                      │ │
│ └──────────────────────┘ │
│  ┌────────────────────┐  │
│  │ TITLE (vàng)       │  │  title/hook AI (CP6)
│  └────────────────────┘  │
└──────────────────────────┘
```

Tham số đo từ ảnh mẫu (576×1280), biểu diễn theo chiều rộng khung W để độc lập độ phân giải:

| Thành phần | Thông số |
|---|---|
| Nền | đen `#000000` |
| Header panel | rộng ≈ 0.79 W, căn giữa; cao ≈ 0.27 W; bo góc; nền vàng `#FEDB00`; chữ đen, sans-serif, căn giữa, tối đa 3 dòng |
| Video | full width W; cao ≈ 1.12 W (tỉ lệ ≈ 8:9); scale + crop giữa theo chiều ngang (nguồn 4:3 giữ ≈ 67 % bề ngang, nguồn 16:9 giữ ≈ 50 %); giữ nguyên chữ burn-in sẵn có của nguồn |
| Title panel | ngay dưới video (khe ≈ 0.01 W); rộng ≈ 0.81 W, căn giữa; cao ≈ 0.27 W; bo góc; nền `#FEDB00`; chữ đen, cỡ ≈ 1.5× chữ header, tối đa 2 dòng |
| Khoảng cách header→video | ≈ 0.005 W |
| Khối nội dung | căn giữa theo chiều dọc trong khung 1080×1920, phần còn lại là nền đen |
| Lower panel / subtitle | không có (subtitle tắt, §7) |

- Font: sans-serif hỗ trợ đầy đủ dấu tiếng Việt, license mở (OFL), đóng gói trong repo ở CP7; tên font cụ thể chốt ở CP7 bằng so sánh trực quan với ảnh mẫu.
- CP7 phải render khớp mẫu này (so sánh trực quan với ảnh mẫu là acceptance); không redesign.
- Ảnh mẫu lưu tại `docs/decisions/assets/cp1-layout-reference.jpg`.

## 5. Clip selection boundaries

- Clip phải bắt đầu/kết thúc tại ranh giới segment transcript (không cắt giữa câu); có thể nới ±0.3 s để tránh cắt âm.
- Một clip = một ý trọn vẹn; không ghép đoạn không liên tục (không "jump cut") trong MVP.
- Không chồng lấn giữa các clip được chọn của cùng episode.
- Tối đa **20** Short mỗi episode (config). Mỗi Short **ưu tiên trình bày trọn vẹn một ý**: tiêu chí hoàn chỉnh ý đứng trên số lượng và trên độ dài mục tiêu — thà ít clip hơn còn hơn clip cụt ý.
- AI (CP5) chỉ chọn trong danh sách candidate do code deterministic sinh ra (CP4), không tự tạo timestamp mới.
- Sửa đổi HUMAN LEAD 2026-09-26 (sau review CP3): video giảng pháp chỉ có nhạc ở phần giới thiệu đầu và phần kết; hai phần này không dùng cho Short và có thể loại bỏ khi sinh candidate (CP4).
- Sửa đổi HUMAN LEAD 2026-09-26 (chốt CP4):
  - "Không jump cut" nghĩa là không ghép các ý/đoạn không liên tục. **Rút khoảng lặng** bên trong một đoạn liên tục được phép: mọi khoảng lặng audio trong clip dài hơn `max_pause` = **1.0 s** được rút còn `max_pause` khi render (CP7). Lý do: video giảng pháp nhịp chậm, khoảng lặng chiếm ~45 % thời lượng (đo video test). Giá trị 1.0 s chọn sau khi nghe thử so sánh với 0.5 s, 0.7 s và phương án 2 tầng (`docs/tasks/CP4-analysis.md`).
  - Phần giới thiệu tên kinh/tập/người giảng ngay sau nhạc mở đầu thuộc intro, bị loại cùng nhạc intro.
- Sửa đổi HUMAN LEAD 2026-09-26 (mở CP5): tối đa **25** Short mỗi episode (config `[selection] max_clips`), thay cho 20 ở trên. Ưu tiên trọn ý vẫn đứng trên số lượng. Rule chọn clip: `docs/decisions/CP5-selection-contract.md`.
- Sửa đổi HUMAN LEAD 2026-09-26 (CP5): đầu clip có thể lùi vào trong segment đầu để bỏ từ nối thuần (cắt deterministic theo word timing, không do AI) — `docs/decisions/CP5-selection-contract.md` B11.

## 6. Title / header structure

- **Header:** deterministic — lấy từ config/CLI (`speaker`, `series`, `episode`) hoặc metadata YouTube; không dùng AI.
- **Title/hook (yellow panel):** AI sinh từ transcript của clip; tiếng Việt; ≤ 60 ký tự, tối đa 2 dòng; không thêm thông tin không có trong clip; không emoji/clickbait.
- Lưu `titles.json` với clip ID, model, prompt version, source hash.

## 7. Subtitle policy

- Subtitle **tắt** mặc định. Lower panel không chứa subtitle; nội dung khung theo mẫu layout (§4).
- Đã cân nhắc: burn-in subtitle ở lower panel; subtitle karaoke/từng từ.

## 8. Artifact model & pipeline boundaries

Workspace: `work/<episode_id>/` (đã gitignore). Mỗi stage một artifact, có `stage`, `inputs` (path + sha256), `config_hash`, `created_at`:

| Stage | Artifact | Deterministic? | CP |
|---|---|---|---|
| ingest | `source.*`, `metadata.json` | có | CP2 |
| transcript | `transcript.json` (YouTube → local subtitle → Whisper) | có (provider ngoài) | CP3 |
| analysis | `shots.json`, `silences.json`, `candidates.json` | có | CP4 |
| selection | `clips.json` | **AI** + validate | CP5 |
| titling | `titles.json` | **AI** + validate | CP6 |
| review | `review.json` (approve/reject/edit) | người | CP9 |
| render | `render_manifest.json`, `shorts/*.mp4` | có | CP7 |

- Stage bỏ qua khi artifact tồn tại và input hash + config hash khớp; lệch → stage và downstream stale.
- Boundary deterministic ↔ AI: AI chỉ ở selection và titling; output AI phải qua schema validation trước khi thành artifact trusted.
- **Human review:** mặc định render mọi clip AI chọn (MVP CP8); review gate đầy đủ ở CP9. Auto-approve chỉ là config explicit.

## 9. Execution profile

- `dual-agent` mặc định cho các checkpoint (main session = ORCHESTRATOR, `.claude/agents/implementer` = IMPLEMENTER theo `.claude/rules/execution.md`); đổi profile cho một task vẫn cần HUMAN LEAD approve.

## 10. Dependency policy

Nguyên tắc: stdlib trước; không thêm dependency ngoài danh sách dưới đây; dependency mới phải qua dependency proposal (`docs/ai/workflow.md` §3). Đây là danh sách canonical duy nhất của dependency được duyệt.

| Library | Purpose | Scope |
|---|---|---|
| Python 3.12 trong conda env riêng (không dùng base) + pip, `pyproject.toml` (hatchling) | runtime + packaging | conda env `auto-short` |
| `yt-dlp` | tải video + lấy caption YouTube (kể cả auto-generated) | runtime |
| `faster-whisper` | fallback transcript khi không có caption hợp lệ; local, có timestamp | runtime, model tải về `models/` |
| `pytest` | test | dev only |
| `ffmpeg`/`ffprobe` (system binary) | probe, cắt, compose, render; scene detect bằng filter `select=gt(scene,…)` | cài hệ thống |
| Ollama HTTP API qua `urllib` (stdlib) | clip selection + title | không thêm dep |
| `tomllib` (stdlib) | đọc config TOML | không thêm dep |
| `pyyaml` | dùng khi cần (hiện có mặt dạng transitive qua `faster-whisper`) | runtime khi dùng |

- Config dùng **TOML / `tomllib`**.
- Đã cân nhắc, không chọn: `uv`, `.venv` system Python, `youtube-transcript-api`, `openai-whisper`, PySceneDetect, `ollama` python client.
- Sửa đổi HUMAN LEAD 2026-09-26 (sau review CP2): runtime đổi từ `.venv` system Python sang conda env riêng (không dùng base); `yt-dlp` pin phiên bản theo `docs/decisions/CP2-workspace-contract.md` D2.
- Sửa đổi HUMAN LEAD 2026-09-26 (sau review CP3): `pyyaml` được phép dùng khi cần (bỏ loại trừ trước đó); config vẫn là TOML.

## 11. Local GPU / Ollama assumptions

- Ollama chạy trên **máy GPU riêng**, truy cập qua `OLLAMA_HOST`, mặc định `http://127.0.0.1:11435`; code không hard-code host/model.
- Sửa đổi HUMAN LEAD 2026-09-26 (CP5): port 11437 — mặc định `ollama_host` là `http://127.0.0.1:11437` (`OLLAMA_HOST` vẫn ghi đè).
- Model khởi đầu: **`qwen3:14b`** (có sẵn trên máy GPU; thay cho `gemma3:12b` ghi trước đó). CP5/CP10 đo so sánh với `gemma3:12b` và `qwen3:30b` rồi chốt lại.
- Đo CP5 (2026-09-26, video test, chi tiết `docs/decisions/CP5-selection-contract.md` § Đo thực tế): `qwen3:14b` think off 120 s → 25 clip / 1058 s; `qwen3:14b` think on 305 s → 24 clip / 1206 s; `qwen3:30b` think off → 0 clip (bản chỉ-suy-luận, không dùng được với think off); `qwen3:30b` think on 564 s → 13 clip / 780 s (prompt v1). Prompt v2 (thời gian cộng dồn): `qwen3:14b` think off 113 s → 25 clip / 1407 s; think on 405 s → 17 clip / 919 s; `qwen3:30b` think on 450 s → 19 clip / 1111 s. Số đo C2 + lọc B11: `docs/decisions/CP5-selection-contract.md`.
- Sửa đổi HUMAN LEAD 2026-09-26 (chốt CP5): model selection **`qwen3:30b`**, `think = true`, prompt `v2` (cấu hình C2, chọn sau khi nghe mẫu v1/v2), thay cho model khởi đầu `qwen3:14b` ở trên. Titling (CP6) chốt model riêng.
- Whisper chỉ là fallback; trên VM không GPU chạy CPU (`int8`, 48 core). Đo thực tế ở CP11.

## 12. Open questions

Không còn open question cho CP1. Mọi mục §1–§11 đã được HUMAN LEAD chốt ngày 2026-09-26.
