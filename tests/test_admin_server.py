"""The operator HTTP boundary uses the existing append-only Store rules."""
import http.client
import json
import sqlite3

import pytest

from exp_tracker.admin_server import AdminServer, Handler
from exp_tracker.schema import STATEMENTS, MIGRATION_2, MIGRATION_3
from exp_tracker.server import create_server
from exp_tracker.store import Store
from tests.test_manual_admin import at, current
from tests.test_product import tracking
from tests.test_server import MemorySocket, request as public_request
from tests.test_store import profile, reading
from tests.test_tracked_exp_totals import save


def request(server, path='/api/inspect?channel=alpha', method='GET', data=None, headers=None, raw=None):
    body = raw if raw is not None else json.dumps(data).encode() if data is not None else b''
    fields = {'Host': server.origin.removeprefix('http://'), 'X-Admin-Token': server.token,
              'Origin': server.origin, 'Content-Type': 'application/json', 'Content-Length': str(len(body))}
    fields.update(headers or {})
    head = ''.join(f'{k}: {v}\r\n' for k,v in fields.items() if v is not None)
    wire = MemorySocket(f'{method} {path} HTTP/1.1\r\n{head}Connection: close\r\n\r\n'.encode()+body)
    Handler(wire, ('127.0.0.1', 0), server)
    response = http.client.HTTPResponse(MemorySocket(wire.output.getvalue())); response.begin()
    content = response.read()
    value = json.loads(content) if response.headers.get_content_type() == 'application/json' else content
    return response.status, response.headers, value


@pytest.fixture
def admin(tracking):
    path, store, d = tracking
    with AdminServer(path, 0) as server:
        yield server, store, d


def baseline(store, **changes):
    return dict(action='set', channel='alpha', character_id=str(store.state('alpha')['selected_character_id']),
                level='42', percentage='99.40', effective_at=at(25).isoformat(), **changes)


def preview(server, data):
    status, _, result = request(server, '/api/preview', 'POST', data)
    assert status == 200, result
    return result


def commit(server, data):
    p = preview(server, data)
    status, _, result = request(server, '/api/save', 'POST', {'preview_id':p['preview_id']})
    assert status == 200, result
    return result


def test_page_inspection_and_preview_never_write(admin):
    server, store, d = admin
    save(d, 'run', 1, 0, 3300)
    before = store.db.total_changes
    status, headers, page = request(server, '/', headers={'X-Admin-Token':None, 'Origin':None})
    assert status == 200 and server.token.encode() in page
    assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    assert headers['Cache-Control'] == 'no-store'
    assert request(server, '/admin.js')[0] == request(server, '/admin.css')[0] == 200
    assert request(server, '/admin-time.js')[0] == 200
    assert server.server_address[0] == '127.0.0.1'
    assert request(server, '/api/channels')[2]['channels'][0]['login'] == 'alpha'
    result = request(server)[2]
    assert result['readings'][0]['identity'] == 'run:1'
    p = preview(server, baseline(store))
    assert p['reading']['exp'] is None and p['reading']['estimated_exp']
    assert p['event']['provenance'] == 'manual_admin'
    assert store.manual_history('alpha') == [] and store.db.total_changes == before


def test_explicit_now_is_frozen_and_retry_saves_once(admin):
    server, store, _ = admin
    data = baseline(store); data.pop('effective_at'); data['use_now'] = True
    p = preview(server, data)
    stamp = p['event']['effective_at']
    for _ in range(2):
        status, _, result = request(server, '/api/save', 'POST', dict(preview_id=p['preview_id']))
        assert status == 200 and result['event']['effective_at'] == stamp
    assert len(store.manual_history('alpha')) == 1
    with Store(server.database, read_only=True) as reopened:
        assert reopened.manual_history('alpha')[0]['effective_at'] == stamp


