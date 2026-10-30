"""KTI1: real local media, deterministic content identity and intro-free consumers (no sockets)."""
import shutil
import subprocess
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from auto_short import hashing, khaithi
from auto_short.compilation.assemble import assemble
from auto_short.config import Config, PackagingConfig, RenderConfig, WorkspaceConfig
from auto_short.packaging import cover, khaithi_thumbs as kt
from auto_short.render import intro, stage
from auto_short.web.priority import Priority
from auto_short.workspace import Workspace, atomic_write_json, read_json_dict
from render_helpers import EID, make_render_episode, make_source, write_docs
from test_packaging_cover import source_image
from test_packaging_episode import PID
from test_store_server import PLAYLIST, archive  # noqa: F401
from test_store_shorts_edit import memory_store  # noqa: F401


@pytest.fixture
def rendered(tmp_path, request):
    rate, preset = getattr(request, "param", ("25", "ultrafast"))
    cfg = Config(workspace=WorkspaceConfig(tmp_path / 'work'),
                 packaging=PackagingConfig(tmp_path / 'assets'),
                 render=RenderConfig(output_dir=tmp_path / 'output', preset=preset, threads=2))
    source = make_source(tmp_path / 'source.mp4', size='320x240', rate=rate, seconds=2)
    base = make_render_episode(cfg.workspace.dir, source)
    ws = Workspace(cfg.workspace.dir, EID + '.kt')
    base.dir.rename(ws.dir)
    manifest = ws.load_manifest()
    manifest['episode_id'] = ws.episode_id
    ws.save_manifest(manifest)
    write_docs(ws, clips=[dict(id='k01', candidate_id='c1', source_start=0, source_end=1.2, duration=1.2)],
               candidates=[dict(id='c1', trims=[])], titles={'k01': 'Giữ tâm thanh tịnh'})
    titles = read_json_dict(ws.dir / 'titles.json')
    titles['header']['fields'] = dict(series='Kinh Vô Lượng Thọ', episode='31', speaker='HT. Tịnh Không')
    atomic_write_json(ws.dir / 'titles.json', titles)
    khaithi.write(ws.dir, khaithi.KhaiThi(EID, 4, 7))
    atomic_write_json(cfg.workspace.dir / '_playlists' / f'{PID}.json',
                      dict(playlist_id=PID, entries=[dict(video_id=EID, episode='31')]))
    stage.run_render(ws.episode_id, cfg)
    folder = cfg.render.output_dir / ws.episode_id
    baseline = tmp_path / 'baseline.mp4'
    shutil.copyfile(folder / 'shorts/k01.mp4', baseline)
    cover.install(cfg, PID, 'kt_vertical', source_image(tmp_path), [100, 700, 880, 700])
    atomic_write_json(cfg.packaging.asset_dir / 'khaithi_from.json', dict(schema_version=1, playlists={PID: 31}))
    return cfg, ws, folder, baseline


def ffmpeg(*args):
    return subprocess.run(['ffmpeg', '-v', 'error', *map(str, args)], capture_output=True, check=True, timeout=60).stdout


def frame_hashes(path):
    text = ffmpeg('-i', path, '-map', '0:v', '-f', 'framemd5', '-').decode()
    return [line.split(',')[-1].strip() for line in text.splitlines() if not line.startswith('#')]


