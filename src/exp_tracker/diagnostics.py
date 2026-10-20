"""Experimental shadow persistence. This module never calls trusted ingestion."""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

from .shadow_view import MAX_LINE, MAX_ROWS, ShadowLog, observation, timestamp
from .store import Store, utc
from .shadow_grammar import interpret_exp, propose_full_exp
from .exp_requirements import community_table, requirement
from .diagnostic_progress import progress
from .product import player,refresh,history,PRODUCT_ROWS
from .diagnostic_evidence import project
from .manual import annotate,active,corrected_reading

MAX_REPLAY_BYTES = 4 * 1024 * 1024


def operation(value,runtime,now):
    """Only this HTTP process's coordinator can establish current activity."""
    if not runtime:
        return dict(state='capture_finished' if value.get('run_status')=='completed' else
            'capture_interrupted' if value.get('run_status')=='interrupted' else
            'historical_session' if value.get('historical') else
            'previous_unfinished_run' if value.get('unfinished_run_count') else 'coordinator_stopped')
    result=dict(runtime)
    if runtime['state']=='running' and (now-datetime.fromisoformat(runtime['updated_at'])).total_seconds()>runtime['expected_completion_seconds']:
        result['state']='capture_delayed'
    # Sequential work can start a few seconds late without missing a capture slot.
    elif runtime['state']=='waiting' and (now-datetime.fromisoformat(runtime['next_due_at'])).total_seconds()>max(2,min(15,runtime.get('requested_interval_seconds',15)/2)):
        result['state']='capture_delayed'
    return result


def due(player,built_at,now):
    """A cached player must be rebuilt as rolling windows age, even without a new revision."""
    paces=[player.get('responsive_pace')]+[w.get('pace') for w in player['recent_windows'].values()]
    pace_due=any(pace and not pace.get('retained_history') and
        datetime.fromisoformat(pace['start'])<now-timedelta(seconds=pace['trend_seconds']) for pace in paces)
    history_due=(any(w['available'] for w in player['recent_windows'].values())
        and (now-datetime.fromisoformat(built_at)).total_seconds()>=10)
    return pace_due or history_due


def present_card(card,*,now,active_runs=None,coordinator_status=None):
    """Time presentation of a cached card as a new dict; the cached card is never mutated."""
    card = deepcopy(card)
    def age(when):
        return (now-datetime.fromisoformat(when)).total_seconds() if when else None
    local_age = age(card['last_attempt_at'])
    percentage_age = age((card['percentage'] or {}).get('timestamp'))
    card.update(age_seconds=max(0,local_age) if local_age is not None else None,
        percentage_age_seconds=max(0,percentage_age) if percentage_age is not None else None,
        percentage_stale=percentage_age is None or percentage_age<0 or percentage_age>card['stale_after_seconds'],
        stale=local_age is None or local_age<0 or local_age>card['stale_after_seconds'] or card['last_attempt_noncurrent'])
    if card['stale'] or percentage_age is None or percentage_age<0 or percentage_age>card['stale_after_seconds']:
        card['pace']=None
    if card['run_status']=='unfinished' and active_runs is not None and card['run_id'] in active_runs:
        card['run_status']='active'
    card['operation']=operation(card,(coordinator_status or {}).get(card['channel']),now)
    card['player']=refresh(card['player'],now=now,activity=card['operation'])
    return card


def rotation_link(previous, current):
    """Check recorded lifecycle evidence; an arbitrary UUID change is never enough."""
    if not previous or not current: return False
    before=json.loads(previous['configuration_json']); after=json.loads(current['configuration_json'])
    summary=json.loads(previous['summary_json']) if previous['summary_json'] else {}
    same=('coordinator','coordinator_instance','source_identity','source_kind','interval',
          'requirements_sha256','experimental_neural_level','neural_level_preprocessing','timing_mode')
    return (after.get('start_reason')=='scheduled_rotation' and after.get('previous_run_id')==previous['run_id']
        and summary.get('completion_reason')=='scheduled_rotation' and summary.get('next_run_id')==current['run_id']
        and summary.get('attempts')==60 and summary.get('interrupted') is False
        and after.get('coordinator')=='multi_alpha_v1'
        and isinstance(after.get('coordinator_instance'),str) and bool(re.fullmatch(r'[0-9a-f]{32}',after['coordinator_instance']))
        and isinstance(after.get('source_identity'),str) and bool(re.fullmatch(r'[0-9a-f]{64}',after['source_identity']))
        and all(before.get(k)==after.get(k) for k in same)
        and all(previous[k]==current[k] for k in ('streamer_id','character_id','session_id')))


