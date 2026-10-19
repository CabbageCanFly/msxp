"""Synthetic saved-video prefixes; no private samples or sockets required."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

from exp_tracker.store import Store
from tools import product_updates_fixture as preview


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = Path('private/video.jsonl')
    path.parent.mkdir()
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = [dict(type='configuration', trusted=False, run_id='synthetic-video', interval=5, source_kind='file')]
    for index, offset in enumerate((0, 5, 10), 1):
        stamp = (origin + timedelta(seconds=offset)).isoformat()
        records.append(dict(type='attempt', index=index, current=True, trusted=False,
                            attempted_at=stamp, received_at=stamp, frame_sha256=f'{index:064x}',
                            source=dict(kind='file', requested_video_offset_seconds=offset),
                            status='diagnostic_pair', localization=dict(count=1),
                            neural=dict(text=f'{353800+index*100}[99.{12+index*3:02}%]')))
    records.append(dict(type='summary', trusted=False, attempts=3, interrupted=False))
    path.write_text(''.join(json.dumps(r)+'\n' for r in records), encoding='utf-8')
    return path


def test_forward_prefixes_keep_future_evidence_out_of_database(log, monkeypatch):
    import exp_tracker.diagnostics as diagnostics
    import exp_tracker.server as server
    before = (server.datetime, diagnostics.datetime)
    database = Path('private/preview.sqlite3')
    class HTTP:
        server_port = 8788
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def serve_forever(self): pass
        def shutdown(self): pass
    monkeypatch.setattr(preview, 'create_server', lambda *a, **kw: HTTP())
    def assert_prefix(count, seconds):
        with Store(database, read_only=True) as store:
            assert store.db.execute('SELECT count(*) FROM diagnostic_attempts').fetchone()[0] == count
            assert not store.db.execute('SELECT 1 FROM observations').fetchone()
        assert server.datetime.now().second == seconds
    def commands():
        assert_prefix(1, 0)
        yield '5'
        assert_prefix(2, 5)
        yield '0'  # Cannot rewind or replace previously ingested evidence.
        yield 'invalid'
        assert_prefix(2, 5)
        yield 'all'
        assert_prefix(3, 10)
    preview.log_trial(database, 8788, log, commands=commands())
    assert (server.datetime, diagnostics.datetime) == before


@pytest.mark.parametrize('problem', ['duplicate_offsets', 'twitch', 'too_many', 'partial', 'outside'])
def test_invalid_evidence_rejected_before_database_creation(log, problem):
    records = [json.loads(s) for s in log.read_text().splitlines()]
    if problem == 'duplicate_offsets': records[2]['source']['requested_video_offset_seconds'] = 0
    if problem == 'twitch': records[1]['source']['kind'] = 'twitch'
    if problem == 'too_many': records[1:1] = [records[1]]*60
    log.write_text(''.join(json.dumps(r)+'\n' for r in records))
    if problem == 'partial': log.write_text(log.read_text().rstrip())
    if problem == 'outside':
        log = Path('outside.jsonl')
        log.write_text('{}\n')
    database = Path('private/not-created.sqlite3')
    with pytest.raises(ValueError): preview.log_trial(database, 8788, log, commands=[])
    assert not database.exists()


@pytest.mark.parametrize('directory', ['outside', 'private/existing'])
def test_cli_refuses_external_or_existing_output(log, monkeypatch, directory):
    output = Path(directory)
    if directory.startswith('private/'):
        output.mkdir()
        (output/'keep.txt').write_text('untouched')
    monkeypatch.setattr(sys, 'argv', ['preview', '--directory', directory, '--port', '8788', '--replay-log', str(log)])
    with pytest.raises((ValueError, FileExistsError)): preview.main()
    assert not (output/'updates.sqlite3').exists()
    if output.exists(): assert (output/'keep.txt').read_text() == 'untouched'
