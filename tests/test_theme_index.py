import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import pytest

from auto_short import hashing, khaithi
from auto_short import theme_index as tc1
from auto_short.compilation import store
from auto_short.review import logic
from auto_short.selection.client import ChatError, ChatResult
from auto_short.theme_index import audit_playlist, build_index, IndexError
from auto_short.workspace import Workspace, atomic_write_json


@pytest.fixture
def memo_cache():
    caches = (tc1._cached_json, tc1._file_digest, tc1._json_digest)
    for cache in caches:
        cache.cache_clear()
    yield caches
    for cache in caches:
        cache.cache_clear()


class Fake:
    def __init__(self, bad=None):
        self.calls = []
        self.bad = bad

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        evidence = json.loads(kwargs['messages'][1]['content'])['evidence']
        sid = evidence[0]['evidence_id']
        doc = dict(topic='Tu học', subtopic='Chuyên tâm', synopsis=[sid], key_messages=[sid], uncertainty=[])
        if self.bad:
            self.bad(doc)
        return ChatResult(json.dumps(doc, ensure_ascii=False))


@pytest.fixture
def episode(cfg):
    ws = Workspace(cfg.workspace.dir, 'lecture.kt')
    ws.dir.mkdir(parents=True)
    src = ws.dir / 'source.mp4'
    src.write_bytes(b'landscape-original')
    sha = hashing.sha256_file(src)
    ws.save_manifest(ws.new_manifest(dict(path='source.mp4', sha256=sha)))
    khaithi.write(ws.dir, khaithi.KhaiThi('lecture', 5, 7))
    atomic_write_json(cfg.workspace.dir / '_playlists' / 'PLtest.json',
                      dict(playlist_id='PLtest', entries=[dict(video_id='lecture', available=True)]))
    folder = store.directory(cfg.render.output_dir, 'PLtest')
    atomic_write_json(folder / 'favorites.json', dict(schema_version=1, items=[dict(episode_id='lecture.kt', clip='k01')]))
    clips = dict(clips=[dict(id='k01', candidate_id='c1', source_start=0, source_end=360, duration=350)])
    candidates = dict(candidates=[dict(id='c1', trims=[[100, 110]])], params=dict(max_pause=1))
    transcript = dict(media_sha256=sha, segments=[
        dict(id='outside', start=400, end=410, kind='speech', text='OUTSIDE SECRET'),
        dict(id='s1', start=10, end=20, kind='speech', text='Phải chuyên tâm tu học.'),
        dict(id='cut', start=101, end=109, kind='speech', text='REMOVED SECRET'),
        dict(id='cross', start=99, end=111, kind='speech', text='CROSSING SECRET')])
    digest = hashing.config_hash(transcript['segments'])
    transcript['transcript_sha256'] = digest
    candidates['transcript_sha256'] = digest
    for name, doc in [('clips.json', clips), ('candidates.json', candidates), ('titles.json', {}),
                      ('transcript.json', transcript)]:
        atomic_write_json(ws.dir / name, doc)
    out = cfg.render.output_dir / ws.episode_id
    (out / 'shorts').mkdir(parents=True)
    video = out / 'shorts' / 'k01.mp4'
    video.write_bytes(b'rendered')
    record = dict(clip_id='k01', candidate_id='c1', status='rendered', file='shorts/k01.mp4',
                  sha256=hashing.sha256_file(video), source_start=0, source_end=360,
                  segments=[[0, 100], [110, 360]], duration=350, origin='ai', cut=None)
    rendered = dict(episode_id=ws.episode_id, source_sha256=sha, clips_sha256=hashing.config_hash(clips),
                    candidates_sha256=hashing.config_hash(candidates), titles_sha256=hashing.config_hash({}), shorts=[record])
    atomic_write_json(out / 'render_manifest.json', rendered)
    return cfg, ws, folder, out


def change(path, mutate):
    doc = json.loads(path.read_text())
    mutate(doc)
    atomic_write_json(path, doc)


def test_final_evidence_and_cache(episode):
    cfg, ws, folder, out = episode
    fake = Fake()
    first = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert first['status'] == 'indexed', first
    assert first['final_segments'] == [[0, 100], [110, 360]]
    assert first['uncertainty']
    prompt = fake.calls[0]['messages'][1]['content']
    assert all(secret not in prompt for secret in ('OUTSIDE SECRET', 'REMOVED SECRET', 'CROSSING SECRET'))
    second = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert second['cached'] and len(fake.calls) == 1
    change(folder / 'theme_index.json', lambda d: d['records'][0]['metadata']['synopsis'].update(text='invented'))
    assert not build_index(cfg, 'PLtest', client=fake)['records'][0]['cached']
    assert len(fake.calls) == 2


@pytest.mark.parametrize('mutation,reason', [
    ('reject', 'rejected'), ('short', 'not a khai'), ('duration', 'duration'),
    ('cut', 'stale render'), ('source', 'stale content'), ('render', 'stale content'),
    ('transcript_source', 'stale transcript'), ('kept', 'kept')])
