# CP1 — Product Contract & Architecture Baseline

| Metadata | Value |
|---|---|
| Status | PROPOSED — chờ HUMAN LEAD DECIDE |
| Checkpoint | CP1 (S2) |
| Roadmap | `AUTO_SHORT_CHECKPOINT_PLAN.md` §4 CP1 |
| Task contract | `docs/tasks/CP1-product-contract.md` |

> Tài liệu này là **đề xuất** của pha DISCUSS. Không mục nào là quyết định cho tới khi HUMAN LEAD chốt; sau DECIDE, Status đổi thành ACCEPTED và từng mục ghi quyết định cuối.
>
> Mỗi mục: **Đề xuất** (recommendation) · **Lựa chọn khác** · **Cần HUMAN LEAD** khi là lựa chọn sản phẩm/thẩm mỹ mà agent không có dữ kiện.

## 0. Dữ kiện môi trường (đo 2026-09-26)

| Mục | Kết quả |
|---|---|
| Máy chạy repo | VM VMware, 48 CPU, 125 GB RAM, **không có GPU** (`VMware SVGA II`, không có `/dev/nvidia*`) |
| Python | Miniconda 3, Python 3.14.7 (base env) |
| `ffmpeg` / `ffprobe` / `yt-dlp` | **chưa cài** |
| Ollama | `127.0.0.1:11434` và `:11435` đang LISTEN nhưng trả `Connection reset` — có vẻ là SSH tunnel tới máy GPU mà đầu kia chưa chạy Ollama. HUMAN LEAD cho biết GPU ở port 11435. |
| Reference `youtube-vietnamese-dubber` | Python ≥3.11, `pyproject.toml` + hatchling, `yt-dlp`, `faster-whisper`, `pyyaml`; Ollama gọi bằng `urllib` stdlib; model đã kiểm chứng `gemma3:12b` cho tiếng Việt |

## 1. Input contract

- **Đề xuất:** một episode = một nguồn, một trong hai:
  1. YouTube URL (video đơn);
  2. file video local (`.mp4/.mkv/.webm`) + tùy chọn file phụ đề local (`.srt/.vtt`).
- Nguồn là tiếng Việt; không nhận/không tạo translation, TTS, dubbing.
- Playlist/batch: ngoài CP1–CP8, để CP9.
- Metadata tùy chọn cho header: `series`, `episode`, `speaker` qua config/CLI (xem §6).
- **Quyết định HUMAN LEAD (2026-09-26):** video test chuẩn là `https://youtu.be/rbjfCfFq3Dk` ("Phật Thuyết Thập Thiện Nghiệp Đạo Kinh tập 9 - Lão Pháp Sư Tịnh Không", kênh PhapHanh), đã tải về local để test lặp lại:
  - `input/rbjfCfFq3Dk/rbjfCfFq3Dk.mp4` — H.264 1440×1080 (4:3), 29.97 fps, Opus audio, 3622 s, sha256 `7271326d…c3b77b`;
  - `rbjfCfFq3Dk.vi.json3` (= `vi-orig`) — caption YouTube tiếng Việt **auto-generated** (827 event, không dấu câu, có nhãn `[âm nhạc]`), không có phụ đề thủ công;
  - `rbjfCfFq3Dk.info.json` — metadata.
  - `input/` đã gitignore; file không commit. Tải lại: `yt-dlp -f "bv*[height<=1080]+ba/b" --merge-output-format mp4 --write-info-json --write-auto-subs --sub-langs vi --sub-format json3 -o "input/%(id)s/%(id)s.%(ext)s" <url>`.

## 2. Output contract

- **Đề xuất:** mỗi Short một file `output/<episode_id>/shorts/<clip_id>.mp4`:
  - 1080×1920 (9:16), H.264 (yuv420p), AAC 48 kHz, 30 fps (hoặc giữ fps nguồn nếu ≤ 30);
  - kèm `render_manifest.json` (clip, title, source hash, render config hash).
- Không tự upload YouTube (ngoài scope; nếu cần là quyết định riêng sau CP12).

## 3. Short duration policy

- **Đề xuất:** mục tiêu 30–60 s, tối thiểu 20 s, tối đa 60 s; không cắt giữa câu.
- Lựa chọn khác: cho phép tới 180 s (YouTube Shorts hiện hỗ trợ tới 3 phút).
- **Quyết định HUMAN LEAD (2026-09-26):** min 30 s / mục tiêu 60–90 s / max 180 s; không cắt giữa câu.

## 4. Composition 9:16

**Quyết định HUMAN LEAD (2026-09-26):** theo mẫu HUMAN LEAD cung cấp (ảnh chụp Short "HT.Tịnh Không / Thập Thiện Nghiệp Đạo Kinh (tập 14)" — "Các bậc thang tu học Phật pháp").

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
- **Quyết định HUMAN LEAD (2026-09-26):** tối đa **20** Short mỗi episode (config). Mỗi Short **ưu tiên trình bày trọn vẹn một ý**: tiêu chí hoàn chỉnh ý đứng trên số lượng và trên độ dài mục tiêu — thà ít clip hơn còn hơn clip cụt ý.
- AI (CP5) chỉ chọn trong danh sách candidate do code deterministic sinh ra (CP4), không tự tạo timestamp mới.

## 6. Title / header structure

- **Header:** deterministic — lấy từ config/CLI (`series`, `episode`) hoặc metadata YouTube; không dùng AI.
- **Title/hook (yellow panel):** AI sinh từ transcript của clip; tiếng Việt; **đề xuất** ≤ 60 ký tự, tối đa 2 dòng; không thêm thông tin không có trong clip; không emoji/clickbait.
- Lưu `titles.json` với clip ID, model, prompt version, source hash.

