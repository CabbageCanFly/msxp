"""Exceptional, preview-bound offline recovery; never called by capture/ingestion."""
from contextlib import closing, nullcontext
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from .diagnostics import Diagnostics
from .models import same_character_name
from .invalidations import Invalidations, MAX_SELECTION, validate_reason
from .schema import VERSION, MIGRATION_10
from .store import Store, utc
from .writer_lock import writer_lease


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def database_digest(store):
    result = hashlib.sha256(str(store.schema_version).encode())
    for line in store.db.iterdump():
        result.update(line.encode())
        result.update(b'\n')
    return result.hexdigest()


def owner(store, channel, cid, label):
    sid = Invalidations(store).owner(channel, cid)
    actual = store.db.execute('SELECT label FROM characters WHERE id=?', (cid,)).fetchone()[0]
    if actual != label or store._channel(channel)['selected_character_id'] != cid:
        raise ValueError('exact character ID/name must match the currently selected character')
    return sid


def validate(store, plan):
    if store.schema_version not in (10,11) or VERSION not in (10,11):
        raise ValueError('floor repair requires schema 10 or 11; review the recovery tool before using another schema')
    cid = plan['character_id']
    owner(store, plan['channel'], cid, plan['character'])
    trigger = store.db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='character_level_no_regression'").fetchone()
    if not trigger or ' '.join(trigger[0].split()).lower() != ' '.join(MIGRATION_10[-1].split()).lower():
        raise ValueError('normal monotone level trigger is missing or changed')
    # shortcut: refuse all compacted history, until frozen-history repair has its own audited workflow.
    for sql in ('SELECT 1 FROM retention_state WHERE character_id=?',
                'SELECT 1 FROM daily_character_exp WHERE character_id=?',
                'SELECT 1 FROM trusted_checkpoints WHERE session_id IN (SELECT id FROM sessions WHERE character_id=?)'):
        if store.db.execute(sql, (cid,)).fetchone():
            raise ValueError('expired or frozen character history cannot be repaired safely by this tool; no changes made')
    level, exp, bp = plan['level'], plan['exp'], plan['percentage_bp']
    if type(level) is not int or not 1 <= level <= 200 or type(exp) is not int or not 0 <= exp < 2**63:
        raise ValueError('level must be 1..200 and EXP a nonnegative SQLite integer')
    if bp is not None and (type(bp) is not int or not 0 <= bp <= 9999):
        raise ValueError('percentage must be 0.00..99.99')
    from .manual import corrected_reading
    if corrected_reading(dict(level=level, current_exp=exp, percentage_bp=bp, event_id='preview',
                              effective_at=plan['at'], id=0))['exp_validity']['status'] == 'invalid':
        raise ValueError('corrected EXP/percentage contradicts the proposed level')
    validate_reason(plan['reason'])
    if not 15 <= len(plan['reason'].strip()) <= 250 or len(plan['reason'].split()) < 3:
        raise ValueError('repair reason must explain the reviewed error in 15..250 characters (at least three words)')
    since, at = (datetime.fromisoformat(plan[k]) for k in ('since', 'at'))
    if not utc(since) < utc(at) <= utc():
        raise ValueError('review start must precede the corrected baseline, which cannot be in the future')
    floor = store.db.execute('SELECT * FROM character_level_guard WHERE character_id=?', (cid,)).fetchone()
    if not floor or floor['level'] is None or floor['level'] <= level:
        raise ValueError('repair must lower an existing validated floor')
    try:proof = json.loads(floor['proof_json'])
    except (TypeError, ValueError):raise ValueError('floor proof is missing or invalid; no safe repair evidence') from None
    if not isinstance(proof, dict) or not proof.get('received_at') or proof.get('level') != floor['level']:
        raise ValueError('floor proof is missing or ambiguous')
    if proof.get('support') is not None and not isinstance(proof['support'], dict):
        raise ValueError('floor support evidence is ambiguous')
    for item in (proof, proof.get('support') or {}):
        if item.get('received_at') and datetime.fromisoformat(item['received_at']) < since:
            raise ValueError('review period omits the original floor/support evidence')
    from .character_automation import original, independent, level_evidence, NAMED_LEVEL_UP_SECONDS
    from .diagnostic_evidence import CONFIRM_GAP_SECONDS
    history = store.manual_history(plan['channel'], character_id=cid)
    events = [e for e in history if e['active']]
    corrected = {(e['target_kind'], e['target_event_id']) for e in events if e['kind']=='point' and
                 e['level'] is not None and e['level'] <= level and corrected_reading(e)['exp_validity']['status'] != 'invalid'}
    latest = since
    retained_proofs = set()
    sources = []
    for row in store.db.execute('''SELECT a.payload_json,a.run_id||':'||a.attempt_index AS identity,COALESCE(a.received_at,a.attempted_at) AS stamp
            ,r.character_id FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
            WHERE r.streamer_id=?''', (store._channel(plan['channel'])['id'],)):
        raw = original(json.loads(row['payload_json']))
        stamp = datetime.fromisoformat(row['stamp'])
        hashes = (raw.get('frame_sha256'), (raw.get('character_name', {}).get('evidence') or {}).get('pixel_sha256'))
        retained_proofs.update((stamp, h) for h in hashes if h)
        if row['character_id'] != cid: continue
        claims = (raw.get('visual_level'), (raw.get('neural_level') or {}).get('level'),
                  (raw.get('level_policy') or {}).get('validated_level'),
                  (level_evidence(dict(raw, current=True)) or {}).get('level'))
        latest = max(latest, stamp, datetime.fromisoformat(raw['attempted_at']))
        if any(v is not None and v > level for v in claims) and stamp < since:
            raise ValueError('review period omits earlier conflicting diagnostic evidence')
        if any(v is not None and v > level for v in claims) and stamp >= since and ('diagnostic',row['identity']) not in corrected:
            sources.append(['diagnostic',row['identity']])
    for row in store.db.execute('SELECT id,level,observed_at FROM observations WHERE character_id=?', (cid,)):
        stamp = datetime.fromisoformat(row['observed_at']); latest = max(latest, stamp)
        if row['level'] is not None and row['level'] > level and stamp < since:
            raise ValueError('review period omits earlier conflicting observation evidence')
        if row['level'] is not None and row['level'] > level and stamp >= since and ('observation',str(row['id'])) not in corrected:
            sources.append(['observation',str(row['id'])])
    if proof.get('event_id'):
        if not any(e['event_id'] == proof['event_id'] and e['level'] == floor['level'] and
                   datetime.fromisoformat(e['effective_at']) == datetime.fromisoformat(proof['received_at']) for e in history):
            raise ValueError('original manual floor proof is unavailable; refusing a guard-only repair')
    else:
        support = proof.get('support') or {}
        named_pair=(proof.get('basis')==support.get('basis')=='named_normal_level_up'
            and proof.get('session_id') is not None and proof['session_id']==support.get('session_id')
            and same_character_name(proof.get('name'),plan['character'])
            and same_character_name(support.get('name'),plan['character']))
        if (not support.get('received_at') or not support.get('pixel_sha256') or
                support.get('level') != floor['level'] or not independent(support, proof,
                    max_seconds=NAMED_LEVEL_UP_SECONDS if named_pair else CONFIRM_GAP_SECONDS) or
                not all((datetime.fromisoformat(p['received_at']), p.get('pixel_sha256')) in retained_proofs
                        for p in (proof, support))):
            raise ValueError('original independent floor frames are unavailable; refusing a guard-only repair')
    for event in events:
        stamp = datetime.fromisoformat(event['effective_at']); latest = max(latest, stamp)
        if event['level'] is not None and event['level'] > level and stamp < since:
            raise ValueError('review period omits a conflicting manual assertion')
    for row in store.db.execute('SELECT started_at,ended_at FROM sessions WHERE streamer_id=?', (store._channel(plan['channel'])['id'],)):
        latest = max(latest, *(datetime.fromisoformat(v) for v in row if v))
    for row in store.db.execute('SELECT last_event_at FROM tracking_state WHERE character_id=? AND last_event_at IS NOT NULL', (cid,)):
        latest = max(latest, datetime.fromisoformat(row[0]))
    if at <= latest:
        raise ValueError('corrected baseline must follow all recorded activity and session boundaries')
    manuals = [e for e in events if datetime.fromisoformat(e['effective_at']) >= since and e['level'] is not None and
               (e['level'] > level or corrected_reading(e)['exp_validity']['status']=='invalid')]
    return dict(floor), manuals, sorted(sources)


