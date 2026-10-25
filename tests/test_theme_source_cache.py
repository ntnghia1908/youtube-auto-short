import hashlib
import json

import pytest

from auto_short import hashing, theme_render
from auto_short.compilation import store
from auto_short.compilation.spec import Item
from auto_short.ingest.youtube import Download, DownloadError, YoutubeBlocked
from auto_short.render.full import SourceBlocked
from auto_short.render.stage import RenderError
from auto_short.theme_render import sources as sc
from auto_short.workspace import atomic_write_json


def no_call(*args, **kwargs):
    pytest.fail('unexpected side effect')


def ingest(cfg, video_id, *, duration=300, present=False):
    folder = cfg.workspace.dir / video_id
    original = b'original source'
    source = dict(path='source.mp4', uri=f'https://youtube.test/{video_id}',
                  sha256=hashlib.sha256(original).hexdigest(), size=len(original))
    atomic_write_json(folder / 'manifest.json', dict(source=source))
    atomic_write_json(folder / 'metadata.json', dict(duration=duration, height=720))
    if present:
        (folder / 'source.mp4').write_bytes(original)
    return folder, source


@pytest.fixture
def fake_probe(monkeypatch):
    info = dict(duration=300, height=720)
    monkeypatch.setattr(sc.probe, 'probe', lambda path: dict(info))
    return info


def download(uri, dest, config):
    path = dest / 'source.webm'
    path.write_bytes(b'downloaded source')
    return Download(path, {})


def favorites(cfg, playlist, *ids):
    store.write_favorites(store.directory(cfg.render.output_dir, playlist),
                          [Item(ident, f'k{i:02d}') for i, ident in enumerate(ids, 1)])


def assert_no_temporary(cfg):
    assert not list(sc.cache_dir(cfg).glob('.*'))


def test_favorites_owners_deduplicate_all_playlists_and_skip_ready(cfg, fake_probe):
    favorites(cfg, 'PL1', 'bravo.kt', 'alpha', 'alpha.kt')
    favorites(cfg, 'PL2', 'bravo', 'charlie.kt')
    ingest(cfg, 'alpha', present=True)
    ingest(cfg, 'bravo')
    ingest(cfg, 'charlie')
    sc.fetch_to_cache(cfg, 'bravo', download)
    assert sc.favorite_videos(cfg) == ['alpha', 'bravo', 'charlie']
    before = {p: p.read_bytes() for p in cfg.workspace.dir.parent.rglob('*') if p.is_file()}
    result = sc.run(cfg, dry_run=True, downloader=no_call, sleep=no_call, log=lambda _: None)
    assert result == dict(total=3, skipped=2, downloaded=0, failed=0, pending=1, interrupted=False)
    assert {p: p.read_bytes() for p in cfg.workspace.dir.parent.rglob('*') if p.is_file()} == before


def test_cache_metadata_integrity_ingest_unchanged_and_reuse(cfg, fake_probe):
    folder, original = ingest(cfg, 'lecture')
    before = {p: p.read_bytes() for p in folder.iterdir()}
    path = sc.fetch_to_cache(cfg, 'lecture.kt', download, clock=lambda: 0)
    assert path == sc.cache_dir(cfg) / 'lecture' / 'source.webm'
    meta = json.loads(path.with_name('meta.json').read_text())
    assert meta == dict(schema_version=1, video_id='lecture', file='source.webm', uri=original['uri'],
                        downloaded_at='1970-01-01T00:00:00Z', size=path.stat().st_size,
                        sha256=hashing.sha256_file(path), duration=300, height=720,
                        ingest_sha256=original['sha256'], differs_from_ingest=True)
    assert sc.cached_source(cfg, 'lecture') == path
    assert sc.fetch_to_cache(cfg, 'lecture', no_call) == path
    assert {p: p.read_bytes() for p in folder.iterdir()} == before
    assert_no_temporary(cfg)


@pytest.mark.parametrize('damage', ['missing', 'bytes', 'size', 'json', 'duration', 'timestamp', 'file', 'sha',
                                    'ingest', 'uri', 'metadata_missing', 'metadata_invalid'])
