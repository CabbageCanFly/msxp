"""Opt-in autonomous attribution. All mutations run on the serialized Store writer."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import sys

from .diagnostic_evidence import project, consistency, full_reading, CONFIRM_GAP_SECONDS, NEURAL_SEED_SCORE
from .diagnostics import Diagnostics, HELD_ENVELOPE, encoded, identity_held
from .jobs import match, min_level, tier
from .manual import active
from .models import PLACEHOLDER_CHARACTER, same_character_name
from .shadow_view import observation
from .store import utc

MAX_AUTOMATIC_CHARACTERS = 16
JOB_GAP_SECONDS = 300  # Job reads are a minute or more apart, so two agreeing ones may span several captures.


def job_vote(record):
    """This capture's job read, if it is current and its text still matches the job list."""
    evidence = (record.get('character_name') or {}).get('evidence') or {}
    job = evidence.get('job') or {}
    if (not record.get('current') or job.get('status') != 'candidate' or type(job.get('score')) not in (int, float)
            or not .9 <= job['score'] <= 1 or match(job.get('text')) != job.get('job') or job.get('job') is None):
        return None
    return dict(job=job['job'], received_at=evidence.get('received_at'), pixel_sha256=evidence.get('pixel_sha256'))


def confirm_job(store, character, record):
    """Two agreeing job reads of different frames within JOB_GAP_SECONDS record the job. It only moves
    up a tier and never above what the character's validated level allows."""
    vote = job_vote(record)
    if vote is None or not vote['received_at'] or not vote['pixel_sha256']:
        return None
    prior = None
    for (payload,) in store.db.execute('''SELECT a.payload_json FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
            WHERE r.character_id=? ORDER BY a.id DESC LIMIT 30''', (character,)):
        found = job_vote(json.loads(payload))
        if found and found['pixel_sha256'] != vote['pixel_sha256']:
            prior = found
            break
    if prior is None or prior['job'] != vote['job'] or not prior['received_at']:
        return None
    gap = (datetime.fromisoformat(vote['received_at']) - datetime.fromisoformat(prior['received_at'])).total_seconds()
    known = store.character_job(character)
    floor = store.db.execute('SELECT level FROM character_level_guard WHERE character_id=?', (character,)).fetchone()
    if (not 0 < gap <= JOB_GAP_SECONDS or known and tier(known['job']) >= tier(vote['job'])
            or floor and floor[0] is not None and floor[0] < min_level(vote['job'])):
        return None
    store.set_character_job(character, vote['job'], source='ocr', evidence=[prior, vote])
    return vote['job']


def original(record):
    for key in ('level_hold', 'identity_hold'):
        if key in record:
            record = {**{k: record[k] for k in HELD_ENVELOPE if k in record}, **record[key]['evidence']}
    return record


def fingerprint(record):
    return hashlib.sha256(encoded(record).encode()).hexdigest()


def name_evidence(record):
    value = record.get('character_name', {}).get('evidence', {})
    name, score = value.get('name'), value.get('score')
    raw = value.get('raw') or {}
    raw = raw.get('raw') or {}
    texts = raw.get('txts')
    provenance = value.get('provenance') or {}
    if (not record.get('current') or record.get('localization', {}).get('count') != 1 or value.get('status') != 'candidate'
            or value.get('received_at') != record.get('received_at')
            or record.get('character_name', {}).get('suggestion', {}).get('latest_status') in ('duplicate_frame','out_of_order')
            or not isinstance(name, str) or same_character_name(name, PLACEHOLDER_CHARACTER) or not name.isascii() or not name.isalnum()
            or not name[0:1].isalpha() or not 2 <= len(name) <= 12
            or type(score) not in (int, float) or not math.isfinite(score) or not NEURAL_SEED_SCORE <= score <= 1
            or provenance.get('layout_count') != 1 or provenance.get('search') != 'full_frame'
            or not isinstance(texts, list) or len(texts) != 1 or not isinstance(texts[0], str)
            or len(texts[0]) > 160 or texts[0].strip() != name
            or raw.get('scores') != [score]):
        return None
    digest = value.get('pixel_sha256')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        return None
    return dict(name=name, score=score, pixel_sha256=digest, received_at=value['received_at'], box=value.get('box'))


