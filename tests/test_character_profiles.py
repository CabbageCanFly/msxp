"""Public multi-character streamer profiles: view-only, per-character, read-only HTTP."""
from datetime import datetime, timedelta, timezone
import json
import shutil
import sqlite3
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest

import exp_tracker.publisher as publisher_module
import exp_tracker.server as server_module
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.publisher import PRIVATE_FIELDS, public, public_character, public_roster
from exp_tracker.retention import prune
from exp_tracker.store import Store
import tests.test_character_identity  # noqa: F401  (puts tools/ on sys.path)
from tests.test_server import request
import character_demo as demo

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
CHANNEL = demo.CHANNEL
PLACEHOLDER, ALPHA, BETA = 1, 2, 3


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        at = NOW
        @classmethod
        def now(cls, tz=None):return cls.at
    monkeypatch.setattr(server_module, 'datetime', Clock)
    return Clock


@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'demo.sqlite3'
    switches = demo.create(now=NOW, path=path)
    assert [(s['name'], s['character_id']) for s in switches] == [('Alpha', ALPHA), ('Beta', BETA), ('Alpha', ALPHA)]
    return path


def get(httpd, path, attempts=4):
    """Inline publishing: a cold view answers warming once, then the next poll builds it."""
    for _ in range(attempts):
        code, headers, body = request((httpd, None), path)
        if code != 503 or json.loads(body).get('error') != 'warming_up':break
    return code, json.loads(body)


def snapshot(path):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as con:
        return list(con.iterdump())


def private_keys(value):
    if isinstance(value, dict):return {k for k in value if k in PRIVATE_FIELDS} | {k for v in value.values() for k in private_keys(v)}
    if isinstance(value, list):return {k for v in value for k in private_keys(v)}
    return set()


def test_alpha_beta_alpha_keeps_ids_sessions_and_independent_histories(db):
    with Store(db, read_only=True) as store:
        sessions = [tuple(r) for r in store.db.execute('SELECT id,character_id FROM sessions ORDER BY id')]
        assert sessions == [(1, PLACEHOLDER), (2, ALPHA), (3, BETA), (4, ALPHA)]
        d = Diagnostics(store)
        alpha, beta = (d.rolling_history(CHANNEL, now=NOW, character=c) for c in (ALPHA, BETA))
        assert alpha == d.rolling_history(CHANNEL, now=NOW)  # The selected default is unchanged.
        assert (alpha['character_id'], beta['character_id']) == (ALPHA, BETA)
        assert alpha['tracked_exp'] and beta['tracked_exp'] and alpha['tracked_exp'] != beta['tracked_exp']
        # Beta stopped 28 minutes ago: no recent windows, its own 30/60-minute and 24h totals.
        assert [beta['windows'][m]['gain'] for m in ('5', '10', '15')] == [None, None, None]
        assert beta['windows']['60']['gain'] == beta['tracked_exp']
        beta_end = NOW - timedelta(seconds=demo.INTERVAL * 56)
        assert beta['chart_intervals'] and all(datetime.fromisoformat(g['end']) <= beta_end for g in beta['chart_intervals'])
        assert {g['level'] for g in beta['chart_intervals']} == {43} and {g['level'] for g in alpha['chart_intervals']} == {67}


@pytest.mark.parametrize('character', [ALPHA, BETA])
def test_explicit_character_equals_selecting_it_in_a_disposable_copy(db, tmp_path, character):
    """Oracle only: the copy is selected by SQL; the public path never selects anything."""
    copy = tmp_path / 'oracle.sqlite3'
    shutil.copy(db, copy)
    with sqlite3.connect(copy) as con:
        con.execute('UPDATE streamers SET selected_character_id=?', (character,))
    with Store(db, read_only=True) as store, Store(copy, read_only=True) as oracle:
        explicit, selected = Diagnostics(store), Diagnostics(oracle)
        assert explicit.rolling_history(CHANNEL, now=NOW, character=character) == selected.rolling_history(CHANNEL, now=NOW)
        recent = explicit.recent_snapshot(CHANNEL, now=NOW, character=character)
        assert {r['character_id'] for r in recent['observations']} == {character}
        assert recent['observations'] == selected.recent_snapshot(CHANNEL, now=NOW, character=character)['observations']