def test_cache_rejects_invalid_entry(cfg, fake_probe, damage):
    folder, _ = ingest(cfg, 'lecture')
    path = sc.fetch_to_cache(cfg, 'lecture', download)
    meta_path = path.with_name('meta.json')
    meta = json.loads(meta_path.read_text())
    if damage == 'missing':
        path.unlink()
    elif damage == 'bytes':
        path.write_bytes(b'x' * path.stat().st_size)
    elif damage == 'size':
        path.write_bytes(b'x')
    elif damage == 'json':
        meta_path.write_text('{broken')
    elif damage == 'ingest':
        manifest = json.loads((folder / 'manifest.json').read_text())
        manifest['source']['sha256'] = 'new ingest'
        atomic_write_json(folder / 'manifest.json', manifest)
    elif damage.startswith('metadata'):
        (folder / 'metadata.json').unlink()
        if damage == 'metadata_invalid':
            atomic_write_json(folder / 'metadata.json', dict(duration=0))
    else:
        key, value = {'duration': ('duration', 303.01), 'timestamp': ('downloaded_at', None),
                      'file': ('file', '../outside.mp4'), 'sha': ('sha256', 'x'),
                      'uri': ('uri', 'https://youtube.test/other')}[damage]
        meta[key] = value
        atomic_write_json(meta_path, meta)
    assert sc.cached_source(cfg, 'lecture') is None


@pytest.mark.parametrize('expected,actual,valid', [(100, 102, True), (100, 102.01, False),
                                                (300, 303, True), (300, 303.01, False),
                                                (300, float('nan'), False)])
def test_download_duration_tolerance(cfg, fake_probe, expected, actual, valid):
    ingest(cfg, 'lecture', duration=expected)
    fake_probe['duration'] = actual
    if valid:
        path = sc.fetch_to_cache(cfg, 'lecture', download)
        assert sc.cached_source(cfg, 'lecture') == path
    else:
        with pytest.raises(RenderError, match='dài'):
            sc.fetch_to_cache(cfg, 'lecture', download)
        assert not (sc.cache_dir(cfg) / 'lecture').exists()
    assert_no_temporary(cfg)


@pytest.mark.parametrize('failure', ['download', 'blocked', 'cancel', 'probe', 'outside'])
def test_download_failure_cleans_partial_and_preserves_old_cache(cfg, fake_probe, monkeypatch, failure):
    ingest(cfg, 'lecture')
    old = sc.fetch_to_cache(cfg, 'lecture', download)
    before = {p: p.read_bytes() for p in old.parent.iterdir()}
    monkeypatch.setattr(sc, 'cached_source', lambda *args: None)

    def broken(uri, dest, config):
        (dest / 'incomplete.part').write_bytes(b'partial')
        if failure in ('download', 'blocked', 'cancel'):
            raise {'download': DownloadError, 'blocked': YoutubeBlocked, 'cancel': KeyboardInterrupt}[failure]()
        if failure == 'outside':
            return Download(old, {})
        raise sc.probe.ProbeError('unreadable')

    error = KeyboardInterrupt if failure == 'cancel' else YoutubeBlocked if failure == 'blocked' else RenderError
    with pytest.raises(error):
        sc.fetch_to_cache(cfg, 'lecture', broken)
    assert {p: p.read_bytes() for p in old.parent.iterdir()} == before
    assert_no_temporary(cfg)


@pytest.mark.parametrize('step', ['source', 'meta'])
@pytest.mark.parametrize('error', [OSError, KeyboardInterrupt])
def test_publication_failure_leaves_no_new_file_or_temp(cfg, fake_probe, monkeypatch, step, error):
    ingest(cfg, 'lecture')
    real_replace = sc.os.replace

    def replace(src, dest):
        dest = sc.Path(dest)
        if dest.parent.name == 'lecture' and dest.name == ('source.webm' if step == 'source' else 'meta.json'):
            raise error('injected publication failure')
        return real_replace(src, dest)

    monkeypatch.setattr(sc.os, 'replace', replace)
    with pytest.raises(error):
        sc.fetch_to_cache(cfg, 'lecture', download)
    assert sc.cached_source(cfg, 'lecture') is None
    assert not list(sc.cache_dir(cfg).rglob('source.*'))
    assert_no_temporary(cfg)


def test_cache_same_as_ingest_records_no_difference(cfg, fake_probe):
    folder, _ = ingest(cfg, 'lecture', present=True)

    def same(uri, dest, config):
        target = dest / 'source.mp4'
        target.write_bytes((folder / 'source.mp4').read_bytes())
        return Download(target, {})

    path = sc.fetch_to_cache(cfg, 'lecture', same)
    assert not json.loads(path.with_name('meta.json').read_text())['differs_from_ingest']
    assert sc.cached_source(cfg, 'lecture') == path