def test_ineligible(episode, mutation, reason):
    cfg, ws, folder, out = episode
    if mutation == 'reject':
        review = logic.with_rejected(logic.empty_review(ws.episode_id), ['k01'], clip_id='k01', candidate_id='c1')
        atomic_write_json(ws.dir / 'review.json', review)
    elif mutation == 'short':
        (ws.dir / 'khaithi.json').unlink()
    elif mutation == 'duration':
        change(ws.dir / 'clips.json', lambda d: d['clips'][0].update(source_end=200, duration=190))
    elif mutation == 'cut':
        review = logic.with_cut(logic.empty_review(ws.episode_id), ['k01'], clip_id='k01', candidate_id='c1', start=1, end=360)
        atomic_write_json(ws.dir / 'review.json', review)
        silences = dict(silences=[])
        atomic_write_json(ws.dir / 'silences.json', silences)
        change(ws.dir / 'candidates.json', lambda d: d.update(silences_sha256=hashing.config_hash(silences)))
    elif mutation == 'source':
        (ws.dir / 'source.mp4').write_bytes(b'changed')
    elif mutation == 'render':
        (out / 'shorts' / 'k01.mp4').write_bytes(b'changed')
    elif mutation == 'transcript_source':
        change(ws.dir / 'transcript.json', lambda d: d.update(media_sha256='wrong'))
    else:
        change(folder / 'favorites.json', lambda d: d['items'][0].update(kept=dict(path='kept/lecture.kt/k01.mp4', title=None,
            duration=350, episode_number='1', clip_number=1, clip_total=1, saved_at='now')))
    fake = Fake()
    record = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert record['status'] == 'ineligible' and reason in record['reason'], record
    assert fake.calls == []


def test_invalid_favorites_and_playlist(episode):
    cfg, ws, folder, _ = episode
    change(folder / 'favorites.json', lambda d: d['items'].extend([None, dict(episode_id='../oops', clip='k01')]))
    records = audit_playlist(cfg, 'PLtest')
    assert len(records) == 3 and [r['status'] for r in records] == ['eligible', 'ineligible', 'ineligible']
    change(cfg.workspace.dir / '_playlists' / 'PLtest.json', lambda d: d.update(entries=[]))
    assert 'outside selected' in audit_playlist(cfg, 'PLtest')[0]['reason']


@pytest.mark.parametrize('field', ['model', 'prompt', 'transcript', 'render'])
def test_invalidation(episode, field):
    cfg, ws, folder, out = episode
    fake = Fake()
    first = build_index(cfg, 'PLtest', client=fake)['records'][0]
    kwargs = {}
    if field == 'model':
        cfg = replace(cfg, selection=replace(cfg.selection, model='different-model'))
    elif field == 'prompt':
        kwargs['prompt_version'] = 'tc1-future'
    elif field == 'transcript':
        path = ws.dir / 'transcript.json'
        change(path, lambda d: d['segments'][1].update(text='Lời tu học đã sửa.'))
        doc = json.loads(path.read_text())
        digest = hashing.config_hash(doc['segments'])
        change(path, lambda d: d.update(transcript_sha256=digest))
        change(ws.dir / 'candidates.json', lambda d: d.update(transcript_sha256=digest))
        cand = json.loads((ws.dir / 'candidates.json').read_text())
        change(out / 'render_manifest.json', lambda d: d.update(candidates_sha256=hashing.config_hash(cand)))
    else:
        change(out / 'render_manifest.json', lambda d: d.update(render_config_hash='changed'))
    second = build_index(cfg, 'PLtest', client=fake, **kwargs)['records'][0]
    assert second['status'] == 'indexed' and not second['cached']
    assert first['input_fingerprint'] != second['input_fingerprint'] and len(fake.calls) == 2


@pytest.mark.parametrize('bad', [lambda d: d.update(quote='invented'),
    lambda d: d.update(synopsis=[{'evidence_id': 's1', 'text': 'invented'}]),
    lambda d: d.update(synopsis='s1'), lambda d: d.update(synopsis=None),
    lambda d: d.update(synopsis=['s1'] * 13), lambda d: d.update(key_messages=['s1'] * 9),
    lambda d: d.update(key_messages=[1]), lambda d: d.update(key_messages=None),
    lambda d: d.update(topic=123), lambda d: d.update(topic='“invented speech”'),
    lambda d: d.update(topic='a\nb'), lambda d: d.update(subtopic='a\rb'),
    lambda d: d.update(topic='x' * 121), lambda d: d.update(uncertainty='unknown')])
def test_malformed_metadata_rejected(episode, bad):
    cfg, *_ = episode
    record = build_index(cfg, 'PLtest', client=Fake(bad))['records'][0]
    assert record['status'] == 'ai_error'


