import json
from dataclasses import replace

import pytest

from auto_short import hashing, khaithi
from auto_short.compilation import store
from auto_short.review import logic
from auto_short.selection.client import ChatResult
from auto_short.theme_index import audit_playlist, build_index, validate_metadata, IndexError
from auto_short.workspace import Workspace, atomic_write_json


class Fake:
    def __init__(self, bad=None):
        self.calls = []
        self.bad = bad

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        evidence = json.loads(kwargs['messages'][1]['content'])['evidence']
        ref = {k: evidence[0][k] for k in ('evidence_id', 'text')}
        doc = dict(topic='Tu học', subtopic='Chuyên tâm', synopsis=ref, key_messages=[ref], uncertainty=[])
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
        kwargs['prompt_version'] = 'tc1-v2'
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
    lambda d: d['synopsis'].update(text='invented'), lambda d: d['key_messages'][0].update(evidence_id='outside'),
    lambda d: d.update(topic='“invented speech”'), lambda d: d.update(uncertainty='unknown')])
def test_hallucination_rejected(episode, bad):
    cfg, *_ = episode
    record = build_index(cfg, 'PLtest', client=Fake(bad))['records'][0]
    assert record['status'] == 'ai_error'


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


@pytest.mark.parametrize('duration,eligible', [(299, False), (300, True), (420, True), (421, False)])
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


def test_uncertainty_cannot_carry_fabricated_speech(episode):
    record = build_index(episode[0], 'PLtest', client=Fake(lambda d: d.update(uncertainty=['invented speech'])))['records'][0]
    assert record['status'] == 'ai_error'