def retract(store, plan):
    for event in plan['manual_assertions']:
        store.retract_manual(plan['channel'], f"{plan['repair_id']}:undo:{event['id']}", event['id'],
                             reason=f"Floor repair {plan['fingerprint']}: {plan['reason']}")


def selection(store, plan):
    return Invalidations(store).selection(plan['channel'], plan['character_id'],
        dict(action='invalidate', start=plan['since'], end=plan['at'], only=plan['sources']))


def change(store, plan, backup_sha256):
    """Caller holds the outer exclusive transaction; nested audit APIs use savepoints."""
    channel, cid, event = plan['channel'], plan['character_id'], plan['repair_id']
    retract(store, plan)
    service = Invalidations(store)
    rows, fingerprint = selection(store, plan)
    if [service.original(r) for r in rows] != plan['affected_readings']:
        raise ValueError('affected evidence changed since preview')
    batch = service.commit(channel, cid, event + ':invalidate',
        dict(action='invalidate', start=plan['since'], end=plan['at'], only=plan['sources']), fingerprint,
        f"Floor repair {plan['fingerprint']}: {plan['reason']}") if any(r['selected'] for r in rows) else None
    for run in store.db.execute('SELECT run_id FROM diagnostic_runs WHERE character_id=? AND summary_json IS NULL', (cid,)).fetchall():
        count = store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?', (run[0],)).fetchone()[0]
        Diagnostics(store)._append(run[0], dict(type='summary', trusted=False, attempts=count, interrupted=False,
                                               completion_reason='operator_floor_repair'))
    when = datetime.fromisoformat(plan['at'])
    store.end_session(channel, at=when)
    session = store.start_session(channel, at=when, expected_character_id=cid)
    audit = dict(repair='level_floor_v1', preview_sha256=plan['fingerprint'],
                 superseded_level=plan['old_guard']['level'], superseded_guard_sha256=digest(plan['old_guard']),
                 superseded_proof_sha256=digest(json.loads(plan['old_guard']['proof_json'])),
                 backup_sha256=backup_sha256, invalidation_batch=batch['id'] if batch else None, reason=plan['reason'])
    # Deliberate exceptional replacement: keep the normal monotone UPDATE trigger installed.
    store.db.execute('DELETE FROM character_level_guard WHERE character_id=?', (cid,))
    baseline = store.correct_manual(channel, event, cid, level=plan['level'], current_exp=plan['exp'],
        percentage_bp=plan['percentage_bp'], effective_at=when, session_id=session, reason=json.dumps(audit, sort_keys=True, ensure_ascii=False))
    proof = dict(audit, level=plan['level'], received_at=plan['at'], basis='manual_admin_repair', event_id=event)
    store.db.execute('INSERT INTO character_level_guard VALUES(?,?,?,?,?)', (cid, plan['level'], json.dumps(proof), None, utc()))
    if store.db.execute('PRAGMA foreign_key_check').fetchone() or store.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('post-repair SQLite integrity check failed')
    return dict(repair_id=event, character_id=cid, session_id=session, level=plan['level'], baseline_id=baseline['id'],
                audit=audit, duplicate=False)