def test_id_only_output_is_resolved_verbatim_and_options_recorded(episode):
    cfg, ws, *_ = episode
    text = '  Phải chuyên tâm tu học, giữ nguyên dấu câu!\nKhông tự viết lại.  '
    change(ws.dir / 'transcript.json', lambda d: d['segments'][1].update(text=text))
    transcript = json.loads((ws.dir / 'transcript.json').read_text())
    digest = hashing.config_hash(transcript['segments'])
    change(ws.dir / 'transcript.json', lambda d: d.update(transcript_sha256=digest))
    change(ws.dir / 'candidates.json', lambda d: d.update(transcript_sha256=digest))
    candidates = json.loads((ws.dir / 'candidates.json').read_text())
    out = cfg.render.output_dir / ws.episode_id
    change(out / 'render_manifest.json', lambda d: d.update(candidates_sha256=hashing.config_hash(candidates)))
    fake = Fake()
    record = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert record['status'] == 'indexed'
    ref = {'evidence_id': 's1', 'text': text}
    assert record['metadata']['synopsis'] == {**ref, 'evidence_ids': ['s1']}
    assert record['metadata']['key_messages'] == [ref]
    assert record['metadata']['uncertainty'] == []
    call = fake.calls[0]
    assert call['options']['num_predict'] == tc1.NUM_PREDICT == 8192
    assert record['provenance']['options'] == call['options']
    assert record['provenance']['prompt_version'] == 'tc1-v4'
    for key in ('synopsis', 'key_messages'):
        assert call['format']['properties'][key]['items'] == {'type': 'string', 'enum': ['s1']}
    assert call['format']['properties']['synopsis']['maxItems'] == 12
    assert call['format']['properties']['key_messages']['maxItems'] == 8
    system = call['messages'][0]['content']
    assert 'return ONLY evidence_id strings' in system and 'Do NOT write sentences or a summary' in system
    assert 'consecutive evidence order' in system and 'ids need not be numerically consecutive' in system
    assert '2-8 sentences' not in system and 'aiming for 20-80 words' not in system
    assert 'Always provide a topic IN VIETNAMESE whenever evidence exists' in system
    assert 'Avoid fragments shorter than 6 words' not in system


def test_request_schema_is_scoped_to_each_clip(episode, monkeypatch):
    cfg, *_ = episode
    records = audit_playlist(cfg, 'PLtest')
    records.append(deepcopy(records[0]))
    records[1]['identity']['clip'] = 'k02'
    for record, ids in zip(records, (['s00331', 's00334', 's00336'], ['s00901', 's00905'])):
        record['evidence'] = [{'evidence_id': sid, 'text': 'Phải chuyên tâm tu học.'} for sid in ids]
    monkeypatch.setattr(tc1, 'audit_playlist', lambda *a: deepcopy(records))
    template = deepcopy(tc1.SCHEMA)
    fake = Fake()
    result = build_index(cfg, 'PLtest', client=fake, write=False)
    assert len(fake.calls) == 2 and all(r['status'] == 'indexed' for r in result['records'])
    for call, record in zip(fake.calls, result['records']):
        ids = [e['evidence_id'] for e in record['evidence']]
        for key in ('synopsis', 'key_messages'):
            assert call['format']['properties'][key]['items'] == {'type': 'string', 'enum': ids}
        assert record['metadata']['synopsis']['evidence_ids'] == ids
        assert record['provenance']['prompt_sha256'] == hashing.config_hash({'system': tc1.SYSTEM, 'schema': template})
    assert tc1.SCHEMA == template
    fake.calls[0]['format']['properties']['synopsis']['items']['enum'].append('invented')
    assert fake.calls[1]['format']['properties']['synopsis']['items']['enum'] == ['s00901', 's00905']
    assert tc1.SCHEMA == template


@pytest.mark.parametrize('synopsis,messages,expected_synopsis,expected_messages', [
    (['outside', 's1'], ['s1', 'outside'], 's1', ['s1']),
    (['s1', 's1'], ['s1', 's1'], 's1', ['s1']),
    (['outside'], ['outside'], None, []),
    (['Cha mẹ phải làm tấm gương tốt cho con cái.'], ['s1'], None, ['s1']),
    ([], ['s1'], None, ['s1']),
])
def test_unknown_and_duplicate_ids_are_dropped_with_uncertainty(
        episode, synopsis, messages, expected_synopsis, expected_messages):
    cfg, *_ = episode
    fake = Fake(lambda d: d.update(synopsis=synopsis, key_messages=messages))
    record = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert record['status'] == 'indexed'
    meta = record['metadata']
    assert (meta['synopsis']['evidence_id'] if meta['synopsis'] else None) == expected_synopsis
    assert [r['evidence_id'] for r in meta['key_messages']] == expected_messages
    assert meta['uncertainty'] == ['missing_metadata']
    assert build_index(cfg, 'PLtest', client=fake)['records'][0]['cached']
    assert len(fake.calls) == 1


@pytest.mark.parametrize('field', ['topic', 'subtopic', 'synopsis', 'key_messages'])
@pytest.mark.parametrize('absent', [False, True])
def test_missing_metadata_is_indexed(episode, field, absent):
    def missing(doc):
        if absent:
            doc.pop(field)
        else:
            doc[field] = None if field in ('topic', 'subtopic') else []
        doc['uncertainty'] = ['uncertain_topic']
    fake = Fake(missing)
    record = build_index(episode[0], 'PLtest', client=fake)['records'][0]
    assert record['status'] == 'indexed'
    assert not record['metadata'][field]
    assert record['metadata']['uncertainty'] == ['uncertain_topic', 'missing_metadata']
    assert build_index(episode[0], 'PLtest', client=fake)['records'][0]['cached']
    assert len(fake.calls) == 1


def test_null_subtopic_adds_missing_metadata_without_model_uncertainty(episode):
    record = build_index(episode[0], 'PLtest', client=Fake(lambda d: d.update(subtopic=None)))['records'][0]
    assert record['status'] == 'indexed'
    assert record['metadata']['subtopic'] is None
    assert record['metadata']['uncertainty'] == ['missing_metadata']


