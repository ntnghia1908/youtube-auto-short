# Task: CP8.29 — Làn chuẩn bị chạy song song nhiều tập

## Status / Approval

- Status: APPROVED
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `8de06c9` (`main`) / `feature/cp8.29-parallel-prepare` (worktree `../youtube-auto-short-pprep`)
- Human Lead approval: APPROVED 2026-10-04 ("Làm B ngay" — phương án B ORCHESTRATOR đề xuất cùng ngày: 2–3 tập chuẩn bị song song, chia luồng Whisper)
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: mở rộng số worker của một làn trong khuôn CP8.10 (làn vẫn là `prepare` / `ai` / `render`), thêm khóa config; không đổi dependency, security model, public API.

## Bối cảnh (2026-10-04)

- VM nay 32 nhân, 125 GB RAM (dùng ~9 GB). Làn `prepare` (ingest → transcript → analysis) chạy **một job một lúc**; 86 tập Địa Tạng ("Chuẩn bị + HD", CP13.2) cần Whisper CPU (`large-v3-turbo`, int8, `[transcript.whisper] cpu_threads = 24`) ~20–25 phút / tập → ~30–36 giờ tuần tự; 3090 rảnh trong lúc đó.
- Whisper không tăng tuyến tính theo luồng: CP11 đo 24 luồng nhanh hơn 48 trên máy 48 nhân → chạy 2–3 tập song song với ít luồng hơn mỗi tập thường cho tổng thông lượng cao hơn.
- `transcript/whisper.py` cache model theo khóa có `effective_cpu_threads`.

## Amendment 1 (HUMAN LEAD 2026-10-04)

"Chừa lại 4 core để chạy web và tải video mượt" → tổng luồng tính toán (Whisper của các job chuẩn bị + ffmpeg render `[render] jobs` × luồng mỗi job) đặt sao cho chừa ≥ 4 nhân: cấu hình đề xuất dùng tối đa 28 luồng cho Whisper khi làn render rảnh, và tổng Whisper + render không vượt 28 khi cả hai chạy (giới hạn luồng ffmpeg render nếu cần — IMPLEMENTER đề xuất cách, ví dụ `[render] threads`); đo P4 dưới ràng buộc này. Có thể giảm ưu tiên CPU (nice) cho tiến trình con nặng (ffmpeg) để web / tải không bị chậm — ghi rõ nếu làm.

## Goal

Làn `prepare` chạy tối đa N job cùng lúc (khóa config, mặc định 1 = như cũ), mỗi job Whisper dùng số luồng đã chia; đo và đặt N + luồng tối ưu cho 32 nhân để 86 tập Địa Tạng chuẩn bị nhanh hơn ≥ 1,8 lần.

## Scope

- In scope:
  - **P1 Config.** `[web] prepare_workers` (1–8, mặc định 1) và `[transcript.whisper] cpu_threads_per_job` (0 = `cpu_threads` / `prepare_workers`, làm tròn xuống, tối thiểu 1) hoặc cách tương đương IMPLEMENTER chọn (ghi Result). `cpu_threads` không đổi nghĩa khi `prepare_workers = 1`; không đổi hash transcript (thực thi, như CP11 R2).
  - **P2 Hàng đợi.** Làn `prepare` có N thread worker; giữ đúng các luật hiện có: thứ tự + ưu tiên (CP8.26), tạm dừng toàn cục (CP8.22), đợi YouTube (chỉ job cần tải bị chặn; nhiều worker cùng thấy chặn), prefetch (`PREFETCH_LIMIT` theo job đã chuẩn bị đợi làn `ai`; job prepare-only CP13.2 không tính), đợi GPU, bền qua khởi động lại, CP8.28 monitor (hiện N job đang chạy của làn), log job theo thread. Một episode không chạy hai job cùng lúc (khóa episode sẵn có); Short và `.kt` cùng video có thể chạy song song nếu an toàn (ingest `.kt` dùng nguồn gốc — đợi ingest gốc xong, nếu cần thì không chạy cùng lúc).
  - **P3 Whisper.** Model cache an toàn khi nhiều thread (mỗi thread / mỗi số luồng một instance hoặc khóa — IMPLEMENTER chọn, đo RAM); `cpu_threads` cho mỗi job theo P1.
  - **P4 Đo.** Trên bản sao 3–4 tập Địa Tạng (audio thật, không ghi `work/` chính): đo thời gian chuẩn bị tổng cho N = 1 / 2 / 3 / 4 với luồng chia tương ứng (và một mức luồng khác nếu rẻ), ghi load; chọn mặc định đề xuất cho `config.toml` (ORCHESTRATOR áp dụng sau merge, ghi trong Result). Chạy đo khi các thí nghiệm khác đã xong hoặc ghi rõ nhiễu.
  - Test + README / Test policy nếu cần.
- Out of scope: Whisper trên GPU (CP14); song song làn `ai` / `render` (`[render] jobs` đã có); đổi model Whisper.

## Authority / key decisions

- `docs/tasks/CP8.10-queue-lanes.md`, `docs/tasks/CP8.22-queue-pause-persist.md`, `docs/tasks/CP8.26-priority.md`, `docs/tasks/CP8.28-monitor.md`, `docs/tasks/FIX-youtube-botcheck-wait.md`, `docs/tasks/CP13.2-hd-first.md`, `docs/tasks/CP11-performance-measure.md` + `docs/decisions/CP11-performance-report.md` (R2 luồng Whisper).

## Acceptance Criteria

1. `prepare_workers = 1`: hành vi giống hệt trước (test hiện có PASS).
2. `prepare_workers = 3`, 6 job giả: tối đa 3 chạy cùng lúc, thứ tự bắt đầu theo hàng đợi + ưu tiên; tạm dừng / đợi YouTube / khởi động lại đúng.
3. Whisper mỗi job nhận đúng số luồng chia; transcript giống hệt (byte) với chạy tuần tự cùng tham số model (hoặc ghi rõ nếu số luồng khác làm đổi kết quả và hash không đổi).
4. Đo P4: bảng thời gian N = 1..4; mức đề xuất nhanh hơn N = 1 ≥ 1,8 lần (hoặc ghi lý do + số tốt nhất).
5. Monitor (CP8.28) hiện mọi job đang chạy của làn `prepare`.
6. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–3, 5, 6.
- Đo P4 thật (bảng trong Result) — AC 3, 4.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080 sau khi đặt config: tab Theo dõi thấy N job chuẩn bị chạy cùng lúc; CPU VM dùng nhiều hơn.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