def test_public_profile_shows_current_and_inactive_views_without_mutation(db, clock):
    before = snapshot(db)
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        code, current = get(httpd, f'/api/players/{CHANNEL}')
        assert code == 200 and current['view'] == dict(character_id=ALPHA, current=True)
        assert [(r['id'], r['label'], r['level'], r['current']) for r in current['roster']] == [(ALPHA, 'Alpha', 67, True), (BETA, 'Beta', 43, False)]
        assert current['player']['character'] == dict(id=ALPHA, label='Alpha')
        # Single-reader frames: the level floor is the display level, with the evidence the page reads.
        assert current['player']['display_level']['evidence'] == dict(value=67, status='validated_level_floor', reason='validated_level_floor', trusted=False)
        assert current['tracked_history']['character_id'] == ALPHA
        code, inactive = get(httpd, f'/api/players/{CHANNEL}?character={BETA}')
        assert code == 200 and inactive['view'] == dict(character_id=BETA, current=False)
        assert [{k:v for k,v in r.items() if k != 'last_exp_at'} for r in inactive['roster']] == [
            {k:v for k,v in r.items() if k != 'last_exp_at'} for r in current['roster']]
        assert next(r for r in inactive['roster'] if r['id'] == BETA)['last_exp_at'] == inactive['player']['reading']['timestamp']
        player = inactive['player']
        assert player['character'] == dict(id=BETA, label='Beta') and player['reading']['level']['value'] == 43
        assert player['activity'] == dict(state='historical_session') and player['twitch']['status'] == 'not_applicable'
        assert player['stale'] and player['reading']['timestamp'] == current['roster'][1]['last_seen_at']
        tracked = inactive['tracked_history']
        with Store(db, read_only=True) as store:
            expected = Diagnostics(store).rolling_history(CHANNEL, now=datetime.fromisoformat(tracked['as_of']), character=BETA)
        assert tracked == public(json.loads(json.dumps(expected)))
        assert all(row['level']['value'] in (43, None) for row in inactive['history'])
        assert not private_keys(inactive) and not private_keys(current)
        # The selected ID names the channel entry; a held revision still omits unchanged sections.
        code, same = get(httpd, f"/api/players/{CHANNEL}?character={ALPHA}&history={current['history_revision']}&tracked={current['tracked_revision']}")
        assert code == 200 and same['view']['current'] and 'history' not in same and 'tracked_history' not in same
        code, home = get(httpd, '/api/players')
        assert [(p['channel'], p['character']) for p in home['players']] == [(CHANNEL, dict(id=ALPHA, label='Alpha'))]
        assert request((httpd, None), f'/live/overlay/{CHANNEL}')[0] == request((httpd, None), f'/stream/{CHANNEL}?character={BETA}')[0] == 200
        assert request((httpd, None), f'/dashboard/{CHANNEL}')[0] == 404
        assert request((httpd, None), f'/api/players/{CHANNEL}?character={BETA}', 'POST')[0] == 405
    with Store(db, read_only=True) as store:
        assert store._channel(CHANNEL)['selected_character_id'] == ALPHA
    assert snapshot(db) == before


@pytest.mark.parametrize('query,status,error', [
    (f'character={PLACEHOLDER}', 404, 'unknown_character'), ('character=999', 404, 'unknown_character'),
    ('character=abc', 400, 'invalid_character'), ('character=0', 400, 'invalid_character'),
    (f'character={ALPHA}&character={BETA}', 400, 'invalid_character')])
def test_invalid_placeholder_and_unknown_character_ids_are_refused(db, clock, query, status, error):
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        get(httpd, f'/api/players/{CHANNEL}')
        assert get(httpd, f'/api/players/{CHANNEL}?{query}') == (status, {'error': error})


def test_cross_channel_character_id_is_not_served(db, clock):
    with Store(db) as store:
        store.add_channel('other_demo')
        other = store.add_character('other_demo', 'Gamma')
        store.select_character('other_demo', other); store.start_session('other_demo')
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        get(httpd, f'/api/players/{CHANNEL}')
        assert get(httpd, f'/api/players/{CHANNEL}?character={other}') == (404, {'error': 'unknown_character'})
        code, body = get(httpd, f'/api/players/other_demo?character={BETA}')
        assert code == 404 and body == {'error': 'unknown_character'}


def test_live_switch_while_a_visitor_views_the_inactive_character(db, clock):
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        assert get(httpd, f'/api/players/{CHANNEL}?character={BETA}')[1]['view'] == dict(character_id=BETA, current=False)
        clock.at = NOW + timedelta(seconds=demo.INTERVAL)
        assert [s['name'] for s in demo.switch(now=clock.at, path=db)] == ['Beta']
        code, beta = get(httpd, f'/api/players/{CHANNEL}?character={BETA}')
        assert code == 200 and beta['view'] == dict(character_id=BETA, current=True)
        assert [r['id'] for r in beta['roster']] == [BETA, ALPHA] and beta['roster'][0]['current']
        assert beta['player']['activity']['state'] != 'historical_session'
        code, alpha = get(httpd, f'/api/players/{CHANNEL}?character={ALPHA}')
        assert code == 200 and alpha['view'] == dict(character_id=ALPHA, current=False)
        assert alpha['tracked_history']['character_id'] == ALPHA and alpha['player']['character']['label'] == 'Alpha'
        assert get(httpd, f'/api/players/{CHANNEL}')[1]['view']['character_id'] == BETA
        assert [p['character']['label'] for p in get(httpd, '/api/players')[1]['players']] == ['Beta']