def independent(before, after):
    return bool(before and after and before['pixel_sha256'] != after['pixel_sha256']
                and 0 < (datetime.fromisoformat(after['received_at']) -
                         datetime.fromisoformat(before['received_at'])).total_seconds() <= CONFIRM_GAP_SECONDS)


def level_evidence(record):
    if not record.get('current') or record.get('localization', {}).get('count') != 1:
        return None
    row = observation(record)
    row.update(hud_count=1, capture_acquired=True, event_id='level_evidence')
    projected = project([row])[0]
    evidence = projected['experimental_level']
    level, basis = evidence.get('value'), evidence['status']
    # guard_level supplies the two-frame confirmation; a one-frame projection cannot do it itself.
    if (level is None and evidence['status'] == 'pending' and evidence.get('neural_score', 0) >= NEURAL_SEED_SCORE
            and (row.get('neural_level') or {}).get('preprocessing') == 'neutral4'):
        level, basis = evidence['neural'], 'single_neural_arithmetic'
    full = full_reading(projected)  # A pair the projection could not verify is no level evidence.
    check=consistency(full,level)
    agreed=(projected['experimental_level']['status']=='agreement' and
            (row.get('neural_level') or {}).get('score',0)>=NEURAL_SEED_SCORE)
    informative=bool(full and int(full['exp'])>0 and float(full['percentage'])>0)
    if (level is None or row['crop_suspect'] or not row['frame_sha256']
            or not (check['status']=='consistent' and (informative or agreed) or check['status']=='indeterminate' and agreed)):
        return None
    name=name_evidence(record)
    return dict(level=level, name=name['name'] if name else None,
                pixel_sha256=record.get('character_name', {}).get('evidence', {}).get('pixel_sha256')
                or row['frame_sha256'], received_at=row['received_at'], basis=basis)


def level_held(record, reason, floor):
    return {**{k: record[k] for k in HELD_ENVELOPE if k in record},
            'status': 'unavailable', 'current': False, 'reasons': [],
            'level_hold': dict(reason=reason, validated_level=floor,
                               evidence={k: v for k, v in record.items() if k not in HELD_ENVELOPE})}


