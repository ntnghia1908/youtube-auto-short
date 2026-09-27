# CL1 Roadmap — Chinese Learning

## Status / Approval

- Status: APPROVED
- Type: DOC
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: single-agent
- Human Lead: HUMAN LEAD
- Base commit / branch: `0a61637` / `docs/cl1-roadmap` (merged, PR #13)
- Human Lead approval: accepted 2026-09-27 (merge PR #13) — roadmap là bản đồ thực thi, không phải approval implementation
- Implementation authorized: NO

Roadmap, không phải task contract thực thi: mỗi bước (CL1.x, G6A, G6B) cần task contract riêng được approve.

## Goal

Thứ tự gate và bước thực thi CL1 sau CL1.1 — xem § Product objective, § Gate order.

## Scope

Các gate G6A/G6B, CL1.3 (+ C10), CL1.4 và phần ngoài scope — xem § Scope guard.

## Acceptance Criteria

Theo từng task contract của từng bước; acceptance G6A ở § G6A.

## Required verification

Theo từng task contract của từng bước.

## Status

- Main baseline: `0a61637` (CL1.1 merged, PR #12).
- CL1.2 local status reported by HUMAN LEAD on 2026-09-27: READY at local HEAD `415ae75`, branch `feature/cl1.2-lesson`, worktree `../youtube-auto-short-cl1`.
- CL1.2 is not yet present on GitHub because its local branch has not been pushed.
- G6 is intentionally **NOT APPROVED** yet.
- This roadmap is the execution map after CL1.1 and is not itself an approval to implement every future task.

## Product objective

Keep CL1 as a very small listening-comprehension loop:

`Listen → Chinese → Pinyin → Vietnamese → Replay → Next`

For the first experiment, correctness of the Chinese text/timestamps is authoritative; AI only enriches the lesson.

## Gate order

```
CL1.1 merged
   ↓
CL1.2 integration
   ↓
G6A: Pinyin authority strategy
   ↓
G6B: translation/model choice
   ↓
CL1.3 web backend + media serving
   ↓
C10 measurement / media decision
   ↓
CL1.4 web UI + localStorage progress
   ↓
HUMAN LEAD manual gate
   ↓
CL1 complete
```

Do not skip a gate by choosing a model merely because the pipeline is technically runnable.

## G6 — split into two decisions

### G6A — Pinyin authority

Current real-world measurement shows both tested LLMs can produce materially incorrect Pinyin. Examples recorded in the CL1.2 task report include wrong readings such as `这样` and `贩卖机`, inconsistent tone sandhi for `一/不`, and output-format drift.

Therefore, **do not treat an LLM as the final Pinyin authority yet**.

Evaluate these strategies in this order:

1. **Deterministic Pinyin library / hybrid** — propose a dependency such as `pypinyin` separately; use the library for baseline conversion and LLM only where context-sensitive handling is needed.
2. **LLM-only with stronger validation** — allowed only if a convincing validation strategy can detect wrong readings; schema/format validation alone is insufficient.
3. **Two-model agreement** — useful as an experiment, but agreement is not proof of correctness.

Acceptance for G6A:
- inspect the existing 20-line real sample;
- compare against expected readings;
- explicitly account for polyphonic characters and `一/不` tone changes;
- record false positives (wrong Pinyin accepted by validators).

### G6B — translation model

Choose a model for Vietnamese meaning separately from Pinyin quality.

The current measurement is evidence only:
- `qwen3:14b`: completed all three videos; some contextual translation errors were observed.
- `qwen3:30b`: faster on two successful runs, but one video failed validation because Pinyin contained the Han character `害`; it also showed formatting drift and at least one translation error.

No model is finally approved by this roadmap. HUMAN LEAD must inspect the 20-line sample and decide.

## Retry policy

Current behavior:
- retry is useful for transport/timeout/schema failures;
- with deterministic settings (`temperature=0`, fixed seed), retrying the same content error can reproduce the same answer.

For CL1, do **not** silently weaken validation.

Next investigation should compare:
- same-model retry with a changed prompt/repair instruction;
- optional retry with a different decoding setting;
- optional second-model verification;
- deterministic Pinyin fallback if G6A adopts a library.

Any change that alters reproducibility or model settings must be documented and included in the lesson configuration/invalidation contract.

## CL1.3 — Web backend + media

Implement only after CL1.2 integration.

Required outcomes:
- Learning router remains inside `src/auto_short/learning/`.
- Learning jobs use `kind=learning`, key `learning:<id>`.
- Existing Auto Short job/episode behavior remains unchanged.
- Protected Auto Short modules remain untouched.
- Learning routes inherit the existing authentication boundary.
- Clip route serves only server-resolved `work/_learning/<id>/clip.mp4`.
- Range requests must work for browser seeking.

### C10 media decision

CL1.1 proved that partial download works and does not download the whole source video.

Observed issue:
- `force_keyframes_at_cuts` causes H.264 re-encoding;
- clip size can become much larger than the source bytes for the first 5 minutes.

Default for CL1.3:
1. Measure current path first.
2. Prefer a source format that is already H.264/AAC when available.
3. Test whether partial retrieval can avoid re-encoding while preserving a usable browser clip.
4. Keep the current re-encode path as correctness fallback if the no-reencode path is unreliable.
5. Do not add a new dependency.

Record:
- source format;
- downloaded bytes;
- clip size;
- wall-clock time;
- ffprobe codecs;
- browser/mobile playback result;
- seek/range behavior.

## CL1.3 regression: stale lesson/media

Known issue from CL1.2 report:
- if `clip.mp4` is removed during media rerun/failure, an older `lesson.json` may still reference it.

Before READY for CL1.3, add a regression test and choose one explicit invariant:
- invalidate/remove lesson when media becomes unavailable, or
- make the learning API refuse to serve a lesson whose referenced media artifact is missing.

Do not leave a silently broken lesson page.

## CL1.4 — UI

After CL1.3 passes:

- `/learn` list + URL input
- `/learn/<id>` lesson player
- click line → seek
- current-line highlight
- repeat line
- speed 0.75 / 1.0
- independent Pinyin / Vietnamese visibility
- localStorage progress only
- mobile width target 360–640 px
- no external JS library / no build step

Manual gate:
- desktop;
- phone on LAN;
- 20-line content quality check;
- Auto Short behavior unchanged;
- delete isolation verified both directions.

## Scope guard

Still out of scope for CL1:
- Whisper Chinese fallback
- Simplified ↔ Traditional conversion
- dictionary/word segmentation
- pronunciation scoring
- TTS
- Anki/SRS/gamification
- accounts/database
- React/native mobile
- shared source cache across Auto Short and Learning

## Recommended implementation sequence

### Step 1 — integrate CL1.2
- Rebase/push local `feature/cl1.2-lesson` from main `0a61637`.
- Create PR for CL1.2.
- HUMAN LEAD reviews 20-line sample before approving G6.

### Step 2 — decide G6A
- Run a focused Pinyin quality experiment.
- Prepare dependency proposal if `pypinyin`/hybrid is the best engineering option.
- Do not modify CL1.3 while G6A is unresolved.

### Step 3 — decide G6B
- Choose the translation model only after reading real output.
- Record model, prompt version, and rationale in the CL1 contract.

### Step 4 — CL1.3
- Web backend/job routes.
- Media serving.
- C10 measurements.
- stale lesson/media regression.

### Step 5 — CL1.4
- UI + progress.
- docs update.
- final manual gate.

## Claude bootstrap

Use this as the next session context:

```
Bootstrap repo youtube-auto-short.

Current main baseline: 0a61637 (CL1.1 merged).

CL1.2 is READY locally at 415ae75 in worktree ../youtube-auto-short-cl1 on branch feature/cl1.2-lesson, but is not yet pushed.

Read:
- docs/tasks/CL1.2-ai-enrichment-lesson.md
- docs/tasks/CL1-chinese-learning-mvp.md
- docs/decisions/CL1-chinese-learning-contract.md
- docs/tasks/CL1-roadmap.md

HUMAN LEAD decisions:
1. Do not declare G6 model approval yet.
2. Separate G6 into:
   - G6A: Pinyin authority strategy
   - G6B: Vietnamese translation model
3. Investigate Pinyin correctness before selecting a model.
4. Keep Auto Short protected areas unchanged.
5. Do not begin CL1.3 implementation until CL1.2 integration is approved and G6A/G6B are resolved enough for implementation.

Next task:
prepare the G6A experiment and recommendation, using the existing 20-line real sample and the current CL1.2 artifacts/tests. Do not modify production behavior until HUMAN LEAD approves the proposed strategy.
```

## Human Lead decision log

- [2026-09-27] CL1.1 merged in PR #12.
- [2026-09-27] CL1.2 reported READY locally at `415ae75`.
- [2026-09-27] G6 not approved; both tested models show meaningful Pinyin errors.