def test_placeholder_is_an_em_dash_and_never_a_roster_entry(tmp_path, clock):
    path = tmp_path / 'pending.sqlite3'
    with Store(path) as store:
        store.add_channel(CHANNEL)
        pending = store.add_character(CHANNEL, demo.PLACEHOLDER_CHARACTER)
        store.select_character(CHANNEL, pending, at=NOW - timedelta(minutes=5)); store.start_session(CHANNEL, at=NOW - timedelta(minutes=5))
        Diagnostics(store).begin('start', CHANNEL, demo.configuration('start'))
        demo.append(store, [('Alpha', 67, 2000, NOW - timedelta(minutes=1))])  # One frame: held, no switch.
    with server_module.create_server(path, port=0, public_only=True) as httpd:
        code, body = get(httpd, f'/api/players/{CHANNEL}')
        assert code == 200 and body['player']['character'] == dict(id=pending, label='—') and body['roster'] == []
        assert b'PendingOCR' not in request((httpd, None), f'/api/players/{CHANNEL}')[2]
        assert get(httpd, f'/api/players/{CHANNEL}?character=')[1]['view']['current']  # Blank: follow live.
        assert get(httpd, f'/api/players/{CHANNEL}?character={pending}') == (404, {'error': 'unknown_character'})
        assert b'PendingOCR' not in request((httpd, None), '/api/players')[2]
        assert get(httpd, '/api/players')[1]['players'][0]['character']['label'] == '—'
    with Store(path, read_only=True) as store:  # Presentation only: the record is unchanged.
        assert store.db.execute('SELECT label FROM characters WHERE id=?', (pending,)).fetchone()[0] == 'PendingOCR'


def test_only_the_exact_placeholder_label_is_hidden():
    rows = [dict(id=i, label=label, level=None, last_seen_at=None, current=False, revision=None)
            for i, label in enumerate(['PendingOCR', 'Pending', 'pendingocr', 'PendingOCR2', 'Alpha'], 1)]
    assert [r['label'] for r in public_roster(rows, None)] == ['Pending', 'pendingocr', 'PendingOCR2', 'Alpha']
    assert public_character(dict(id=1, label='PendingOCR'))['label'] == '—'
    assert public_character(dict(id=2, label='Pending'))['label'] == 'Pending' and public_character(None) is None


def test_roster_orders_current_then_recent_and_counts_only_genuine_characters(db):
    with Store(db, read_only=True) as store:
        rows = Diagnostics(store).roster(CHANNEL)
    assert len(rows) == 3 and [r['label'] for r in public_roster(rows, 68)] == ['Alpha', 'Beta']
    assert public_roster(rows, 68)[0]['level'] == 68  # The tracked character shows its displayed level.
    older = [dict(r, current=False) for r in rows if r['label'] != 'PendingOCR']
    assert [r['label'] for r in public_roster(older, None)] == ['Alpha', 'Beta']  # Most recently seen first.
    one = [r for r in rows if r['label'] != 'Beta']
    assert len(public_roster(one, None)) == 1  # One genuine character: the page shows no selector.


def test_expired_granular_history_keeps_saved_level_and_reading(db, clock):
    later = NOW + timedelta(days=2)
    with Store(db) as store:
        prune(store, now=later, dry_run=False)
    clock.at = later
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        code, body = get(httpd, f'/api/players/{CHANNEL}?character={BETA}')
        assert code == 200 and body['view'] == dict(character_id=BETA, current=False)
        assert body['tracked_history']['tracked_exp'] is None and body['tracked_history']['chart_intervals'] == []
        assert [(r['label'], r['level']) for r in body['roster']] == [('Alpha', 67), ('Beta', 43)]
        assert body['player']['reading']['level']['value'] == 43 and body['player']['reading']['exp'] is not None


