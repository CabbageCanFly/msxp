"""Stuck-stream alerts: which windows count as stuck, one message per episode, and a webhook URL never printed."""
from datetime import datetime, timedelta, timezone
import json
from urllib.error import HTTPError

import pytest

from exp_tracker import alerts, streamer_roster
from exp_tracker.store import Store

NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
WINDOW = timedelta(minutes=30)
HUD = dict(localization=dict(count=1))
HELD = dict(status='unavailable', level_hold=dict(reason='unresolved_level_change', evidence={**HUD, 'neural_level': dict(level=81)}))


def window(payload, login='Streamer_A', minutes=31, last=0, every=1):
    return [(login, NOW - timedelta(minutes=m), payload) for m in range(minutes, last - 1, -every)]


@pytest.mark.parametrize('rows,stuck', [
    (window(HELD), True),
    (window(dict(status='unavailable')), False),  # No HUD on screen: another game or a web page.
    (window(HELD) + [('Streamer_A', NOW, dict(status='diagnostic_pair'))], False),
    (window(HELD, minutes=20), False),  # Live for less than the window.
    (window(HELD, last=10), False),  # No captures lately: the stream ended.
    (window(HELD, minutes=30, every=2) + window(dict(status='unavailable'), minutes=30, every=2), True),  # Half the captures saw the HUD.
], ids=['held', 'no_hud', 'usable', 'too_new', 'ended', 'half_hud'])
def test_a_stream_is_stuck_only_when_live_throughout_with_its_hud_and_nothing_usable(rows, stuck):
    found = alerts.summary(sorted(rows, key=lambda r: r[1]), NOW, WINDOW)['Streamer_A']
    assert found['stuck'] is stuck


def test_one_message_per_episode_then_recovery_and_no_repeat_while_flapping():
    def run(state, rows, now):
        return alerts.step(state, alerts.summary(rows, now, WINDOW), now, WINDOW, 'https://example.test/')
    messages, state = run({}, window(HELD), NOW)
    assert len(messages) == 1 and 'Streamer_A' in messages[0] and 'Lv. 81' in messages[0]
    assert 'https://example.test/stream/Streamer_A' in messages[0] and state['Streamer_A']['open']
    assert run(state, window(HELD), NOW + timedelta(minutes=5)) == ([], state)  # Still stuck: no repeat.
    later = NOW + timedelta(minutes=10)
    resumed = [(login, at + timedelta(minutes=10), p) for login, at, p in window(HELD)] + [('Streamer_A', later, dict(status='diagnostic_pair'))]
    messages, state = run(state, resumed, later)
    assert messages == ['✅ **Streamer_A** is reading again.'] and not state['Streamer_A']['open']
    soon = NOW + timedelta(hours=2)
    assert run(state, [(l, at + timedelta(hours=2), p) for l, at, p in window(HELD)], soon)[0] == []  # Flapping.
    far = NOW + timedelta(hours=7)
    assert len(run(state, [(l, at + timedelta(hours=7), p) for l, at, p in window(HELD)], far)[0]) == 1


def test_an_alert_closes_silently_when_the_stream_ends_so_the_next_stream_alerts_again():
    _, state = alerts.step({}, alerts.summary(window(HELD), NOW, WINDOW), NOW, WINDOW)
    messages, state = alerts.step(state, {}, NOW + timedelta(minutes=20), WINDOW)
    assert messages == [] and not state['Streamer_A']['open']