@pytest.mark.parametrize('word_counts,selected,span,missing', [
    ([10] * 5, [0, 1], (0, 2), False),  # consecutive by evidence position, not numeric id
    ([10] * 5, [0, 1, 3, 4], (0, 2), True),  # stop at the first gap
    ([10] * 5, [0, 'invented', 1], (0, 2), True),
    ([10] * 5, [0, 0, 1], (0, 2), True),
    ([10] * 5, [2, 1], (2, 4), True),  # reversed ids are not a consecutive passage
    ([5] * 6, [2], (2, 6), False),  # extend after before considering preceding evidence
    ([5] * 6, [4], (2, 6), False),  # end reached: extend before
    ([30] * 4, [0, 1, 2, 3], (0, 2), False),  # trim only whole tail segments
    ([10, 75], [0], (0, 2), False),  # retain 85 words rather than drop below the minimum
    ([15, 10, 70], [0, 1, 2], (0, 2), False),  # tail removal leaves 25 words
    ([20] * 5, [0, 1, 2, 3], (0, 4), False),  # exactly max words
    ([100, 5], [0], (0, 1), False),  # retain at least one, even an oversized segment
    ([3, 4], [1], (0, 2), False),  # use all evidence when fewer than min words exist
    ([1] * 25, [0], (0, 20), False),  # expanded cache may exceed AI maxItems
])
def test_synopsis_spans_are_extractive_and_bounded(episode, monkeypatch, word_counts, selected, span, missing):
    cfg, *_ = episode
    records = audit_playlist(cfg, 'PLtest')
    # Deliberately nonnumeric order; preserve whitespace and punctuation verbatim.
    segments = [dict(id=f's{100 - i}', start=i * 2, end=i * 2 + 1, kind='speech',
                     text='  ' + ' '.join([f'từ{i}'] * n) + '.\n') for i, n in enumerate(word_counts)]
    evidence, _ = tc1._evidence({'segments': segments}, [[0, 100]])
    records[0]['evidence'] = evidence
    monkeypatch.setattr(tc1, 'audit_playlist', lambda *a: deepcopy(records))
    ids = [evidence[i]['evidence_id'] if isinstance(i, int) else i for i in selected]
    fake = Fake(lambda d: d.update(synopsis=ids))
    record = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert record['status'] == 'indexed', record
    expected = evidence[slice(*span)]
    assert record['metadata']['synopsis'] == {
        'evidence_id': expected[0]['evidence_id'], 'evidence_ids': [e['evidence_id'] for e in expected],
        'text': ' '.join(e['text'] for e in expected)}
    assert record['metadata']['uncertainty'] == (['missing_metadata'] if missing else [])
    assert record['metadata']['key_messages'] == [
        {'evidence_id': evidence[0]['evidence_id'], 'text': evidence[0]['text']}]
    assert json.loads(fake.calls[0]['messages'][1]['content'])['evidence'] == evidence
    cached = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert cached['cached'] and len(fake.calls) == 1
    assert cached['metadata'] == record['metadata']


@pytest.mark.parametrize('mutation', ['text', 'first_id', 'unknown_id', 'duplicate_id', 'old_shape', 'empty_ids',
                                      'reordered_ids', 'nonconsecutive_ids', 'ids_not_list'])
def test_tampered_synopsis_cache_is_rejected(episode, monkeypatch, mutation):
    cfg, _, folder, _ = episode
    records = audit_playlist(cfg, 'PLtest')
    records[0]['evidence'] = [{'evidence_id': f's{i}', 'text': ' '.join([f'từ{i}'] * 10)} for i in range(5)]
    evidence = records[0]['evidence']
    monkeypatch.setattr(tc1, 'audit_playlist', lambda *a: deepcopy(records))
    fake = Fake()
    build_index(cfg, 'PLtest', client=fake)

    def tamper(doc):
        ref = doc['records'][0]['metadata']['synopsis']
        if mutation == 'text':
            ref['text'] = 'invented'
        elif mutation == 'first_id':
            ref['evidence_id'] = 's1'
        elif mutation == 'unknown_id':
            ref['evidence_ids'][0] = 'invented'
        elif mutation == 'duplicate_id':
            ref['evidence_ids'] = ['s0', 's0']
        elif mutation == 'old_shape':
            ref.pop('evidence_ids')
        elif mutation == 'empty_ids':
            ref['evidence_ids'] = []
        elif mutation in ('reordered_ids', 'nonconsecutive_ids'):
            indexes = [1, 0] if mutation == 'reordered_ids' else [0, 2]
            ref.update(evidence_id=f's{indexes[0]}', evidence_ids=[f's{i}' for i in indexes],
                       text=' '.join(evidence[i]['text'] for i in indexes))
        else:
            ref['evidence_ids'] = 's0'
    change(folder / 'theme_index.json', tamper)
    meta = json.loads((folder / 'theme_index.json').read_text())['records'][0]['metadata']
    with pytest.raises(IndexError):
        tc1._validate_cached_metadata(meta, evidence)
    fresh = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert fresh['status'] == 'indexed' and not fresh['cached'] and len(fake.calls) == 2