def test_sequential_gaps_backoff_cap_other_error_continue_and_resume(cfg, fake_probe, monkeypatch):
    favorites(cfg, 'PL', 'alpha', 'bravo.kt', 'charlie')
    for ident in ('alpha', 'bravo', 'charlie'):
        ingest(cfg, ident)
    monkeypatch.setattr(sc.shutil, 'which', lambda _: '/bin/node')
    attempts, waits, logs, uniforms = [], [], [], []
    elapsed = [0]

    class Rng:
        def uniform(self, lo, hi):
            uniforms.append((lo, hi))
            return 15

    def sleep(seconds):
        assert_no_temporary(cfg)
        waits.append(seconds)
        elapsed[0] += seconds

    def downloader(uri, dest, config):
        ident = uri.rsplit('/', 1)[1]
        attempts.append(ident)
        if ident == 'alpha' and attempts.count(ident) <= 4:
            (dest / 'partial').write_bytes(b'partial')
            raise YoutubeBlocked('bot check')
        if ident == 'bravo':
            raise RuntimeError('unexpected downloader failure')
        return download(uri, dest, config)

    result = sc.run(cfg, downloader=downloader, sleep=sleep, rng=Rng(), clock=lambda: elapsed[0], log=logs.append,
                    min_gap=10, max_gap=20, blocked_wait=30, max_blocked_wait=100)
    assert attempts == ['alpha'] * 5 + ['bravo', 'charlie']
    assert waits == [30, 60, 100, 100, 15, 15]
    assert uniforms == [(10, 20), (10, 20)]
    assert result['downloaded'] == 2 and result['failed'] == 1
    assert any('lỗi' in s and 'bravo' in s for s in logs) and 'tổng kết' in logs[-1]
    assert sc.run(cfg, downloader=download, sleep=no_call, log=lambda _: None)['downloaded'] == 1
    assert sc.run(cfg, downloader=no_call, sleep=no_call, log=lambda _: None)['skipped'] == 3


@pytest.mark.parametrize('where', ['download', 'gap', 'blocked_wait'])
def test_interrupt_safe_and_rerun_continues(cfg, fake_probe, monkeypatch, where):
    favorites(cfg, 'PL', 'alpha', 'bravo')
    for ident in ('alpha', 'bravo'):
        ingest(cfg, ident)
    monkeypatch.setattr(sc.shutil, 'which', lambda _: '/bin/node')

    def downloader(uri, dest, config):
        if where in ('download', 'blocked_wait'):
            (dest / 'partial').write_bytes(b'partial')
            raise KeyboardInterrupt() if where == 'download' else YoutubeBlocked()
        return download(uri, dest, config)

    def interrupted_sleep(seconds):
        raise KeyboardInterrupt()

    result = sc.run(cfg, downloader=downloader, sleep=interrupted_sleep, log=lambda _: None)
    assert result['interrupted'] and result['downloaded'] == (1 if where == 'gap' else 0)
    assert_no_temporary(cfg)
    resumed = sc.run(cfg, downloader=download, sleep=lambda _: None, log=lambda _: None)
    assert resumed['downloaded'] == (1 if where == 'gap' else 2)


def test_cli_dry_run_no_node_no_writes_and_missing_node_guidance(cfg, config_file, monkeypatch, capsys):
    favorites(cfg, 'PL', 'lecture.kt')
    monkeypatch.setattr(sc.shutil, 'which', no_call)
    assert sc.main(['--config', str(config_file), '--dry-run']) == 0
    assert 'lecture: pending' in capsys.readouterr().out
    assert not cfg.workspace.dir.exists()
    monkeypatch.setattr(sc.shutil, 'which', lambda _: None)
    assert sc.main(['--config', str(config_file)]) == 1
    assert 'node trên PATH' in capsys.readouterr().out
    assert not sc.cache_dir(cfg).exists()


@pytest.mark.parametrize('args', [['--min-gap', '20', '--max-gap', '10'], ['--blocked-wait', '0'],
                                 ['--min-gap', '-1'], ['--max-gap', 'nan'],
                                 ['--blocked-wait', '100', '--max-blocked-wait', '50']])
def test_cli_invalid_waits(config_file, args):
    assert sc.main(['--config', str(config_file), '--dry-run', *args]) == 1