def test_views_are_bounded_reused_and_dropped_when_unviewed(db, clock, monkeypatch):
    with Store(db) as store:
        store.add_character(CHANNEL, 'Gamma')
        gamma = store.db.execute("SELECT id FROM characters WHERE label='Gamma'").fetchone()[0]
        # A saved session for Gamma makes it a roster entry without any readings.
        store.db.execute('INSERT INTO sessions(streamer_id,character_id,started_at,ended_at,end_reason) VALUES (1,?,?,?,?)',
                         (gamma, '2025-12-31T00:00:00+00:00', '2025-12-31T00:00:01+00:00', 'explicit_end'))
    monkeypatch.setattr(publisher_module, 'MAX_VIEWS', 1)
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        assert get(httpd, f'/api/players/{CHANNEL}?character={BETA}')[0] == 200
        calls = []
        original = Diagnostics.card
        monkeypatch.setattr(Diagnostics, 'card', lambda self, *a, **k: calls.append(k.get('character')) or original(self, *a, **k))
        for _ in range(3):assert get(httpd, f'/api/players/{CHANNEL}?character={BETA}')[0] == 200
        assert calls == []  # Unchanged views are presented, never rebuilt per request.
        assert get(httpd, f'/api/players/{CHANNEL}?character={gamma}')[0] == 200
        assert list(httpd.publisher.viewed) == [('view', CHANNEL, gamma)]
        assert list(httpd.publisher.views) == [('view', CHANNEL, gamma)]
        assert not any(isinstance(k, tuple) and k[:3] == ('view', CHANNEL, BETA) for k in httpd.publisher.presented)
        assert get(httpd, f'/api/players/{CHANNEL}?character={BETA}')[0] == 200  # Returning rebuilds, never locks out browsing.
        monkeypatch.setattr(publisher_module, 'VIEW_IDLE_SECONDS', -1)
        clock.at += timedelta(seconds=31); calls.clear(); httpd.publisher.settle()
        assert BETA not in calls and list(httpd.publisher.views) == [('view', CHANNEL, BETA)]  # Unpolled: kept, not rebuilt.
        monkeypatch.setattr(publisher_module, 'VIEW_KEEP_SECONDS', -1)
        httpd.publisher.settle()
        assert not httpd.publisher.views and not httpd.publisher.viewed
        monkeypatch.setattr(publisher_module, 'VIEW_KEEP_SECONDS', 1800)
        monkeypatch.setattr(publisher_module, 'VIEW_IDLE_SECONDS', 60)
        code, body = get(httpd, f'/api/players/{CHANNEL}?character={gamma}')
        assert code == 200 and body['player']['character']['label'] == 'Gamma' and body['player']['reading'] is None


def test_restart_serves_a_cached_view_before_rebuilding_it(db, clock, tmp_path, monkeypatch):
    cache = tmp_path / 'warm.sqlite3'
    with server_module.create_server(db, port=0, public_only=True, publication_cache=cache) as httpd:
        code, built = get(httpd, f'/api/players/{CHANNEL}?character={BETA}')
        assert code == 200 and not httpd.publisher.stats['cache_error']
    with server_module.create_server(db, port=0, public_only=True, publication_cache=cache) as httpd:
        build = httpd.publisher.build
        monkeypatch.setattr(httpd.publisher, 'build', lambda *a, **k: None if k.get('view') else build(*a, **k))
        code, body = get(httpd, f'/api/players/{CHANNEL}?character={BETA}')
        assert code == 200 and body['publication']['state'] == 'restored'
        assert body['view'] == built['view'] and body['player']['reading'] == built['player']['reading']
        monkeypatch.setattr(httpd.publisher, 'build', build)
        code, body = get(httpd, f'/api/players/{CHANNEL}?character={BETA}')
        assert code == 200 and 'publication' not in body and not httpd.publisher.stats['cache_error']


def test_demo_switch_back_resumes_own_valid_endpoint_in_public_api(db, clock):
    """Beta's switch-out frame contains Alpha's lower percentage; it is NOT Beta's baseline."""
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        previous = {c: get(httpd, f'/api/players/{CHANNEL}?character={c}')[1] for c in (ALPHA, BETA)}
        assert previous[BETA]['player']['reading']['bp'] > 5700
        for target in (BETA, ALPHA, BETA):
            clock.at += timedelta(seconds=35)
            assert [s['character_id'] for s in demo.switch(now=clock.at, path=db)] == [target]
            for character in (ALPHA, BETA):
                code, body = get(httpd, f'/api/players/{CHANNEL}?character={character}')
                assert code == 200 and body['tracked_history']['character_id'] == character
                current, before = body['player']['reading'], previous[character]['player']['reading']
                assert int(current['exp']) > int(before['exp']) if character == target else current == before
                assert body['view']['current'] == (character == target)
                values = [int(p['reading']['exp']) for p in body['history'] if p.get('reading') and p['reading']['exp'] is not None]
                assert values
                assert values == sorted(values)  # No synthetic chart drops on any return.
                assert all(i['level'] == (67 if character == ALPHA else 43) and i['value']['numerator'] >= 0
                           for i in body['tracked_history']['chart_intervals'])
                previous[character] = body
        with Store(db, read_only=True) as store:
            # Each switch still holds the first observation and attributes only the confirmation.
            assert store.db.execute("SELECT COUNT(*) FROM diagnostic_attempts WHERE json_extract(payload_json,'$.identity_hold') IS NOT NULL").fetchone()[0] == 6
            assert len(Diagnostics(store).roster(CHANNEL)) == 3


