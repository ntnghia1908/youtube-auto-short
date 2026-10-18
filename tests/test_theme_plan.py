import json
from dataclasses import replace

import pytest

from auto_short import hashing, theme_plan as tp
from auto_short.review import logic
from auto_short.selection.client import ChatError, ChatResult
from auto_short.workspace import atomic_write_json

from test_theme_index import Fake as IndexFake, change, episode  # noqa: F401  (episode is a fixture)


class Planner(IndexFake):
    """Answers TC1 indexing calls like the TC1 fake and TC2 planning calls from ``themes``."""

    def __init__(self, themes=None, raw=None):
        super().__init__()
        self.themes, self.raw, self.plan_calls = themes, raw, []

    def chat(self, **kwargs):
        data = json.loads(kwargs['messages'][1]['content'])
        if 'clips' not in data:
            return super().chat(**kwargs)
        self.plan_calls.append(kwargs)
        if self.raw is not None:
            return ChatResult(self.raw)
        ids = [c['id'] for c in data['clips']]
        themes = self.themes(ids) if callable(self.themes) else self.themes
        return ChatResult(json.dumps({'themes': themes if themes is not None else
                                      [dict(label='Tu học', rationale='Cùng chủ đề tu học', clip_ids=ids)]}))


class Down:
    def chat(self, **kwargs):
        raise ChatError('connection refused')


def ids(n):
    return [f'lecture.kt/k{i:02d}' for i in range(1, n + 1)]


@pytest.fixture
def multi(episode):
    cfg, ws, folder, out = episode
    n = 8
    clips = dict(clips=[dict(id=f'k{i:02d}', candidate_id='c1', source_start=0, source_end=360, duration=350)
                        for i in range(1, n + 1)])
    atomic_write_json(ws.dir / 'clips.json', clips)
    shorts = []
    for i in range(1, n + 1):
        video = out / 'shorts' / f'k{i:02d}.mp4'
        video.write_bytes(f'rendered{i}'.encode())
        shorts.append(dict(clip_id=f'k{i:02d}', candidate_id='c1', status='rendered', file=f'shorts/k{i:02d}.mp4',
                           sha256=hashing.sha256_file(video), source_start=0, source_end=360,
                           segments=[[0, 100], [110, 360]], duration=350, origin='ai', cut=None))
    change(out / 'render_manifest.json', lambda d: d.update(clips_sha256=hashing.config_hash(clips), shorts=shorts))
    change(folder / 'favorites.json', lambda d: d.update(items=[dict(episode_id='lecture.kt', clip=f'k{i:02d}')
                                                                 for i in range(1, n + 1)]))
    return episode


def proposal(cfg, themes=None, count=None):
    fake = Planner(themes)
    doc = tp.propose(cfg, 'PLtest', client=fake)
    return doc, fake


def test_proposal_basic_and_truncated_to_max(multi):
    cfg, *_ = multi
    doc, fake = proposal(cfg)
    assert 'ai_error' not in doc and len(doc['proposals']) == 1
    p = doc['proposals'][0]
    # 8 clips x 350 = 2800 -> tail cut so the total is <= 2400 (6 clips = 2100)
    assert p['total_duration'] == 2100 and len(p['clips']) == 6 and p['status'] == 'ok'
    assert p['shortfall_seconds'] == 0 and p['dropped_for_length'] == 2
    assert [c['id'] for c in p['clips']] == ids(6)
    c = p['clips'][0]
    assert c['render_sha256'] and c['input_fingerprint'] and c['topic'] == 'Tu học' and c['synopsis']
    saved = json.loads((tp._folder(cfg, 'PLtest') / 'theme_proposals.json').read_text())
    assert saved['proposals'][0]['proposal_id'] == p['proposal_id'] and saved['provenance']['prompt_version'] == 'tc2-v2'
    assert fake.plan_calls[0]['options']['num_predict'] == tp.NUM_PREDICT == 8192
    assert saved['provenance']['options'] == fake.plan_calls[0]['options']
    prompt = json.loads(fake.plan_calls[0]['messages'][1]['content'])
    assert {x['id'] for x in prompt['clips']} == set(ids(8))
    assert prompt['clips'][0]['synopsis'] == c['synopsis'] == 'Phải chuyên tâm tu học.'
    assert prompt['clips'][0]['key_messages'] == ['Phải chuyên tâm tu học.']


