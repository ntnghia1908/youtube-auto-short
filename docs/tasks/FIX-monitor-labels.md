# Task: FIX-monitor-labels — Tab "Theo dõi" hiện tên tập thay vì mã video

## Status / Approval

- Status: READY
- Type: BUG
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: `.claude/agents/implementer` (Sonnet) — mặc định dual-agent của project.
- Base commit / branch: `7a734fe` (`main`) / `fix/monitor-labels` (worktree `../youtube-auto-short-monlabel`)
- Human Lead approval: APPROVED 2026-10-04 ("Tab theo dõi hàng đợi nên để tên tập thay vì mã")
- Implementation authorized: YES

Lifecycle: `DRAFT → APPROVED → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

S1 vì: chỉ đổi cách hiển thị nhãn tập trong tab Theo dõi (CP8.28); không đổi dependency, security model, public API ngoài trường nhãn.

## Bối cảnh

`web/monitor.episode_label` lấy bộ kinh / số tập từ dữ liệu sau titling; job chưa tải / chưa titling (gần như mọi job chờ — ví dụ 86 tập Địa Tạng "Chuẩn bị + HD") rơi về mã video `ND1Eu4aax44`.

## Goal

Mọi dòng job trong tab Theo dõi (đang chạy, đang đợi, chờ) hiện tên dễ đọc "<bộ kinh> · Tập N" (+ "(khai thị)"), mã video nhỏ bên cạnh; chỉ khi không có nguồn nào mới hiện mã.

## Scope

- In scope: thứ tự nguồn nhãn: (1) dữ liệu hiện có (`titles.json` / CP8.11); (2) `metadata.json` title qua `[titling.header] title_patterns` (như `enhance/service._series_episode`); (3) bộ kinh đã lưu `_playlists/*.json` (entry có `video_id` → tên bộ kinh / `series` + `episode`, hoặc `title` của entry); (4) mã video. Cache nhẹ (theo mtime hoặc vài chục giây) để làm mới 4 s không đọc lại mọi file; UI hiện nhãn chính + mã nhỏ (title tooltip). Test.
- Out of scope: đổi trang khác; đổi API ngoài trường nhãn.

## Acceptance Criteria

1. Job chờ chưa tải của một video thuộc bộ kinh đã lưu → nhãn "<bộ kinh> · Tập N"; `.kt` → thêm "(khai thị)".
2. Video đã tải nhưng chưa titling → nhãn từ `metadata.json` title.
3. Không nguồn nào → mã video (như cũ).
4. API monitor 100 job chờ vẫn trả nhanh (cache; test đếm số lần đọc file hoặc thời gian hợp lý).
5. Không regression: lệnh chuẩn PASS.

## Required verification

- `python -m pytest -q -n auto` (PYTHONPATH=worktree `src`) — AC 1–5.
- `node scripts/framework-check.mjs`.

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Không chạm database / security model / public API. Điểm danh trên 8080: tab Theo dõi, danh sách chờ hiện "Kinh Địa Tạng Bồ Tát Bổn Nguyện · Tập N".

## Result

- Main changes: `web/monitor.episode_label` tách thành `_compute_label` với thứ tự nguồn titles.json → `metadata.json` title (`title_patterns`) → `_playlists/*.json` (bộ kinh + tập, hoặc title entry) → mã video; `.kt` chưa ingest vẫn "(khai thị)". Cache: nhãn theo (workspace, id) và chỉ mục playlist 20 s (`LABEL_CACHE_SECONDS`). `app.js`: nhãn chính + mã video nhỏ (title tooltip) cạnh tên job (`jobCode`).
- Tests: 5 test mới trong `tests/test_monitor_cp828.py` (playlist, title entry, metadata, mã video, 100 job đọc playlist 1 lần); `pytest -q -n auto` 1502 passed, 1 skipped; `node scripts/framework-check.mjs` PASS.
- Review: ORCHESTRATOR 2026-10-04 — ACCEPTED, không có blocking finding (thứ tự nguồn nhãn đúng contract, cache 20 s, đổi cục bộ phần monitor; chạy lại 22 test monitor PASS). Non-blocking: nhãn từ `title_patterns` có thể giữ tiền tố "[HD] " (giống `_series_episode`).
- Important findings / decisions: kiểm trên dữ liệu thật (đọc): `ND1Eu4aax44` -> "Kinh Địa Tạng Bồ Tát Bổn Nguyện · Tập 3"; nhãn từ title patterns/playlist có thể mang tiền tố "[HD] " nếu pattern `series` bắt cả tiền tố (giống `_series_episode`).
- Known limitations: nhãn mới đổi tối đa sau 20 s.
- PR: #70