@pytest.mark.parametrize('characters', [1, 12])
def test_optional_demo_rosters_and_lightweight_home_projection(tmp_path, clock, monkeypatch, characters):
    path = tmp_path / 'roster.sqlite3'
    demo.create(now=NOW, path=path, characters=characters)
    before = snapshot(path)
    with server_module.create_server(path, port=0, public_only=True) as httpd:
        code, current = get(httpd, f'/api/players/{CHANNEL}')
        assert code == 200 and len(current['roster']) == characters
        # Published rosters suffice, even if every heavy history entry point is unavailable.
        def forbidden(*a, **k):raise AssertionError('Homepage must not replay inactive history')
        monkeypatch.setattr(Diagnostics, 'card', forbidden)
        monkeypatch.setattr(Diagnostics, 'rolling_history', forbidden)
        code, home = get(httpd, '/api/players?mode=characters')
        assert code == 200 and len(home['characters']) == characters and 'players' not in home
        assert sum(r['current'] for r in home['characters']) == 1
        # The tracked character carries its own build's summary; inline requests never build the others'.
        base = {'id', 'label', 'level', 'last_seen_at', 'current', 'channel', 'online'}
        assert all(set(r) == (base | {'reading', 'display_level', 'as_of', 'day_buckets', 'day', 'recent_windows'} if r['current'] else base) for r in home['characters'])
        tracked = next(r for r in home['characters'] if r['current'])
        expected = current['player']['recent_windows']['5']
        expected = expected.get('pace') or expected.get('last_observed_pace')
        pace = tracked['recent_windows']['5']['last_observed_pace']
        assert pace and expected and pace['estimates']['exp_per_hour'] == expected['estimates']['exp_per_hour']
        assert pace['end'] == expected['end']
        assert tracked['recent_windows']['5']['eta'] == current['player']['recent_windows']['5']['eta']
        assert {r['id'] for r in home['characters']} == {r['id'] for r in current['roster']}
        assert 'PendingOCR' not in json.dumps(home) and not httpd.publisher.views
        assert len(get(httpd, '/api/players')[1]['players']) == 1
        assert get(httpd, '/api/players?mode=unknown') == (400, {'error': 'invalid_mode'})
    assert snapshot(path) == before


def test_twelve_profiles_can_be_opened_without_waiting_for_idle_expiry(tmp_path, clock):
    path = tmp_path / 'twelve.sqlite3'
    demo.create(now=NOW, path=path, characters=12)
    before = snapshot(path)
    with server_module.create_server(path, port=0, public_only=True) as httpd:
        roster = get(httpd, '/api/players?mode=characters')[1]['characters']
        for row in roster + roster[:2]:
            code, body = get(httpd, f"/api/players/{CHANNEL}?character={row['id']}")
            assert code == 200 and body['player']['character']['id'] == row['id']
            assert body['tracked_history']['character_id'] == row['id']
            assert len(httpd.publisher.views) <= publisher_module.MAX_VIEWS
            assert len(httpd.publisher.viewed) <= publisher_module.MAX_VIEWS
        assert len([k for k in httpd.publisher.present_locks if isinstance(k, tuple) and k[0] == 'view']) <= 4 * publisher_module.MAX_VIEWS
    assert snapshot(path) == before


def test_saved_character_without_a_session_has_an_empty_profile_and_no_mixed_stats(db, clock):
    with Store(db) as store:
        character = store.add_character(CHANNEL, 'Unplayed')
    before = snapshot(db)
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        rows = get(httpd, '/api/players?mode=characters')[1]['characters']
        assert next(r for r in rows if r['id'] == character) == dict(id=character, label='Unplayed', level=None,
            last_seen_at=None, current=False, channel=CHANNEL, online=False)
        code, body = get(httpd, f'/api/players/{CHANNEL}?character={character}')
        assert code == 200 and body['player']['character'] == dict(id=character, label='Unplayed')
        assert body['player']['reading'] is None and body['history'] == []
        assert body['tracked_history']['character_id'] == character and body['tracked_history']['tracked_exp'] is None
    assert snapshot(db) == before