@pytest.mark.parametrize('old_version', ['tc1-v2', 'tc1-v3'])
def test_old_cache_invalidated_and_v4_reused(episode, old_version):
    cfg, _, folder, _ = episode
    fake = Fake()
    old = build_index(cfg, 'PLtest', client=fake, prompt_version=old_version)['records'][0]
    if old_version == 'tc1-v2':
        change(folder / 'theme_index.json', lambda d: d['records'][0]['metadata']['synopsis'].pop('evidence_ids'))
    current = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert old['provenance']['prompt_version'] == old_version and current['provenance']['prompt_version'] == 'tc1-v4'
    assert old['input_fingerprint'] != current['input_fingerprint'] and not current['cached']
    assert build_index(cfg, 'PLtest', client=fake)['records'][0]['cached'] and len(fake.calls) == 2


def test_num_predict_change_invalidates_index_cache(episode, monkeypatch):
    fake = Fake()
    first = build_index(episode[0], 'PLtest', client=fake)['records'][0]
    monkeypatch.setattr(tc1, 'NUM_PREDICT', 4096)
    second = build_index(episode[0], 'PLtest', client=fake)['records'][0]
    assert second['status'] == 'indexed' and not second['cached']
    assert first['input_fingerprint'] != second['input_fingerprint']
    assert fake.calls[1]['options']['num_predict'] == second['provenance']['options']['num_predict'] == 4096


def test_unheart_and_watched_do_not_approve(episode):
    cfg, ws, folder, _ = episode
    build_index(cfg, 'PLtest', client=Fake())
    atomic_write_json(ws.dir / 'watched.json', {'clips': ['k01']})
    change(folder / 'favorites.json', lambda d: d.update(items=[]))
    assert build_index(cfg, 'PLtest', client=Fake())['records'] == []


def test_stale_transcript_linkage(episode):
    cfg, ws, *_ = episode
    change(ws.dir / 'transcript.json', lambda d: d['segments'][1].update(text='unrelated'))
    record = build_index(cfg, 'PLtest', client=Fake())['records'][0]
    assert record['status'] == 'ineligible' and 'linkage' in record['reason']


def test_manual_cut_reconstruction_and_invalidation(episode):
    cfg, ws, _, out = episode
    fake = Fake()
    first = build_index(cfg, 'PLtest', client=fake)['records'][0]
    review = logic.with_cut(logic.empty_review(ws.episode_id), ['k01'], clip_id='k01', candidate_id='c1', start=5, end=360)
    atomic_write_json(ws.dir / 'review.json', review)
    silences = dict(silences=[dict(start=100, end=110)])
    atomic_write_json(ws.dir / 'silences.json', silences)
    change(ws.dir / 'candidates.json', lambda d: d.update(silences_sha256=hashing.config_hash(silences)))
    from auto_short.render.stage import render_targets, load_silences
    clips = json.loads((ws.dir / 'clips.json').read_text())
    cand = json.loads((ws.dir / 'candidates.json').read_text())
    target = render_targets(clips, review, cand, lambda: load_silences(ws, cand))[0][0]
    from auto_short.render.plan import segments_seconds
    def update(d):
        d['candidates_sha256'] = hashing.config_hash(cand)
        d['shorts'][0].update({k: target[k] for k in ('source_start', 'source_end', 'duration', 'cut', 'origin')})
        d['shorts'][0]['segments'] = segments_seconds(target['segments'])
    change(out / 'render_manifest.json', update)
    second = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert second['status'] == 'indexed' and not second['cached'], second
    assert second['final_segments'] == segments_seconds(target['segments'])
    assert second['input_fingerprint'] != first['input_fingerprint']


def test_reconstructed_source_change_invalidates(episode):
    cfg, ws, _, out = episode
    fake = Fake()
    first = build_index(cfg, 'PLtest', client=fake)['records'][0]
    (ws.dir / 'source.mp4').write_bytes(b'replacement original')
    sha = hashing.sha256_file(ws.dir / 'source.mp4')
    change(ws.dir / 'manifest.json', lambda d: d['source'].update(sha256=sha))
    change(ws.dir / 'transcript.json', lambda d: d.update(media_sha256=sha))
    change(out / 'render_manifest.json', lambda d: d.update(source_sha256=sha))
    second = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert second['status'] == 'indexed' and not second['cached'], second
    assert second['input_fingerprint'] != first['input_fingerprint']


@pytest.mark.parametrize('duration,eligible', [(239, False), (240, True), (420, True), (421, False)])
def test_duration_boundaries(episode, duration, eligible):
    cfg, ws, _, out = episode
    change(ws.dir / 'clips.json', lambda d: d['clips'][0].update(source_end=duration + 10, duration=duration))
    clips = json.loads((ws.dir / 'clips.json').read_text())
    def update(d):
        d['clips_sha256'] = hashing.config_hash(clips)
        d['shorts'][0].update(source_end=duration + 10, duration=duration, segments=[[0, 100], [110, duration + 10]])
    change(out / 'render_manifest.json', update)
    assert (audit_playlist(cfg, 'PLtest')[0]['status'] == 'eligible') == eligible


def test_not_rendered(episode):
    cfg, _, _, out = episode
    change(out / 'render_manifest.json', lambda d: d['shorts'][0].update(status='skipped'))
    assert 'not rendered' in audit_playlist(cfg, 'PLtest')[0]['reason']


