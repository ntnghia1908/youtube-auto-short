"""Render Shorts first and reserve a slot while AI still has work; no workers or services needed."""

from collections import deque

import pytest

from auto_short.web.jobs import (AI, KIND_ADD, KIND_PIPELINE, KIND_RENDER, KIND_VERTICAL, RENDER,
                                 Job, JobRunner, Step)


def _job(number, kind=KIND_VERTICAL, episode_id=None):
    return Job(str(number), episode_id or f"video-{number}", kind, lambda job: None)


@pytest.mark.parametrize("kind,episode_id", [
    (KIND_PIPELINE, "short"), (KIND_PIPELINE, "lecture.kt"), (KIND_RENDER, "short"), (KIND_ADD, "short"),
])
def test_non_vertical_precedes_marked_vertical(kind, episode_id):
    r = JobRunner(render_workers=2, cpu_source=lambda: 0.0)
    vertical, short = _job(1), _job(2, kind, episode_id)
    r.priority.mark([vertical.episode_id])
    queue = deque([vertical, short])
    with r._lock:
        assert r._render_pick_locked(queue, extra=False) == (short, False)
        assert list(queue) == [vertical]


@pytest.mark.parametrize("marked", [False, True])
def test_p2_and_fifo_within_short_group(marked):
    r = JobRunner(cpu_source=lambda: 0.0)
    vertical = _job(1)
    first, second = _job(2, KIND_RENDER), _job(3, KIND_PIPELINE, "lecture.kt")
    r.priority.mark([vertical.episode_id] + (["lecture"] if marked else []))
    queue = deque([vertical, first, second])
    expected = [second, first] if marked else [first, second]
    with r._lock:
        for job in expected + [vertical]:
            assert r._render_pick_locked(queue, extra=False) == (job, False)


@pytest.mark.parametrize("workers", [1, 2, 4])
@pytest.mark.parametrize("ai_state", ["queued", "running"])
@pytest.mark.parametrize("extra", [False, True])
def test_vertical_reserves_last_slot_while_ai_busy(workers, ai_state, extra):
    r = JobRunner(render_workers=workers, cpu_source=lambda: 0.0)
    slots = [slot for slot, lane in r._slot_lane.items() if lane == RENDER]
    for number, slot in enumerate(slots[:-1], 1):
        r._current[slot] = _job(number)
    ai, vertical = _job(10, KIND_PIPELINE), _job(11)
    if ai_state == "queued":
        r._queues[AI].append(ai)
    else:
        r._current[AI] = ai
    queue = r._queues[RENDER]
    queue.append(vertical)
    with r._lock:
        if workers == 1:
            assert r._render_pick_locked(queue, extra=extra) == (vertical, False)
        else:
            assert r._render_pick_locked(queue, extra=extra) == (None, False)
            assert list(queue) == [vertical]
            r._queues[AI].clear()
            r._current[AI] = None
            assert r._render_pick_locked(queue, extra=extra) == (vertical, False)


def test_reservation_counts_vertical_jobs_only():
    r = JobRunner(render_workers=4, cpu_source=lambda: 0.0)
    r._current[RENDER] = _job(1)
    r._current[f"{RENDER}#1"] = _job(2, KIND_RENDER)
    r._current[f"{RENDER}#2"] = _job(3, KIND_RENDER)
    r._queues[AI].append(_job(4, KIND_PIPELINE))
    vertical = _job(5)
    with r._lock:
        assert r._render_pick_locked(deque([vertical]), extra=True) == (vertical, False)


@pytest.mark.parametrize("workers", [2, 3, 4])
def test_vertical_uses_all_slots_when_ai_idle(workers):
    r = JobRunner(render_workers=workers, cpu_source=lambda: 0.0)
    jobs = [_job(number) for number in range(1, workers + 1)]
    queue = deque(jobs)
    with r._lock:
        for slot, job in zip((s for s, lane in r._slot_lane.items() if lane == RENDER), jobs):
            assert r._render_pick_locked(queue, extra=slot != RENDER) == (job, False)
            r._current[slot] = job
        assert len(r._lane_running_locked(RENDER)) == workers
        assert not queue


@pytest.mark.parametrize("to_render", [False, True])
def test_ai_completion_notifies_reserved_render_slot(monkeypatch, to_render):
    r = JobRunner(render_workers=2, cpu_source=lambda: 0.0)
    r._current[RENDER] = _job(1)
    ai, vertical = _job(2, KIND_PIPELINE), _job(3)
    ai.steps = [Step(AI, ai.target)] + ([Step(RENDER, ai.target)] if to_render else [])
    r._current[AI] = ai
    queue = r._queues[RENDER]
    queue.append(vertical)
    with r._lock:
        assert r._render_pick_locked(queue, extra=True) == (None, False)
    notifications = []
    monkeypatch.setattr(r._lock, "notify_all", lambda: notifications.append(True))
    r._after(AI, ai, ok=True)
    assert notifications
    with r._lock:
        assert not r._queues[AI] and not r._lane_running_locked(AI)
        assert r._render_pick_locked(queue, extra=True) == (ai if to_render else vertical, False)
