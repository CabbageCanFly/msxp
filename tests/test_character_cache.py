"""Inactive profiles reuse validated summaries and reports without request-time replay."""
from datetime import timedelta
import json

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.server import create_server
from exp_tracker.store import Store
from tests.test_character_profiles import db, clock, CHANNEL, ALPHA, BETA, NOW, snapshot
from tests.test_server import request


def warm(server, path):
    server.publisher.settle()
    with Store(path, read_only=True) as store:
        # The background directory sweep builds this without a visitor/view slot.
        server.publisher.build(Diagnostics(store), store, CHANNEL, NOW, view=(('view', CHANNEL, BETA), None))
    assert not server.publisher.views and not server.publisher.viewed
    assert not server.publisher.stats['cache_error']
    return server.publisher.summaries[(CHANNEL, BETA)]['reading']


def test_background_reports_survive_eviction_and_restart_and_preview_never_replays(db, clock, tmp_path, monkeypatch):
    cache = tmp_path/'warm.sqlite3'; before = snapshot(db)
    with create_server(db, port=0, public_only=True, publication_cache=cache) as server:
        reading = warm(server, db)
        assert reading and reading['level']['value'] == 43
    with create_server(db, port=0, public_only=True, publication_cache=cache) as server:
        server.publisher.background = True  # Deterministic worker steps, no inline request builds.
        def forbidden(*a, **k):raise AssertionError('A preview or restored report must not replay history')
        monkeypatch.setattr(Diagnostics, 'card', forbidden)
        monkeypatch.setattr(Diagnostics, 'rolling_history', forbidden)
        code, _, raw = request((server, None), f'/api/players/{CHANNEL}?character={BETA}')
        body = json.loads(raw)
        assert code == 503 and body['summary']['character_id'] == BETA
        assert body['summary']['reading'] == reading and not body.get('history')
        assert not server.publisher.views
        # Restoring on the sole worker opens no extra unbounded in-memory views.
        monkeypatch.setattr(server.publisher, 'build', lambda *a, **k: None)
        for _ in range(2):
            server.publisher.step()
            body = json.loads(server.publisher.character(CHANNEL, view=BETA))
            assert body['player']['reading'] == reading and body['publication']['state'] == 'restored'
            assert body['view'] == dict(character_id=BETA, current=False)
            assert body['tracked_history']['character_id'] == BETA
            with server.publisher.lock:server.publisher.drop_view(('view', CHANNEL, BETA))
            assert server.publisher.character(CHANNEL, view=BETA) is None
        assert not server.publisher.stats['cache_error']
    assert snapshot(db) == before


def test_summary_outlives_report_expiry_without_resurrecting_rolling_totals(db, clock, tmp_path, monkeypatch):
    cache = tmp_path/'warm.sqlite3'
    with create_server(db, port=0, public_only=True, publication_cache=cache) as server:reading = warm(server, db)
    clock.at += timedelta(days=60)
    with create_server(db, port=0, public_only=True, publication_cache=cache) as server:
        assert server.publisher.summaries[(CHANNEL, BETA)]['reading'] == reading
        server.publisher.settle()  # Only the selected report is rebuilt, no inactive replay.
        server.publisher.background = True
        def forbidden(*a, **k):raise AssertionError('Old summary must be independently readable')
        monkeypatch.setattr(Diagnostics, 'card', forbidden)
        preview = server.publisher.preview(CHANNEL, BETA)['summary']
        assert preview['reading'] == reading and preview['day'] is None
        assert preview['day_buckets'] == [None]*48
        server.publisher.character(CHANNEL, view=BETA)
        head = server.publisher.heads[0]
        with Store(db, read_only=True) as store:
            due = server.publisher.due_views(Diagnostics(store), [head], clock.at)
        assert due and not server.publisher.views  # A 60-day-old full report must not claim current windows.


@pytest.mark.parametrize('change', ['clear', 'invalidation', 'retention', 'source', 'code'])
def test_changed_source_or_operator_revision_withholds_persisted_summary(db, clock, tmp_path, monkeypatch, change):
    cache = tmp_path/'warm.sqlite3'
    with create_server(db, port=0, public_only=True, publication_cache=cache) as server:warm(server, db)
    with Store(db) as store:
        if change == 'clear':store.correct_manual(CHANNEL, 'clear-beta', BETA, clear=True, effective_at=NOW-timedelta(minutes=30))
        elif change == 'invalidation':
            from exp_tracker.invalidations import Invalidations
            row = store.db.execute('SELECT a.run_id,a.attempt_index,a.attempted_at FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id WHERE r.character_id=? LIMIT 1', (BETA,)).fetchone()
            spec = dict(action='invalidate', kind='diagnostic', identity=f'{row[0]}:{row[1]}', timestamp=row[2])
            service = Invalidations(store); preview = service.preview(CHANNEL, BETA, spec)
            service.commit(CHANNEL, BETA, 'exclude', spec, preview['fingerprint'])
        elif change == 'retention':store.db.execute('UPDATE retention_meta SET revision=revision+1 WHERE id=1')
        elif change == 'source':
            row = store.db.execute('SELECT a.id,a.payload_json FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id WHERE r.character_id=? LIMIT 1', (BETA,)).fetchone()
            payload = json.loads(row[1]);payload['current'] = False
            store.db.execute('UPDATE diagnostic_attempts SET payload_json=? WHERE id=?', (json.dumps(payload), row[0]))
        else:
            import exp_tracker.publication_cache as module
            monkeypatch.setattr(module, 'code_revision', lambda: 'new-policy')
    with create_server(db, port=0, public_only=True, publication_cache=cache) as server:
        assert (CHANNEL, BETA) not in server.publisher.summaries
        assert not server.publisher.preview(CHANNEL, BETA).get('summary', {}).get('reading')