def preview(path, channel, cid, label, *, level, exp, percentage_bp, since, at, reason):
    path = path.resolve(strict=True)
    if path.stat().st_nlink > 1: raise ValueError('hard-linked databases have unsafe WAL/lease aliases; use a SQLite backup copy')
    plan = dict(version=1, database=str(path.resolve()), channel=channel.lower(), character_id=cid, character=label,
                level=level, exp=exp, percentage_bp=percentage_bp, since=utc(since), at=utc(at), reason=reason)
    with Store(path, read_only=True) as source, source._transaction():
        old, manuals, sources = validate(source, plan)
        plan.update(old_guard=old, old_proof=json.loads(old['proof_json']),
                    old_guard_sha256=digest(old), old_proof_sha256=digest(json.loads(old['proof_json'])),
                    manual_assertions=manuals, sources=sources, state_sha256=database_digest(source),
                    fingerprint='preview', repair_id='floor-repair:preview')
        with tempfile.TemporaryDirectory(prefix='exp-floor-review-') as directory:
            copied = Path(directory) / 'review.sqlite3'
            with closing(sqlite3.connect(copied)) as target: source.db.backup(target)
            with Store(copied) as rehearsal:
                with rehearsal._transaction():
                    retract(rehearsal, plan)
                    rows, _ = selection(rehearsal, plan)
                    if len(rows) + len(manuals) > MAX_SELECTION or not rows and not manuals:
                        raise ValueError('no retained evidence to repair, or review exceeds the bounded selection limit')
                    plan['affected_readings'] = [Invalidations(rehearsal).original(r) for r in rows]
                # Reopen the untouched snapshot before rehearsing the complete atomic operation.
            with closing(sqlite3.connect(copied)) as target: source.db.backup(target)
            del plan['fingerprint'], plan['repair_id']
            plan['fingerprint'] = digest(plan)
            plan['repair_id'] = 'floor-repair:' + plan['fingerprint']
            with Store(copied) as rehearsal, rehearsal._transaction():
                change(rehearsal, plan, '0' * 64)
    return plan


