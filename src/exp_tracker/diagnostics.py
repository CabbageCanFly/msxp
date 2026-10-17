"""Experimental shadow persistence. This module never calls trusted ingestion."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

from .shadow_view import MAX_LINE, MAX_ROWS, ShadowLog, observation, timestamp
from .store import Store, utc

MAX_REPLAY_BYTES = 4 * 1024 * 1024


def encoded(record):
    if not isinstance(record, dict) or record.get('trusted') is not False:
        raise ValueError('Expected an explicitly untrusted shadow record')
    payload = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(payload.encode()) > MAX_LINE:
        raise ValueError('Diagnostic record exceeds 64 KiB')
    return payload


class Diagnostics:
    """Use an existing Store connection and its atomic transaction boundary."""

    def __init__(self, store):
        self.store = store
        self.db = store.db

    def _begin(self, run_id, channel, configuration):
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id):
            raise ValueError('Invalid diagnostic run ID')
        payload = encoded(configuration)
        interval = configuration.get('interval')
        if configuration.get('type') != 'configuration' or type(interval) not in (int, float) or not 5 <= interval <= 300:
            raise ValueError('Expected bounded shadow configuration')
        streamer = self.store._channel(channel)
        existing = self.db.execute('SELECT * FROM diagnostic_runs WHERE run_id=?', (run_id,)).fetchone()
        if existing:
            if existing['streamer_id'] != streamer['id'] or existing['configuration_json'] != payload:
                raise ValueError('Run ID reused with different source/configuration')
            return dict(existing)  # Replay retains the original assignment, including after a switch.
        session = self.store._open_session(streamer['id'])
        if not session or session['character_id'] != streamer['selected_character_id']:
            raise ValueError('Explicitly select a character and start a session first')
        self.db.execute('''INSERT INTO diagnostic_runs
            (run_id,streamer_id,character_id,session_id,created_at,configuration_json)
            VALUES (?,?,?,?,?,?)''', (run_id, streamer['id'], session['character_id'], session['id'], utc(), payload))
        return dict(self.db.execute('SELECT * FROM diagnostic_runs WHERE run_id=?', (run_id,)).fetchone())

    def begin(self, run_id, channel, configuration):
        with self.store._transaction():
            return self._begin(run_id, channel, configuration)

    def _append(self, run_id, record):
        payload = encoded(record)
        run = self.db.execute('SELECT * FROM diagnostic_runs WHERE run_id=?', (run_id,)).fetchone()
        if run is None:
            raise ValueError('Unknown diagnostic run')
        kind = record.get('type')
        if kind == 'attempt':
            if not isinstance(record.get('status'), str) or any(
                    key in record and not isinstance(record[key], str) for key in ('visual_status', 'neural_status')):
                raise ValueError('Incompatible shadow attempt status')
            try:
                observation(record)
            except (TypeError, ValueError, OverflowError, RecursionError):
                raise ValueError('Incompatible shadow attempt structure') from None
            index = record.get('index')
            if type(index) is not int or not 1 <= index <= 60 or timestamp(record.get('attempted_at')) is None:
                raise ValueError('Attempt needs a bounded index and aware timestamp')
            received = record.get('received_at')
            if received is not None and timestamp(received) is None:
                raise ValueError('Invalid receipt timestamp')
            source = record.get('source')
            channel = self.db.execute('SELECT login FROM streamers WHERE id=?', (run['streamer_id'],)).fetchone()[0]
            if not isinstance(source, dict) or source.get('kind') not in ('file', 'twitch') or (
                    source.get('kind') == 'twitch' and str(source.get('channel', '')).lower() != channel):
                raise ValueError('Shadow source does not match assigned channel')
            previous = self.db.execute('SELECT payload_json FROM diagnostic_attempts WHERE run_id=? AND attempt_index=?',
                                       (run_id, index)).fetchone()
            if previous:
                if previous[0] != payload:
                    raise ValueError('Attempt ID reused with different contents')
                return False
        elif kind == 'summary':
            if run['summary_json'] is not None:
                if run['summary_json'] != payload:
                    raise ValueError('Summary replay differs')
                return False
        else:
            raise ValueError('Expected shadow attempt or summary')
        session = self.store._open_session(run['streamer_id'])
        selected = self.db.execute('SELECT selected_character_id FROM streamers WHERE id=?', (run['streamer_id'],)).fetchone()[0]
        if not session or session['id'] != run['session_id'] or selected != run['character_id']:
            raise ValueError('Diagnostic assignment changed; stop and start a new run')
        if kind == 'summary':
            self.db.execute('UPDATE diagnostic_runs SET summary_json=? WHERE run_id=?', (payload, run_id))
        else:
            last = self.db.execute('SELECT COALESCE(MAX(attempt_index),0) FROM diagnostic_attempts WHERE run_id=?', (run_id,)).fetchone()[0]
            if run['summary_json'] is not None or index != last + 1:
                raise ValueError('Attempt order must be contiguous within an unfinished run')
            self.db.execute('''INSERT INTO diagnostic_attempts
                (run_id,attempt_index,attempted_at,received_at,recorded_at,payload_json) VALUES (?,?,?,?,?,?)''',
                (run_id, index, timestamp(record['attempted_at']), timestamp(received), utc(), payload))
        return True

    def append(self, run_id, record):
        with self.store._transaction():
            return self._append(run_id, record)

    def replay(self, channel, path):
        path = ShadowLog(path).validate_path()
        with path.open('rb') as handle:
            data = handle.read(MAX_REPLAY_BYTES + 1)
        if len(data) > MAX_REPLAY_BYTES or not data.endswith(b'\n'):
            raise ValueError('Replay must contain completed lines, at most 4 MiB')
        lines = data.splitlines()
        if not 2 <= len(lines) <= 62 or any(len(line) > MAX_LINE for line in lines):
            raise ValueError('Replay must contain one configuration and at most 60 attempts plus summary')
        records = [json.loads(line) for line in lines]
        configuration = records[0]
        if not isinstance(configuration, dict):
            raise ValueError('Missing configuration')
        run_id = configuration.get('run_id')
        if run_id is None:
            if not isinstance(records[-1], dict) or records[-1].get('type') != 'summary':
                raise ValueError('Legacy replay needs a completed summary for stable identity')
            run_id = hashlib.sha256(data).hexdigest()
        with self.store._transaction():
            binding = self._begin(run_id, channel, configuration)
            inserted = sum(self._append(run_id, record) for record in records[1:])
        return dict(run_id=run_id, session_id=binding['session_id'], character_id=binding['character_id'],
                    inserted_records=inserted, source_sha256=hashlib.sha256(data).hexdigest(), trusted=False)

    def snapshot(self, channel, *, now=None):
        now = now or datetime.now(timezone.utc)
        with self.store._transaction():
            state = self.store._state(channel, as_of=now)
            selected = next((c for c in state['characters'] if c['id'] == state['selected_character_id']), None)
            session = state['session']
            run = self.db.execute('''SELECT rowid,* FROM diagnostic_runs WHERE session_id=?
                ORDER BY rowid DESC LIMIT 1''', (session['id'],)).fetchone() if session else None
            result = dict(trusted=False, storage='sqlite_diagnostics', served_at=utc(now), log_status='ready',
                channel=state['channel'], selected_character=selected, session=session,
                source_status='waiting' if session else 'unconfigured', run_status='waiting', run_id=None,
                age_seconds=None, stale=False, interval_seconds=None, stale_after_seconds=45, poll_seconds=2,
                observations=[], truncated=False, mixed_channels=False, latest_reading=None,
                trusted_state=state)
            if not run:
                return result
            configuration = json.loads(run['configuration_json'])
            rows = list(self.db.execute('''SELECT a.* FROM diagnostic_attempts a
                JOIN diagnostic_runs r ON r.run_id=a.run_id WHERE r.session_id=?
                ORDER BY a.id DESC LIMIT ?''', (session['id'], MAX_ROWS + 1)))
            result['truncated'] = len(rows) > MAX_ROWS
            rows = list(reversed(rows[:MAX_ROWS]))
            observations = []
            previous = None
            for row in rows:
                value = observation(json.loads(row['payload_json']))  # Same HTTP allowlist as the log viewer.
                when = value['received_at'] or value['attempted_at']
                value.update(event_id=f"{row['run_id']}:{row['attempt_index']}", run_id=row['run_id'],
                             timestamp_ordered=previous is None or when > previous)
                previous = max(previous, when) if previous else when
                observations.append(value)
            interval = configuration['interval']
            summary = json.loads(run['summary_json']) if run['summary_json'] else None
            result.update(run_id=run['run_id'], observations=observations, interval_seconds=interval,
                stale_after_seconds=max(45, 3 * interval),
                run_status=('interrupted' if summary.get('interrupted') else 'completed') if summary else 'unfinished')
            if observations:
                latest = observations[-1]
                when = latest['received_at'] or latest['attempted_at']
                age = (now - datetime.fromisoformat(when)).total_seconds()
                result.update(source_status=latest['status'], age_seconds=max(0, age),
                              stale=age < 0 or age > result['stale_after_seconds'] or not latest['timestamp_ordered'])
                # The latest attempt can fail; an older candidate is explicitly aged, never made current.
                reading = next((o for o in reversed(observations) if o['timestamp_ordered'] and
                                (o['candidate'] or o['percentage_only_candidate'])), None)
                if reading:
                    age = (now - datetime.fromisoformat(reading['received_at'] or reading['attempted_at'])).total_seconds()
                    result['latest_reading'] = dict(observation=reading, age_seconds=max(0, age),
                        stale=age < 0 or age > result['stale_after_seconds'] or not reading['fresh_at_capture']
                              or not reading['timestamp_ordered'])
            return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--channel', required=True)
    parser.add_argument('log', type=Path, help='Replay an existing private/artifacts shadow JSONL')
    args = parser.parse_args(argv)
    try:
        if not args.db.is_file():
            raise ValueError('Initialize/select/start using the tracking CLI first')
        with Store(args.db) as store:
            print(json.dumps(Diagnostics(store).replay(args.channel, args.log), indent=2))
        return 0
    except (OSError, ValueError, TypeError, sqlite3.Error, RecursionError) as error:
        print(f'Diagnostic replay failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
