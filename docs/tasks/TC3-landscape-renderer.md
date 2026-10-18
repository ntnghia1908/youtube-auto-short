# Task: TC3 — Landscape Thematic Compilation Renderer

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code — main session (Opus), review độc lập
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort high), một writer; pilot Codex IMPLEMENTER đầu tiên (project-profile §7)
- Human Lead: HUMAN LEAD
- Authorization mode: boundary
- Authorization source: `docs/decisions/TC1-TC3-implementation-authorization.md` §5 + A1; G2 TC2 (“Tải lại file nguồn nếu cần”)
- Parallel group: —
- Owned paths: `src/auto_short/theme_render/` (mới), `tests/test_theme_render.py` (mới), contract này
- Dependencies: TC2 phase A (`src/auto_short/theme_plan/`, `approved_plan`); không dependency thư viện mới
- Base commit / branch: `ceda96b` (TC2 phase A READY) / `feature/tc2-theme-plan` (cùng branch, tuần tự, một writer)
- Human Lead approval: inherited from boundary
- Implementation authorized: YES

Lifecycle: `boundary` mode = `DRAFT → IN_PROGRESS → READY`. Web (job làn render, nút tải) thuộc TC2 phase C (chờ G3).

## Goal

Từ một plan TC2 đã duyệt, xuất một MP4 ngang 16:9 (1920×1080) dựng lại từ video nguồn đầy đủ khung hình, giữ đúng phần lời và các điểm cắt của từng khai thị đã duyệt, theo thứ tự plan; kèm chapters + mô tả YouTube. Không kéo giãn / crop Short 9:16.

## Scope

- In scope: callable `render_landscape(config, playlist_id, plan_id, *, runner=..., downloader=...)`; chọn / tải lại nguồn; dựng từng clip; kiểm tương đương lời nói; ghép; metadata; cache; dọn file tạm.
- Out of scope: web / job / UI (phase C), sửa render Short, sửa CP8.32 / CP8.33 / archive, tiêu đề chữ trên video, publish.

## Authority / key decisions (S1 cục bộ, ORCHESTRATOR)

- Plan phải `approved` (`theme_plan.approved_plan`); stale / draft → từ chối, không render.
- Clip: tái dựng bằng TC1 (record hiện tại: `final_segments`, `source_reference`, identity); `input_fingerprint` phải bằng snapshot trong plan.
- Nguồn: dùng file `source_reference` nếu còn và sha khớp (`source_status: present`). Mất → tải lại bằng downloader của ingest (`ingest.youtube.ytdlp_download`, `[ingest]`, URI trong `manifest.json` của workspace) vào thư mục tạm riêng `output/_compilations/<pid>/theme/.fetch/` (không ghi vào `work/`, không đụng `archive.json`, không phụ thuộc ngưỡng 720p của CP8.32); YouTube chặn (`ingest.youtube.YoutubeBlocked`) → raise `render.full.SourceBlocked` để web chờ; xóa sau khi dùng (mọi kết cục). Nhiều clip cùng video dùng chung một lần tải.
- Dựng clip: cùng frame / dissolve logic của Short (`render.plan.frame_plan`, `dissolve_plan`, `_video_cut` / `_video_dissolve`, dissolve = cấu hình khai thị qua `render_config_for`), per-frame scale giữ tỉ lệ vào 1920×1080 + pad đen, audio = atrim đúng các segment như Short; encode bằng `render.plan.ffmpeg_command` + `[render]` crf / preset / audio_bitrate / threads; fps = `plan.output_fps(source)`.
- Kiểm tương đương lời nói (fail closed): giải mã audio clip mới và audio Short đã render (file trong `render_manifest`, sha khớp) hoặc bản kept của CP8.33 → mono 16 kHz; envelope RMS 20 ms; tìm lệch tốt nhất trong ±0,5 s; yêu cầu |lag| ≤ 0,04 s, tương quan ≥ 0,9, chênh thời lượng ≤ 0,1 s. Không đạt → lỗi có lý do cho người dùng, không ghép. Python thuần (không numpy). Ngưỡng là hằng số module.
- Ghép: `compilation.assemble.assemble` (copy, các clip cùng thông số). Chapters / mô tả: `compilation.meta.chapters` / `description("concat", ...)`, tiêu đề chương = tiêu đề Short trong render manifest (fallback `T<tập> KT<n>`).
- Output: `output/_compilations/<pid>/theme/<plan_id>-r<revision>.mp4` + `.json` {schema_version, plan_id, revision, plan_fingerprint, encode key, clips [{id, source: present|refetched, warning, audio_match {corr, lag, duration_diff}}], duration, chapters, description, download_name, created_at, sha256}. Ghi tạm rồi rename; cache reuse khi plan_fingerprint + encode key + sha file khớp. Không đụng `<cid>.json` / favorites / kept của CP8.33.
- `nice`: caller (web) lo; module không tự đổi priority.

## Acceptance Criteria

1. Plan chưa duyệt / stale / fingerprint clip lệch → từ chối, không ghi output.
2. Output 1920×1080, SAR 1, có audio + video, thời lượng = tổng thời lượng clip (± 1 frame / clip); thứ tự = plan; chapters bắt đầu đúng tổng các clip trước.
3. Audio mỗi clip khớp Short đã duyệt theo ngưỡng; nguồn lệch (offset, nội dung khác) → fail closed với lý do; test có ca nguồn lệch.
4. Nguồn mất → tải lại (downloader inject trong tests), dùng xong xóa thư mục tạm cả khi lỗi; chặn YouTube → lỗi riêng.
5. Cache: gọi lại cùng plan → reuse không encode; plan revision mới → file mới.
6. Không sửa file ngoài Owned paths; CP8.33 / Short không đổi; full suite PASS.

## Required verification

- `env PYTHONPATH=/home/ntnghia/youtube-auto-short-tc2/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_theme_render.py tests/test_theme_plan.py tests/test_theme_index.py -x --tb=short` — gồm ít nhất một test ffmpeg thật trên nguồn tổng hợp (lavfi testsrc + tiếng) dựng 2 clip, tạo "Short" tham chiếu, kiểm AC2–AC5.
- Cùng prefix `-m pytest -q -n auto` — full suite.
- `node scripts/framework-check.mjs`; `git diff --check`; inventory ⊆ Owned paths.
- ORCHESTRATOR: chạy thật trên bản sao dữ liệu (hard link, không ghi production) một plan nhỏ, xem frame + nghe thử.

## Manual test checklist (Tech Lead)

Không chạm database / security / public API (web ở phase C).

- [ ] Xem video ngang xuất từ plan thật: nội dung và điểm cắt giống Short đã duyệt; chapters đúng.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