def confirmation(plan):
    return f"repair:{plan['channel']}:{plan['character_id']}:{plan['old_guard']['level']}->{plan['level']}:{plan['fingerprint'][:12]}"


def apply(path, channel, cid, label, plan, *, confirm, backup):
    path = path.resolve(strict=True)
    if path.stat().st_nlink > 1: raise ValueError('hard-linked databases have unsafe WAL/lease aliases; use a SQLite backup copy')
    contents = {k: v for k, v in plan.items() if k not in ('fingerprint', 'repair_id')}
    if (plan['version'] != 1 or digest(contents) != plan['fingerprint'] or
            plan['repair_id'] != 'floor-repair:' + plan['fingerprint'] or
            (str(path.resolve()), channel.lower(), cid, label) !=
            (plan['database'], plan['channel'], plan['character_id'], plan['character'])):
        raise ValueError('preview does not match this database/channel/character or has been modified')
    if confirm != confirmation(plan): raise ValueError('supply the exact confirmation token from the preview')
    marker = path.with_suffix(path.suffix + '.multi-alpha.json')
    with (writer_lease(marker) if marker.exists() else nullcontext()) as handle:
        if handle:
            info = json.load(handle)
            if not isinstance(info, dict) or info.get('application') != 'multi_alpha_v1':
                raise ValueError('not a multi-alpha database marker')
        # Opening Store read-only first prevents implicit migration before backup/locking.
        with Store(path, read_only=True) as store:
            if store.schema_version not in (10,11): raise ValueError('floor repair requires schema 10 or 11')
            store.db.close()
            store.db = sqlite3.connect(path, timeout=0, isolation_level=None)
            store.db.row_factory = sqlite3.Row
            store.db.execute('PRAGMA foreign_keys=ON')
            if store.db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                raise ValueError('repair requires the existing WAL database; no journal conversion is performed')
            store.read_only = False
            store.db.execute('BEGIN EXCLUSIVE')
            try:
                existing = store.db.execute('SELECT * FROM manual_corrections WHERE streamer_id=? AND event_id=?',
                    (store._channel(channel)['id'], plan['repair_id'])).fetchone()
                if existing:
                    audit = json.loads(existing['reason'])
                    if (existing['character_id'] != cid or existing['level'] != plan['level'] or
                            audit.get('repair') != 'level_floor_v1' or audit.get('preview_sha256') != plan['fingerprint']):
                        raise ValueError('repair retry identity conflicts with an existing manual event')
                    return dict(repair_id=plan['repair_id'], character_id=cid, session_id=existing['session_id'],
                                baseline_id=existing['id'], audit=audit, duplicate=True)
                if database_digest(store) != plan['state_sha256']:
                    raise ValueError('stale preview: database changed; create and review a new preview')
                floor, manuals, sources = validate(store, plan)
                if floor != plan['old_guard'] or manuals != plan['manual_assertions'] or sources != plan['sources']:
                    raise ValueError('floor or manual assertions do not match the reviewed evidence')
                with backup.open('xb'):
                    pass
                with Store(path, read_only=True) as source, closing(sqlite3.connect(backup)) as target:
                    source.db.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or target.execute('PRAGMA foreign_key_check').fetchone():
                        raise ValueError('backup integrity check failed')
                with Store(backup, read_only=True) as saved:
                    if database_digest(saved) != plan['state_sha256']: raise ValueError('backup does not match reviewed state')
                with backup.open('rb') as saved_file:
                    backup_hash = hashlib.file_digest(saved_file, 'sha256').hexdigest()
                result = change(store, plan, backup_hash)
                store.db.execute('COMMIT')
                return dict(result, backup=str(backup.resolve()))
            finally:
                if store.db.in_transaction: store.db.execute('ROLLBACK')