def test_short_proposal_reports_shortfall(multi):
    cfg, *_ = multi
    doc, _ = proposal(cfg, [dict(label='Ngắn', rationale='Ít clip', clip_ids=ids(3))])
    p = doc['proposals'][0]
    assert p['status'] == 'short' and p['total_duration'] == 1050 and p['shortfall_seconds'] == 750


def test_unknown_or_duplicate_ids_reject_only_that_theme(multi):
    cfg, *_ = multi
    doc, _ = proposal(cfg, [dict(label='Bịa', rationale='x', clip_ids=[ids(1)[0], 'lecture.kt/zzz']),
                            dict(label='Trùng', rationale='x', clip_ids=[ids(1)[0], ids(1)[0]]),
                            dict(label='Tốt', rationale='ổn', clip_ids=ids(6))])
    assert [p['label'] for p in doc['proposals']] == ['Tốt']
    reasons = [r['reason'] for r in doc['rejected_themes']]
    assert len(reasons) == 2 and 'unknown clip id' in reasons[0] and 'duplicate' in reasons[1]


@pytest.mark.parametrize('bad', [dict(label='“trích”', rationale='x'), dict(label='a\nb', rationale='x'),
                                 dict(label='x' * 121, rationale='x'), dict(label='ok', rationale='y' * 401),
                                 dict(label='ok', rationale='"quote"'), dict(label='ok', rationale='x', extra=1)])
def test_invalid_theme_text_rejected(multi, bad):
    cfg, *_ = multi
    good = dict(label='Tốt', rationale='ổn', clip_ids=ids(6))
    doc, _ = proposal(cfg, [dict(clip_ids=ids(2), **bad), good])
    assert [p['label'] for p in doc['proposals']] == ['Tốt'] and len(doc['rejected_themes']) == 1


@pytest.mark.parametrize('raw', ['not json', '[]', '{"themes": "x"}', '{"themes": [], "extra": 1}', '{"other": 1}'])
def test_malformed_output_is_ai_error_and_not_written(multi, raw):
    cfg, *_ = multi
    doc = tp.propose(cfg, 'PLtest', client=Planner(raw=raw))
    assert doc['ai_error'] and doc['proposals'] == []
    assert not (tp._folder(cfg, 'PLtest') / 'theme_proposals.json').exists()


class SequencePlanner(Planner):
    def __init__(self, outputs):
        super().__init__()
        self.outputs = outputs

    def chat(self, **kwargs):
        result = super().chat(**kwargs)
        if 'clips' in json.loads(kwargs['messages'][1]['content']):
            output = self.outputs[len(self.plan_calls) - 1]
            if isinstance(output, Exception):
                raise output
            return result if output is None else ChatResult(output)
        return result


@pytest.mark.parametrize('raw', ['', 'not json'])
def test_propose_parse_failure_retries_without_thinking(multi, raw):
    cfg, *_ = multi
    cfg = replace(cfg, selection=replace(cfg.selection, think=True))
    fake = SequencePlanner([raw, None])
    doc = tp.propose(cfg, 'PLtest', client=fake)
    assert 'ai_error' not in doc and doc['proposals']
    assert len(fake.plan_calls) == 2
    assert fake.plan_calls[0]['think'] is True
    assert fake.plan_calls[1] == {**fake.plan_calls[0], 'think': False}
    assert doc['provenance']['think_used'] is False
    assert tp.read_proposals(cfg, 'PLtest')['provenance']['think_used'] is False


@pytest.mark.parametrize('outputs,calls', [(['', ''], 2), (['{"themes": [], "extra": 1}'], 1)])
def test_failed_propose_attempts_are_bounded(multi, outputs, calls):
    cfg, *_ = multi
    fake = SequencePlanner(outputs)
    doc = tp.propose(cfg, 'PLtest', client=fake)
    assert doc['ai_error'] and doc['proposals'] == [] and len(fake.plan_calls) == calls
    assert tp.read_proposals(cfg, 'PLtest') is None
    if calls == 2:
        assert fake.plan_calls[1] == {**fake.plan_calls[0], 'think': False}
        assert doc['provenance']['think_used'] is False


