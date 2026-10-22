"""An ETA row limit and failed polls must not erase or refresh a character's last sighting."""
from datetime import timedelta
import json

import pytest

from exp_tracker.diagnostics import Diagnostics
from exp_tracker.publisher import public
from exp_tracker.rolling_history import recent_snapshot
from exp_tracker.server import create_server
from exp_tracker.store import Store
from tests.test_product import tracking, NOW, get
from tests.test_publisher import clock
from tests.test_diagnostic_history import config
from tests.test_tracked_exp_totals import save
from tests.test_server import request


@pytest.mark.parametrize('full', [True, False])
def test_last_reading_survives_eta_row_limit_and_can_advance_after_it(tracking, clock, full):
    path, store, d = tracking
    for i in range(1, 4):save(d, 'run', i, (i-1)*20, 3300+i*5, full=full)
    original = get(d, 40)['reading']
    d.append('run', dict(type='summary', trusted=False, attempts=3, interrupted=True))
    # More than the historical ETA's 4,096-row bound, but still inside the 24h projection.
    for n in range(4200):
        run = f'failed-{n//60}'
        if n % 60 == 0:d.begin(run, 'alpha', config(run))
        save(d, run, n % 60+1, 80+n*10, 0, missing=True)
        if n % 60 == 59:d.append(run, dict(type='summary', trusted=False, attempts=60, interrupted=True))
    clock.at = NOW+timedelta(seconds=42100)
    with create_server(path, port=0, public_only=True) as server:
        status, _, raw = request((server, None), '/api/players/alpha')
        body = json.loads(raw); value = body['player']
        assert status == 200 and value['recent_history']['eta_status'] == 'history_limit'
        assert value['reading'] == public(original)
        assert value['last_seen']['timestamp'] == original['timestamp'] and value['stale']
        assert value['estimates']['eta'] is None and not value['recent_windows']['5']['available']
        assert body['tracked_history']['status'] == 'ready' and body['tracked_history']['tracked_exp']
        rows = json.loads(server.publisher.characters())['characters']
        assert rows[0]['reading'] == public(original) and rows[0]['last_seen_at'] == original['timestamp']
    # Continue validating after the ETA buffer filled, rather than returning only a partial prefix.
    d.begin('resumed', 'alpha', config('resumed'))
    for i in range(1, 4):save(d, 'resumed', i, 42100+i*20, 3400+i*5, full=full)
    clock.at += timedelta(seconds=60)
    with Store(path, read_only=True) as cold:
        restored = recent_snapshot(Diagnostics(cold), 'alpha', now=clock.at, _historical=True)
        assert restored['recent_history_status'] == 'history_limit' and not restored['observations']
        assert restored['historical_display']['reading']['event_id'] == 'resumed:3'
    # Operator clears still apply after a long replay; cached display is never an accounting input.
    cid = store.state('alpha')['selected_character_id']
    store.correct_manual('alpha', 'clear-long-history', cid, clear=True, effective_at=clock.at)
    with create_server(path, port=0, public_only=True) as server:
        body = json.loads(request((server, None), '/api/players/alpha')[2])
        assert body['player']['reading'] is None


def test_character_sighting_ignores_failed_stale_missing_and_held_frames(tracking):
    _, _, d = tracking
    save(d, 'run', 1, 0, 3300)
    for i, changes in enumerate([
        dict(missing=True),
        dict(current=False),
        dict(localization=dict(count=0)),
        dict(identity_hold=dict(hold_reasons=['name_mismatch'])),
        dict(received_at=None),
        dict(status='capture_failed'),
    ], 2):save(d, 'run', i, i*20, 3300+i, **changes)
    row = d.roster('alpha')[0]
    assert row['last_seen_at'] == NOW.isoformat()
    assert row['revision'] == 7  # Failed attempts still invalidate report caches.


def test_retained_sighting_uses_observed_display_time_not_last_failed_poll(tracking):
    from exp_tracker.retention import prune
    _, store, d = tracking
    for i in range(1, 4):save(d, 'run', i, (i-1)*20, 3300+i*5)
    save(d, 'run', 4, 80, 0, missing=True)
    d.append('run', dict(type='summary', trusted=False, attempts=4, interrupted=True))
    prune(store, now=NOW+timedelta(days=2), dry_run=False)
    assert not store.db.execute('SELECT 1 FROM diagnostic_attempts').fetchone()
    assert d.roster('alpha')[0]['last_seen_at'] == (NOW+timedelta(seconds=40)).isoformat()