def guard_level(store, character, record, *, support=None):
    """Persistent monotone floor; two independent arithmetically supported frames advance it."""
    if 'level_hold' in record and record.get('current') is False:
        return record
    row = store.db.execute('SELECT * FROM character_level_guard WHERE character_id=?', (character,)).fetchone()
    floor = row['level'] if row else None
    pending = json.loads(row['pending_json']) if row and row['pending_json'] else None
    if not record.get('current'):
        gap = observation(record)
        when = gap['received_at']
        elapsed = ((datetime.fromisoformat(when)-datetime.fromisoformat(pending['received_at'])).total_seconds()
                   if pending and when else None)
        # A fresh unreadable HUD is no vote and must not erase a normal level-up's first vote.
        unreadable = (record.get('current') is False and floor is not None and pending
            and pending['level']==floor+1 and elapsed is not None and 0<elapsed<=CONFIRM_GAP_SECONDS
            and record.get('status')=='unavailable' and record.get('reasons')==['missing_hud']
            and (record.get('localization') or {}).get('count')==0
            and gap['frame_sha256'] is not None
            and gap['local_age_seconds'] is not None and gap['local_age_seconds']<=15
            and record.get('candidate') is None and record.get('neural') is None
            and record.get('visual_level') is None and (record.get('neural_level') or {}).get('level') is None
            and not record.get('automatic_identity_risk'))
        if not unreadable:
            store.db.execute('UPDATE character_level_guard SET pending_json=NULL WHERE character_id=? AND pending_json IS NOT NULL', (character,))
        return record
    # A saved policy receipt can predate today's floor; only exact stored retries bypass validation.
    record = {k:v for k,v in record.items() if k!='level_policy'}
    proof = json.loads(row['proof_json']) if row and row['proof_json'] else None
    owner = store.db.execute('SELECT s.login,c.label FROM streamers s JOIN characters c ON c.streamer_id=s.id WHERE c.id=?', (character,)).fetchone()
    login = owner['login']
    # Explicit operator baselines are validated assertions; OCR-only legacy maxima are not imported.
    manual = [e for e in active(store.manual_history(login, character_id=character)) if e.get('level')]
    if manual:
        highest = max(manual, key=lambda e: e['level'])
        if floor is None or highest['level'] > floor:
            floor, proof = highest['level'], dict(level=highest['level'], received_at=highest['effective_at'],
                                                basis='manual_admin', event_id=highest['event_id'])
    normalized = observation(record)
    # A reader below the floor that this frame's own strict EXP pair contradicts misread the digits
    # (Tesseract read Lv. 19 as 13 twice); it is no regression, and the frame is judged without it.
    strict = full_reading(normalized) if normalized.get('candidate') else None
    misread = [k for k, v in (('visual_level', normalized['visual_level']), ('neural_level', (normalized.get('neural_level') or {}).get('level')))
               if floor and v is not None and v < floor and strict and consistency(strict, v)['status'] == 'invalid']
    judged = {**record, **dict.fromkeys(misread)}  # Evaluation only; the stored record keeps both readings.
    if misread:normalized = observation(judged)
    qualified = level_evidence(judged)
    reason = None
    claims = [v for v in (normalized['visual_level'], (normalized.get('neural_level') or {}).get('level'),
                         (qualified or {}).get('level')) if v is not None]
    if floor and any(v < floor for v in claims):
        reason, pending = 'level_regression', None
    elif qualified and (floor is None or qualified['level'] > floor):
        prior = support or pending
        identity_supported=(floor is None or qualified['level']<=floor+1 or
                            same_character_name(qualified['name'], (prior or {}).get('name')) and same_character_name(qualified['name'], owner['label']))
        if prior and prior['level'] == qualified['level'] and independent(prior, qualified) and identity_supported:
            floor, proof, pending = qualified['level'], {**qualified, 'support': prior}, None
        else:
            pending, reason = qualified, 'level_confirmation_pending'
    elif qualified:
        pending = None
    elif floor is None and claims:
        reason, pending = 'level_unvalidated', None
    elif floor and (any(v > floor for v in claims) or
                    consistency(full_reading(normalized), floor)['status'] == 'invalid'):
        reason, pending = 'unresolved_level_change', None
    elif pending:
        pending = None
    store.db.execute('''INSERT INTO character_level_guard VALUES(?,?,?,?,?)
        ON CONFLICT(character_id) DO UPDATE SET level=excluded.level,proof_json=excluded.proof_json,
        pending_json=excluded.pending_json,updated_at=excluded.updated_at''',
        (character, floor, json.dumps(proof) if proof else None, json.dumps(pending) if pending else None, utc()))
    result = deepcopy(record)
    result['level_policy'] = dict(validated_level=floor, input_sha256=fingerprint(record),
                                  reason=reason or 'within_validated_level', proof=proof)
    return level_held(result, reason, floor) if reason else result