def coverage(observations, total):
    """Bounded read-only summary; overlapping proposal categories are explicit."""
    unique = lambda value: value.get('classification') == 'unique_proposal'
    return dict(scope='selected_session_recent_history', session_attempts=total,
        summarized_attempts=len(observations), history_limit=MAX_ROWS,
        acquired_frames=sum(r['capture_acquired'] is True for r in observations),
        acquisition_unknown=sum(r['capture_acquired'] is None for r in observations),
        unique_huds=sum(r['hud_count'] == 1 for r in observations),
        hud_unknown=sum(r['hud_count'] is None for r in observations),
        strict_full_pairs=sum(r['candidate'] is not None for r in observations),
        strict_percentage_only=sum(r['percentage_only_candidate'] is not None for r in observations),
        malformed_or_missing_strict=sum(not r['candidate'] and not r['percentage_only_candidate'] for r in observations),
        recovered_full_exp=sum(unique(r['interpretations']['full_exp']) for r in observations),
        recovered_percentages=sum(unique(r['interpretations']['percentage']) for r in observations),
        percentage_recovery_without_full=sum(unique(r['interpretations']['percentage']) and
            not unique(r['interpretations']['full_exp']) for r in observations),
        unrecoverable=sum(not r['candidate'] and not r['percentage_only_candidate'] and
            not unique(r['interpretations']['full_exp']) and not unique(r['interpretations']['percentage']) for r in observations),
        ambiguous=sum(any(r['interpretations'][f]['classification'] == 'ambiguous'
                          for f in ('full_exp', 'percentage')) for r in observations),
        visual_level_unavailable=sum(r['visual_level'] is None for r in observations),
        neural_level_unavailable=sum(not r['neural_level'] or r['neural_level']['level'] is None for r in observations),
        level_conflicts=sum(bool(r['neural_level'] and r['neural_level']['comparison'] == 'conflict') for r in observations),
        categories_overlap=True, trusted=False)


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
        self._validity_key=None
        self._validity={}

    def _begin(self, run_id, channel, configuration):
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id):
            raise ValueError('Invalid diagnostic run ID')
        payload = encoded(configuration)
        interval = configuration.get('interval')
        fast=configuration.get('offline_fast_test') is True and configuration.get('source_kind')=='file'
        if configuration.get('type') != 'configuration' or type(interval) not in (int, float) or not (3 if fast else 5) <= interval <= 300:
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
        if configuration.get('start_reason')=='scheduled_rotation':
            previous=self.db.execute('SELECT * FROM diagnostic_runs WHERE run_id=?',(configuration.get('previous_run_id'),)).fetchone()
            candidate=dict(run_id=run_id,configuration_json=payload,streamer_id=streamer['id'],character_id=session['character_id'],session_id=session['id'])
            if not rotation_link(previous,candidate) or self.db.execute(
                    'SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?',(previous['run_id'],)).fetchone()[0]!=60:
                raise ValueError('Scheduled rotation needs a finalized matching 60-attempt predecessor')
        self.db.execute('''INSERT INTO diagnostic_runs
            (run_id,streamer_id,character_id,session_id,created_at,configuration_json)
            VALUES (?,?,?,?,?,?)''', (run_id, streamer['id'], session['character_id'], session['id'], utc(), payload))
        return dict(self.db.execute('SELECT * FROM diagnostic_runs WHERE run_id=?', (run_id,)).fetchone())

    def begin(self, run_id, channel, configuration):
        with self.store._transaction():
            return self._begin(run_id, channel, configuration)

    def rotate(self, previous, following, channel, summary, configuration):
        """Finalize + bind the successor atomically; log flush alone proves neither."""
        with self.store._transaction():
            self._append(previous,summary)
            return self._begin(following,channel,configuration)

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
            configuration=json.loads(run['configuration_json'])
            if configuration.get('offline_fast_test') and (not isinstance(source,dict) or source.get('kind')!='file'):
                raise ValueError('Offline fast-test evidence must be local video')
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
                (run_id,attempt_index,attempted_at,received_at,recorded_at,payload_json,session_id) VALUES (?,?,?,?,?,?,?)''',
                (run_id, index, timestamp(record['attempted_at']), timestamp(received), utc(), payload,run['session_id']))
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

    def sessions(self,channel,*,before=None,limit=30):
        streamer=self.store._channel(channel)
        if type(limit) is not int or not 1<=limit<=50 or before is not None and (type(before) is not int or before<1):
            raise ValueError('Invalid session page')
        rows=list(self.db.execute('''SELECT s.*,c.label FROM sessions s JOIN characters c ON c.id=s.character_id
            WHERE s.streamer_id=? AND s.id<? ORDER BY s.id DESC LIMIT ?''',(streamer['id'],before or 2**63-1,limit+1)))
        return dict(sessions=[dict(r) for r in rows[:limit]],next_before=rows[limit-1]['id'] if len(rows)>limit else None,trusted=False)

    def runs(self,channel,session_id,*,before=None,limit=30):
        streamer=self.store._channel(channel)
        if type(session_id) is not int or not self.db.execute('SELECT 1 FROM sessions WHERE id=? AND streamer_id=?',(session_id,streamer['id'])).fetchone():
            raise ValueError('Unknown channel session')
        if type(limit) is not int or not 1<=limit<=50 or before is not None and (type(before) is not int or before<1):
            raise ValueError('Invalid run page')
        rows=list(self.db.execute('SELECT rowid,* FROM diagnostic_runs WHERE session_id=? AND rowid<? ORDER BY rowid DESC LIMIT ?',
            (session_id,before or 2**63-1,limit+1)))
        values=[]
        for row in rows[:limit]:
            config=json.loads(row['configuration_json']); summary=json.loads(row['summary_json']) if row['summary_json'] else {}
            values.append(dict(run_id=row['run_id'],created_at=row['created_at'],source_kind=config.get('source_kind') if config.get('source_kind') in ('file','twitch') else None,
                completion_reason=summary.get('completion_reason') if summary.get('completion_reason') in ('scheduled_rotation','bounded_complete','stop_condition','operator_interrupted') else None,
                start_reason=config.get('start_reason') if config.get('start_reason') in ('scheduled_rotation','process_start') else None,
                status='interrupted' if summary.get('interrupted') else 'completed' if summary else 'unfinished',
                attempts=self.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?',(row['run_id'],)).fetchone()[0]))
        return dict(runs=values,next_before=rows[limit-1]['rowid'] if len(rows)>limit else None,trusted=False)

    def snapshot(self, channel, *, now=None, active_runs=None,session_id=None,run_id=None,before=None,start=None,end=None,limit=MAX_ROWS):
        now = now or datetime.now(timezone.utc)
        with self.store._transaction():
            return self._snapshot(channel, now=now, active_runs=active_runs,session_id=session_id,run_id=run_id,before=before,start=start,end=end,limit=limit)

    def _snapshot(self, channel, *, now, active_runs=None,session_id=None,run_id=None,before=None,start=None,end=None,limit=MAX_ROWS,_rows_only=False):
        if type(limit) is not int or not 1<=limit<=PRODUCT_ROWS:raise ValueError('Invalid history limit')
        state = self.store._state(channel, as_of=now)
        selected = next((c for c in state['characters'] if c['id'] == state['selected_character_id']), None)
        session = state['session']
        historical=any(v is not None for v in (session_id,run_id,before,start,end))
        if session_id is not None:
            if type(session_id) is not int or session_id<1: raise ValueError('Invalid session')
            found=self.db.execute('SELECT * FROM sessions WHERE id=? AND streamer_id=(SELECT id FROM streamers WHERE login=?)',(session_id,state['channel'])).fetchone()
            if not found: raise ValueError('Unknown channel session')
            session=dict(found)
            selected=next(c for c in state['characters'] if c['id']==session['character_id'])
        if before is not None and (type(before) is not int or not 1<=before<2**63): raise ValueError('Invalid history cursor')
        for name,value in [('start',start),('end',end)]:
            if value is not None and timestamp(value) is None: raise ValueError(f'Invalid {name} timestamp')
        start=timestamp(start);end=timestamp(end)
        if start and end and (start>=end or (datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()>31*86400):
            raise ValueError('History window must increase and span at most 31 days')
        if run_id is not None and (not session or not self.db.execute('SELECT 1 FROM diagnostic_runs WHERE run_id=? AND session_id=?',(run_id,session['id'])).fetchone()):
            raise ValueError('Unknown session run')
        run = self.db.execute('SELECT rowid,* FROM diagnostic_runs WHERE session_id=?'+(' AND run_id=?' if run_id else '')+
            ' ORDER BY rowid DESC LIMIT 1', (session['id'],run_id) if run_id else (session['id'],)).fetchone() if session else None
        result = dict(trusted=False, storage='sqlite_diagnostics', served_at=utc(now), log_status='ready',
            channel=state['channel'], selected_character=selected, session=session,
            source_status='waiting' if session else 'unconfigured', run_status='waiting', run_id=None,
            age_seconds=None, stale=False, interval_seconds=None, stale_after_seconds=45, poll_seconds=2,
            observations=[], truncated=False, mixed_channels=False, latest_reading=None,
            trusted_state=state)
        result['manual_corrections'] = self.store.manual_history(channel,
            character_id=selected['id'] if selected else None,as_of=now) if selected else []
        from .invalidations import states,revision as invalidation_revision,mask,barriers
        result['invalidation_revision']=invalidation_revision(self.store,channel)
        validity_key=(selected['id'] if selected else None,result['invalidation_revision'])
        if validity_key!=self._validity_key:
            self._validity=states(self.store,selected['id'],'diagnostic',active_only=True) if selected else {}
            self._validity_key=validity_key
        validity=self._validity
        result['manual_observations']=[corrected_reading(e,event_id='observation:'+e['target_event_id'])
            for e in active(result['manual_corrections']) if e['kind']=='point' and e['target_kind']=='observation'
            and e['session_id']==(session['id'] if session else None)]
        result.update(historical=historical or bool(session and session['ended_at']),
            history=dict(session_id=session['id'] if session else None,run_id=run_id,before=before,start=start,end=end,next_before=None))
        table, sha = community_table()
        result['requirements_table'] = dict(version=table['version'], sha256=sha,
            status=table['status'], agreeing_levels=[1, 89], disputed_levels=[90, 99],
            missing_levels=[100, 200], authoritative=False)
        result['coverage'] = coverage([], 0)
        result['unfinished_run_count'] = self.db.execute(
            'SELECT COUNT(*) FROM diagnostic_runs WHERE session_id=? AND summary_json IS NULL',
            (session['id'],)).fetchone()[0] if session else 0
        if not run:
            result['percentage_progress'] = progress([],now=now)
            return result
        configuration = json.loads(run['configuration_json'])
        where=['a.session_id=?' if self.store.schema_version>=4 else 'r.session_id=?']
        values=[session['id']]
        for condition,value in [('a.run_id=?',run_id),('a.id<?',before),('a.attempted_at>=?',start),('a.attempted_at<?',end)]:
            if value is not None: where.append(condition);values.append(value)
        rows = list(self.db.execute('SELECT a.*,r.configuration_json,r.summary_json FROM diagnostic_attempts a '
            'JOIN diagnostic_runs r ON r.run_id=a.run_id WHERE '+' AND '.join(where)+' ORDER BY a.id DESC LIMIT ?',(*values,limit+1)))
        result['truncated'] = len(rows) > limit
        if result['truncated']: result['history']['next_before']=rows[limit-1]['id']
        rows = list(reversed(rows[:limit]))
        observations = []
        previous = None
        links={}
        for row in rows:
            payload = json.loads(row['payload_json'])
            value = observation(payload)  # Same HTTP allowlist as the log viewer.
            value['grammar_recovery'] = propose_full_exp(value['raw_text'])
            value['interpretations'] = interpret_exp(value['raw_text'])
            config=json.loads(row['configuration_json'])
            if config.get('timing_mode')=='simulated': value['timing_mode']='simulated'
            value['interval_seconds'] = config['interval']
            value['rotation_from']=None
            if config.get('start_reason')=='scheduled_rotation':
                if row['run_id'] not in links:
                    prior=self.db.execute('SELECT * FROM diagnostic_runs WHERE run_id=?',(config.get('previous_run_id'),)).fetchone()
                    current_run=self.db.execute('SELECT * FROM diagnostic_runs WHERE run_id=?',(row['run_id'],)).fetchone()
                    links[row['run_id']]=prior['run_id'] if rotation_link(prior,current_run) else None
                value['rotation_from']=links[row['run_id']]
            value['source_identity']=config.get('source_identity') if re.fullmatch(r'[0-9a-f]{64}',str(config.get('source_identity'))) else None
            value['coordinator_instance']=config.get('coordinator_instance') if re.fullmatch(r'[0-9a-f]{32}',str(config.get('coordinator_instance'))) else None
            value.update(assigned_channel=state['channel'], character_id=selected['id'], session_id=session['id'],
                         run_start_reason=config.get('start_reason') if config.get('start_reason') in ('process_start','scheduled_rotation') else None,
                         run_interrupted=bool(row['summary_json'] and json.loads(row['summary_json']).get('interrupted')))
            localization = payload.get('localization')
            count = localization.get('count') if isinstance(localization, dict) else None
            value['hud_count'] = count if type(count) is int and 0 <= count <= 200 else None
            value['capture_acquired'] = False if value['status'] == 'capture_failed' else (
                True if value['received_at'] is not None else None)
            value['requirements'] = dict(visual=requirement(value['visual_level']),
                neural=requirement((value['neural_level'] or {}).get('level')))
            when = value['received_at'] or value['attempted_at']
            value.update(event_id=f"{row['run_id']}:{row['attempt_index']}", run_id=row['run_id'],
                         timestamp_ordered=previous is None or when > previous)
            excluded=validity.get(('diagnostic',row['id']))
            if excluded and excluded['action']=='invalidate':mask(value,excluded)
            else:previous = max(previous, when) if previous else when
            observations.append(value)
        annotate(observations,result['manual_corrections'])
        if _rows_only:
            return observations  # Internal streaming history: reuse the exact sanitized decoder.
        barriers(observations)
        total = self.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE session_id=?' if self.store.schema_version>=4 else
            'SELECT COUNT(*) FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id WHERE r.session_id=?', (session['id'],)).fetchone()[0]
        observations=project(observations)
        for row in observations:
            if row.get('manual_point'):
                row['manual_presentation']=corrected_reading(row['manual_point'],event_id=row['event_id'],
                    timestamp=row.get('received_at') or row['attempted_at'],epoch=row['manual_epoch'])
        result['coverage'] = coverage(observations, total)
        result['coverage']['history_limit']=limit
        if result['historical']: result['coverage']['scope']='selected_history_page'
        interval = configuration['interval']
        summary = json.loads(run['summary_json']) if run['summary_json'] else None
        result.update(run_id=run['run_id'], observations=observations, interval_seconds=interval,
            source_identity=configuration.get('source_identity') if re.fullmatch(r'[0-9a-f]{64}',str(configuration.get('source_identity'))) else None,
            source_kind=configuration.get('source_kind') if configuration.get('source_kind') in ('file','twitch') else (observations[-1]['source_kind'] if observations else None),
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
        if active_runs is not None and result['run_status']=='unfinished' and run['run_id'] in active_runs:
            result['run_status']='active'
        result['percentage_progress'] = progress(observations,now=now,stale_after_seconds=result['stale_after_seconds'],current_run_id=run['run_id'])
        for observation_value,decision in zip(observations,result['percentage_progress']['percentage_reviews']):
            observation_value['percentage_review']=decision
        if result['historical']:
            result['percentage_progress']['history_scope']='selected_history_page'
            result['percentage_progress']['current_pace']=None
            result['percentage_progress']['current_segment']=None
            result['percentage_progress']['reason']='historical_window_not_current'
        return result

    def rolling_history(self,channel,*,now=None,checkpoints=None):
        from .rolling_history import aggregate
        if self.db.in_transaction:return aggregate(self,channel,now=now or datetime.now(timezone.utc),checkpoints=checkpoints)
        with self.store._transaction():
            return aggregate(self,channel,now=now or datetime.now(timezone.utc),checkpoints=checkpoints)

    def recent_snapshot(self,channel,*,now,eta_cache=None,checkpoints=None):
        from .rolling_history import recent_snapshot
        if self.db.in_transaction:return recent_snapshot(self,channel,now=now,eta_cache=eta_cache,checkpoints=checkpoints)
        with self.store._transaction():
            return recent_snapshot(self,channel,now=now,eta_cache=eta_cache,checkpoints=checkpoints)

    def heads(self,login=None):
        """Committed revision per channel: selection, open session, latest run and attempt."""
        manual='(SELECT MAX(id) FROM manual_corrections WHERE streamer_id=s.id)' if self.store.schema_version>=5 else 'NULL'
        rename='(SELECT MAX(id) FROM character_renames WHERE streamer_id=s.id)' if self.store.schema_version>=6 else 'NULL'
        invalidation='(SELECT MAX(c.id) FROM reading_commits c JOIN reading_batches b ON b.id=c.batch_id WHERE b.streamer_id=s.id)' if self.store.schema_version>=7 else 'NULL'
        latest='SELECT MAX(id) FROM diagnostic_attempts WHERE session_id=se.id' if self.store.schema_version>=4 else (
            'SELECT MAX(a.id) FROM diagnostic_attempts a JOIN diagnostic_runs dr ON dr.run_id=a.run_id WHERE dr.session_id=se.id')
        return list(self.db.execute('''SELECT s.login,s.selected_character_id,se.id AS session_id,
            r.run_id,r.summary_json,
            (SELECT COUNT(*) FROM diagnostic_runs WHERE session_id=se.id AND summary_json IS NULL) AS unfinished_count,
            ('''+latest+''') AS last_attempt_id,
            '''+manual+''' AS manual_revision,
            '''+rename+''' AS rename_revision,
            '''+invalidation+''' AS invalidation_revision
            FROM streamers s LEFT JOIN sessions se ON se.streamer_id=s.id AND se.ended_at IS NULL
            LEFT JOIN diagnostic_runs r ON r.rowid=(SELECT MAX(rowid) FROM diagnostic_runs WHERE session_id=se.id)
            '''+('WHERE s.login=? ' if login else '')+'ORDER BY s.login LIMIT 26',(login,) if login else ()))

    def card(self,cache,head,*,now,checkpoints=None,eta_cache=None):
        """One shared computation per channel revision for the homepage and character API.

        Entry: (revision, card, extras); extras carry the character page's chart history.
        """
        key=tuple(head);cached=cache.get(head['login'])
        if cached is None or cached[0]!=key or due(cached[1]['player'],cached[1]['recent_as_of'],now):
            snap = self._snapshot(head['login'],now=now,limit=PRODUCT_ROWS)
            recent=self.recent_snapshot(head['login'],now=now,eta_cache=eta_cache,checkpoints=checkpoints)
            p = snap['percentage_progress']
            last = snap['observations'][-1] if snap['observations'] else {}
            full = None
            for row in reversed(snap['observations']):
                if not row['timestamp_ordered'] or row['candidate_invalid'] or row['percentage_only_invalid']: continue
                if row['exp_validity']['status']=='invalid': continue
                proposal = row['interpretations']['full_exp']
                reading = row['candidate'] or (proposal['proposals'][0]['reading'] if proposal['classification']=='unique_proposal' else None)
                if reading:
                    full = dict(exp=reading['exp'],percentage=reading['percentage'],
                        evidence='strict_full' if row['candidate'] else 'grammar_recovered',
                        event_id=row['event_id'],timestamp=row['received_at'] or row['attempted_at'])
                    break
            point = p['latest_percentage']
            card = dict(channel=snap['channel'],character=snap['selected_character'],session=snap['session'],
                source_kind=snap.get('source_kind'),
                source_status=snap['source_status'],run_status=snap['run_status'],run_id=snap['run_id'],
                reasons=last.get('reasons',[]),
                last_attempt_at=last.get('received_at') or last.get('attempted_at'),
                last_attempt_noncurrent=last.get('timestamp_ordered') is False or not last.get('fresh_at_capture'),
                percentage={k:point[k] for k in ('percentage','evidence','timestamp','event_id')} if point else None,
                full_exp=full,visual_level=last.get('visual_level'),neural_level=(last.get('neural_level') or {}).get('level'),
                movement=p['latest_movement'],progress_reason=p['reason'],pace=p['current_pace'],
                stale_after_seconds=snap['stale_after_seconds'],history_limit=PRODUCT_ROWS,
                history_truncated=snap['truncated'],trusted=False)
            card['player']=player(snap,now=now,recent_snapshot=recent)
            card['recent_as_of']=now.isoformat()
            card['unfinished_run_count'] = snap['unfinished_run_count']
            cache[head['login']]=(key,card,dict(history=history(recent),truncated=recent.get('recent_history_status')=='history_limit',
                lifecycle={k:snap[k] for k in ('run_status','historical','unfinished_run_count')}))
        return cache[head['login']]

    def directory(self, cache, *, now=None, active_runs=None,coordinator_status=None,checkpoints=None,eta_cache=None):
        """Cache compact cards by committed revision; never retain full histories."""
        now = now or datetime.now(timezone.utc)
        cards = []
        with self.store._transaction():
            heads=self.heads()
            for head in heads[:25]:
                self.card(cache,head,now=now,checkpoints=checkpoints,eta_cache=eta_cache)
            for head in heads[:25]:
                cards.append(present_card(cache[head['login']][1],now=now,active_runs=active_runs,coordinator_status=coordinator_status))
            allowed = {head['login'] for head in heads[:25]}
            for key in list(cache):
                if key not in allowed: del cache[key]
        return dict(streams=cards,truncated=len(heads)>25,poll_seconds=2,served_at=utc(now),trusted=False)


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