@pytest.mark.parametrize('outputs,calls', [([ChatError('refused')], 1), (['', ChatError('refused')], 2)])
def test_propose_chat_error_does_not_retry(multi, outputs, calls):
    cfg, *_ = multi
    fake = SequencePlanner(outputs)
    with pytest.raises(ChatError, match='refused'):
        tp.propose(cfg, 'PLtest', client=fake)
    assert len(fake.plan_calls) == calls and tp.read_proposals(cfg, 'PLtest') is None


def test_all_themes_invalid_is_ai_error(multi):
    cfg, *_ = multi
    doc, _ = proposal(cfg, [dict(label='Bịa', rationale='x', clip_ids=['nope'])])
    assert doc['ai_error'] and len(doc['rejected_themes']) == 1


def test_chat_error_propagates_without_writing(multi):
    cfg, *_ = multi
    fake = Planner()
    tp.propose(cfg, 'PLtest', client=fake)  # indexes everything, writes a good file
    path = tp._folder(cfg, 'PLtest') / 'theme_proposals.json'
    before = path.read_text()

    class DownForPlanning(Planner):
        def chat(self, **kwargs):
            if 'clips' in json.loads(kwargs['messages'][1]['content']):
                raise ChatError('refused')
            return super().chat(**kwargs)
    with pytest.raises(ChatError):
        tp.propose(cfg, 'PLtest', client=DownForPlanning())
    assert path.read_text() == before


def test_only_indexed_clips_are_proposed(multi):
    cfg, ws, folder, out = multi
    (out / 'shorts' / 'k01.mp4').write_bytes(b'tampered')  # k01 becomes ineligible (stale content)
    doc, fake = proposal(cfg, lambda all_ids: [dict(label='Tất cả', rationale='x', clip_ids=all_ids)])
    assert 'lecture.kt/k01' not in [c['id'] for c in doc['proposals'][0]['clips']]
    assert doc['index_counts']['by_status'] == {'indexed': 7, 'ineligible': 1}


def test_zero_indexed_gives_shortfall_message(episode):
    cfg, ws, *_ = episode
    (ws.dir / 'khaithi.json').unlink()
    fake = Planner()
    doc = tp.propose(cfg, 'PLtest', client=fake)
    assert doc['proposals'] == [] and 'no indexed clips' in doc['shortfall'] and 'not a khai thi' in doc['shortfall']
    assert fake.plan_calls == []


# --- plans ------------------------------------------------------------------------------------------------------
def make_plan(cfg, themes=None):
    doc, _ = proposal(cfg, themes)
    return tp.create_plan(cfg, 'PLtest', doc['proposals'][0]['proposal_id'])


def test_create_update_conflict_and_approval_cleared(multi):
    cfg, *_ = multi
    plan = make_plan(cfg)
    assert plan['revision'] == 1 and plan['approval'] is None and plan['title'] == 'Tu học'
    assert plan['theme'] == {'label': 'Tu học', 'rationale': 'Cùng chủ đề tu học'}
    approved = tp.approve_plan(cfg, 'PLtest', plan['plan_id'], revision=1)
    assert approved['approval']['revision'] == 1 and approved['approval']['plan_fingerprint']
    assert approved['approval']['duration_override'] is False
    order = list(reversed(ids(6)))
    updated = tp.update_plan(cfg, 'PLtest', plan['plan_id'], revision=1, title='Mới', clip_ids=order)
    assert updated['revision'] == 2 and updated['approval'] is None and [c['id'] for c in updated['clips']] == order
    with pytest.raises(tp.PlanConflict):
        tp.update_plan(cfg, 'PLtest', plan['plan_id'], revision=1, title='Cũ', clip_ids=order)
    with pytest.raises(tp.PlanConflict):
        tp.approve_plan(cfg, 'PLtest', plan['plan_id'], revision=1)


