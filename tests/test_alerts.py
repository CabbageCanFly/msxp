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
    (window(HELD, every=2) + window(dict(status='unavailable'), minutes=30, every=2), True),  # Half the captures saw the HUD.
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
    assert [(login, int((NOW - at).total_seconds() // 60)) for login, at, _ in rows] == [('Streamer_A', 20), ('Streamer_A', 5)]


def test_webhook_failures_never_print_the_url(monkeypatch, capsys):
    secret = 'https://discord.com/api/webhooks/1/SECRET'
    def refuse(request, timeout):
        raise HTTPError(request.full_url, 404, f'Not Found {request.full_url}', {}, None)
    monkeypatch.setattr(alerts, 'urlopen', refuse)
    assert alerts.send(secret, 'hello') is False
    out = capsys.readouterr().out
    assert 'HTTP 404' in out and 'SECRET' not in out