def arguments(command):
    from .manual_admin import timestamp, percentage
    modes = command.add_subparsers(dest='repair_mode', required=True)
    for name in ('preview', 'apply'):
        mode = modes.add_parser(name)
        mode.add_argument('--character-id', type=int, required=True)
        mode.add_argument('--character', required=True, help='Exact currently selected character name')
        mode.add_argument('--preview', type=Path, required=True, help='Private JSON review file (new file for preview)')
        if name == 'preview':
            mode.add_argument('--since', type=timestamp, required=True, help='First erroneous evidence to quarantine, inclusive')
            mode.add_argument('--at', type=timestamp, required=True, help='Corrected baseline after all recorded activity')
            mode.add_argument('--level', type=int, required=True)
            mode.add_argument('--exp', type=int, required=True)
            mode.add_argument('--percentage', type=percentage)
            mode.add_argument('--reason', required=True)
        else:
            mode.add_argument('--confirm', required=True, help='Exact repair token printed by preview; stop all writers first')
            mode.add_argument('--backup', type=Path, required=True, help='New consistent SQLite backup; never overwritten')


def run(args):
    if args.repair_mode == 'preview':
        plan = preview(args.db, args.channel, args.character_id, args.character, level=args.level, exp=args.exp,
                       percentage_bp=args.percentage, since=args.since, at=args.at, reason=args.reason)
        with args.preview.open('x', encoding='utf-8') as output: json.dump(plan, output, indent=2, allow_nan=False)
        return dict(preview=plan, confirmation=confirmation(plan), warning='Stop all database writers; rehearse on a private copy first.')
    with args.preview.open(encoding='utf-8') as source: plan = json.load(source)
    if not isinstance(plan, dict): raise ValueError('malformed repair preview')
    try:
        return apply(args.db, args.channel, args.character_id, args.character, plan, confirm=args.confirm, backup=args.backup)
    except (KeyError, TypeError) as error:
        raise ValueError('malformed repair preview') from error