def test_exact_sqlite_exp_survives_json_and_both_values_preserved(admin):
    server, store, _ = admin
    data = baseline(store); data.update(level='200', exp=str(2**63-1))
    p = preview(server, data)
    assert p['event']['current_exp'] == str(2**63-1)
    result = commit(server, data)
    assert result['event']['current_exp'] == str(2**63-1)
    assert store.manual_history('alpha')[0]['current_exp'] == 2**63-1
    assert request(server)[2]['corrections'][0]['current_exp'] == str(2**63-1)
    data.update(level='49', exp='12345', percentage='90.00')
    p = preview(server, data)
    assert p['reading']['exp'] == '12345' and p['reading']['percentage'] == '90.00'
    assert p['reading']['exp_validity']['status'] == 'invalid'


@pytest.mark.parametrize('change', [
    {'level':None}, {'level':True}, {'level':'201'}, {'level':'1.5'}, {'exp':'-1'}, {'exp':str(2**63)},
    {'percentage':'100'}, {'percentage':'1.234'}, {'effective_at':'2026-01-01T00:00Z'},
    {'effective_at':'2026-01-01T00:00:00'}, {'effective_at':'2026-01-01T00:00:00+00:99'},
    {'effective_at':'2999-01-01T00:00:00Z'},
    {'use_now':True}, {'use_now':'true'}, {'character_id':'9999'}, {'channel':'../alpha'},
    {'action':'surprise'}, {'action':{}}, {'unexpected':'x'}, {'reason':'bad\nreason'},
])
def test_invalid_preview_requests_are_rejected_without_write(admin, change):
    server, store, _ = admin
    data = baseline(store); data.update(change)
    status, _, result = request(server, '/api/preview', 'POST', data)
    assert status == 400 and result['error']
    assert store.manual_history('alpha') == []


@pytest.mark.parametrize('missing', ['level', 'percentage', 'effective_at', 'character_id', 'channel'])
def test_required_fields_and_no_implicit_time(admin, missing):
    server, store, _ = admin
    data = baseline(store); data.pop(missing)
    assert request(server, '/api/preview', 'POST', data)[0] == 400
    assert store.manual_history('alpha') == []


@pytest.mark.parametrize('headers', [
    {'Host':'evil.test'}, {'Host':'localhost'}, {'Host':None}, {'Host':'127.0.0.1'},
    {'Origin':'https://evil.test'}, {'Origin':'null'}, {'Origin':None},
    {'X-Admin-Token':None}, {'X-Admin-Token':'wrong'}, {'X-Admin-Token':'é'},
    {'Sec-Fetch-Site':'cross-site'},
])
def test_protected_writes_reject_rebinding_cross_origin_and_missing_token(admin, headers):
    server, store, _ = admin
    assert request(server, '/api/preview', 'POST', baseline(store), headers)[0] == 403
    assert store.manual_history('alpha') == []


def test_api_reads_are_protected_and_no_get_or_direct_save_writes(admin):
    server, store, _ = admin
    assert request(server, '/api/channels', headers={'X-Admin-Token':None})[0] == 403
    assert request(server, '/api/inspect?channel=alpha&channel=beta')[0] == 400
    assert request(server, '/api/preview')[0] == 404
    assert request(server, '/api/preview', 'OPTIONS')[0] == 405
    assert request(server, '/api/save', 'POST', baseline(store))[0] == 409
    assert request(server, '/api/save', 'POST', {'preview_id':'unknown'})[0] == 409
    p = preview(server, baseline(store))
    server.previews[p['preview_id']]['expires'] = 0
    assert request(server, '/api/save', 'POST', {'preview_id':p['preview_id']})[0] == 409


@pytest.mark.parametrize('body,headers', [
    (b'{"action":"set","action":"undo"}', {}), (b'[]', {}), (b'null', {}), (b'not json', {}),
    (b'\xff', {}), (b'{}', {'Content-Type':'text/plain'}), (b'{}', {'Transfer-Encoding':'chunked'}),
    (b'{}', {'Content-Length':'99999'}), (b'{}', {'Content-Length':None}),
])
def test_malformed_bodies(admin, body, headers):
    server, store, _ = admin
    assert request(server, '/api/preview', 'POST', raw=body, headers=headers)[0] == 400
    assert store.manual_history('alpha') == []