@pytest.mark.parametrize('fault', ['rejected', 'stale', 'mismatched_name'])
def test_demo_rejects_unusable_numeric_baselines(db, clock, fault):
    # Model bad historical evidence without weakening the real attribution writer.
    with Store(db) as store:
        last = store.db.execute('''SELECT a.* FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
            WHERE r.character_id=? ORDER BY a.id DESC LIMIT 1''', (BETA,)).fetchone()
        payload = demo.attempt(last['attempt_index'], 'Beta', 43, 8000,
            datetime.fromisoformat(last['attempted_at']), 'Beta')
        if fault == 'rejected':payload['candidate'] = [999999999, 80.0]
        elif fault == 'stale':payload['current'] = False;payload['local_age_seconds'] = 300
        else:payload['character_name']['evidence']['name'] = 'Alpha';payload['character_name']['evidence']['raw']['raw']['txts'] = ['Alpha']
        store.db.execute('UPDATE diagnostic_attempts SET payload_json=? WHERE id=?', (json.dumps(payload), last['id']))
    clock.at += timedelta(seconds=30)
    assert [s['character_id'] for s in demo.switch(now=clock.at, path=db)] == [BETA]
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        body = get(httpd, f'/api/players/{CHANNEL}')[1]
        assert 5700 < body['player']['reading']['bp'] < 5800


def test_cold_profile_browsing_does_not_delay_changed_tracked_character(db, clock, monkeypatch):
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        get(httpd, f'/api/players/{CHANNEL}')
        assert httpd.publisher.character(CHANNEL, view=BETA) is None
        clock.at += timedelta(seconds=30)
        with Store(db) as store:demo.append(store, [('Alpha', 67, 2948, clock.at)])
        calls = []
        build = httpd.publisher.build
        monkeypatch.setattr(httpd.publisher, 'build', lambda *a, **k: calls.append(k.get('view')) or build(*a, **k))
        httpd.publisher.step()
        assert calls == [None]
        httpd.publisher.step()
        assert calls[-1][0] == ('view', CHANNEL, BETA)


def test_real_http_can_browse_twelve_profiles_without_changing_selection(tmp_path, clock):
    path = tmp_path / 'http-twelve.sqlite3'
    demo.create(now=NOW, path=path, characters=12)
    before = snapshot(path)
    with server_module.create_server(path, port=0, public_only=True) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True);thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        def fetch(route):
            for _ in range(4):
                try:
                    with urlopen(base + route, timeout=3) as response:return json.load(response)
                except HTTPError as error:
                    assert error.code == 503 and json.load(error)['error'] == 'warming_up'
            raise AssertionError('Profile did not become ready')
        try:
            try:roster = fetch('/api/players?mode=characters')['characters']
            except URLError as error:
                if isinstance(error.reason, OSError) and (error.reason.errno == 13 or getattr(error.reason, 'winerror', None) == 10013):
                    pytest.skip('Session policy blocks loopback client sockets; handler and separate browser HTTP tests cover navigation')
                raise
            for row in roster + roster[:2]:
                body = fetch(f"/api/players/{CHANNEL}?character={row['id']}")
                assert body['player']['character']['id'] == body['tracked_history']['character_id'] == row['id']
                assert len(httpd.publisher.views) <= publisher_module.MAX_VIEWS
            assert fetch(f'/api/players/{CHANNEL}')['player']['character']['id'] == next(r['id'] for r in roster if r['current'])
        finally:
            httpd.shutdown();thread.join(timeout=5)
    assert snapshot(path) == before


def test_home_roster_keeps_same_names_on_different_channels_separate(db, clock):
    with Store(db) as store:
        store.add_channel('other_demo')
        other = store.add_character('other_demo', 'Alpha')
        store.select_character('other_demo', other, at=NOW);store.start_session('other_demo', at=NOW)
    before = snapshot(db)
    with server_module.create_server(db, port=0, public_only=True) as httpd:
        rows = get(httpd, '/api/players?mode=characters')[1]['characters']
        assert {(r['channel'], r['id']) for r in rows if r['label'] == 'Alpha'} == {(CHANNEL, ALPHA), ('other_demo', other)}
        code, body = get(httpd, f'/api/players/other_demo?character={other}')
        assert code == 200 and body['player']['reading'] is None and body['tracked_history']['character_id'] == other
    assert snapshot(db) == before