def assert_fade(video, fps):
    pixels = ffmpeg('-i', video, '-map', '0:v', '-vf', 'scale=36:64', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-')
    size = 36 * 64 * 3
    count = round(3 * fps)
    first = pixels[:size]
    last = pixels[(count-1)*size:count*size]
    content = pixels[count*size:(count+1)*size]
    middle_at = round((count / float(fps) - .5) * fps)
    middle = pixels[middle_at*size:(middle_at+1)*size]
    def distance(a, b):
        return sum(abs(x-y) for x, y in zip(a, b)) / size
    contrast = distance(first, content)
    assert contrast > 20  # distinct synthetic thumbnail and video; blending must be observable
    assert distance(last, content) < contrast * .1
    assert contrast * .2 < distance(middle, first) < contrast * .8
    assert contrast * .2 < distance(middle, content) < contrast * .8
    assert distance(middle, bytes((a+b)//2 for a, b in zip(first, content))) < 5
    return first


@pytest.mark.parametrize("fresh", [False, True])
def test_intro_pixels_silence_content_sha_cache_and_title(rendered, tmp_path, fresh):
    cfg, ws, folder, baseline = rendered
    before = read_json_dict(folder / 'render_manifest.json')
    old_ws_sha = hashing.sha256_file(ws.manifest_path)
    if fresh:
        (folder / 'render_manifest.json').unlink()
        (folder / 'shorts/k01.mp4').unlink()
        manifest = ws.load_manifest()
        manifest['stages'].pop('render')
        ws.save_manifest(manifest)
    result = stage.run_render(ws.episode_id, cfg)
    assert result.encoded == 1
    doc = read_json_dict(result.path)
    record = doc['shorts'][0]
    assert record['intro']['seconds'] == 3 and record['content_offset'] == 3
    assert record['intro']['transition'] == dict(type='fade', seconds=1)
    assert record['content_sha256'] == hashing.sha256_file(baseline)
    assert intro.content_manifest(doc) == before
    if not fresh:
        assert doc['content_workspace_manifest_sha256'] == old_ws_sha
    video = folder / record['file']
    info = stage.probe_media(video, stage._run)
    assert abs(info['duration'] - 4.2) < .1
    image = kt.vertical_clip(cfg, ws.episode_id, 'k01', pid=PID, fields=kt.intro_context(cfg, ws.episode_id)[1])
    assert record['intro']['sha256'] == hashing.sha256_file(image)
    # Compare the first thumbnail frame at feed scale, allowing H.264/JPEG rounding only.
    pixel_args = ('-frames:v', '1', '-vf', 'scale=36:64', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-')
    got, expected = ffmpeg('-i', video, *pixel_args), ffmpeg('-i', image, *pixel_args)
    assert sum(abs(a-b) for a, b in zip(got, expected)) / len(got) < 5
    assert_fade(video, Fraction(25))
    pcm = ffmpeg('-i', video, '-t', '3', '-map', '0:a', '-f', 's16le', '-')
    assert max(abs(int.from_bytes(pcm[i:i+2], 'little', signed=True)) for i in range(0, len(pcm), 2)) == 0
    keys = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-skip_frame', 'nokey',
                           '-show_entries', 'frame=pts_time', '-of', 'csv=p=0', str(video)],
                          capture_output=True, text=True, check=True, timeout=30).stdout
    assert any(abs(float(s.split(',')[0]) - 3) < .001 for s in keys.splitlines() if s[:1].isdigit())
    assert not stage.run_render(ws.episode_id, cfg).ran
    review = dict(schema_version=1, episode_id=ws.episode_id,
                  titles=[dict(clip_id='k01', candidate_id='c1', title='Học cách sống an vui', origin='manual')])
    atomic_write_json(ws.dir / 'review.json', review)
    assert stage.run_render(ws.episode_id, cfg).encoded == 1
    changed = read_json_dict(result.path)['shorts'][0]
    assert changed['intro']['sha256'] != record['intro']['sha256']
    assert changed['render_key'] != record['render_key']


@pytest.mark.parametrize('kind', ['before_start', 'short', 'unconfigured'])
def test_outside_scope_keeps_bytes_and_key(rendered, kind):
    cfg, ws, folder, baseline = rendered
    before = read_json_dict(folder / 'render_manifest.json')
    if kind == 'before_start':
        atomic_write_json(cfg.packaging.asset_dir / 'khaithi_from.json', dict(schema_version=1, playlists={PID: 32}))
    elif kind == 'short':
        (ws.dir / 'khaithi.json').unlink()
        # A Short has its own layout/key; establish that baseline before checking unchanged reruns.
        stage.run_render(ws.episode_id, cfg)
        before = read_json_dict(folder / 'render_manifest.json')
    else:
        (cfg.packaging.asset_dir / 'khaithi_from.json').unlink()
    assert not stage.run_render(ws.episode_id, cfg).ran
    after = read_json_dict(folder / 'render_manifest.json')
    assert after == before and 'intro' not in after['shorts'][0]
    assert hashing.sha256_file(folder / 'shorts/k01.mp4') == before['shorts'][0]['sha256']


def test_missing_cover_fails_with_link_and_no_new_clip(rendered):
    cfg, ws, folder, baseline = rendered
    cover.remove(cfg, PID, 'kt_vertical')
    before = (folder / 'shorts/k01.mp4').read_bytes()
    with pytest.raises(stage.RenderError, match=f'Bộ kinh chưa có ảnh bìa khai thị.* /playlists/{PID}/thumbs'):
        stage.run_render(ws.episode_id, cfg)
    assert (folder / 'shorts/k01.mp4').read_bytes() == before
    assert ws.load_manifest()['stages']['render']['status'] == 'failed'
    (folder / 'shorts/k01.mp4').unlink()
    with pytest.raises(stage.RenderError):
        stage.run_render(ws.episode_id, cfg)
    assert not (folder / 'shorts/k01.mp4').exists()
    from auto_short.web.app import create_app
    from auto_short.web.jobs import Job, JobFailed, KIND_RENDER, render_target
    from test_store_download import request as call_route
    app = create_app(cfg, 'pw', preflight=None, post_preflight=None)
    target = render_target(cfg)
    with pytest.raises(JobFailed, match='Bộ kinh chưa có ảnh bìa khai thị'):
        target(Job('missing-cover', ws.episode_id, KIND_RENDER, target))
    response = call_route(app, 'GET', f'/api/episodes/{ws.episode_id}', transport='direct')
    assert response.status_code == 200
    failed = next(s for s in response.json()['stages'] if s['stage'] == 'render')
    assert f'/playlists/{PID}/thumbs' in failed['error']


@pytest.mark.parametrize("rendered", [("25", "medium"), ("30000/1001", "ultrafast")], indirect=True)
def test_compilation_copy_and_reencode_skip_intro(rendered, tmp_path):
    cfg, ws, folder, baseline = rendered
    stage.run_render(ws.episode_id, cfg)
    video = folder / 'shorts/k01.mp4'
    expected, actual = tmp_path / 'plain.mp4', tmp_path / 'joined.mp4'
    assemble([baseline, baseline], expected)
    result = assemble([video, video], actual)
    assert not result.reencoded
    assert result.parts == pytest.approx((1.2, 1.2), abs=.1)
    assert frame_hashes(actual) == frame_hashes(expected)
    # Force the existing copy-failure fallback, checking the seek is also applied to re-encode inputs.
    seeks = []
    # Permit the copy after normalization.
    count = 0
    def once(cmd):
        nonlocal count
        if 'concat' in cmd:
            count += 1
            if count == 1:
                return subprocess.CompletedProcess(cmd, 1, '', 'force normalization')
        if '-ss' in cmd:
            seeks.append(float(cmd[cmd.index('-ss') + 1]))
        return stage._run(cmd)
    normalized = assemble([video, video], tmp_path / 'normalized.mp4', runner=once)
    assert normalized.reencoded and seeks == [intro.offset(read_json_dict(folder / "render_manifest.json")["shorts"][0])]
    assert len(frame_hashes(tmp_path / 'normalized.mp4')) == len(frame_hashes(expected))


def test_rebuild_range_priority_and_skip_current(rendered):
    cfg, ws, folder, baseline = rendered
    jobs = []
    runner = SimpleNamespace(priority=Priority(), submit=lambda ident, kind, target: (jobs.append(ident), True))
    assert not kt.enqueue_intro_rebuild(cfg, runner, PID, 1, 30)['queued']
    result = kt.enqueue_intro_rebuild(cfg, runner, PID, 31, 50, prioritize_first_ten=True)
    assert result['queued'] == [ws.episode_id] and runner.priority.marked(EID)
    stage.run_render(ws.episode_id, cfg)
    result = kt.enqueue_intro_rebuild(cfg, runner, PID, 31, 50)
    assert result == dict(queued=[], skipped=[ws.episode_id])
    entries = [dict(video_id=EID, episode='31')]
    for number in (30, 32, 40, 41, 52):
        base = f'lecture{number:04d}'
        ident = base + '.kt'
        other = cfg.workspace.dir / ident
        shutil.copytree(ws.dir, other)
        manifest = read_json_dict(other / 'manifest.json')
        manifest['episode_id'] = ident
        atomic_write_json(other / 'manifest.json', manifest)
        titles = read_json_dict(other / 'titles.json')
        titles['header']['fields']['episode'] = str(number)
        atomic_write_json(other / 'titles.json', titles)
        khaithi.write(other, khaithi.KhaiThi(base, 4, 7))
        shutil.copytree(folder, cfg.render.output_dir / ident)
        entries.append(dict(video_id=base, episode=str(number)))
    atomic_write_json(cfg.workspace.dir / '_playlists' / f'{PID}.json', dict(playlist_id=PID, entries=entries))
    result = kt.enqueue_intro_rebuild(cfg, runner, PID, 31, 41, prioritize_first_ten=True)
    assert result['queued'] == ['lecture0032.kt', 'lecture0040.kt', 'lecture0041.kt']
    assert runner.priority.marked('lecture0032') and runner.priority.marked('lecture0040')
    assert not runner.priority.marked('lecture0041')


def test_borrow_revision_kept_duration_and_cleanup(rendered, tmp_path, memory_store):
    from auto_short.config import StoreConfig
    from auto_short.compilation import Item, store
    from auto_short.store.shorts import borrow_short
    from auto_short.web.compilations import Clip, Compilations
    from auto_short.web.episodes import StoredShort
    cfg, ws, folder, baseline = rendered
    stage.run_render(ws.episode_id, cfg)
    video = folder / 'shorts/k01.mp4'
    record = read_json_dict(folder / 'render_manifest.json')['shorts'][0]
    data, stat = video.read_bytes(), video.stat()
    stored = StoredShort(ws.episode_id, video.name, record['sha256'], stat.st_size, stat.st_mtime_ns)
    cfg = replace(cfg, store=StoreConfig(enabled=True))
    name = '[KhaiThi] Tap 31 - k01.mp4'
    client = memory_store.client
    client.put(ws.episode_id, 'short', PLAYLIST, name, baseline, hashing.sha256_file(baseline), clip='k01.mp4')
    client.put(ws.episode_id, 'short', PLAYLIST, name, video, record['sha256'], clip='k01.mp4')
    row = next(r for r in memory_store.service.index() if r['video_id'] == ws.episode_id and r['clip'] == 'k01.mp4')
    assert row['file'].endswith('k01 (r2).mp4')
    with borrow_short(cfg, stored, tmp_path, client=client) as borrowed:
        assert intro.clip_record(borrowed) == record
        result = assemble([borrowed], tmp_path / 'borrowed-content.mp4')
        assert not result.reencoded
        assert frame_hashes(tmp_path / 'borrowed-content.mp4') == frame_hashes(baseline)
    assert not borrowed.exists() and not borrowed.with_suffix('.intro.json').exists()
    # Kept snapshots retain the same timeline metadata after the workspace is deleted.
    kept_folder = tmp_path / 'kept-root'
    kept = kept_folder / 'kept' / ws.episode_id / 'k01.mp4'
    kept.parent.mkdir(parents=True)
    kept.write_bytes(data)
    atomic_write_json(kept.with_suffix('.intro.json'), record)
    service = Compilations(cfg, None, None, lambda _: None)
    clip = Clip(Item(ws.episode_id, 'k01'), (0, 0, 1), '31', 1, 1, 'title', 1.2, kept)
    assert service.duration(clip) == pytest.approx(1.2, abs=.1)
    snapshot = dict(path=kept.relative_to(kept_folder).as_posix(), title='title', duration=1.2,
                    episode_number='31', clip_number=1, clip_total=1, saved_at='now')
    store.remove_kept(kept_folder, Item(ws.episode_id, 'k01', snapshot))
    assert not kept.parent.exists()


@pytest.mark.parametrize('released', [False, True])
def test_existing_content_gets_intro_after_source_cleanup(rendered, memory_store, tmp_path, released):
    from auto_short.config import StoreConfig
    cfg, ws, folder, baseline = rendered
    cfg = replace(cfg, store=StoreConfig(enabled=True))
    video = folder / 'shorts/k01.mp4'
    if released:
        stat = video.stat()
        sha = hashing.sha256_file(video)
        memory_store.client.put(ws.episode_id, 'short', PLAYLIST, '[KhaiThi] Tap 31 - k01.mp4', video, sha,
                                clip='k01.mp4')
        atomic_write_json(folder / 'store.json', dict(released={'k01': dict(
            sha256=sha, size=stat.st_size, mtime_ns=stat.st_mtime_ns)}, at='now'))
        video.unlink()
    (ws.dir / 'source.mp4').unlink()
    atomic_write_json(ws.dir / 'archive.json', dict(schema_version=1, removed=['source.mp4']))
    if not released:
        def fail_prefix(cmd):
            if cmd[0] == 'ffmpeg':
                return subprocess.CompletedProcess(cmd, 1, '', 'temporary encoder failure')
            return stage._run(cmd)
        with pytest.raises(stage.RenderError, match='temporary encoder failure'):
            stage.run_render(ws.episode_id, cfg, run=fail_prefix)
        assert hashing.sha256_file(video) == hashing.sha256_file(baseline)
        assert not list(video.parent.glob('*.part'))
    calls = []
    def runner(cmd):
        calls.append(cmd)
        return stage._run(cmd)
    result = stage.run_render(ws.episode_id, cfg, run=runner)
    assert result.encoded == 1 and not (ws.dir / 'source.mp4').exists()
    assert all(str(ws.dir / 'source.mp4') not in cmd for cmd in calls)
    record = read_json_dict(folder / 'render_manifest.json')['shorts'][0]
    assert record['content_sha256'] == hashing.sha256_file(baseline)
    assemble([video], tmp_path / 'content.mp4')
    assert frame_hashes(tmp_path / 'content.mp4') == frame_hashes(baseline)
    assert not stage.run_render(ws.episode_id, cfg, run=runner).ran
    queue = SimpleNamespace(priority=Priority(), submit=lambda *args: pytest.fail('current archived clip was queued'))
    assert kt.enqueue_intro_rebuild(cfg, queue, PID, 31, 31)['skipped'] == [ws.episode_id]


@pytest.mark.parametrize('rendered', [('25', 'medium'), ('30000/1001', 'ultrafast')], indirect=True)
def test_legacy_intro_replaced_with_fade_without_source_or_content_encode(rendered, monkeypatch, tmp_path):
    cfg, ws, folder, baseline = rendered
    video = folder / 'shorts/k01.mp4'
    doc = read_json_dict(folder / 'render_manifest.json')
    record = doc['shorts'][0]
    fps = Fraction(doc['encode']['fps'])
    image = kt.vertical_clip(cfg, ws.episode_id, 'k01', pid=PID, fields=kt.intro_context(cfg, ws.episode_id)[1])
    old_intro = dict(sha256=hashing.sha256_file(image), seconds=3)
    original_filters = intro.filters
    def legacy_filters(rate, **kwargs):
        return ['[0:v]null[contentv]', '[0:a]anull[contenta]',
                *original_filters(rate, color_correct=kwargs['color_correct'])]
    work = tmp_path / 'old-intro'
    work.mkdir()
    with monkeypatch.context() as old:
        old.setattr(intro, 'filters', legacy_filters)
        offset = intro.prepend(baseline, video, image, fps, cfg.render, work, stage._run)
    record.update(content_sha256=record['sha256'], content_render_key=record['render_key'], content_offset=offset,
                  intro=old_intro, sha256=hashing.sha256_file(video))
    record['render_key'] = hashing.config_hash(dict(content_render_key=record['content_render_key'], intro=old_intro))
    old_key = record['render_key']
    atomic_write_json(folder / 'render_manifest.json', doc)
    manifest = ws.load_manifest()
    manifest['stages']['render']['inputs'].append(dict(clip_intro='k01', **old_intro))
    ws.save_manifest(manifest)
    # The selector must not skip a clip merely because its image and intro length still match.
    queued = []
    runner = SimpleNamespace(priority=Priority(), submit=lambda eid, *args: (queued.append(eid), True))
    assert kt.enqueue_intro_rebuild(cfg, runner, PID, 31, 31)['queued'] == [ws.episode_id]
    (ws.dir / 'source.mp4').unlink()
    atomic_write_json(ws.dir / 'archive.json', dict(schema_version=1, removed=['source.mp4']))
    calls = []
    def run(cmd):
        calls.append(cmd)
        return stage._run(cmd)
    result = stage.run_render(ws.episode_id, cfg, run=run)
    changed_doc = read_json_dict(result.path)
    changed = changed_doc['shorts'][0]
    assert result.encoded == 1 and changed['intro'] == intro.metadata(image)
    assert changed['render_key'] != old_key and changed['content_offset'] == offset
    assert changed['content_sha256'] == record['content_sha256'] == hashing.sha256_file(baseline)
    assert changed['content_render_key'] == record['content_render_key']
    assert intro.content_manifest(changed_doc) == intro.content_manifest(doc)
    assert all(str(ws.dir / 'source.mp4') not in cmd for cmd in calls)
    assert len([cmd for cmd in calls if '-c:v' in cmd and 'libx264' in cmd]) == 1  # only the intro encodes
    assert_fade(video, fps)
    content = tmp_path / 'new-content.mp4'
    intro.extract_content(video, content, changed, stage._run)
    assert frame_hashes(content) == frame_hashes(baseline)
    assert not stage.run_render(ws.episode_id, cfg).ran
    assert kt.enqueue_intro_rebuild(cfg, runner, PID, 31, 31)['skipped'] == [ws.episode_id]