def test_baseline_amend_undo_clear_and_no_artificial_gain(admin):
    server, store, d = admin
    for i, seconds in enumerate((0,20,40,60), 1):save(d, 'run', i, seconds, 3300+i*10)
    before = d.rolling_history('alpha', now=at(61))['tracked_exp']['approximate']
    first = commit(server, baseline(store))['event']
    # An older amendment remains possible even with a newer independent correction.
    newer = baseline(store); newer.update(effective_at=at(55).isoformat(), level='43')
    second = commit(server, newer)['event']
    amended = baseline(store); amended.update(action='amend', correction_id=str(first['id']), level='41', reason='Wrong level')
    third = commit(server, amended)['event']
    assert third['replaces_id'] == first['id']
    assert current(d, 61)['display_level']['value'] == 43
    commit(server, dict(action='undo', channel='alpha', character_id=amended['character_id'], correction_id=str(third['id']), reason='Wrong entry'))
    events = store.manual_history('alpha')
    assert not next(e for e in events if e['id'] == first['id'])['active']
    assert d.rolling_history('alpha', now=at(61))['tracked_exp']['approximate'] <= before
    clear = dict(action='clear', channel='alpha', character_id=amended['character_id'], effective_at=at(65).isoformat())
    commit(server, clear)
    assert current(d, 66)['reading'] is None
    assert len(request(server)[2]['corrections']) == 5


def test_historical_point_amend_undo_ownership_and_original_identity(admin):
    server, store, d = admin
    for i, seconds in enumerate((0,20,40,60), 1):save(d, 'run', i, seconds, 3300+i*10)
    before = list(store.db.execute('SELECT payload_json FROM diagnostic_attempts'))
    before_gain = d.rolling_history('alpha', now=at(61))['tracked_exp']['approximate']
    data = baseline(store); data.update(action='correct', target_kind='diagnostic', target_event_id='run:2',
                                       effective_at=at(20).isoformat(), level='49', exp='12345', percentage='2.10')
    first = commit(server, data)['event']
    rows = request(server)[2]['readings']
    point = next(r for r in rows if r['identity'] == 'run:2')
    assert point['original_level'] == 64 and point['presentation']['level']['value'] == 49
    assert current(d, 61)['reading']['event_id'] == 'run:4'
    assert d.rolling_history('alpha', now=at(61))['tracked_exp']['approximate'] <= before_gain
    duplicate = request(server, '/api/preview', 'POST', data)
    assert duplicate[0] == 400 and 'already corrected' in duplicate[2]['error']
    data.update(action='amend', correction_id=str(first['id']), reason='Actually 48', level='48')
    second = commit(server, data)['event']
    commit(server, dict(action='undo', channel='alpha', character_id=data['character_id'], correction_id=str(second['id']), reason='Restore OCR'))
    assert next(r for r in request(server)[2]['readings'] if r['identity']=='run:2')['presentation']['evidence'] == 'strict_full'
    assert d.rolling_history('alpha', now=at(61))['tracked_exp']['approximate'] == before_gain
    assert list(store.db.execute('SELECT payload_json FROM diagnostic_attempts')) == before
    data.update(action='correct'); data.pop('correction_id')
    data['effective_at'] = at(21).isoformat()
    assert request(server, '/api/preview', 'POST', data)[0] == 400
    other = store.add_character('alpha', 'Other')
    data['character_id'] = str(other); data['effective_at'] = at(20).isoformat()
    assert request(server, '/api/preview', 'POST', data)[0] == 400