class AutonomousCharacters:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.diagnostics = Diagnostics(store)

    def append(self, run_id, record, following, configuration, *, write=None):
        """Atomic selection + session + immutable run + current baseline + durable receipt.

        write() may flush private logs before COMMIT; failures roll SQLite back. Callers
        change lane/worker state only after this method returns successfully.
        """
        event = f'{run_id}:{record["index"]}'
        digest = fingerprint(record)
        with self.store._transaction():
            receipt = self.db.execute('SELECT * FROM automatic_character_events WHERE event_id=?', (event,)).fetchone()
            if receipt:
                if receipt['fingerprint'] != digest: raise ValueError('Automatic decision ID reused with different input')
                saved = json.loads(receipt['receipt_json'])
                payload = self.db.execute('SELECT payload_json FROM diagnostic_attempts WHERE run_id=? AND attempt_index=1', (saved['run_id'],)).fetchone()
                if not payload: raise ValueError('Automatic baseline evidence expired')
                return dict(**saved, record=json.loads(payload[0]), duplicate=True)
            run = self.db.execute('SELECT * FROM diagnostic_runs WHERE run_id=?', (run_id,)).fetchone()
            if not run or not json.loads(run['configuration_json']).get('automatic_characters'):
                raise ValueError('Automatic attribution requires an opted-in run')
            duplicate = self.db.execute('SELECT payload_json FROM diagnostic_attempts WHERE run_id=? AND attempt_index=?',
                                        (run_id, record['index'])).fetchone()
            if duplicate:
                saved = json.loads(duplicate[0])
                if original(saved).get('automation_input_sha256') != digest:
                    raise ValueError('Automatic attempt ID reused with different input')
                return dict(run_id=run_id, character_id=run['character_id'], session_id=run['session_id'],
                            switched=False, record=saved, duplicate=True)
            streamer = self.db.execute('SELECT * FROM streamers WHERE id=?', (run['streamer_id'],)).fetchone()
            session = self.store._open_session(streamer['id'])
            if not session or session['id'] != run['session_id'] or streamer['selected_character_id'] != run['character_id']:
                raise ValueError('Automatic attribution assignment changed')
            selected = self.db.execute('SELECT label FROM characters WHERE id=?', (run['character_id'],)).fetchone()[0]
            reference=record.get('character_name',{}).get('suggestion',{}).get('reference_name')
            if reference is not None and not same_character_name(reference, selected):
                raise ValueError('Character identity reference changed; restart after a rename or selection')
            login = streamer['login']
            from .automatic_adoption import state, save_state
            adopted = state(self.store, streamer['id'])
            from .streamer_roster import discovery_state, save_identity
            discovery = None if adopted else discovery_state(self.store,streamer['id'])
            adopted = adopted or discovery
            identity_scope = 'roster_identity_scope' if discovery else 'existing_adoption_id'
            identity_tag = (adopted.get('scope_id') or adopted.get('adoption_id')) if adopted else None
            previous = self.db.execute('''SELECT a.payload_json FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
                WHERE r.streamer_id=? AND r.session_id=? ORDER BY a.id DESC LIMIT 1''',
                (streamer['id'],run['session_id'])).fetchone()
            previous = original(json.loads(previous[0])) if previous else None
            # Initial adoption cannot use pre-adoption/manual frames as identity votes.
            if adopted and not adopted['verified'] and (previous or {}).get(identity_scope) != identity_tag:
                previous = None
            current_name, prior_name = name_evidence(record), name_evidence(previous or {})
            switch = bool(current_name and not same_character_name(current_name['name'], selected) and prior_name
                          and same_character_name(prior_name['name'], current_name['name']) and independent(prior_name, current_name))
            summary = None
            target, target_session, target_run = run['character_id'], run['session_id'], run_id
            result = deepcopy(record)
            result['automation_input_sha256'] = digest
            if adopted:
                result[identity_scope] = identity_tag
            if switch:
                target_label = current_name['name']
                found = self.db.execute('SELECT id,label FROM characters WHERE streamer_id=? AND label=? COLLATE NOCASE ORDER BY id LIMIT 1', (streamer['id'], target_label)).fetchone()
                if found:target_label = found['label']
                count = self.db.execute('SELECT COUNT(*) FROM characters WHERE streamer_id=?', (streamer['id'],)).fetchone()[0]
                if not found and count >= MAX_AUTOMATIC_CHARACTERS:
                    switch = False  # Keep the existing mismatch hold; this exceptional case needs an operator.
                elif found and found[0] in self.store.invalidated_characters(streamer['id']):
                    switch = False  # An operator ruled this name out (e.g. another player's video): its frames stay held.
                else:
                    count = self.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?', (run_id,)).fetchone()[0]
                    if record['index'] != count + 1: raise ValueError('Automatic switch attempt order changed')
                    when = datetime.fromisoformat(record['received_at'])
                    summary = dict(type='summary', trusted=False, attempts=count, interrupted=False,
                                   completion_reason='automatic_character_switch', next_run_id=following)
                    self.diagnostics._append(run_id, summary)
                    target = found['id'] if found else self.store.add_character(login, target_label)
                    self.store.select_character(login, target, at=when)
                    target_session = self.store.start_session(login, at=when, expected_character_id=target)
                    configuration = dict(configuration, start_reason='automatic_character_switch',
                                         previous_run_id=run_id, automatic_decision_id=event)
                    binding = self.diagnostics._begin(following, login, configuration)
                    target_run = binding['run_id']
                    result['index'] = 1
                    result['automatic_selection'] = dict(event_id=event, previous_run=run_id,
                        previous_character_id=run['character_id'], character_id=target, name=target_label,
                        previous_attempt_index=record['index'], evidence=[prior_name, current_name], visible_feed_association=True)
                    name = result['character_name']
                    name['previous_attribution_decision'] = {k: deepcopy(name.get(k)) for k in ('hold_reasons', 'identity_conflict')}
                    name.update(reading_hold_recommended=False, hold_reasons=[], identity_conflict=None,
                                tracking_action='automatic_character_switch')
            # A known mismatch remains a risk through unreadable frames and process restarts.
            observed = result.get('character_name', {}).get('evidence', {}).get('name')
            risk = adopted['risk'] if adopted else (previous or {}).get('automatic_identity_risk')
            if switch or current_name and same_character_name(current_name['name'], selected):
                risk = None
            elif observed and not same_character_name(observed, selected):
                risk = observed
            result['automatic_identity_risk'] = risk
            if risk and result.get('current'):
                name = result['character_name']
                name['reading_hold_recommended'] = True
                name['hold_reasons'] = list(dict.fromkeys(name.get('hold_reasons', []) + ['unresolved_name_mismatch']))
            confirmed_adoption = bool(adopted and not adopted['verified'] and (switch or
                current_name and prior_name and same_character_name(current_name['name'], prior_name['name']) and same_character_name(current_name['name'], selected)
                and independent(prior_name, current_name)))
            if adopted and not adopted['verified'] and not confirmed_adoption and result.get('current'):
                name = result.setdefault('character_name', {})
                name['reading_hold_recommended'] = True
                name['hold_reasons'] = list(dict.fromkeys(name.get('hold_reasons', []) +
                    ['character_discovery_pending' if discovery else 'adoption_name_confirmation_pending']))
            if selected==PLACEHOLDER_CHARACTER and not switch and result.get('current'):
                name=result.setdefault('character_name',{})
                name['reading_hold_recommended']=True
                name['hold_reasons']=list(dict.fromkeys(name.get('hold_reasons',[])+['character_discovery_pending']))
            result = identity_held(result)
            # Level proof may use the first B frame, but its EXP is never moved out of A's held run.
            support = level_evidence(previous) if (switch or confirmed_adoption) and previous else None
            result = guard_level(self.store, target, result, support=support)
            self.diagnostics._append(target_run, result)
            result = json.loads(self.db.execute('SELECT payload_json FROM diagnostic_attempts WHERE run_id=? AND attempt_index=?',
                                               (target_run, result['index'])).fetchone()[0])
            if not switch and current_name and same_character_name(current_name['name'], selected):  # A job read counts only for the named character.
                try:
                    confirm_job(self.store, target, result)
                except Exception as error:  # The job is a bonus: it must never stop this capture from being saved.
                    print(f'job not recorded for character {target}: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
            receipt = dict(run_id=target_run, character_id=target, session_id=target_session,
                           name=target_label if switch else selected, switched=switch,
                           summary=summary, configuration=configuration if switch else None)
            if switch:
                receipt.update(decision=result.get('automatic_selection') or original(result)['automatic_selection'],
                               selected_at=record['received_at'])
                self.db.execute('INSERT INTO automatic_character_events VALUES(?,?,?,?,?,?,?)',
                    (event, digest, streamer['id'], target, target_run, encoded(dict(type='receipt',trusted=False,**receipt)), utc()))
            if adopted:
                adopted['started'] = True
                if confirmed_adoption:
                    adopted.update(verified=True, verification=dict(run_id=target_run, index=result['index'],
                        evidence=[prior_name, current_name]))
                adopted['risk'] = risk
                (save_identity if discovery else save_state)(self.store, streamer['id'], adopted)
            if write: write(receipt, result)
            return dict(**receipt, record=result, duplicate=False)
