"""Opt-in autonomous attribution. All mutations run on the serialized Store writer."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math

from .diagnostic_evidence import project, consistency, full_reading, CONFIRM_GAP_SECONDS, NEURAL_SEED_SCORE
from .diagnostics import Diagnostics, HELD_ENVELOPE, encoded, identity_held
from .manual import active
from .shadow_view import observation
from .store import utc

MAX_AUTOMATIC_CHARACTERS = 16


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
            or not isinstance(name, str) or not name.isascii() or not name.isalnum()
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
    level = projected['experimental_level'].get('value')
    full = full_reading(row)
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
                or row['frame_sha256'], received_at=row['received_at'], basis=projected['experimental_level']['status'])


def level_held(record, reason, floor):
    return {**{k: record[k] for k in HELD_ENVELOPE if k in record},
            'status': 'unavailable', 'current': False, 'reasons': [],
            'level_hold': dict(reason=reason, validated_level=floor,
                               evidence={k: v for k, v in record.items() if k not in HELD_ENVELOPE})}


def guard_level(store, character, record, *, support=None):
    """Persistent monotone floor; two independent arithmetically supported frames advance it."""
    if 'level_hold' in record and record.get('current') is False:
        return record
    if not record.get('current'):
        store.db.execute('UPDATE character_level_guard SET pending_json=NULL WHERE character_id=? AND pending_json IS NOT NULL', (character,))
        return record
    # A saved policy receipt can predate today's floor; only exact stored retries bypass validation.
    record = {k:v for k,v in record.items() if k!='level_policy'}
    row = store.db.execute('SELECT * FROM character_level_guard WHERE character_id=?', (character,)).fetchone()
    floor = row['level'] if row else None
    pending = json.loads(row['pending_json']) if row and row['pending_json'] else None
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
    qualified = level_evidence(record)
    reason = None
    normalized = observation(record)
    claims = [v for v in (normalized['visual_level'], (normalized.get('neural_level') or {}).get('level'),
                         (qualified or {}).get('level')) if v is not None]
    if floor and any(v < floor for v in claims):
        reason, pending = 'level_regression', None
    elif qualified and (floor is None or qualified['level'] > floor):
        prior = support or pending
        identity_supported=(floor is None or qualified['level']<=floor+1 or
                            qualified['name']==(prior or {}).get('name')==owner['label'])
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
            if reference is not None and reference!=selected:
                raise ValueError('Character identity reference changed; restart after a rename or selection')
            login = streamer['login']
            previous = self.db.execute('''SELECT a.payload_json FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
                WHERE r.streamer_id=? AND r.session_id=? ORDER BY a.id DESC LIMIT 1''',
                (streamer['id'],run['session_id'])).fetchone()
            previous = original(json.loads(previous[0])) if previous else None
            current_name, prior_name = name_evidence(record), name_evidence(previous or {})
            switch = bool(current_name and current_name['name'] != selected and prior_name
                          and prior_name['name'] == current_name['name'] and independent(prior_name, current_name))
            summary = None
            target, target_session, target_run = run['character_id'], run['session_id'], run_id
            result = deepcopy(record)
            result['automation_input_sha256'] = digest
            if switch:
                target_label = current_name['name']
                found = self.db.execute('SELECT id FROM characters WHERE streamer_id=? AND label=?', (streamer['id'], target_label)).fetchone()
                count = self.db.execute('SELECT COUNT(*) FROM characters WHERE streamer_id=?', (streamer['id'],)).fetchone()[0]
                if not found and count >= MAX_AUTOMATIC_CHARACTERS:
                    switch = False  # Keep the existing mismatch hold; this exceptional case needs an operator.
                else:
                    count = self.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?', (run_id,)).fetchone()[0]
                    if record['index'] != count + 1: raise ValueError('Automatic switch attempt order changed')
                    when = datetime.fromisoformat(record['received_at'])
                    summary = dict(type='summary', trusted=False, attempts=count, interrupted=False,
                                   completion_reason='automatic_character_switch', next_run_id=following)
                    self.diagnostics._append(run_id, summary)
                    target = self.store.add_character(login, target_label)
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
            risk = (previous or {}).get('automatic_identity_risk')
            if switch or current_name and current_name['name'] == selected:
                risk = None
            elif observed and observed != selected:
                risk = observed
            result['automatic_identity_risk'] = risk
            if risk and result.get('current'):
                name = result['character_name']
                name['reading_hold_recommended'] = True
                name['hold_reasons'] = list(dict.fromkeys(name.get('hold_reasons', []) + ['unresolved_name_mismatch']))
            result = identity_held(result)
            # Level proof may use the first B frame, but its EXP is never moved out of A's held run.
            support = level_evidence(previous) if switch and previous else None
            result = guard_level(self.store, target, result, support=support)
            self.diagnostics._append(target_run, result)
            result = json.loads(self.db.execute('SELECT payload_json FROM diagnostic_attempts WHERE run_id=? AND attempt_index=?',
                                               (target_run, result['index'])).fetchone()[0])
            receipt = dict(run_id=target_run, character_id=target, session_id=target_session,
                           name=current_name['name'] if switch else selected, switched=switch,
                           summary=summary, configuration=configuration if switch else None)
            if switch:
                receipt.update(decision=result.get('automatic_selection') or original(result)['automatic_selection'],
                               selected_at=record['received_at'])
                self.db.execute('INSERT INTO automatic_character_events VALUES(?,?,?,?,?,?,?)',
                    (event, digest, streamer['id'], target, target_run, encoded(dict(type='receipt',trusted=False,**receipt)), utc()))
            if write: write(receipt, result)
            return dict(**receipt, record=result, duplicate=False)
