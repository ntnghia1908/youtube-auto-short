# Task: SRC3 — Sửa tập đã dọn tự lấy lại nguồn (3090 trước YouTube)

## Status / Approval

- Status: APPROVED
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Orchestrator: claude-code
- Implementer: codex — `codex exec` (gpt-6.1-sol, effort `high`), một writer; test web / full suite do ORCHESTRATOR chạy ngoài sandbox
- Authorization mode: task
- Authorization source: `docs/decisions/SRC3-SRC4-store-first-sources.md` G1–G3 (ACCEPTED 2026-10-25, G1–G3; G2 = a)
- Parallel group: SRC3 ∥ SRC4 (Owned paths rời nhau)
- Owned paths: `src/auto_short/review/archive.py` (`restore_source`, kiểm bản khác byte); `src/auto_short/web/routes/episode_edit.py` (5 route sửa); `src/auto_short/web/app.py` (chỉ target khôi phục + nối thao tác sau khôi phục); `src/auto_short/web/static/` phần trang tập (trạng thái "đang lấy lại nguồn"); `tests/test_restore_source_cp837.py`, `tests/test_src3_auto_restore.py` (mới); file này
- Dependencies: SRC1 (#154), SRC2 (#155) — làm sau khi merge
- Base commit / branch: `docs/src3-src4` (xếp chồng SRC2 #155 → SRC1 #154; rebase lên main sau merge) / `feature/src3-auto-restore`
- Human Lead approval: accepted — HUMAN LEAD 2026-10-25 "Duyệt cả hai"
- Implementation authorized: YES

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`.

S2 vì đổi luật CP8.6 S3 (tập `archived` từ chối sửa) và CP8.37 (chỉ nhận đúng sha).

## Goal

Sửa tiêu đề / cắt lại / thêm / khôi phục Short trên tập đã dọn chạy được ngay: web tự lấy lại nguồn (3090 trước YouTube) rồi làm tiếp thao tác, không bắt bấm "Khôi phục nguồn" trước.

## Scope

- In scope: G1, G2 a.
- Out of scope: G4 (chỉ đổi `config.toml`); sửa transcript / analysis; ingest (SRC4); ghép chủ đề (TC3.2).

## Authority / key decisions

- G1: 5 route trong `episode_edit.py` đang trả 409 `ArchivedError` → xếp job khôi phục (làn prepare, `YoutubeWait` khi chặn) rồi xếp thao tác; trả 202 + trạng thái. Hai lần sửa liên tiếp trên cùng tập dùng chung một job khôi phục.
- G2 a (HUMAN LEAD chọn): bản khác sha nhận khi thời lượng khớp và mọi Short đã render khớp `theme_render.audio.compare` với |lag| ≤ 1 khung; `restored.json` ghi `differs_from_ingest`, sha mới; `manifest.source` giữ nguyên.

## Implementation approach

- `restore_source(…, accept_redownload=…)`: sau khi bản tải về không trùng sha → nếu G2 a: kiểm thời lượng + audio từng Short (dùng lại `audio.compare`, `_reference`-tương đương lấy Short từ `render_manifest.json`) trong thư mục tạm; đạt → cài như hiện nay, ghi provenance.
- Web: target khôi phục hiện có (`app.py` ~123) nhận "thao tác tiếp theo" (route + payload đã kiểm) và submit khi xong; route trả 202 kèm job id.
- Frontend: thông báo "đang lấy lại nguồn từ 3090…" thay lỗi 409.

## Phải giữ nguyên

- Nút "Khôi phục nguồn" và API hiện có; rollback khi cài lỗi; grace `restored.json`; luật dọn của SRC1.

## Code bị thay / xóa

- Nhánh 409 `ArchivedError` trong 5 route (giữ class `ArchivedError` cho chỗ khác còn dùng).

## Acceptance Criteria

1. Sửa trên tập `archived` → job khôi phục + thao tác chạy nối tiếp; xong thì kết quả như tập chưa dọn.
2. Khôi phục lấy kho 3090 trước YouTube; YouTube chặn → chờ, không hỏng.
3. G2 a: bản khác byte đạt kiểm → khôi phục, `restored.json` ghi provenance; lệch > 1 khung / thời lượng sai → từ chối, không đổi file nào.
4. Full suite PASS.

## Required verification

- `env PYTHONPATH=<worktree>/src /home/ntnghia/miniconda3/envs/auto-short/bin/python -m pytest -q tests/test_restore_source_cp837.py tests/test_src3_auto_restore.py tests/test_web_app.py -x --tb=short` — AC 1–3.
- `… -m pytest -q -n auto`; `node --check` JS đã sửa; `node scripts/framework-check.mjs`; `git diff --check` — AC 4.
- Chạy thật trên 8080 (ghim branch, hỏi trước khi restart): sửa tiêu đề 1 Short của 1 tập đã dọn có bản trên 3090 → Short render lại.

## Manual test checklist (Tech Lead)

- [ ] Sửa tiêu đề Short trên tập đã dọn: thấy "đang lấy lại nguồn", sau đó Short mới đúng tiêu đề.

## Result

- Main changes:
