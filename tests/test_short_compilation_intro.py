"""KTI2: local media and live-runner adapters, without sockets or real services."""
import shutil
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from auto_short import hashing, khaithi, theme_index, theme_plan, theme_render
from auto_short.compilation import Item, Spec, meta, store
from auto_short.compilation.assemble import assemble
from auto_short.config import Config, PackagingConfig, RenderConfig, WorkspaceConfig, StoreConfig
from auto_short.packaging import compilation_thumbs as ct, cover, khaithi_thumbs as kt
from auto_short.render import intro, stage
from auto_short.web.compilations import Clip, Compilations
from auto_short.web.jobs import Job, JobFailed, KIND_RENDER, render_target
from auto_short.web.priority import Priority
from auto_short.workspace import atomic_write_json, read_json_dict
from render_helpers import EID, make_render_episode, make_source, ffmpeg, frame_hashes, assert_fade
from test_packaging_cover import source_image
from test_packaging_episode import PID
from test_store_server import PLAYLIST, archive  # noqa: F401
from test_store_shorts_edit import memory_store  # noqa: F401
from test_theme_index import episode, Fake  # noqa: F401
from test_theme_render import media, synthetic_source  # noqa: F401


def assert_picture(video, image):
    pixels = ('-frames:v', '1', '-vf', 'scale=36:64', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-')
    actual, expected = ffmpeg('-i', video, *pixels), ffmpeg('-i', image, *pixels)
    assert sum(abs(a-b) for a, b in zip(actual, expected)) / len(actual) < 5


@pytest.mark.parametrize('filename', ['khaithi_from.json', 'short_intro_from.json'])
@pytest.mark.parametrize('value,expected', [(1, 1), (31, 31), (0, None), (-1, None), (True, None),
                                             (1.5, None), ('1', None), (None, None)])
def test_start_one_and_invalid_values(tmp_path, filename, value, expected):
    cfg = Config(packaging=PackagingConfig(tmp_path / 'assets'))
    atomic_write_json(cfg.packaging.asset_dir / filename, dict(schema_version=1, playlists={PID: value}))
    assert kt.start_episode(cfg, PID, filename=filename) == expected
    assert kt.before_start(cfg, PID, 1, filename=filename) == (expected is not None and expected > 1)


@pytest.fixture
def short(tmp_path):
    cfg = Config(workspace=WorkspaceConfig(tmp_path / 'work'), packaging=PackagingConfig(tmp_path / 'assets'),
                 render=RenderConfig(output_dir=tmp_path / 'output', preset='ultrafast', threads=2))
    ws = make_render_episode(cfg.workspace.dir, make_source(tmp_path / 'source.mp4', size='320x240', rate='25', seconds=2),
        clips=[dict(id='k01', candidate_id='c1', source_start=0, source_end=1.2, duration=1.2)],
        candidates=[dict(id='c1', trims=[])], titles={'k01': 'Giữ tâm thanh tịnh'})
    doc = read_json_dict(ws.dir / 'titles.json')
    doc['header']['fields'] = dict(series='Kinh Vô Lượng Thọ', episode='31', speaker='HT. Tịnh Không')
    atomic_write_json(ws.dir / 'titles.json', doc)
    atomic_write_json(cfg.workspace.dir / '_playlists' / f'{PID}.json',
                      dict(playlist_id=PID, entries=[dict(video_id=EID, episode='31')]))
    stage.run_render(EID, cfg)
    folder = cfg.render.output_dir / EID
    baseline = tmp_path / 'baseline.mp4'
    shutil.copyfile(folder / 'shorts/k01.mp4', baseline)
    cover.install(cfg, PID, 'kt_vertical', source_image(tmp_path), [100, 700, 880, 700])
    atomic_write_json(cfg.packaging.asset_dir / 'short_intro_from.json', dict(schema_version=1, playlists={PID: 31}))
    return cfg, ws, folder, baseline


@pytest.mark.parametrize('fresh', [False, True])
def test_short_intro_pixels_silence_cache_title_and_review(short, fresh, monkeypatch):
    cfg, ws, folder, baseline = short
    before = read_json_dict(folder / 'render_manifest.json')
    if fresh:
        (folder / 'render_manifest.json').unlink()
        (folder / 'shorts/k01.mp4').unlink()
    seen = []
    original = kt.draw
    def draw(*args, **kwargs):
        seen.append(kwargs['label'])
        return original(*args, **kwargs)
    monkeypatch.setattr(kt, 'draw', draw)
    result = stage.run_render(EID, cfg)
    doc = read_json_dict(result.path)
    clip = doc['shorts'][0]
    assert seen == ['TRÍCH ĐOẠN'] and result.encoded == 1
    assert intro.content_manifest(doc) == before
    assert clip['content_sha256'] == hashing.sha256_file(baseline)
    assert clip['content_render_key'] == before['shorts'][0]['render_key']
    assert clip['content_offset'] == 3 and clip['intro']['transition'] == dict(type='fade', seconds=1)
    video = folder / clip['file']
    fields = kt.intro_context(cfg, EID, short=True)[1]
    image = kt.vertical_clip(cfg, EID, 'k01', pid=PID, fields=fields, short=True)
    assert image.parent.name == 'short_intro_thumbs' and not (folder / 'thumbs').exists()
    assert_picture(video, image)
    assert_fade(video, Fraction(25))
    pcm = ffmpeg('-i', video, '-t', 3, '-map', '0:a', '-f', 's16le', '-')
    assert not any(pcm)
    assert abs(stage.probe_media(video, stage._run)['duration'] - 4.2) < .1
    assemble([video, video], folder / 'content.mp4')
    assemble([baseline, baseline], folder / 'expected.mp4')
    assert frame_hashes(folder / 'content.mp4') == frame_hashes(folder / 'expected.mp4')
    assert not stage.run_render(EID, cfg).ran
    atomic_write_json(ws.dir / 'review.json', dict(schema_version=1, episode_id=EID,
        titles=[dict(clip_id='k01', candidate_id='c1', title='Học cách sống an vui', origin='manual')]))
    assert stage.run_render(EID, cfg).encoded == 1
    changed = read_json_dict(result.path)['shorts'][0]
    assert changed['intro']['sha256'] != clip['intro']['sha256'] and changed['render_key'] != clip['render_key']
    assert kt.titles(cfg, EID, short=True)[0].title == 'Học cách sống an vui'


@pytest.mark.parametrize('scope', ['before', 'other_playlist', 'only_kt_config'])
def test_short_outside_scope_keeps_bytes_and_key(short, scope):
    cfg, ws, folder, baseline = short
    atomic_write_json(cfg.packaging.asset_dir / 'short_intro_from.json',
                      dict(schema_version=1, playlists={PID: 32} if scope == 'before' else {}))
    if scope == 'only_kt_config':
        atomic_write_json(cfg.packaging.asset_dir / 'khaithi_from.json', dict(schema_version=1, playlists={PID: 12}))
    before = (folder / 'render_manifest.json').read_bytes()
    assert not stage.run_render(EID, cfg).ran
    assert (folder / 'render_manifest.json').read_bytes() == before
    assert (folder / 'shorts/k01.mp4').read_bytes() == baseline.read_bytes()


def test_short_missing_cover_has_reason_link_and_no_clip(short):
    cfg, ws, folder, _ = short
    cover.remove(cfg, PID, 'kt_vertical')
    video = folder / 'shorts/k01.mp4'
    previous = video.read_bytes()
    with pytest.raises(stage.RenderError, match=f'Bộ kinh chưa có ảnh bìa khai thị.* /playlists/{PID}/thumbs'):
        stage.run_render(EID, cfg)
    assert video.read_bytes() == previous
    video.unlink()
    target = render_target(cfg)
    with pytest.raises(JobFailed, match='Bộ kinh chưa có ảnh bìa khai thị'):
        target(Job('missing-short-cover', EID, KIND_RENDER, target))
    assert not video.exists() and ws.load_manifest()['stages']['render']['status'] == 'failed'


@pytest.mark.parametrize('released', [False, True])
def test_short_existing_archived_or_store_revision_without_source(short, memory_store, tmp_path, released):
    cfg, ws, folder, baseline = short
    cfg = replace(cfg, store=StoreConfig(enabled=True))
    video = folder / 'shorts/k01.mp4'
    stat, sha = video.stat(), hashing.sha256_file(video)
    client = memory_store.client
    client.put(EID, 'short', PLAYLIST, 'Tap 31 - k01.mp4', video, sha, clip='k01.mp4')
    if released:
        atomic_write_json(folder / 'store.json', dict(released={'k01': dict(sha256=sha, size=stat.st_size,
                                                                         mtime_ns=stat.st_mtime_ns)}))
        video.unlink()
    (ws.dir / 'source.mp4').unlink()
    atomic_write_json(ws.dir / 'archive.json', dict(schema_version=1, removed=['source.mp4']))
    calls = []
    def runner(cmd):
        calls.append(cmd)
        return stage._run(cmd)
    assert stage.run_render(EID, cfg, run=runner).encoded == 1
    assert all(str(ws.dir / 'source.mp4') not in cmd for cmd in calls)
    clip = read_json_dict(folder / 'render_manifest.json')['shorts'][0]
    client.put(EID, 'short', PLAYLIST, 'Tap 31 - k01.mp4', video, clip['sha256'], clip='k01.mp4')
    row = next(r for r in memory_store.service.index() if r['video_id'] == EID and r['clip'] == 'k01.mp4')
    assert row['file'].endswith('k01 (r2).mp4')
    from auto_short.store.shorts import borrow_short
    from auto_short.web.episodes import StoredShort
    stat = video.stat()
    stored = StoredShort(EID, 'k01.mp4', clip['sha256'], stat.st_size, stat.st_mtime_ns)
    with borrow_short(cfg, stored, tmp_path, client=client) as borrowed:
        assert intro.clip_record(borrowed) == clip
        assemble([borrowed], tmp_path / 'restored.mp4')
        assert frame_hashes(tmp_path / 'restored.mp4') == frame_hashes(baseline)
    assert not stage.run_render(EID, cfg).ran
    queue = SimpleNamespace(priority=Priority(), submit=lambda *a: pytest.fail('queued current Short'))
    assert kt.enqueue_intro_rebuild(cfg, queue, PID, 1, 50, short=True)['skipped'] == [EID]


def test_short_selector_range_priority_and_current(short):
    cfg, ws, folder, _ = short
    entries = [dict(video_id=EID)]
    for number in (30, 32, 40, 41):
        ident = f'lecture{number:04d}'
        shutil.copytree(ws.dir, cfg.workspace.dir / ident)
        doc = read_json_dict(cfg.workspace.dir / ident / 'titles.json')
        doc['header']['fields']['episode'] = str(number)
        atomic_write_json(cfg.workspace.dir / ident / 'titles.json', doc)
        shutil.copytree(folder, cfg.render.output_dir / ident)
        entries.append(dict(video_id=ident))
    atomic_write_json(cfg.workspace.dir / '_playlists' / f'{PID}.json', dict(playlist_id=PID, entries=entries))
    jobs = []
    queue = SimpleNamespace(priority=Priority(), submit=lambda eid, *args: (jobs.append(eid), True))
    result = kt.enqueue_intro_rebuild(cfg, queue, PID, 32, 41, short=True, prioritize_first_ten=True)
    assert result['queued'] == ['lecture0032', 'lecture0040', 'lecture0041']
    assert queue.priority.marked('lecture0032') and queue.priority.marked('lecture0040')
    assert not queue.priority.marked('lecture0041') and EID not in jobs


@pytest.mark.parametrize('short_kind', [False, True])
def test_episode_one_is_in_intro_context(short, short_kind):
    cfg, ws, _, _ = short
    ident = EID
    if not short_kind:
        ident += '.kt'
        shutil.copytree(ws.dir, cfg.workspace.dir / ident)
        khaithi.write(cfg.workspace.dir / ident, khaithi.KhaiThi(EID, 4, 7))
    path = cfg.workspace.dir / ident / 'titles.json'
    titles = read_json_dict(path)
    titles['header']['fields']['episode'] = '1'
    atomic_write_json(path, titles)
    atomic_write_json(ws.dir / 'titles.json', titles)
    filename = 'short_intro_from.json' if short_kind else 'khaithi_from.json'
    atomic_write_json(cfg.packaging.asset_dir / filename, dict(schema_version=1, playlists={PID: 1}))
    assert kt.intro_context(cfg, ident, short=short_kind)[1]['episode'] == '1'


def test_batch_queue_order_current_duplicates_priority_and_later_dia_tang(short, monkeypatch):
    from auto_short.web.jobs import compilation_key
    from auto_short.web.theme_plan import render_key
    cfg, ws, _, _ = short
    pids = [PID, 'PLcamungthien', 'PLthapthien1', 'PLdiatang123']
    pending = EID + '.kt'
    shutil.copytree(ws.dir, cfg.workspace.dir / pending)
    khaithi.write(cfg.workspace.dir / pending, khaithi.KhaiThi(EID, 4, 7))
    atomic_write_json(cfg.packaging.asset_dir / 'khaithi_from.json', dict(schema_version=1, playlists={p: 1 for p in pids}))
    calls, targets = [], []
    priority = Priority()
    priority.mark(['existing-kti1'])
    def submit(key, kind, target):
        calls.append((key, kind))
        return None, not key.endswith('3' * 12)
    runner = SimpleNamespace(priority=priority, submit=submit,
        jobs=lambda: [SimpleNamespace(episode_id=pending, active=True)])
    for pid in pids:
        atomic_write_json(cfg.workspace.dir / '_playlists' / f'{pid}.json',
                          dict(playlist_id=pid, entries=[dict(video_id=EID)]))
        folder = store.directory(cfg.render.output_dir, pid)
        for cid in ('1' * 12, '2' * 12, '3' * 12):
            store.write_doc(folder, dict(cid=cid, playlist_id=pid, status=store.DONE))
            store.video_path(folder, cid).write_bytes(b'old video')
        for plan_id in ('a' * 8, 'b' * 8, 'd' * 8):
            path = folder / 'theme' / f'{plan_id}-r1.mp4'
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'old landscape')
            atomic_write_json(path.with_suffix('.json'), dict(current=plan_id == 'd' * 8))
    def rebuild(key, doc):
        targets.append(key)
        return object()
    comps = SimpleNamespace(intro_current=lambda pid, doc: doc['cid'] == '2' * 12, rebuild=rebuild)
    plans = SimpleNamespace(plans=lambda pid: [dict(plan_id=c * 8, revision=1,
        check=dict(state='stale' if c == 'b' else 'approved')) for c in 'abcd'],
        render=lambda pid, ident: runner.submit(render_key(pid, ident), 'theme_render', object()))
    monkeypatch.setattr(ct, 'theme', lambda config, pid, ident: object())
    monkeypatch.setattr(ct, 'intro_current', lambda config, source, shape, doc, path: doc.get('current', False))
    def shorts(config, queue, pid, first, last, **kwargs):
        calls.append((pid, 'short' if kwargs.get('short') else 'khaithi'))
        assert kwargs.get('prioritize_first_ten', False) == (pid in pids[:3])
        return dict(queued=[pid], skipped=[])
    monkeypatch.setattr(kt, 'enqueue_intro_rebuild', shorts)
    result = ct.enqueue_intro_rebuild(cfg, runner, pids, compilations=comps, theme_plans=plans)
    video_calls = lambda pid: [(compilation_key(pid, '1' * 12), 'compilation'),
                               (compilation_key(pid, '3' * 12), 'compilation'),
                               (render_key(pid, 'a' * 8), 'theme_render')]
    assert calls == [item for pid in pids[:3] for item in video_calls(pid)] + [(pid, 'short') for pid in pids[:3]] \
        + video_calls(pids[3]) + [(pids[3], 'short'), (pids[3], 'khaithi')]
    assert len(result['queued']) == 8  # one favourite + one theme per playlist
    assert priority.videos()[:2] == ['existing-kti1', EID]
    assert all(priority.marked(compilation_key(pid, '1' * 12)) for pid in pids[:3])
    assert not priority.marked(compilation_key(pids[3], '1' * 12))
    assert all(compilation_key(pid, '2' * 12) in result['skipped'] for pid in pids)
    assert all(compilation_key(pid, '3' * 12) in result['skipped'] for pid in pids)


def test_favorites_builds_thumb2_intro_and_removes_short_intros(short, tmp_path):
    cfg, ws, folder, baseline = short
    stage.run_render(EID, cfg)
    cover.install(cfg, PID, 'kt_landscape', source_image(tmp_path, (1280, 720)), [300, 150, 880, 500])
    atomic_write_json(cfg.packaging.asset_dir / 'khaithi_from.json', dict(schema_version=1, playlists={PID: 12}))
    spec = Spec('concat', (Item(EID, 'k01'), Item(EID, 'k01')), 1)
    root = store.directory(cfg.render.output_dir, PID)
    stored = store.new_doc(PID, spec.cid, spec.mode, spec.items, 1, download_name='video.mp4',
                           title='Giữ tâm thanh tịnh', duration_estimate=2.4)
    store.write_doc(root, stored)
    queue = SimpleNamespace(latest=lambda key: None)
    playlists = SimpleNamespace(load=lambda pid: dict(playlist_id=pid), effective_hashtags=lambda doc: ([], None))
    service = Compilations(cfg, playlists, queue, lambda _: None)
    clip = Clip(Item(EID, 'k01'), (0, 0, 1), '31', 1, 1, 'Giữ tâm thanh tịnh', 1.2, folder / 'shorts/k01.mp4', 'short')
    service._lookup = lambda doc: {clip.item: clip}
    service._work(PID, spec, SimpleNamespace())
    doc = store.read_doc(root, spec.cid)
    assert doc['status'] == store.DONE and service.intro_current(PID, doc)
    source = ct.favorite(cfg, PID, spec.cid)
    thumbs = ct.read(source)
    image = source.folder / thumbs['files']['vertical']['file']
    assert doc['intro'] == intro.metadata(image) and doc['content_offset'] == 3
    output = store.video_path(root, spec.cid)
    assert_picture(output, image)
    expected = tmp_path / 'expected.mp4'
    assemble([baseline, baseline], expected)
    stripped = tmp_path / 'stripped.mp4'
    assemble([folder / 'shorts/k01.mp4'] * 2, stripped)
    assert doc['content_sha256'] == hashing.sha256_file(stripped)
    assert frame_hashes(output)[75:] == frame_hashes(expected)
    assert doc['chapters'] == meta.chapters(['Giữ tâm thanh tịnh'] * 2, [1.2, 1.2], content_offset=3)
    # Two input clips have become exactly two content sections after the one compilation prefix.
    assert len(frame_hashes(output)) == 135
    assert_fade(output, Fraction(25))
    snapshots = {p.name: p.read_bytes() for p in source.folder.iterdir()}
    assert ct.build(cfg, source) == dict(built=0, reused=2)
    assert {p.name: p.read_bytes() for p in source.folder.iterdir()} == snapshots
    stored = store.read_doc(root, spec.cid)
    stored['title'] = 'Học cách sống an vui'
    store.write_doc(root, stored)
    assert not service.intro_current(PID, stored)
    assert service.compilation_view(stored, [])['state'] == store.FAILED
    service._work(PID, spec, SimpleNamespace())
    assert service.intro_current(PID, store.read_doc(root, spec.cid))
    previous = output.read_bytes()
    cover.remove(cfg, PID, 'kt_vertical')
    with pytest.raises(JobFailed, match=f'Bộ kinh chưa có ảnh bìa khai thị.* /playlists/{PID}/thumbs'):
        service._work(PID, spec, SimpleNamespace())
    assert output.read_bytes() == previous


def test_theme_intro_preserves_content_plan_thumb2_and_chapters(media, tmp_path):
    cfg, ws, root, _, approved = media
    cfg = replace(cfg, packaging=PackagingConfig(tmp_path / 'assets'))
    # This fixture's playlist id predates the thumbnail ID boundary. Use a valid alias consistently.
    # Keeping the actual plan/records in place preserves its real approval and audio verification chain.
    old_pid = 'PLtest'
    playlist = read_json_dict(cfg.workspace.dir / '_playlists' / f'{old_pid}.json')
    playlist['playlist_id'] = PID
    atomic_write_json(cfg.workspace.dir / '_playlists' / f'{PID}.json', playlist)
    new_root = store.directory(cfg.render.output_dir, PID)
    shutil.copytree(root, new_root)
    plan_path = new_root / theme_plan.PLANS_DIR / f"{approved['plan_id']}.json"
    saved = read_json_dict(plan_path)
    saved['playlist_id'] = PID
    atomic_write_json(plan_path, saved)
    titles = dict(header=dict(fields=dict(series='Kinh Vô Lượng Thọ', episode='31', speaker='HT. Tịnh Không')))
    atomic_write_json(ws.dir / 'titles.json', titles)
    render_path = cfg.render.output_dir / ws.episode_id / 'render_manifest.json'
    rendered = read_json_dict(render_path)
    rendered['titles_sha256'] = hashing.config_hash(titles)
    atomic_write_json(render_path, rendered)
    theme_index.build_index(cfg, PID, client=Fake())
    saved = theme_plan.update_plan(cfg, PID, saved['plan_id'], revision=saved['revision'], title=saved['title'],
                                   clip_ids=[c['id'] for c in saved['clips']])
    # Reapprove under the alias; fingerprints change with playlist identity only before the baseline.
    approved = theme_plan.approve_plan(cfg, PID, saved['plan_id'], revision=saved['revision'], duration_override=True)
    baseline = theme_render.render_landscape(cfg, PID, approved['plan_id'])
    plain = tmp_path / 'plain.mp4'
    shutil.copyfile(baseline.path, plain)
    fingerprint = theme_plan.plan_fingerprint(approved)
    cover.install(cfg, PID, 'kt_vertical', source_image(tmp_path), [100, 700, 880, 700])
    cover.install(cfg, PID, 'kt_landscape', source_image(tmp_path, (1280, 720)), [300, 150, 880, 500])
    atomic_write_json(cfg.packaging.asset_dir / 'khaithi_from.json', dict(schema_version=1, playlists={PID: 12}))
    result = theme_render.render_landscape(cfg, PID, approved['plan_id'])
    doc = result.metadata
    assert result.ran and doc['intro']['seconds'] == 3
    assert frame_hashes(result.path)[75:] == frame_hashes(plain)
    assert doc['content_sha256'] == hashing.sha256_file(plain)
    assert doc['chapters'][0]['start'] == 0
    assert doc['chapters'][1]['start'] == baseline.metadata['chapters'][1]['start'] + 3
    assert '00:00 ' in doc['description'] and '00:05 ' in doc['description']
    assert theme_plan.plan_fingerprint(theme_plan.approved_plan(cfg, PID, approved['plan_id'])) == fingerprint
    source = ct.theme(cfg, PID, approved['plan_id'])
    assert ct.intro_current(cfg, source, 'landscape', doc, result.path)
    image = source.folder / ct.read(source)['files']['landscape']['file']
    assert_picture(result.path, image)
    assert_fade(result.path, Fraction(25))
    assert not theme_render.render_landscape(cfg, PID, approved['plan_id']).ran
    # Cover edits invalidate the render cache without staling approval or changing content frames.
    cover.install(cfg, PID, 'kt_landscape', source_image(tmp_path, (1280, 720), color='blue'), [300, 150, 880, 500])
    assert not ct.intro_current(cfg, ct.theme(cfg, PID, approved['plan_id']), 'landscape', doc, result.path)
    changed = theme_render.render_landscape(cfg, PID, approved['plan_id'])
    assert changed.ran and changed.metadata['encode_key'] != doc['encode_key']
    assert frame_hashes(changed.path)[75:] == frame_hashes(plain)