def offload(out, clip='k01', sha=None):
    """SHO1: keep a verified release record, drop the local bytes; returns the original bytes."""
    video = out / 'shorts' / f'{clip}.mp4'
    data, st = video.read_bytes(), video.stat()
    atomic_write_json(out / 'store.json', dict(released={clip: dict(
        sha256=sha or hashing.sha256_file(video), size=st.st_size, mtime_ns=st.st_mtime_ns)}, at='now'))
    video.unlink()
    return data


def test_offloaded_short_keeps_fingerprint_and_render_sha(episode):
    cfg, _, _, out = episode
    before = build_index(cfg, 'PLtest', client=Fake(), write=False)['records'][0]
    offload(out)
    after = build_index(cfg, 'PLtest', client=Fake(), write=False)['records'][0]
    assert after['status'] == 'indexed', after
    assert after['input_fingerprint'] == before['input_fingerprint']
    assert after['inputs']['render_sha256'] == before['inputs']['render_sha256']


@pytest.mark.parametrize('case', ['record_sha', 'no_record'])
def test_offloaded_short_without_valid_record_stays_ineligible(episode, case):
    cfg, _, _, out = episode
    offload(out, sha='1' * 64 if case == 'record_sha' else None)
    if case == 'no_record':
        (out / 'store.json').unlink()
    reason = audit_playlist(cfg, 'PLtest')[0]['reason']
    assert 'No such file' in reason, reason


def test_kept_only_is_explicitly_ineligible(episode):
    cfg, ws, folder, _ = episode
    kept = folder / 'kept' / 'deleted.kt' / 'k01.mp4'
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b'kept portrait cannot reconstruct')
    change(folder / 'favorites.json', lambda d: d.update(items=[dict(episode_id='deleted.kt', clip='k01',
        kept=dict(path='kept/deleted.kt/k01.mp4', title=None, duration=350, episode_number='1',
                  clip_number=1, clip_total=1, saved_at='now'))]))
    record = audit_playlist(cfg, 'PLtest')[0]
    assert record['status'] == 'ineligible' and 'kept source unreconstructable' in record['reason']


def test_malformed_json(episode):
    class Malformed:
        def chat(self, **kwargs):
            return ChatResult('not json')
    assert build_index(episode[0], 'PLtest', client=Malformed())['records'][0]['status'] == 'ai_error'


@pytest.mark.parametrize('raw', ['', 'not json'])
def test_parse_failure_retries_without_thinking_and_keeps_cache_key(episode, raw):
    cfg, _, folder, _ = episode
    cfg = replace(cfg, selection=replace(cfg.selection, think=True))
    baseline = build_index(cfg, 'PLtest', client=Fake(), write=False)['records'][0]

    class Retry(Fake):
        def chat(self, **kwargs):
            result = super().chat(**kwargs)
            return ChatResult(raw) if len(self.calls) == 1 else result

    fake = Retry()
    record = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert record['status'] == 'indexed' and len(fake.calls) == 2
    assert fake.calls[0]['think'] is True and fake.calls[1] == {**fake.calls[0], 'think': False}
    assert baseline['provenance']['think_used'] is True
    assert record['provenance']['think_used'] is False
    assert record['input_fingerprint'] == baseline['input_fingerprint']
    cached = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert cached['cached'] and cached['provenance']['think_used'] is False and len(fake.calls) == 2
    # Legacy records without think_used retain their cache keys as well.
    change(folder / 'theme_index.json', lambda d: d['records'][0]['provenance'].pop('think_used'))
    legacy = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert legacy['cached'] and legacy['provenance']['think_used'] is True and len(fake.calls) == 2


@pytest.mark.parametrize('outputs,calls', [(['', ''], 2), (['', ChatError('refused')], 2),
                                        ([ChatError('refused')], 1), (['{"extra": 1}'], 1)])
def test_failed_index_attempts_are_bounded(episode, outputs, calls):
    class Failed:
        def __init__(self):
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            output = outputs[len(self.calls) - 1]
            if isinstance(output, Exception):
                raise output
            return ChatResult(output)

    fake = Failed()
    record = build_index(episode[0], 'PLtest', client=fake)['records'][0]
    assert record['status'] == 'ai_error' and len(fake.calls) == calls
    if calls == 2:
        assert fake.calls[1] == {**fake.calls[0], 'think': False}
        assert record['provenance']['think_used'] is False


def test_uncertainty_cannot_carry_fabricated_speech(episode):
    record = build_index(episode[0], 'PLtest', client=Fake(lambda d: d.update(uncertainty=['invented speech'])))['records'][0]
    assert record['status'] == 'ai_error'


# --- G2: source files deleted (disk cleanup) -------------------------------------------------------------------
def _write_hd(ws, original_sha, wanted_state='done'):
    hd = ws.dir / 'source_hd.mp4'
    hd.write_bytes(b'enhanced-hd')
    hd_sha = hashing.sha256_file(hd)
    atomic_write_json(ws.dir / 'enhance.json', dict(schema_version=1, state=wanted_state, wanted=True,
                      source_sha256=original_sha, source_hd_sha256=hd_sha, source_hd_size=hd.stat().st_size,
                      source_hd_mtime_ns=hd.stat().st_mtime_ns))
    return hd, hd_sha