def test_theme_source_uses_persistent_cache_and_rejects_wrong_duration(cfg, fake_probe):
    _, original = ingest(cfg, 'lecture')
    path = sc.fetch_to_cache(cfg, 'lecture', download)
    record = dict(source_reference=dict(path='missing', sha256=original['sha256']), source_status='missing',
                  identity=dict(episode_id='lecture.kt'))
    fetched = {}
    got, status, warning = theme_render._source(cfg, record, fetched, no_call)
    assert got == path and status == 'refetched' and warning
    assert theme_render._source(cfg, record, fetched, no_call)[0] == path
    atomic_write_json(cfg.workspace.dir / 'lecture' / 'metadata.json', dict(duration=600))
    with pytest.raises(RenderError, match='dài'):
        theme_render._source(cfg, record, {}, download)
    assert_no_temporary(cfg)


def test_theme_source_new_download_persists_and_maps_blocked(cfg, fake_probe):
    _, original = ingest(cfg, 'lecture')
    record = dict(source_reference=dict(path='missing', sha256=original['sha256']), source_status='missing',
                  identity=dict(episode_id='lecture.kt'))

    def blocked(*args):
        raise YoutubeBlocked('bot')

    with pytest.raises(SourceBlocked, match='bot'):
        theme_render._source(cfg, record, {}, blocked)
    path, _, _ = theme_render._source(cfg, record, {}, download)
    assert path.is_file() and sc.cached_source(cfg, 'lecture') == path
    assert_no_temporary(cfg)


def test_workspace_skip_requires_ingest_sha(cfg, fake_probe, monkeypatch):
    favorites(cfg, 'PL', 'lecture')
    folder, _ = ingest(cfg, 'lecture', present=True)
    assert sc.workspace_source(cfg, 'lecture') == folder / 'source.mp4'
    (folder / 'source.mp4').write_bytes(b'changed')
    assert sc.workspace_source(cfg, 'lecture') is None
    monkeypatch.setattr(sc.shutil, 'which', lambda _: '/bin/node')
    assert sc.run(cfg, downloader=download, sleep=no_call, log=lambda _: None)['downloaded'] == 1


def test_shared_download_validates_private_file_without_publishing(cfg, fake_probe, tmp_path):
    ingest(cfg, 'lecture')
    dest = tmp_path / 'private'
    dest.mkdir()
    path, meta = sc.download_verified(cfg, 'lecture', dest, download, clock=lambda: 0)
    assert path.read_bytes() == b'downloaded source' and meta['differs_from_ingest']
    assert not sc.cache_dir(cfg).exists() and not (dest / 'meta.json').exists()


def test_fetch_http403_remains_normal_error(cfg, fake_probe):
    ingest(cfg, 'lecture')
    def blocked(uri, dest, config):
        raise DownloadError('HTTP Error 403: Forbidden')
    with pytest.raises(RenderError, match='403'):
        sc.fetch_to_cache(cfg, 'lecture', blocked)
    assert_no_temporary(cfg)


@pytest.mark.parametrize('damage', [None, 'uri', 'uri_type', 'sha', 'duration', 'differs', 'bytes'])
def test_playlist_reference_validates_cache_after_workspace_removal(cfg, fake_probe, damage):
    import shutil

    vid = 'aaaaaaaaaaa'
    folder, source = ingest(cfg, vid)
    source['uri'] = f'https://youtu.be/{vid}?si=old'
    atomic_write_json(folder / 'manifest.json', dict(source=source))
    path = sc.fetch_to_cache(cfg, vid, download)
    shutil.rmtree(folder)
    meta_path = path.with_name('meta.json')
    meta = json.loads(meta_path.read_text())
    if damage == 'bytes':
        path.write_bytes(b'bad')
    elif damage:
        key, value = {'uri': ('uri', 'https://youtu.be/bbbbbbbbbbb'), 'uri_type': ('uri', {}),
                      'sha': ('sha256', '0' * 64), 'duration': ('duration', 400),
                      'differs': ('differs_from_ingest', False)}[damage]
        meta[key] = value
        atomic_write_json(meta_path, meta)
    assert sc.cached_source(cfg, vid) is None  # Default TC3 policy still requires ingest provenance.
    result = sc.cached_source(cfg, vid, reference=dict(duration=300))
    assert result == (path if damage is None else None)
    assert not folder.exists()