def test_update_validation(multi):
    cfg, *_ = multi
    plan = make_plan(cfg)
    pid = plan['plan_id']
    for clips in ([], [ids(1)[0]] * 2, ['lecture.kt/nope']):
        with pytest.raises(tp.PlanError):
            tp.update_plan(cfg, 'PLtest', pid, revision=1, title='T', clip_ids=clips)
    with pytest.raises(tp.PlanError):
        tp.update_plan(cfg, 'PLtest', pid, revision=1, title='“x”', clip_ids=ids(2))
    assert tp.list_plans(cfg, 'PLtest')[0]['revision'] == 1  # nothing changed


def test_approve_requires_override_outside_range(multi):
    cfg, *_ = multi
    plan = make_plan(cfg, [dict(label='Ngắn', rationale='x', clip_ids=ids(3))])
    with pytest.raises(tp.PlanError, match='duration_override'):
        tp.approve_plan(cfg, 'PLtest', plan['plan_id'], revision=1)
    done = tp.approve_plan(cfg, 'PLtest', plan['plan_id'], revision=1, duration_override=True)
    assert done['approval']['duration_override'] is True
    assert tp.approved_plan(cfg, 'PLtest', plan['plan_id'])['plan_id'] == plan['plan_id']


def test_list_delete_and_ids(multi):
    cfg, *_ = multi
    plan = make_plan(cfg)
    listed = tp.list_plans(cfg, 'PLtest')
    assert len(listed) == 1 and listed[0]['check'] == {'state': 'draft', 'problems': []}
    with pytest.raises(tp.PlanError):
        tp.delete_plan(cfg, 'PLtest', '../etc')
    with pytest.raises(tp.PlanError):
        tp.approve_plan(cfg, 'PLtest', 'abcdefgh0000', revision=1)
    tp.delete_plan(cfg, 'PLtest', plan['plan_id'])
    assert tp.list_plans(cfg, 'PLtest') == []
    with pytest.raises(tp.PlanError):
        tp.create_plan(cfg, 'PLtest', 'unknown')


def _break(cfg, ws, folder, out, kind):
    if kind == 'render':
        video = out / 'shorts' / 'k01.mp4'
        video.write_bytes(b'rerendered')
        change(out / 'render_manifest.json', lambda d: d['shorts'][0].update(sha256=hashing.sha256_file(video)))
    elif kind == 'cut':
        review = logic.with_cut(logic.empty_review(ws.episode_id), ['k01'], clip_id='k01', candidate_id='c1', start=1, end=360)
        atomic_write_json(ws.dir / 'review.json', review)
        silences = dict(silences=[])
        atomic_write_json(ws.dir / 'silences.json', silences)
        change(ws.dir / 'candidates.json', lambda d: d.update(silences_sha256=hashing.config_hash(silences)))
    elif kind == 'transcript':
        change(ws.dir / 'transcript.json', lambda d: d['segments'][1].update(text='đã sửa'))
    elif kind == 'unheart':
        change(folder / 'favorites.json', lambda d: d.update(items=[i for i in d['items'] if i['clip'] != 'k01']))
    elif kind == 'reject':
        atomic_write_json(ws.dir / 'review.json',
                          logic.with_rejected(logic.empty_review(ws.episode_id), ['k01'], clip_id='k01', candidate_id='c1'))
    elif kind == 'index':
        change(folder / 'theme_index.json', lambda d: d['records'][0]['metadata']['synopsis'].update(text='invented'))
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize('kind', ['render', 'cut', 'transcript', 'unheart', 'reject', 'index'])
def test_stale_invalidates_plan_and_approval(multi, kind):
    cfg, ws, folder, out = multi
    plan = make_plan(cfg)
    tp.approve_plan(cfg, 'PLtest', plan['plan_id'], revision=1)
    assert tp.approved_plan(cfg, 'PLtest', plan['plan_id'])
    _break(cfg, ws, folder, out, kind)
    check = tp.list_plans(cfg, 'PLtest')[0]['check']
    assert check['state'] == 'stale' and any('lecture.kt/k01' in p for p in check['problems']), check
    with pytest.raises(tp.PlanError, match='stale'):
        tp.approved_plan(cfg, 'PLtest', plan['plan_id'])
    with pytest.raises(tp.PlanError, match='stale'):
        tp.approve_plan(cfg, 'PLtest', plan['plan_id'], revision=1)


