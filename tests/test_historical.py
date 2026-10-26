from datetime import datetime, timedelta, timezone
import json

import pytest

from exp_tracker.daily_snapshots import save
from exp_tracker.historical import daily_history
from exp_tracker.server import create_server
from exp_tracker.store import Store
from tests.test_server import request


NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / 'history.sqlite3'
    with Store(path) as store:
        store.add_channel('streamer_a')
        cid = store.add_character('streamer_a', 'CharA')
        other = store.add_character('streamer_a', 'CharB')
        pending = store.add_character('streamer_a', 'PendingOCR')
        store.select_character('streamer_a', cid)
        store.add_channel('streamer_b')
        foreign = store.add_character('streamer_b', 'CharA')
        for age, level, exp, bp in [(40, 40, 100, 100), (2, 42, 9223372036854775807, 5000),
                                     (1, None, None, 5050), (0, 43, 0, 0)]:
            save(store, cid, (NOW-timedelta(days=age)).isoformat(), level, exp, bp,
                 'diagnostic', 'agreement', 'strict_full' if exp is not None else None, 'strict_full')
        save(store, other, NOW.isoformat(), 50, 10, 1, 'trusted_ocr', 'trusted_ocr', 'observed_integer', 'displayed')
    return path, cid, other, pending, foreign


def test_daily_history_is_bounded_read_only_and_preserves_large_values(archive):
    path, cid, other, _, _ = archive
    with Store(path, read_only=True) as store:
        before = list(store.db.iterdump())
        result = daily_history(store, 'STREAMER_A', days=30, now=NOW)
        assert result['character_id'] == cid
        assert [r['utc_date'] for r in result['points']] == ['2026-10-24', '2026-10-26']
        assert result['points'][0]['current_exp'] == '9223372036854775807'
        assert result['points'][1]['current_exp'] == '0'
        assert len(daily_history(store, 'streamer_a', days=90, now=NOW)['points']) == 3
        assert daily_history(store, 'streamer_a', character=other, now=NOW)['points'][0]['level'] == 50
        assert list(store.db.iterdump()) == before


def test_daily_history_identity_and_unavailable_old_schema(archive):
    path, cid, other, pending, foreign = archive
    with Store(path) as store:
        for bad in (pending, foreign, 999):
            with pytest.raises(LookupError):daily_history(store, 'streamer_a', character=bad, now=NOW)
        store.invalidate_character('streamer_a', other, reason='Synthetic unrelated character')
        with pytest.raises(LookupError):daily_history(store, 'streamer_a', character=other, now=NOW)
        store.schema_version = 8
        result = daily_history(store, 'streamer_a', character=cid, now=NOW)
        assert result['available'] is False and result['points'] == []


def test_legacy_snapshots_complete_values_without_guessing_levels_or_changing_storage(archive):
    path,cid,_,_,_=archive
    with Store(path) as store:
        store.db.execute('''INSERT INTO daily_character_exp VALUES(?,?,?,?,?,?,?,?,?,?)''',
                         (cid,'2026-10-23','2026-10-23T12:00:00+00:00',None,None,5000,'diagnostic',None,None,'displayed'))
        store.db.execute('''INSERT INTO daily_character_exp VALUES(?,?,?,?,?,?,?,?,?,?)''',
                         (cid,'2026-10-22','2026-10-22T12:00:00+00:00',40,None,5000,'diagnostic','agreement',None,'displayed'))
        store.db.execute('''INSERT INTO daily_character_exp VALUES(?,?,?,?,?,?,?,?,?,?)''',
                         (cid,'2026-10-21','2026-10-21T12:00:00+00:00',40,147108,None,'diagnostic','agreement','strict_full',None))
        before=list(store.db.iterdump())
        points=daily_history(store,'streamer_a',now=NOW)['points']
        assert '2026-10-23' not in {p['utc_date'] for p in points}
        derived={p['utc_date']:p for p in points}
        assert derived['2026-10-22']['current_exp']=='147108'
        assert derived['2026-10-22']['exp_basis']=='derived_from_percentage'
        assert derived['2026-10-21']['percentage_bp']==5000
        assert derived['2026-10-21']['percentage_basis']=='derived_from_exp'
        assert list(store.db.iterdump())==before


def test_daily_api_does_not_replay_or_settle_live_history_and_allows_cache_and_cors(archive, monkeypatch):
    path, cid, _, _, foreign = archive
    with create_server(path, port=0, public_only=True, cors_origins=['https://example.org']) as httpd:
        monkeypatch.setattr(httpd.publisher, 'settle', lambda:pytest.fail('daily requests must not build live history'))
        status, headers, raw = request((httpd, None), f'/api/players/streamer_a/daily-history?character={cid}&days=365', origin='https://example.org')
        assert status == 200 and headers['Cache-Control'] == 'private, max-age=86400'
        assert headers['Access-Control-Allow-Origin'] == 'https://example.org'
        assert json.loads(raw)['character_id'] == cid
        assert request((httpd, None), f'/api/players/streamer_a/daily-history?character={foreign}')[0] == 404
        assert request((httpd, None), '/api/players/missing/daily-history')[0] == 404


@pytest.mark.parametrize('query', ['days=0', 'days=366', 'days=-1', 'days=', 'days=30&days=90',
                                  'character=', 'character=0', 'character=1.5', 'character=9999999999999999999',
                                  'extra=1', 'days=1&days=2&days=3&days=4&days=5'])
def test_daily_api_rejects_invalid_queries(archive, query):
    with create_server(archive[0], port=0, public_only=True) as httpd:
        assert request((httpd, None), '/api/players/streamer_a/daily-history?'+query)[0] == 400