def test_attempts_come_only_from_open_sessions_in_the_window(tmp_path):
    db = streamer_roster.create(tmp_path / 'tracker.sqlite3')
    with Store(db) as store, store._transaction():
        for streamer, ended in ((1, None), (2, NOW.isoformat())):
            store.db.execute('INSERT INTO streamers(id,login) VALUES(?,?)', (streamer, f'Streamer_{"AB"[streamer - 1]}'))
            store.db.execute('INSERT INTO characters(id,streamer_id,label) VALUES(?,?,?)', (streamer, streamer, 'CharA'))
            store.db.execute('INSERT INTO sessions(id,streamer_id,character_id,started_at,ended_at) VALUES(?,?,?,?,?)',
                             (streamer, streamer, streamer, (NOW - timedelta(hours=1)).isoformat(), ended))
            store.db.execute('INSERT INTO diagnostic_runs VALUES(?,?,?,?,?,?,?)', (f'run{streamer}', streamer, streamer, streamer, NOW.isoformat(), '{}', None))
            for index, minutes in enumerate((40, 20, 5), 1):
                at = (NOW - timedelta(minutes=minutes)).isoformat()
                store.db.execute('INSERT INTO diagnostic_attempts(run_id,attempt_index,attempted_at,recorded_at,payload_json,session_id) VALUES(?,?,?,?,?,?)',
                                 (f'run{streamer}', index, at, at, json.dumps(HELD), streamer))
    with Store(db, read_only=True) as store:
        rows = alerts.attempts(store, NOW - WINDOW)
        longer = alerts.attempts(store, NOW - WINDOW, cutoffs={'streamer_a': NOW-timedelta(minutes=45)})
    assert [(login, int((NOW - at).total_seconds() // 60)) for login, at, _ in rows] == [('Streamer_A', 20), ('Streamer_A', 5)]
    assert [(login, int((NOW - at).total_seconds() // 60)) for login, at, _ in longer] == [('Streamer_A', 40), ('Streamer_A', 20), ('Streamer_A', 5)]


def test_webhook_failures_never_print_the_url(monkeypatch, capsys):
    secret = 'https://discord.com/api/webhooks/1/SECRET'
    def refuse(request, timeout):
        raise HTTPError(request.full_url, 404, f'Not Found {request.full_url}', {}, None)
    monkeypatch.setattr(alerts, 'urlopen', refuse)
    assert alerts.send(secret, 'hello') is False
    out = capsys.readouterr().out
    assert 'HTTP 404' in out and 'SECRET' not in out


def test_per_streamer_tolerance_keeps_other_streams_at_the_default():
    default, overrides = alerts.windows(dict(MSXP_ALERT_MINUTES='30', MSXP_ALERT_STREAM_MINUTES='Streamer_A=90'))
    rows = sorted(window(HELD, 'streamer_a', minutes=60) + window(HELD, 'streamer_b', minutes=60), key=lambda r:r[1])
    found = alerts.summary(rows, NOW, default, overrides)
    assert not found['streamer_a']['stuck'] and found['streamer_b']['stuck']
    assert found['streamer_b']['count'] == 31  # Extra queried history cannot change the default.
    rows = sorted(window(HELD, 'streamer_a', minutes=91) + window(HELD, 'streamer_b', minutes=91), key=lambda r:r[1])
    messages, _ = alerts.step({}, alerts.summary(rows, NOW, default, overrides), NOW, default)
    assert '90 min' in messages[0] and '30 min' in messages[1]


@pytest.mark.parametrize('default,overrides', [
    ('nan',''), ('0',''), ('1441',''), ('30','Streamer_A=29'), ('30','Streamer_A=inf'),
    ('30','Streamer_A=1441'), ('30','Streamer_A=90,streamer_a=120'), ('30','bad-login=90'),
    ('30','Streamer_A'), ('30','Streamer_A=oops'), ('30','Streamer_A=90,'),
])
def test_invalid_tolerance_is_rejected(default, overrides):
    with pytest.raises(ValueError):
        alerts.windows(dict(MSXP_ALERT_MINUTES=default, MSXP_ALERT_STREAM_MINUTES=overrides))


def test_waits_for_the_full_window_and_any_in_window_usable_read_resets_it():
    duration = timedelta(minutes=90)
    assert not alerts.summary(window(HELD,minutes=89),NOW,duration)['Streamer_A']['stuck']
    rows = window(HELD,minutes=91)
    assert alerts.summary(rows,NOW,duration)['Streamer_A']['stuck']
    assert not alerts.summary(sorted(rows+[('Streamer_A',NOW-timedelta(minutes=89),dict(status='diagnostic_pair'))],key=lambda r:r[1]),NOW,duration)['Streamer_A']['stuck']
    assert alerts.summary(sorted(rows+[('Streamer_A',NOW-timedelta(minutes=91),dict(status='diagnostic_pair'))],key=lambda r:r[1]),NOW,duration)['Streamer_A']['stuck']


@pytest.mark.parametrize('kind,stuck', [('recovered',False), ('held',True), ('stale',True), ('invalid',True)])
def test_real_public_validation_counts_recoveries_without_counting_held_or_bad_reads(tmp_path,monkeypatch,capsys,kind,stuck):
    from exp_tracker.diagnostics import Diagnostics
    db = tmp_path / 'tracker.sqlite3'
    with Store(db) as store:
        store.add_channel('streamer_a')
        char = store.add_character('streamer_a','CharA')
        store.select_character('streamer_a',char)
        store.start_session('streamer_a',at=NOW-timedelta(hours=1))
        diagnostics = Diagnostics(store)
        diagnostics.begin('trial','streamer_a',dict(type='configuration',trusted=False,interval=60,count=31,source_kind='twitch'))
        for index in range(1,32):
            at = (NOW-timedelta(minutes=31-index)).isoformat()
            payload = dict(type='attempt',trusted=False,index=index,attempted_at=at,received_at=at,current=kind!='stale',
                source=dict(kind='twitch',channel='streamer_a'),status='malformed_or_unavailable',candidate=None,
                neural=dict(text='741.657140.00%1' if kind!='invalid' else 'unreadable'),
                visual_level=68,visual_status='available',localization=dict(count=1),local_age_seconds=1,
                frame_sha256=f'{index:064x}',neural_level=dict(status='numeric_candidate',text='68',level=68,score=.99))
            if kind=='held':payload['character_name']=dict(reading_hold_recommended=True,hold_reasons=['name_mismatch'])
            diagnostics.append('trial',payload)
    with Store(db,read_only=True) as store:
        found = alerts.summary(alerts.attempts(store,NOW-WINDOW),NOW,WINDOW)
        assert found['streamer_a']['stuck']  # The former status-only rule fires for all four cases.
        alerts.recovered_readings(store,found,NOW)
        assert found['streamer_a']['stuck'] is stuck
        if not stuck:
            assert found['streamer_a']['usable_at'] == NOW
            _, state = alerts.step({}, alerts.summary(window(HELD,'streamer_a'),NOW,WINDOW),NOW,WINDOW)
            state['streamer_a']['alerted_at'] = (NOW-timedelta(minutes=5)).isoformat()
            messages,state = alerts.step(state,found,NOW,WINDOW)
            assert len(messages)==1 and 'reading again' in messages[0] and not state['streamer_a']['open']
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return NOW
    monkeypatch.setattr(alerts,'datetime',Clock)
    monkeypatch.setattr(alerts,'send',lambda *_:pytest.fail('dry-run must not send'))
    state_file = tmp_path/'alert-state.json'
    state_file.write_text('{}')
    settings = dict(MSXP_ALERT_MINUTES='30',MSXP_FRONTEND_ORIGIN='https://example.test',MSXP_ALERT_WEBHOOK='unused')
    assert alerts.check(db,settings,dry_run=True,state_file=state_file)==0
    output = capsys.readouterr().out
    assert ('would send' in output) is stuck
    assert state_file.read_text()=='{}'