def test_demo_extra_streamers_and_live_ticks_only_touch_recent_streams(tmp_path):
    path = tmp_path / 'streams.sqlite3'
    switches = demo.create(now=NOW, path=path, characters=1, streamers=5)
    assert [s['name'] for s in switches][-4:] == ['Ember', 'Frost', 'Sprout', 'Quiet']
    with Store(path) as store:
        count = lambda: dict(store.db.execute('SELECT s.login, COUNT(*) FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id '
                                              'JOIN streamers s ON s.id=r.streamer_id GROUP BY s.login').fetchall())
        before = count()
        live = demo.tick(store, now=NOW + timedelta(seconds=demo.INTERVAL))
        after = count()
    # The stream that ended hours ago stays ended; every other stream gains exactly one frame.
    assert set(live) == {CHANNEL, 'synthetic_ember', 'synthetic_frost', 'synthetic_sprout'}
    assert {login: after[login] - before[login] for login in after} == {**dict.fromkeys(live, 1), 'synthetic_quiet': 0}
    with Store(path) as store:  # `serve --offline` streams get no live frames either.
        assert set(demo.tick(store, now=NOW + timedelta(seconds=2 * demo.INTERVAL), offline={'synthetic_frost'})) == {CHANNEL, 'synthetic_ember', 'synthetic_sprout'}
    with pytest.raises(ValueError):demo.create(now=NOW, path=tmp_path / 'too-many.sqlite3', streamers=6)


def test_demo_day_history_fills_the_24_hour_charts(tmp_path):
    path = tmp_path / 'day.sqlite3'
    switches = demo.create(now=NOW, path=path, streamers=5, history=True)
    assert [s['name'] for s in switches] == ['Alpha', 'Beta', 'Alpha', 'Ember', 'Frost', 'Sprout', 'Quiet']
    with Store(path, read_only=True) as store:
        d = Diagnostics(store)
        filled = {login: sum(b['value'] is not None for b in d.rolling_history(login, now=NOW)['buckets']) for login in demo.DAY}
    assert min(filled.values()) >= 4 and sum(filled.values()) >= 40, filled  # Sprout plays least, in three short sessions.


def test_saved_summary_slides_its_chart_and_is_withheld_after_a_correction():
    p = publisher_module.Publisher(object(), clock=lambda: NOW, background=False)
    p.summaries[(CHANNEL, BETA)] = dict(revision=(1, 2, 3), as_of=NOW.isoformat(), reading={'bp': 5000}, display_level=None, buckets=[None] * 46 + [10, 20])
    head = dict(login=CHANNEL, manual_revision=1, invalidation_revision=2, retention_revision=3)
    assert p.summary(head, BETA, NOW + timedelta(minutes=29)) == dict(reading={'bp': 5000}, display_level=None, as_of=NOW.isoformat(), day_buckets=[None] * 46 + [10, 20], day=30, recent_windows={'5': {'last_observed_pace': None, 'eta': None}})
    # Half an hour on, both bars move left and the newest bucket is empty: nothing was tracked meanwhile.
    assert p.summary(head, BETA, NOW + timedelta(minutes=31))['day_buckets'] == [None] * 45 + [10, 20, None]
    assert p.summary(head, BETA, NOW + timedelta(hours=24))['day'] is None
    assert p.summary(dict(head, manual_revision=3), BETA, NOW) == {} and p.summary(head, ALPHA, NOW) == {}
    assert p.summary(dict(head, retention_revision=4), BETA, NOW) == {} and p.summary(head, BETA, NOW-timedelta(seconds=1)) == {}
    p.summaries[(CHANNEL, BETA)]['chart_buckets'] = [None] * 46 + [None, 2]
    shown = p.summary(head, BETA, NOW)
    assert shown['day'] == 30 and shown['day_buckets'][-2:] == [None, 2]


def test_character_summary_ages_existing_five_minute_pace_without_mutating_cached_values():
    p = publisher_module.Publisher(object(), clock=lambda: NOW, background=False)
    pace = dict(end=NOW.isoformat(), age_seconds=0, active=False,
        estimates=dict(exp_per_hour=dict(value=dict(approximate=2000))))
    p.summaries[(CHANNEL, BETA)] = dict(revision=(1, 2, 3), as_of=NOW.isoformat(),
        reading={'timestamp': NOW.isoformat()}, display_level=None, buckets=[None] * 48, five_minute_pace=pace)
    head = dict(login=CHANNEL, manual_revision=1, invalidation_revision=2, retention_revision=3)
    shown = p.summary(head, BETA, NOW + timedelta(seconds=300))['recent_windows']['5']['last_observed_pace']
    assert shown['age_seconds'] == 300 and shown['estimates']['exp_per_hour']['value']['approximate'] == 2000
    assert p.summary(head, BETA, NOW + timedelta(seconds=301))['recent_windows']['5']['last_observed_pace'] is None
    assert pace['age_seconds'] == 0