def test_hand_edited_plan_invalidates_approval(multi):
    cfg, *_ = multi
    plan = make_plan(cfg)
    tp.approve_plan(cfg, 'PLtest', plan['plan_id'], revision=1)
    path = tp._plan_path(cfg, 'PLtest', plan['plan_id'])
    change(path, lambda d: d.update(title='Sửa tay'))
    check = tp.check_plan(cfg, 'PLtest', json.loads(path.read_text()))
    assert check['state'] == 'draft' and 'approval' in check['problems'][0]
    with pytest.raises(tp.PlanError, match='draft'):
        tp.approved_plan(cfg, 'PLtest', plan['plan_id'])
    change(path, lambda d: d['clips'].pop())  # reordering/removal also changes the fingerprint
    assert tp.list_plans(cfg, 'PLtest')[0]['check']['state'] == 'draft'


def test_corrupt_plan_is_invalid_not_dropped(multi):
    cfg, *_ = multi
    plan = make_plan(cfg)
    path = tp._plan_path(cfg, 'PLtest', plan['plan_id'])
    path.write_text('{broken')
    listed = tp.list_plans(cfg, 'PLtest')
    assert listed[0]['check']['state'] == 'invalid' and listed[0]['plan_id'] == plan['plan_id']
    change_ok = json.dumps({'schema_version': 1, 'playlist_id': 'PLtest', 'plan_id': plan['plan_id'], 'revision': 1,
                            'clips': [{'id': 'x'}]})
    path.write_text(change_ok)
    assert tp.list_plans(cfg, 'PLtest')[0]['check']['state'] == 'invalid'
    with pytest.raises(tp.PlanError):
        tp.approve_plan(cfg, 'PLtest', plan['plan_id'], revision=1)


def test_check_and_list_never_call_ai_or_write(multi):
    cfg, *_ = multi
    plan = make_plan(cfg)
    folder = tp._folder(cfg, 'PLtest')
    snapshot = {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    assert tp.list_plans(cfg, 'PLtest')[0]['check']['state'] == 'draft'
    assert tp.check_plan(cfg, 'PLtest', plan)['state'] == 'draft'
    assert {p: p.read_bytes() for p in folder.rglob('*') if p.is_file()} == snapshot
    change(folder / 'theme_index.json', lambda d: d['records'][0].update(input_fingerprint='x'))
    # a changed cache must make the clip not indexed (no AI call to repair it), and still write nothing
    assert tp.check_plan(cfg, 'PLtest', plan)['state'] == 'stale'


def test_check_and_list_can_share_a_fresh_index(multi, monkeypatch):
    from copy import deepcopy
    cfg, *_ = multi
    plan = make_plan(cfg)
    index = tp.theme_index.build_index(cfg, 'PLtest', write=False, client=tp._RefusingClient())
    before = deepcopy(index)
    expected_check = tp.check_plan(cfg, 'PLtest', plan)
    expected_list = tp.list_plans(cfg, 'PLtest')
    monkeypatch.setattr(tp.theme_index, 'build_index', lambda *a, **kw: pytest.fail('re-audited shared index'))
    assert tp.check_plan(cfg, 'PLtest', plan, index=index) == expected_check
    assert tp.list_plans(cfg, 'PLtest', index=index) == expected_list
    assert index == before


def test_shared_index_stale_and_wrong_playlist_fail_closed(multi, monkeypatch):
    cfg, ws, folder, out = multi
    plan = make_plan(cfg)
    _break(cfg, ws, folder, out, 'transcript')
    index = tp.theme_index.build_index(cfg, 'PLtest', write=False, client=tp._RefusingClient())
    monkeypatch.setattr(tp.theme_index, 'build_index', lambda *a, **kw: pytest.fail('unexpected second audit'))
    assert tp.check_plan(cfg, 'PLtest', plan, index=index)['state'] == 'stale'
    assert tp.list_plans(cfg, 'PLtest', index=index)[0]['check']['state'] == 'stale'
    wrong = {**index, 'playlist_id': 'PLother'}
    assert tp.check_plan(cfg, 'PLtest', plan, index=wrong)['state'] == 'stale'
    assert 'mismatch' in tp.list_plans(cfg, 'PLtest', index=wrong)[0]['check']['problems'][0]
