"""Explicit, preview-bound adoption of an owned tracker; never called to adopt at startup."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile

from .floor_repair import database_digest, digest
from .schema import MIGRATION_10, VERSION
from .store import Store, utc
from .writer_lock import writer_lease

APP = 'multi_alpha_v1'
STATE_PREFIX = 'existing-auto-state:'


def marker(path):
    return path.with_suffix(path.suffix + '.multi-alpha.json')


def ownership(path):
    if not path.is_file() or path.stat().st_nlink > 1:
        raise ValueError('adoption requires an existing, non-hard-linked database')
    try:
        info = json.loads(marker(path).read_text(encoding='utf-8'))
    except PermissionError:
        raise ValueError('cannot read ownership marker; another coordinator may own this database') from None
    if (not isinstance(info, dict) or info.get('application') != APP or
            info.get('live_twitch_trial') or info.get('automatic_characters')):
        raise ValueError('existing adoption requires an ordinary owned multi-alpha database, not a trial')
    return info


def states(store):
    # Reserved rows hold bounded per-channel state; adoption/switch receipts stay immutable.
    if store.schema_version < 10:
        return {}
    return {r['login']: json.loads(r['receipt_json']) for r in store.db.execute('''
        SELECT s.login,e.receipt_json FROM automatic_character_events e JOIN streamers s ON s.id=e.streamer_id
        WHERE e.event_id LIKE 'existing-auto-state:%' ''')}


def state(store, streamer):
    row = store.db.execute('SELECT receipt_json FROM automatic_character_events WHERE event_id=?',
                           (STATE_PREFIX + str(streamer),)).fetchone()
    return json.loads(row[0]) if row else None


def save_state(store, streamer, value):
    store.db.execute('UPDATE automatic_character_events SET receipt_json=?,recorded_at=? WHERE event_id=?',
                     (json.dumps(value, sort_keys=True), utc(), STATE_PREFIX + str(streamer)))


def validate(store, mappings, reason):
    if store.schema_version not in (9, 10) or VERSION != 10:
        raise ValueError('existing adoption supports schema 9 or 10 only')
    if (not isinstance(reason, str) or not 12 <= len(reason.strip()) <= 1000 or
            any(ord(c) < 32 for c in reason)):
        raise ValueError('provide a meaningful single-line adoption reason (12..1000 characters)')
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= 25:
        raise ValueError('review 1..25 explicit channel/character/name mappings')
    seen = set()
    approved = states(store)
    for m in mappings:
        if not isinstance(m, dict) or set(m) != {'channel', 'character_id', 'character', 'name'}:
            raise ValueError('mapping needs exactly channel, character_id, character and name')
        login, cid, label, name = (m[k] for k in ('channel', 'character_id', 'character', 'name'))
        if (not isinstance(login, str) or not re.fullmatch('[a-z0-9_]{1,25}', login) or login in seen or
                type(cid) is not int or cid < 1 or not isinstance(label, str) or
                not isinstance(name, str) or not re.fullmatch('[A-Za-z][A-Za-z0-9]{1,11}', name) or name == 'PendingOCR'):
            raise ValueError('invalid or duplicate channel/character/name mapping')
        seen.add(login)
        if login in approved:
            raise ValueError(f'{login} is already adopted; do not remap historical identity')
        s = store._channel(login)
        c = store.db.execute('SELECT * FROM characters WHERE id=? AND streamer_id=?', (cid, s['id'])).fetchone()
        if not c or c['label'] != label or s['selected_character_id'] != cid:
            raise ValueError('mapping must match the exact currently selected channel, character ID and label')
        if store.db.execute('SELECT 1 FROM characters WHERE streamer_id=? AND label=? AND id!=?', (s['id'], name, cid)).fetchone():
            raise ValueError('recognized name already belongs to another saved character; histories cannot be merged')


def change(store, plan, backup_hash):
    if store.schema_version == 9:
        for statement in MIGRATION_10:
            store.db.execute(statement)
        store.db.execute('PRAGMA user_version=10')
        store.schema_version = 10
    for m in plan['mappings']:
        login, cid = m['channel'], m['character_id']
        sid = store._channel(login)['id']
        if m['character'] != m['name']:
            store.rename_character(login, cid, m['name'], reason=f"Automatic adoption {plan['fingerprint']}: {plan['reason']}")
        event = 'existing-adoption:' + plan['fingerprint'] + ':' + login
        receipt = dict(type='existing_tracker_adoption', mapping=m, reason=plan['reason'],
                       preview_sha256=plan['fingerprint'], backup_sha256=backup_hash,
                       original_marker=plan['marker'], original_schema=plan['schema'])
        store.db.execute('INSERT INTO automatic_character_events VALUES(?,?,?,?,?,?,?)',
                         (event, plan['fingerprint'], sid, cid, 'operator-adoption', json.dumps(receipt), utc()))
        value = dict(type='existing_tracker_state', adoption_id=event, character_id=cid,
                     name=m['name'], started=False, verified=False, risk=None)
        store.db.execute('INSERT INTO automatic_character_events VALUES(?,?,?,?,?,?,?)',
                         (STATE_PREFIX + str(sid), plan['fingerprint'], sid, cid, 'operator-adoption', json.dumps(value), utc()))
    if store.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or store.db.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('post-adoption integrity check failed')


def preview(path, mappings, reason):
    path = Path(path).resolve(strict=True)
    info = ownership(path)
    with Store(path, read_only=True) as source, source._transaction():
        validate(source, mappings, reason)
        plan = dict(version=1, database=str(path), marker=info, schema=source.schema_version,
                    mappings=mappings, reason=reason, state_sha256=database_digest(source))
        plan['preserved'] = []
        for m in mappings:
            cid = m['character_id']
            floor = source.db.execute('SELECT * FROM character_level_guard WHERE character_id=?', (cid,)).fetchone() if source.schema_version == 10 else None
            plan['preserved'].append(dict(character_id=cid, validated_floor=dict(floor) if floor else None,
                tracking_state=dict(source.db.execute('SELECT * FROM tracking_state WHERE character_id=?', (cid,)).fetchone()),
                counts={table: source.db.execute(f'SELECT COUNT(*) FROM {table} WHERE character_id=?', (cid,)).fetchone()[0]
                    for table in ('sessions','observations','diagnostic_runs','manual_corrections','retention_state','daily_character_exp')}))
        plan['fingerprint'] = digest(plan)
        # Rehearse migration/renames against this exact snapshot, without touching the source.
        with tempfile.TemporaryDirectory(prefix='exp-adoption-') as directory:
            copied = Path(directory) / 'review.sqlite3'
            with closing(sqlite3.connect(copied)) as target:
                source.db.backup(target)
            with Store(copied) as rehearsal, rehearsal._transaction():
                change(rehearsal, plan, '0' * 64)
        return plan


def confirmation(plan):
    return 'adopt-existing:' + plan['fingerprint'][:16]


def apply(path, plan, *, confirm, backup):
    path, backup = Path(path).resolve(strict=True), Path(backup).resolve()
    if (not isinstance(plan, dict) or plan.get('version') != 1 or plan.get('database') != str(path) or
            digest({k: v for k, v in plan.items() if k != 'fingerprint'}) != plan.get('fingerprint')):
        raise ValueError('preview is modified or belongs to another database')
    if confirm != confirmation(plan):
        raise ValueError('supply the exact confirmation token from preview')
    info = ownership(path)
    with writer_lease(marker(path)) as handle:
        if json.load(handle) != info or info != plan['marker']:
            raise ValueError('ownership changed since preview')
        # No Store writer constructor: schema migration must share the adoption transaction.
        with Store(path, read_only=True) as store:
            store.db.close()
            store.db = sqlite3.connect(path, isolation_level=None, timeout=0)
            store.db.row_factory = sqlite3.Row
            store.db.execute('PRAGMA foreign_keys=ON')
            if store.db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                raise ValueError('adoption requires the existing WAL database; no journal conversion is performed')
            store.read_only = False
            store.db.execute('BEGIN EXCLUSIVE')
            try:
                event = 'existing-adoption:' + plan['fingerprint'] + ':' + plan['mappings'][0]['channel']
                if store.schema_version == 10 and store.db.execute('SELECT 1 FROM automatic_character_events WHERE event_id=?', (event,)).fetchone():
                    return dict(duplicate=True, adoption=plan['fingerprint'])
                if database_digest(store) != plan['state_sha256']:
                    raise ValueError('stale preview: stop writers, then create and review a new preview')
                validate(store, plan['mappings'], plan['reason'])
                # A second read-only connection backs up the committed snapshot while we exclude writers.
                with backup.open('xb'):
                    pass
                with Store(path, read_only=True) as source, closing(sqlite3.connect(backup)) as target:
                    source.db.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or target.execute('PRAGMA foreign_key_check').fetchone():
                        raise ValueError('backup integrity check failed')
                with Store(backup, read_only=True) as saved:
                    if database_digest(saved) != plan['state_sha256']:
                        raise ValueError('backup does not match reviewed snapshot')
                with backup.open('rb') as saved_file:
                    backup_hash = hashlib.file_digest(saved_file, 'sha256').hexdigest()
                change(store, plan, backup_hash)
                store.db.execute('COMMIT')
                return dict(duplicate=False, adoption=plan['fingerprint'], backup=str(backup), backup_sha256=backup_hash)
            finally:
                if store.db.in_transaction:
                    store.db.execute('ROLLBACK')


def snapshot(path, output):
    """Read-only source, consistent SQLite snapshot plus its unchanged ownership marker."""
    path, output = Path(path).resolve(strict=True), Path(output).resolve()
    info = ownership(path)
    if output.exists() or marker(output).exists():
        raise ValueError('snapshot destination and marker must be NEW')
    with output.open('xb'):
        pass
    with Store(path, read_only=True) as source, closing(sqlite3.connect(output)) as target:
        source.db.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or target.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('snapshot integrity check failed')
    with marker(output).open('x', encoding='utf-8') as out:
        json.dump(info, out)
    return dict(snapshot=str(output), source_modified=False)