def test_historical_session_rename_and_publication_without_capture(admin):
    server, store, d = admin
    cid = store.state('alpha')['selected_character_id']; old_session = store.state('alpha')['session']['id']
    save(d, 'run', 1, 0, 3300)
    store.end_session('alpha', at=at(30))
    other = store.add_character('alpha', 'Other'); store.select_character('alpha', other, at=at(31)); store.start_session('alpha', at=at(31))
    data = baseline(store); data.update(character_id=str(cid), session_id=str(old_session), level='49')
    commit(server, data)
    assert request(server, f'/api/inspect?channel=alpha&character_id={cid}&session_id={old_session}')[2]['display_level']['value'] == 49
    assert request(server)[2]['reading'] is None
    # New live baseline and rename refresh the same public publisher without another frame.
    with create_server(server.database, port=0, diagnostic_dashboard=True) as public:
        public.publisher.settle()
        data = baseline(store); data.update(effective_at=at(35).isoformat())
        result = commit(server, data)
        def published():return json.loads(public_request((public,None), '/api/players/alpha')[2])
        assert published()['player']['manual_correction']['id'] == result['event']['id']
        rename = dict(action='rename', channel='alpha', character_id=str(other), new_name='Real name', reason='Placeholder')
        assert preview(server, rename)['event']['character_id'] == other
        assert store.state('alpha')['characters'][1]['label'] == 'Other'
        result = commit(server, rename)
        assert result['event']['character_id'] == other and 'roster' in result['notice']
        assert published()['player']['character']['label'] == 'Real name'
        assert public_request((public,None), '/api/preview', method='POST')[0] == 405
    assert store.state('alpha')['selected_character_id'] == other
    assert store.db.execute('SELECT character_id FROM sessions WHERE id=?',(old_session,)).fetchone()[0] == cid


def test_stale_preview_revalidates_and_cannot_undo_another_character(admin):
    server, store, _ = admin
    first = commit(server, baseline(store))['event']
    data = dict(action='undo', channel='alpha', character_id=str(first['character_id']), correction_id=str(first['id']), reason='Wrong')
    p = preview(server, data)
    commit(server, data)
    assert request(server, '/api/save', 'POST', dict(preview_id=p['preview_id']))[0] == 409
    other = store.add_character('alpha', 'Other')
    data['character_id'] = str(other)
    assert request(server, '/api/preview', 'POST', data)[0] == 400
    rename = dict(action='rename', channel='alpha', character_id=str(other), new_name='New')
    p = preview(server, rename)
    store.rename_character('alpha', other, 'Concurrent')
    assert request(server, '/api/save', 'POST', dict(preview_id=p['preview_id']))[0] == 409
    assert store.state('alpha')['characters'][1]['label'] == 'Concurrent'


def test_old_schema_preview_migrates_only_disposable_copy(tmp_path):
    path = tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db:
        for sql in (*STATEMENTS,*MIGRATION_2,*MIGRATION_3):db.execute(sql)
        db.execute('PRAGMA user_version=3')
        db.execute("INSERT INTO streamers(id,login) VALUES(1,'alpha')")
        db.execute("INSERT INTO characters VALUES(1,1,'Main')")
        db.execute('UPDATE streamers SET selected_character_id=1')
        db.execute('INSERT INTO tracking_state(character_id) VALUES(1)')
    before = path.read_bytes()
    with AdminServer(path, 0) as server:
        assert request(server)[2]['schema_version'] == 3
        preview(server, dict(action='set', channel='alpha', character_id='1', level='42', exp='1000', use_now=True))
    assert path.read_bytes() == before
    with Store(path, read_only=True) as store:assert store.schema_version == 3


def test_trusted_and_rejected_observations_and_historical_point(admin, profile):
    server, store, _ = admin
    sid = store.state('alpha')['session']['id']
    trusted = store.ingest('alpha', 'trusted', at(1), reading(), session_id=sid, profile=profile)
    rejected = store.ingest('alpha', 'rejected', at(2), reading(), session_id=sid)
    rows = {r['identity']:r for r in request(server)[2]['readings']}
    assert rows[trusted['id']]['presentation']['exp'] == '1000'
    assert rows[trusted['id']]['presentation']['evidence'] == 'trusted_sqlite_ocr'
    assert rows[rejected['id']]['presentation']['exp'] is None
    assert rows[rejected['id']]['presentation']['percentage'] is None
    assert rows[rejected['id']]['presentation']['evidence'] == 'rejected_sqlite_ocr'
    data = baseline(store); data.update(action='correct', target_kind='observation', target_event_id=str(trusted['id']),
                                       effective_at=trusted['observed_at'], level='49')
    result = commit(server, data)
    rows = {r['identity']:r for r in request(server)[2]['readings']}
    assert rows[trusted['id']]['original']['level'] == 60
    assert rows[trusted['id']]['presentation']['provenance']['id'] == result['event']['id']
    assert store.state('alpha')['last_trusted']['level'] == 60
