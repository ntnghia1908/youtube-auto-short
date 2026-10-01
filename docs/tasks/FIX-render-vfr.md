# Task: FIX-render-vfr — Render lỗi "frame rate" với nguồn có avg_frame_rate lẻ

## Status / Approval

- Status: APPROVED
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project; thay đổi nhỏ, một module.
- Base commit / branch: `224f166` (`origin/main` 2026-10-01) / `fix/render-vfr` (worktree `../youtube-auto-short-render-vfr`)
- Human Lead approval: accepted (HUMAN LEAD 2026-10-01: APPROVE F1–F5 theo đề xuất, S1)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì sửa trong boundary đã duyệt: CP7 R6 "fps giữ nguồn nếu ≤ 30, ngược lại 30" không quy định đọc trường nào của ffprobe; R9 (`r_frame_rate` của file ra = fps R6) giữ nguyên. Không đổi schema, không đổi `config_hash`, không thêm dependency. Nếu HUMAN LEAD muốn ghi luật chọn fps vào CP7 R6 thì nâng S2 (F4).

## Bối cảnh (ORCHESTRATOR điều tra 2026-10-01)

Web 8080: render `failed` ở cả 6 tập của 3 video (mọi stage trước `done`, chưa có Short nào trong `output/`):

| Tập | `r_frame_rate` nguồn | `avg_frame_rate` nguồn | Lỗi (`~/.local/state/auto-short/web.log`) |
|---|---|---|---|
| `2mVA5If4M3w`, `.kt` | `30000/1001` | `50304000/1678477` | `frame rate 192977/6439 != 50304000/1678477` |
| `jr8mue8TJA0`, `.kt` | `30000/1001` | `2495575/83269` | (cùng dạng) |
| `VlLxSpVCcws`, `.kt` | `30000/1001` | `112318000/3747677` | `frame rate 943067/31467 != 112318000/3747677` |

Nguồn: VP9, `time_base=1/16000`; `avg_frame_rate` = nb_frames / duration ≈ 29.97 nhưng là phân số lẻ (container lệch vài ms). Mọi nguồn khác trong `work/` có `avg_frame_rate = r_frame_rate = 30000/1001`.

Nguyên nhân: `render/stage.py::_rate` ưu tiên `avg_frame_rate` → `output_fps` = phân số lẻ → `-r 50304000/1678477`; encoder/muxer không biểu diễn được phân số đó nên file ra có `r_frame_rate` khác (`192977/6439`) → `verify_output` (R9: so khớp đúng `r_frame_rate`) báo lỗi. File ra thực chất ≈ 29.97 fps, chỉ fps kế hoạch là sai.

## Goal

Tập có nguồn mà `avg_frame_rate` là phân số lẻ render thành công với fps chuẩn (`30000/1001` ở các nguồn hiện có); tập đã render không bị render lại.

## Quyết định cục bộ (HUMAN LEAD 2026-10-01: APPROVE F1–F5)

- **F1. Luật chọn fps nguồn** (thay `_rate` trong `render/stage.py`): lấy `r_frame_rate` nếu hợp lệ (> 0) và lệch `avg_frame_rate` ≤ 1 %; nếu không (ví dụ `r_frame_rate` là tbr cao kiểu `1000/1` của VFR thật, hoặc thiếu), lấy `avg_frame_rate` rồi **chuẩn hóa** về fps chuẩn gần nhất trong {`24000/1001`, 24, 25, `30000/1001`, 30, 50, `60000/1001`, 60} nếu lệch ≤ 1 %, không thì `Fraction.limit_denominator(1001)`. Sau đó áp `output_fps` (cap 30) như cũ. Không có trường nào hợp lệ → `RenderError` như cũ.
- **F2. Không làm stale tập cũ:** với mọi nguồn có `avg = r_frame_rate` (toàn bộ tập đã render), F1 cho cùng fps → `render_key` không đổi, không Short nào render lại. 6 tập lỗi chưa có Short nên không có gì stale.
- **F3. `verify_output` giữ nguyên** (so khớp đúng `r_frame_rate`, R9) — không nới thành dung sai, vì lỗi nằm ở fps kế hoạch chứ không ở kiểm tra.
- **F4. Không ghi vào CP7** (S1). Phương án khác: thêm một câu "fps nguồn = …" vào CP7 R6 → S2.
- **F5. Ngoài scope:** `ingest/probe.py::_fps` cũng ưu tiên `avg_frame_rate` nhưng chỉ ghi `metadata.json` làm tròn 3 chữ số (29.97 cả hai cách) → không đổi, tránh làm stale ingest/analysis.

## Scope

- In scope: `_rate` (hoặc hàm mới trong `render/plan.py`) theo F1; unit test cho F1 (nguồn hiện có: r = avg; ba cặp r/avg lỗi ở bảng trên → `30000/1001`; r = `1000/1` + avg ≈ 29.97 → `30000/1001`; avg ≈ 25.01 không có r → 25; chỉ có một trường; không trường nào hợp lệ → `RenderError`); log stderr fps đã chọn (đã có dòng fps ở CLI render, R9 stderr).
- Out of scope: F5; dung sai trong `verify_output`; đổi `RENDER_PLAN_VERSION`; tự render lại 6 tập (HUMAN LEAD bấm "Chạy tiếp" trên web sau khi 8080 ghim commit mới).

## Authority / key decisions

- `docs/decisions/CP7-render-contract.md` R6 (fps giữ nguồn ≤ 30), R9 (kiểm `r_frame_rate`), CP8.2 T5 (`render_key` gồm fps).
- F1–F5 ở trên.

## Implementation approach

- Hàm thuần `source_fps(stream) -> Fraction` (dễ test, không cần ffmpeg), `_rate` gọi nó.
- Test tích hợp nhỏ: tạo nguồn ngắn VFR / có `avg_frame_rate` lẻ bằng ffmpeg trong test (như fixture media sẵn có của `tests/test_render_stage.py`) rồi render một clip qua `verify_output`. Nếu không tạo lại được avg lẻ bằng ffmpeg thì ghi rõ, dựa vào unit test + manual test.

## Acceptance Criteria

1. Với ba cặp (r, avg) ở bảng bối cảnh, fps kế hoạch = `30000/1001`.
2. Với nguồn `r = avg = 30000/1001`, fps và `render_key` không đổi so với `origin/main` (test so `render_key` trên fixture hiện có).
3. Các trường hợp biên F1 có unit test PASS.
4. Toàn bộ suite PASS: `python -m pytest -q -n auto`.
5. Render thật một tập lỗi (bản sao dữ liệu, không ghi vào `work/` / `output/` chính) thành công, mọi Short qua `verify_output`.

## Required verification

- `python -m pytest -q -x tests/test_render_stage.py tests/test_render_plan.py` (hoặc file test mới) — AC1–AC3.
- `python -m pytest -q -n auto` — AC4.
- Sao `work/jr8mue8TJA0` (và `.kt` nếu đủ thời gian) sang thư mục test riêng (`~/.cache/auto-short-render-vfr-test/`, hard-link `source.mp4`), chạy `auto-short render <id> --config <config test>` từ worktree → exit 0, `render_manifest.json` `fps = "30000/1001"` — AC5.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database, security model hoặc public API contract → manual test là điểm danh sau automated verification.

- [ ] Xem 1–2 Short của `jr8mue8TJA0` (bản test): hình / tiếng khớp, không giật.
- [ ] Sau merge + ghim 8080: "Chạy tiếp" 6 tập lỗi trên web, render `done`.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