def test_source_present_status(episode):
    cfg, *_ = episode
    record = audit_playlist(cfg, 'PLtest')[0]
    assert record['status'] == 'eligible' and record['source_status'] == 'present'
    assert record['source_reference']['sha256'] == record['source_reference']['original_sha256']


def test_source_missing_valid_chain_same_fingerprint(episode):
    cfg, ws, *_ = episode
    fake = Fake()
    first = build_index(cfg, 'PLtest', client=fake)['records'][0]
    (ws.dir / 'source.mp4').unlink()
    audited = audit_playlist(cfg, 'PLtest')[0]
    assert audited['status'] == 'eligible' and audited['source_status'] == 'missing'
    assert audited['source_reference']['sha256'] == first['source_reference']['sha256']
    second = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert second['status'] == 'indexed' and second['cached'] and len(fake.calls) == 1
    assert second['input_fingerprint'] == first['input_fingerprint']
    assert first['source_status'] == 'present' and second['source_status'] == 'missing'


@pytest.mark.parametrize('broken', ['transcript', 'render', 'manifest'])
def test_source_missing_inconsistent_chain_ineligible(episode, broken):
    cfg, ws, _, out = episode
    (ws.dir / 'source.mp4').unlink()
    if broken == 'transcript':
        change(ws.dir / 'transcript.json', lambda d: d.update(media_sha256='other'))
    elif broken == 'render':
        change(out / 'render_manifest.json', lambda d: d.update(source_sha256='other'))
    else:
        change(ws.dir / 'manifest.json', lambda d: d['source'].update(sha256='other'))
    record = audit_playlist(cfg, 'PLtest')[0]
    assert record['status'] == 'ineligible' and 'stale' in record['reason'], record


def test_hd_missing_trusts_recorded_sha(episode):
    cfg, ws, _, out = episode
    sha = json.loads((ws.dir / 'manifest.json').read_text())['source']['sha256']
    hd, hd_sha = _write_hd(ws, sha)
    change(out / 'render_manifest.json', lambda d: d.update(source_sha256=hd_sha))
    present = audit_playlist(cfg, 'PLtest')[0]
    assert present['status'] == 'eligible' and present['source_status'] == 'present'
    hd.unlink()
    (ws.dir / 'source.mp4').unlink()
    missing = audit_playlist(cfg, 'PLtest')[0]
    assert missing['status'] == 'eligible' and missing['source_status'] == 'missing', missing
    assert missing['source_reference']['sha256'] == hd_sha and missing['source_reference']['original_sha256'] == sha
    fake = Fake()
    assert build_index(cfg, 'PLtest', client=fake)['records'][0]['status'] == 'indexed'
    assert build_index(cfg, 'PLtest', client=fake)['records'][0]['cached']
    # recorded HD sha no longer matches the render -> fail closed
    change(out / 'render_manifest.json', lambda d: d.update(source_sha256='other'))
    assert audit_playlist(cfg, 'PLtest')[0]['status'] == 'ineligible'


def test_hd_present_but_changed_is_stale(episode):
    cfg, ws, _, out = episode
    sha = json.loads((ws.dir / 'manifest.json').read_text())['source']['sha256']
    hd, hd_sha = _write_hd(ws, sha)
    change(out / 'render_manifest.json', lambda d: d.update(source_sha256=hd_sha))
    hd.write_bytes(b'tampered-hd-different-size')
    assert audit_playlist(cfg, 'PLtest')[0]['status'] == 'ineligible'


def test_warm_audit_reuses_hash_json_and_derived_digests(episode, memo_cache, monkeypatch):
    cfg, ws, _, _ = episode
    before = audit_playlist(cfg, 'PLtest')
    cached_docs = {p: deepcopy(tc1._read(p)) for p in
                   (ws.dir / 'clips.json', ws.dir / 'candidates.json', ws.dir / 'transcript.json')}
    stats = [cache.cache_info() for cache in memo_cache]
    monkeypatch.setattr(hashing, 'sha256_file', lambda p: pytest.fail('warm audit hashed an unchanged file'))
    warm = audit_playlist(cfg, 'PLtest')
    assert warm == before
    assert all(cache.cache_info().hits > old.hits for cache, old in zip(memo_cache, stats))
    assert all(cache.cache_info().misses == old.misses for cache, old in zip(memo_cache, stats))
    assert {p: tc1._read(p) for p in cached_docs} == cached_docs  # render_targets did not mutate inputs