def test_character_summary_dates_and_expires_saved_eta_without_counting_down_or_mutating_cache():
    p = publisher_module.Publisher(object(), clock=lambda: NOW, background=False)
    eta = dict(estimated_at=NOW.isoformat(), age_seconds=0, window_minutes=5, estimate=dict(seconds=dict(approximate=900)))
    p.summaries[(CHANNEL, BETA)] = dict(revision=(1, 2, 3), as_of=NOW.isoformat(),
        reading=None, display_level=None, buckets=[None] * 48, five_minute_eta=eta)
    head = dict(login=CHANNEL, manual_revision=1, invalidation_revision=2, retention_revision=3)
    shown = p.summary(head, BETA, NOW + timedelta(seconds=300))['recent_windows']['5']['eta']
    assert shown['age_seconds'] == 300 and shown['estimate']['seconds']['approximate'] == 900
    assert p.summary(head, BETA, NOW + timedelta(seconds=301))['recent_windows']['5']['eta'] is None
    assert eta['age_seconds'] == 0
    eta['estimated_at'] = (NOW + timedelta(seconds=1)).isoformat()
    assert p.summary(head, BETA, NOW)['recent_windows']['5']['eta'] is None


def test_inactive_character_summaries_are_built_in_the_background_not_by_requests(db, clock, monkeypatch):
    monkeypatch.setattr(publisher_module, 'SUMMARY_SECONDS', 0)
    before = snapshot(db)
    def poll(httpd, path, found):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            code, _, body = request((httpd, None), path)
            if code == 200 and (value := found(json.loads(body))):return value
            time.sleep(.05)
        raise AssertionError(f'Timed out waiting for {path}')
    with server_module.create_server(db, port=0, public_only=True, background=True) as httpd:
        row = poll(httpd, '/api/players?mode=characters', lambda b: next((r for r in b['characters'] if r['id'] == BETA and 'reading' in r), None))
        assert not httpd.publisher.views  # Built for the list only, never kept or cached as a view.
        view = poll(httpd, f'/api/players/{CHANNEL}?character={BETA}', lambda b: b)
        buckets = [None if b['chart_value'] is None else round(b['chart_value']['approximate']) for b in view['tracked_history']['buckets']]
        assert row['reading'] == view['player']['reading'] and row['reading']['bp'] and row['day_buckets'] == buckets
        assert row['day'] == sum(round(b['value']['approximate']) for b in view['tracked_history']['buckets'] if b['value'] is not None) > 0
    assert snapshot(db) == before


def test_demo_offline_streams_report_offline_without_asking_twitch():
    class Availability:
        def snapshot(self, logins, *, now=None):return {c: dict(status='unknown') for c in logins}
    server = type('Server', (), {})();server.twitch_availability = Availability()
    demo.offline_twitch(server, {'synthetic_quiet'})
    statuses = server.twitch_availability.snapshot(['synthetic_ember'], now=NOW)
    assert statuses['synthetic_ember'] == dict(status='unknown') and statuses['synthetic_quiet']['status'] == 'offline'


def test_invalidated_name_is_never_switched_to_until_restored(db):
    with Store(db) as store:
        store.invalidate_character(CHANNEL, BETA, reason="Watched another player's video")
        latest = datetime.fromisoformat(store.db.execute('SELECT MAX(attempted_at) FROM diagnostic_attempts').fetchone()[0])
        frame = lambda i, bp: ('Beta', 43, bp, latest + timedelta(seconds=demo.INTERVAL * i))
        # Two confirming frames would normally switch; these stay with Alpha's capture, held as a name mismatch.
        assert demo.append(store, [frame(1, 6000), frame(2, 6020)]) == []
        assert store.state(CHANNEL)['selected_character_id'] == ALPHA
        assert [s['name'] for s in Diagnostics(store).roster(CHANNEL) if s['id'] == BETA] == []
        store.invalidate_character(CHANNEL, BETA, reason='It was theirs after all', restore=True)
        assert [s['character_id'] for s in demo.append(store, [frame(3, 6040), frame(4, 6060)])] == [BETA]


def test_a_database_without_the_invalidation_table_reads_as_none_invalidated(db):
    with sqlite3.connect(db) as con:con.execute('DROP TABLE character_invalidations')
    with Store(db, read_only=True) as store:
        assert store.invalidated_characters(1) == set() and len(Diagnostics(store).roster(CHANNEL)) == 3
    with Store(db) as store:assert store.invalidated_characters(1) == set()  # Any writer creates it again.
    with sqlite3.connect(db) as con:assert con.execute("SELECT 1 FROM sqlite_master WHERE name='character_invalidations'").fetchone()
