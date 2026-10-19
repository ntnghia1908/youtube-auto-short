import json
import shutil
import subprocess
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from auto_short import hashing, theme_index, theme_plan as tp, theme_render as tr
from auto_short.ingest.youtube import Download, YoutubeBlocked, DownloadError
from auto_short.render.full import SourceBlocked
from auto_short.render.stage import RenderError, probe_media
from auto_short.theme_render import audio
from auto_short.workspace import atomic_write_json

from test_theme_index import Fake, change, episode  # noqa: F401
from test_theme_plan import Planner


def checked(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc


def make_plan(cfg, *, approve=True):
    proposal = tp.propose(cfg, 'PLtest', client=Planner())['proposals'][0]
    doc = tp.create_plan(cfg, 'PLtest', proposal['proposal_id'])
    if approve:
        doc = tp.approve_plan(cfg, 'PLtest', doc['plan_id'], revision=1, duration_override=True)
    return doc


def no_call(*args, **kwargs):
    pytest.fail('unexpected downloader/runner call')


@pytest.mark.parametrize('state', ['draft', 'stale', 'fingerprint'])
def test_unapproved_or_changed_input_writes_nothing(episode, monkeypatch, state):
    cfg, ws, folder, out = episode
    doc = make_plan(cfg, approve=state != 'draft')
    if state == 'stale':
        (ws.dir / 'source.mp4').write_bytes(b'changed')
    elif state == 'fingerprint':
        actual = theme_index.build_index
        calls = 0

        def changed(*args, **kwargs):
            nonlocal calls
            result = actual(*args, **kwargs)
            calls += 1
            if calls == 2:  # approval passed, but the independent TC3 read sees changed input
                result['records'][0]['input_fingerprint'] = 'changed'
            return result

        monkeypatch.setattr(theme_index, 'build_index', changed)
    before = {p: p.read_bytes() for p in cfg.workspace.dir.parent.rglob('*') if p.is_file()}
    with pytest.raises((tp.PlanError, RenderError), match='draft|stale|fingerprint'):
        tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=no_call, downloader=no_call)
    assert {p: p.read_bytes() for p in cfg.workspace.dir.parent.rglob('*') if p.is_file()} == before


@pytest.fixture(scope='module')
def synthetic_source(tmp_path_factory):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg/ffprobe unavailable')
    path = tmp_path_factory.mktemp('tc3-source') / 'source.mp4'
    signal = '(0.3+0.12*sin(7*t)+0.09*sin(19*t)+0.06*sin(31*t))*sin(2*PI*(330*t+37*t*t))'
    checked(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=25:duration=7',
             '-f', 'lavfi', '-i', f'aevalsrc={signal}:s=48000:d=7',
             '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-c:a', 'aac', '-b:a', '192k', str(path)])
    return path


@pytest.fixture
def media(episode, synthetic_source, monkeypatch):
    cfg, ws, folder, out = episode
    cfg = replace(cfg, render=replace(cfg.render, preset='ultrafast', threads=2))
    src = ws.dir / 'source.mp4'
    shutil.copyfile(synthetic_source, src)
    sha = hashing.sha256_file(src)
    change(ws.dir / 'manifest.json', lambda d: d['source'].update(sha256=sha, uri='https://youtube.test/lecture'))
    change(ws.dir / 'transcript.json', lambda d: d.update(media_sha256=sha, segments=[
        dict(id='s1', start=0.7, end=1.5, kind='speech', text='Chuyên tâm tu học.'),
        dict(id='s2', start=3.4, end=5, kind='speech', text='Giữ tâm thanh tịnh.')]))
    transcript = json.loads((ws.dir / 'transcript.json').read_text())
    digest = hashing.config_hash(transcript['segments'])
    change(ws.dir / 'transcript.json', lambda d: d.update(transcript_sha256=digest))
    clips = dict(clips=[dict(id='k01', candidate_id='c1', source_start=0.6, source_end=3.1, duration=2),
                        dict(id='k02', candidate_id='c2', source_start=3.3, source_end=5.3, duration=2)])
    candidates = dict(candidates=[dict(id='c1', trims=[[1.8, 2.3]]), dict(id='c2', trims=[])],
                      transcript_sha256=digest, params=dict(max_pause=1))
    atomic_write_json(ws.dir / 'clips.json', clips)
    atomic_write_json(ws.dir / 'candidates.json', candidates)
    shorts = []
    ranges = [[[0.6, 1.8], [2.3, 3.1]], [[3.3, 5.3]]]
    for i, (clip, segments) in enumerate(zip(clips['clips'], ranges), 1):
        path = out / 'shorts' / f'k{i:02d}.mp4'
        # Independent reference construction: audio trims/concat only, with a small portrait video.
        chains = [f'[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{j}]'
                  for j, (a, b) in enumerate(segments)]
        chains.append(''.join(f'[a{j}]' for j in range(len(segments))) +
                      f'concat=n={len(segments)}:v=0:a=1,aresample=48000,aformat=channel_layouts=stereo[a]')
        checked(['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-f', 'lavfi', '-i',
                 'color=yellow:size=108x192:rate=25:duration=2', '-filter_complex', ';'.join(chains),
                 '-map', '1:v', '-map', '[a]', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2',
                 '-c:a', 'aac', '-b:a', cfg.render.audio_bitrate, str(path)])
        shorts.append(dict(clip_id=clip['id'], candidate_id=clip['candidate_id'], status='rendered',
                           file=f'shorts/k{i:02d}.mp4', sha256=hashing.sha256_file(path),
                           source_start=clip['source_start'], source_end=clip['source_end'], segments=segments,
                           duration=2, origin='ai', cut=None, title=f'Chương {i}'))
    atomic_write_json(out / 'render_manifest.json', dict(episode_id=ws.episode_id, source_sha256=sha,
        clips_sha256=hashing.config_hash(clips), candidates_sha256=hashing.config_hash(candidates),
        titles_sha256=hashing.config_hash({}), shorts=shorts))
    # Reverse the order so the render must respect the plan, rather than the source/manifest order.
    change(folder / 'favorites.json', lambda d: d.update(items=[dict(episode_id=ws.episode_id, clip=k)
                                                              for k in ('k02', 'k01')]))
    # TC1's production minimum is minutes. Only shorten eligibility in this synthetic test workspace.
    monkeypatch.setattr(theme_index, 'MIN_DURATION', 1)
    # Persistent source cache uses the original video's ingest artifacts.
    owner = cfg.workspace.dir / 'lecture'
    atomic_write_json(owner / 'manifest.json', json.loads((ws.dir / 'manifest.json').read_text()))
    atomic_write_json(owner / 'metadata.json', dict(duration=7, height=720))
    doc = make_plan(cfg)
    return cfg, ws, folder, out, doc


def assert_clean(folder):
    theme = folder / 'theme'
    assert not (theme / '.fetch').exists()
    assert not list(theme.glob('.render-*'))


def test_real_render_two_clips_order_chapters_cache_revision(media, tmp_path):
    cfg, ws, folder, out, doc = media
    before = {p: p.read_bytes() for root in (ws.dir, out) for p in root.rglob('*') if p.is_file()}
    calls = []

    def runner(cmd):
        calls.append(cmd)
        return checked(cmd)

    result = tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=runner, downloader=no_call)
    assert result.ran and result.path.name == f"{doc['plan_id']}-r1.mp4"
    info = probe_media(result.path, checked)
    assert (info['video']['width'], info['video']['height'], info['video']['sample_aspect_ratio']) == (1920, 1080, '1:1')
    assert info['audio'] and abs(info['duration'] - 4) <= 2 / 25
    metadata = result.metadata
    assert [c['id'] for c in metadata['clips']] == ['lecture.kt/k02', 'lecture.kt/k01']
    assert [c['title'] for c in metadata['chapters']] == ['Chương 2', 'Chương 1']
    assert metadata['chapters'][0]['start'] == 0
    assert metadata['chapters'][1]['start'] == pytest.approx(2, abs=1 / 25)
    assert '00:00 Chương 2' in metadata['description']
    assert '00:02 Chương 1' in metadata['description']
    assert all(c['audio_match']['corr'] >= .9 and abs(c['audio_match']['lag']) <= .04 for c in metadata['clips'])
    # Also inspect the assembled audio order against independently rendered references.
    values, _ = audio.envelope(result.path, tmp_path / 'joined.wav', checked)
    for n, k in enumerate(('k02', 'k01')):
        ref, _ = audio.envelope(out / 'shorts' / f'{k}.mp4', tmp_path / 'ref.wav', checked)
        # Stream copy keeps AAC priming/padding; allow the contract's 40 ms alignment tolerance.
        assert max(audio._correlation(values[n * 100 + 5 + lag:n * 100 + 90 + lag], ref[5:90])
                   for lag in range(-2, 3)) >= .9
    assert json.loads(result.path.with_suffix('.json').read_text()) == metadata
    assert metadata['sha256'] == hashing.sha256_file(result.path)
    assert tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=no_call, downloader=no_call).ran is False
    new = tp.update_plan(cfg, 'PLtest', doc['plan_id'], revision=1, title='Đổi thứ tự',
                         clip_ids=['lecture.kt/k01', 'lecture.kt/k02'])
    tp.approve_plan(cfg, 'PLtest', doc['plan_id'], revision=new['revision'], duration_override=True)
    revised = tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=runner, downloader=no_call)
    assert revised.ran and revised.path != result.path and revised.path.is_file() and result.path.is_file()
    assert revised.metadata['plan_fingerprint'] != metadata['plan_fingerprint']
    assert {p: p.read_bytes() for p in before} == before
    assert_clean(folder)
    assert not any('-vf' in cmd for cmd in calls)  # compatible clips assembled by stream copy


def test_real_missing_source_download_once_and_cleanup(media, synthetic_source):
    cfg, ws, folder, _, doc = media
    (ws.dir / 'source.mp4').unlink()
    (ws.dir / 'archive.json').write_text('{"archived": true}')
    before = {p: p.read_bytes() for p in ws.dir.rglob('*') if p.is_file()}
    calls = []

    def downloader(uri, dest, ingest):
        calls.append((uri, dest, ingest))
        assert dest.is_relative_to(cfg.workspace.dir / '_theme_sources')
        target = dest / 'source.mp4'
        shutil.copyfile(synthetic_source, target)
        # Different container bytes, identical decoded content: warn, then rely on the speech gate.
        with target.open('ab') as stream:
            stream.write(b'tc3-equivalent-container')
        return Download(target, {})

    result = tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=checked, downloader=downloader)
    assert len(calls) == 1 and calls[0][2] == cfg.ingest
    assert all(c['source'] == 'refetched' for c in result.metadata['clips'])
    assert all(c['warning'] for c in result.metadata['clips'])
    assert not calls[0][1].exists() and not (ws.dir / 'source.mp4').exists()
    assert (cfg.workspace.dir / '_theme_sources' / 'lecture' / 'source.mp4').is_file()
    assert {p: p.read_bytes() for p in ws.dir.rglob('*') if p.is_file()} == before
    assert_clean(folder)


@pytest.mark.parametrize('failure', ['offset', 'content', 'blocked', 'download', 'encode', 'cancel'])
def test_fetch_failure_closed_and_cleanup(media, synthetic_source, failure):
    cfg, ws, folder, _, doc = media
    (ws.dir / 'source.mp4').unlink()

    def downloader(uri, dest, ingest):
        if failure == 'blocked':
            raise YoutubeBlocked('bot check')
        if failure == 'download':
            (dest / 'partial').write_bytes(b'partial')
            raise DownloadError('broken download')
        target = dest / 'source.mp4'
        if failure in ('offset', 'content'):
            vf = ['-af', 'adelay=200:all=1'] if failure == 'offset' else [
                '-af', 'aeval=0.3*sin(2*PI*440*t)*(0.5+0.4*sin(43*t)):c=mono']
            checked(['ffmpeg', '-v', 'error', '-y', '-i', str(synthetic_source), *vf,
                     '-c:v', 'copy', '-c:a', 'aac', '-ac', '2', '-b:a', '192k', str(target)])
        else:
            shutil.copyfile(synthetic_source, target)
        return Download(target, {})

    def runner(cmd):
        if '-filter_complex_script' in cmd:
            if failure == 'encode':
                return subprocess.CompletedProcess(cmd, 1, '', 'injected encode failure')
            if failure == 'cancel':
                raise KeyboardInterrupt()
        return checked(cmd)

    error = SourceBlocked if failure == 'blocked' else KeyboardInterrupt if failure == 'cancel' else RenderError
    with pytest.raises(error) as caught:
        tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=runner, downloader=downloader)
    if failure in ('offset', 'content'):
        assert 'phần lời' in str(caught.value), caught.value
    assert not list((folder / 'theme').glob('*.mp4'))
    assert not list((folder / 'theme').glob('*.json'))
    assert not (ws.dir / 'source.mp4').exists()
    assert_clean(folder)


def test_reference_kept_sha_and_fallback_title(episode):
    cfg, ws, folder, out = episode
    doc = make_plan(cfg)
    record = theme_index.build_index(cfg, 'PLtest', client=Fake(), write=False)['records'][0]
    kept = folder / 'kept' / ws.episode_id / 'k01.mp4'
    kept.parent.mkdir(parents=True)
    shutil.copyfile(out / 'shorts' / 'k01.mp4', kept)
    record['inputs']['favorite']['kept'] = dict(path=f'kept/{ws.episode_id}/k01.mp4', title=None,
        duration=350, episode_number='9', clip_number=1, clip_total=1, saved_at='now')
    (out / 'shorts' / 'k01.mp4').unlink()
    atomic_write_json(ws.dir / 'titles.json', dict(header=dict(fields=dict(episode='9'))))
    path, title = tr._reference(cfg, 'PLtest', record)
    assert path == kept and title == 'T9 KT1'
    kept.write_bytes(b'wrong')
    with pytest.raises(RenderError, match='sha256'):
        tr._reference(cfg, 'PLtest', record)
    # TC1 currently rejects a missing Short even when a kept copy is available.
    with pytest.raises(tp.PlanError, match='stale'):
        tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=no_call, downloader=no_call)


def test_graph_uses_short_frame_grid_and_audio_cuts():
    segments = [(600, 1800), (2300, 3100)]
    graph = tr.filter_graph(segments, Fraction(25), .15)
    assert 'xfade=transition=fade:duration=0.16:offset=1.12' in graph
    assert 'atrim=start=0.6:end=1.8' in graph and 'atrim=start=2.3:end=3.1' in graph
    hard = tr.filter_graph(segments, Fraction(25), 0)
    assert "between(round(t*25),15,44)+between(round(t*25),58,77)" in hard
    assert 'xfade' not in hard and 'crop=' not in graph


@pytest.mark.parametrize('kind', ['silence', 'constant', 'duration'])
def test_audio_gate_unverifiable_envelope_or_duration(monkeypatch, tmp_path, kind):
    values = [0.0] * 100 if kind == 'silence' else [100.0] * 100 if kind == 'constant' else [float(i % 11) for i in range(100)]
    monkeypatch.setattr(audio, 'envelope', lambda path, *args: (values, 2.2 if kind == 'duration' and path.name == 'new' else 2))
    with pytest.raises(RenderError, match='tương quan|thời lượng'):
        audio.compare(Path('new'), Path('ref'), tmp_path, no_call)


def test_cache_key_tracks_encode_and_audio_policy(episode, monkeypatch):
    cfg, *_ = episode
    make_plan(cfg)
    records = theme_index.build_index(cfg, 'PLtest', client=Fake(), write=False)['records']
    key = tr._encode_key(cfg, records)
    assert key != tr._encode_key(replace(cfg, render=replace(cfg.render, crf=cfg.render.crf + 1)), records)
    monkeypatch.setattr(audio, 'MIN_CORRELATION', .95)
    assert key != tr._encode_key(cfg, records)


@pytest.mark.parametrize('mismatch', ['none', 'file', 'encode_key', 'plan_fingerprint', 'json'])
def test_cache_requires_matching_fingerprint_key_and_file_sha(episode, monkeypatch, mismatch):
    cfg, _, folder, _ = episode
    doc = make_plan(cfg)
    records = theme_index.build_index(cfg, 'PLtest', client=Fake(), write=False)['records']
    folder = folder / 'theme'
    folder.mkdir()
    output = folder / f"{doc['plan_id']}-r1.mp4"
    output.write_bytes(b'previously verified output')
    metadata = dict(schema_version=1, plan_fingerprint=tp.plan_fingerprint(doc),
                    encode_key=tr._encode_key(cfg, records), sha256=hashing.sha256_file(output))
    if mismatch == 'file':
        output.write_bytes(b'tampered output')
    elif mismatch in ('encode_key', 'plan_fingerprint'):
        metadata[mismatch] = 'old'
    atomic_write_json(output.with_suffix('.json'), metadata)
    if mismatch == 'json':
        output.with_suffix('.json').write_text('{bad')
    monkeypatch.setattr(tr, '_reference', lambda *args: (Path('unused'), 'Title'))

    def source(*args):
        raise RenderError('must rebuild')

    monkeypatch.setattr(tr, '_source', source)
    if mismatch == 'none':
        assert not tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=no_call).ran
    else:
        with pytest.raises(RenderError, match='must rebuild'):
            tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=no_call)
    assert_clean(folder.parent)


@pytest.mark.parametrize('fields,byline', [
    ({'speaker': 'HT.Tịnh Không', 'series': 'Kinh Địa Tạng'}, 'HT.Tịnh Không · Kinh Địa Tạng'),
    ({'speaker': 'HT.Tịnh Không'}, 'HT.Tịnh Không'),
    ({'series': 'Kinh Địa Tạng'}, 'Kinh Địa Tạng'), ({}, '')])
def test_description_refresh_on_cache_hit_without_encoding(episode, fields, byline):
    cfg, ws, folder, out = episode
    titles = {'header': {'fields': fields}}
    atomic_write_json(ws.dir / 'titles.json', titles)
    change(out / 'render_manifest.json', lambda d: d.update(titles_sha256=hashing.config_hash(titles)))
    doc = make_plan(cfg)
    records = theme_index.build_index(cfg, 'PLtest', client=Fake(), write=False)['records']
    folder = folder / 'theme'
    folder.mkdir()
    output = folder / f"{doc['plan_id']}-r1.mp4"
    output.write_bytes(b'previously verified output')
    chapters = [{'start': 0, 'title': 'Chuyên tâm'}, {'start': 120, 'title': 'Giữ tâm'}]
    metadata = dict(schema_version=1, plan_fingerprint=tp.plan_fingerprint(doc),
                    encode_key=tr._encode_key(cfg, records), sha256=hashing.sha256_file(output),
                    chapters=chapters, description='old description', created_at='old timestamp')
    path = output.with_suffix('.json')
    atomic_write_json(path, metadata)
    original = output.stat()
    result = tr.render_landscape(cfg, 'PLtest', doc['plan_id'], hashtags=['#DiaTang', '#PhatPhap'],
                                 runner=no_call, downloader=no_call)
    heading = doc['title'] + ('\n' + byline if byline else '')
    assert result.metadata['description'] == heading + '\n\n00:00 Chuyên tâm\n02:00 Giữ tâm\n\n#DiaTang #PhatPhap'
    assert not result.ran and output.stat() == original
    assert json.loads(path.read_text()) == result.metadata
    assert {k: v for k, v in result.metadata.items() if k != 'description'} == {
        k: v for k, v in metadata.items() if k != 'description'}
    unchanged = path.stat()
    same = tr.render_landscape(cfg, 'PLtest', doc['plan_id'], hashtags=['#DiaTang', '#PhatPhap'],
                               runner=no_call, downloader=no_call)
    assert not same.ran and path.stat() == unchanged
    removed = tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=no_call, downloader=no_call)
    assert not removed.ran and '#' not in removed.metadata['description']
    assert output.stat() == original and removed.metadata['encode_key'] == metadata['encode_key']


def test_present_source_sha_checked_again_after_audit(episode, monkeypatch):
    cfg, ws, folder, _ = episode
    doc = make_plan(cfg)
    actual = theme_index.build_index
    calls = 0

    def changed(*args, **kwargs):
        nonlocal calls
        result = actual(*args, **kwargs)
        calls += 1
        if calls == 2:
            (ws.dir / 'source.mp4').write_bytes(b'changed after audit')
        return result

    monkeypatch.setattr(theme_index, 'build_index', changed)
    with pytest.raises(RenderError, match='sau khi audit'):
        tr.render_landscape(cfg, 'PLtest', doc['plan_id'], runner=no_call, downloader=no_call)
    assert_clean(folder)


@pytest.mark.parametrize('sar,bars', [('1', True), ('4/3', False)])
def test_real_aspect_ratio_padding_and_square_pixels(tmp_path, sar, bars):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg/ffprobe unavailable')
    src, dst = tmp_path / 'source.mp4', tmp_path / 'wide.mp4'
    checked(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=red:size=320x240:rate=25:duration=0.4',
             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.4', '-vf', f'setsar={sar}',
             '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-c:a', 'aac', str(src)])
    script = tmp_path / 'landscape.filter'
    script.write_text(tr.filter_graph([(0, 400)], Fraction(25), 0))
    checked(tr.plan.ffmpeg_command(ffmpeg='ffmpeg', source=src, output=dst, graph_script=script,
        segments=[(0, 400)], fps=Fraction(25), crf=22, preset='ultrafast', audio_bitrate='192k', threads=2))
    tr._verify(dst, .4, 1 / 25, checked, fps=Fraction(25), frames=10)
    frame = tmp_path / 'frame.rgb'
    checked(['ffmpeg', '-v', 'error', '-y', '-i', str(dst), '-vf', 'scale=192:108', '-frames:v', '1',
             '-pix_fmt', 'rgb24', '-f', 'rawvideo', str(frame)])
    pixels = frame.read_bytes()

    def pixel(x):
        start = (54 * 192 + x) * 3
        return tuple(pixels[start:start + 3])

    assert pixel(96)[0] > 200 and pixel(96)[1] < 20  # centre preserves the full red picture
    assert (max(pixel(5)) < 20) if bars else (pixel(5)[0] > 200)