@pytest.mark.parametrize('mode', ['write', 'same-size-restored-mtime', 'atomic-replace', 'remove'])
def test_stat_changes_invalidate_sha_json_and_derived_digest(tmp_path, memo_cache, mode):
    path = tmp_path / 'artifact.json'
    path.write_text('{"value":"old"}')
    before = path.stat()
    doc, key = tc1._read_snapshot(path)
    old_digest, old_sha = tc1._json_digest(key), tc1._file(path)
    assert doc == {'value': 'old'}
    if mode == 'remove':
        path.unlink()
        with pytest.raises(OSError):
            tc1._file(path)
        with pytest.raises(IndexError):
            tc1._read(path)
        return
    if mode == 'atomic-replace':
        replacement = tmp_path / 'new.json'
        replacement.write_text('{"value":"new"}')
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(path)
        assert path.stat().st_ino != before.st_ino
    else:
        if mode == 'same-size-restored-mtime':
            # Linux can give two immediate writes the same timestamp tick.
            # This case specifically exercises a *changed ctime* with mtime restored.
            time.sleep(.02)
        path.write_text('{"value":"new"}' if mode != 'write' else '{"value":"new and longer"}')
        if mode == 'same-size-restored-mtime':
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            assert path.stat().st_size == before.st_size and path.stat().st_mtime_ns == before.st_mtime_ns
            assert path.stat().st_ctime_ns != before.st_ctime_ns
    current, new_key = tc1._read_snapshot(path)
    assert new_key != key and current['value'].startswith('new')
    assert tc1._json_digest(new_key) != old_digest
    assert tc1._json_digest(new_key) == hashing.config_hash(current)
    with pytest.raises(IndexError, match='stale content'):
        tc1._file(path, old_sha)


def test_modified_file_still_invalidates_warm_index(episode, memo_cache):
    cfg, ws, _, out = episode
    fake = Fake()
    first = build_index(cfg, 'PLtest', client=fake)
    record = build_index(cfg, 'PLtest', client=fake, write=False)['records'][0]
    assert record['cached'] and record['input_fingerprint'] == first['records'][0]['input_fingerprint']
    # Same length and restored mtime: ctime must still invalidate the media hash.
    video = out / 'shorts' / 'k01.mp4'
    st = video.stat()
    time.sleep(.02)  # ensure this test changes ctime even on a coarse timestamp tick
    video.write_bytes(b'changed!')
    os.utime(video, ns=(st.st_atime_ns, st.st_mtime_ns))
    after = build_index(cfg, 'PLtest', client=fake, write=False)['records'][0]
    assert after['status'] == 'ineligible' and 'stale content' in after['reason']
    assert len(fake.calls) == 1


def test_returned_index_does_not_expose_mutable_cache(episode, memo_cache):
    cfg, *_ = episode
    fake = Fake()
    build_index(cfg, 'PLtest', client=fake)
    original = build_index(cfg, 'PLtest', client=fake, write=False)['records']
    mutated = build_index(cfg, 'PLtest', client=fake, write=False)['records']
    mutated[0]['favorite']['episode_id'] = 'other.kt'
    mutated[0]['inputs']['favorite']['clip'] = 'other'
    mutated[0]['metadata']['synopsis']['text'] = 'invented'
    assert build_index(cfg, 'PLtest', client=fake, write=False)['records'] == original
    assert len(fake.calls) == 1


def test_concurrent_audits_are_equal_and_json_lru_is_bounded(episode, tmp_path, memo_cache):
    cfg, *_ = episode
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda _: audit_playlist(cfg, 'PLtest'), range(16)))
    assert all(r == records[0] for r in records) and records[0][0]['status'] == 'eligible'
    for cache in memo_cache:
        assert 0 < cache.cache_info().maxsize < 10000
    # Exercise real eviction rather than relying on the declared limit alone.
    first = tmp_path / 'lru-0.json'
    for n in range(tc1._cached_json.cache_info().maxsize + 1):
        path = tmp_path / f'lru-{n}.json'
        path.write_text('{"value":1}')
        tc1._read(path)
    stats = tc1._cached_json.cache_info()
    assert stats.currsize == stats.maxsize
    assert tc1._read(first) == {'value': 1}
    assert tc1._cached_json.cache_info().misses == stats.misses + 1


def test_change_during_hash_is_not_cached(tmp_path, memo_cache, monkeypatch):
    path = tmp_path / 'clip.mp4'
    path.write_bytes(b'old')
    original = hashing.sha256_file
    def changing(p):
        digest = original(p)
        p.write_bytes(b'new content')  # size change is deterministic even within one timestamp tick
        return digest
    monkeypatch.setattr(hashing, 'sha256_file', changing)
    with pytest.raises(IndexError, match='changed during audit'):
        tc1._file(path)
    assert tc1._file_digest.cache_info().currsize == 0
    monkeypatch.setattr(hashing, 'sha256_file', original)
    assert tc1._file(path) == original(path)


def test_hd_intro_stored_bytes_keep_content_identity_and_index_cache(episode):
    cfg, ws, _, out = episode
    original_sha = json.loads((ws.dir / 'manifest.json').read_text())['source']['sha256']
    path, hd_sha = _write_hd(ws, original_sha)
    change(out / 'render_manifest.json', lambda d: d.update(source_sha256=hd_sha))
    fake = Fake()
    before = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert before['status'] == 'indexed'
    size = path.stat().st_size
    path.write_bytes(b'intro-and-enhanced-hd')
    atomic_write_json(ws.dir / 'hd_intro.json', {'version': 1, 'status': 'done',
        'original': {'sha256': hd_sha, 'size': size},
        'stored': {'sha256': hashing.sha256_file(path), 'size': path.stat().st_size},
        'frames': 90, 'fps': '30000/1001', 'offset_seconds': 3.003})
    after = build_index(cfg, 'PLtest', client=fake)['records'][0]
    assert after['cached'] and after['source_reference'] == before['source_reference']
    assert len(fake.calls) == 1