## 7. Subtitle policy

- **Đề xuất:** burn-in subtitle tiếng Việt từ transcript đã normalize, mỗi dòng ≤ ~32 ký tự, tối đa 2 dòng, ở lower panel.
- Lựa chọn khác: không có subtitle; hoặc subtitle kiểu karaoke/từng từ (cần timestamp từng từ → phụ thuộc Whisper, không có với YouTube captions).
- **Quyết định HUMAN LEAD (2026-09-26):** **tắt** subtitle mặc định. Lower panel không chứa subtitle; nội dung lower panel theo mẫu layout (§4).

## 8. Artifact model & pipeline boundaries

Workspace: `work/<episode_id>/` (đã gitignore). Mỗi stage một artifact, có `stage`, `inputs` (path + sha256), `config_hash`, `created_at`:

| Stage | Artifact | Deterministic? | CP |
|---|---|---|---|
| ingest | `source.*`, `metadata.json` | có | CP2 |
| transcript | `transcript.json` (YouTube → local subtitle → Whisper) | có (provider ngoài) | CP3 |
| analysis | `shots.json`, `candidates.json` | có | CP4 |
| selection | `clips.json` | **AI** + validate | CP5 |
| titling | `titles.json` | **AI** + validate | CP6 |
| review | `review.json` (approve/reject/edit) | người | CP9 |
| render | `render_manifest.json`, `shorts/*.mp4` | có | CP7 |

- Stage bỏ qua khi artifact tồn tại và input hash + config hash khớp; lệch → stage và downstream stale.
- Boundary deterministic ↔ AI: AI chỉ ở selection và titling; output AI phải qua schema validation trước khi thành artifact trusted.
- **Human review:** mặc định render mọi clip AI chọn (MVP CP8); review gate đầy đủ ở CP9. Auto-approve chỉ là config explicit.

## 9. Execution profile

- **Quyết định HUMAN LEAD (2026-09-26):** `dual-agent` mặc định cho các checkpoint (main session = ORCHESTRATOR, `.claude/agents/implementer` = IMPLEMENTER theo `.claude/rules/execution.md`); đổi profile cho một task vẫn cần HUMAN LEAD approve.

## 10. Dependency policy & proposals

Nguyên tắc: stdlib trước; mỗi dependency qua dependency proposal; không thêm dependency ngoài danh sách được duyệt.

| Library | Purpose | Vì sao cần | Alternative | Impact |
|---|---|---|---|---|
| Python ≥ 3.11 + `venv` + `pip`, `pyproject.toml` (hatchling) | runtime + packaging | giống reference, không cần tool thêm | `uv`, conda env | `.venv/` trong repo (đã gitignore) |
| `yt-dlp` | tải video + lấy caption YouTube (kể cả auto-generated) | một lib cho cả download và transcript YouTube | `youtube-transcript-api` (+ vẫn cần downloader) | runtime |
| `faster-whisper` | fallback transcript khi không có caption hợp lệ | local, có timestamp, đã kiểm chứng ở reference | `openai-whisper` (nặng hơn) | runtime, model tải về `models/` |
| `pytest` | test | chuẩn | `unittest` stdlib | dev only |
| `ffmpeg`/`ffprobe` (system binary) | probe, cắt, compose, render; scene detect bằng filter `select=gt(scene,…)` | không có thay thế thực tế | PySceneDetect (thêm dep) | cần cài hệ thống |
| Ollama HTTP API qua `urllib` | clip selection + title | không cần SDK | `ollama` python client | không thêm dep |

- **Quyết định HUMAN LEAD (2026-09-26):** config dùng **TOML / `tomllib`** (stdlib); **không** thêm `pyyaml`.

## 11. Local GPU / Ollama assumptions

- Ollama chạy trên **máy GPU riêng**, truy cập qua `OLLAMA_HOST` (mặc định đề xuất `http://127.0.0.1:11435` theo HUMAN LEAD); code không hard-code host/model.
- **Quyết định HUMAN LEAD (2026-09-26):** host mặc định `http://127.0.0.1:11435`, model khởi đầu `gemma3:12b`; chốt lại bằng đo đạc ở CP5/CP10.
- Whisper chỉ là fallback; trên VM không GPU chạy CPU (`int8`, 48 core). Đo thực tế ở CP11.
- Môi trường (kiểm 2026-09-26): `ffmpeg` 6.1.1 đã cài (`/usr/bin/ffmpeg`). Ollama `127.0.0.1:11435` phản hồi, version 0.34.4; model có sẵn: `qwen3:30b`, `qwen3:14b`, `qwen3-embedding:8b`, `qwen3-embedding:4b` — **chưa có `gemma3:12b`** (xem §12).
- `yt-dlp` 2026.08.19 cài dạng binary ở `~/.local/bin` (tool máy dùng chung để tải video test); việc dùng `yt-dlp` làm dependency Python của project vẫn theo §10.

## 12. Open questions cho HUMAN LEAD

Đã chốt 2026-09-26: duration (§3), layout (§4), số clip + ưu tiên ý trọn vẹn (§5), subtitle (§7), execution profile (§9), config format (§10), Ollama host (§11), video test (§1).

Còn mở:

1. Model khởi đầu: máy GPU chưa có `gemma3:12b`. Pull `gemma3:12b` như đã chốt, hay đổi sang `qwen3:14b` / `qwen3:30b` đang có sẵn?
2. Chấp nhận hoặc sửa các đề xuất còn lại: §1 (input), §2 (output), §5 (các boundary khác), §6 (title/header), §8 (artifact model), §10 (danh sách dependency).
