"""Database-owned desired capture settings. Admin writes policy; only the coordinator captures."""
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid

from .automatic_adoption import ownership, marker, states, state as adopted_state
from .floor_repair import database_digest, digest
from .schema import MIGRATION_10, MIGRATION_11
from .store import Store, utc
from .video import Source
from .writer_lock import writer_lease

FLAGS = ('authorized','tracking_enabled','public_visible','automatic_characters')
DEFAULTS = dict(interval=20, quality='best', timeout=20, max_age=15, ocr_timeout=10,
                experimental_neural_level=False, save_crops=False)


def ready(store):
    return store.schema_version>=11 and bool(store.db.execute('SELECT 1 FROM streamer_roster_bootstrap').fetchone())


def entry(store, channel):
    if store.schema_version<11:return None
    r=store.db.execute('''SELECT c.*,s.login AS channel,s.selected_character_id FROM streamer_capture c
        JOIN streamers s ON s.id=c.streamer_id WHERE s.login=?''',(channel,)).fetchone()
    if not r:return None
    return dict(channel=r['channel'],streamer_id=r['streamer_id'],origin=r['origin'],revision=r['revision'],
        **{k:bool(r[k]) for k in FLAGS}, **json.loads(r['settings_json']))


def entries(store):
    if not ready(store):raise ValueError('database roster is not initialized; preview and apply JSON bootstrap first')
    return [entry(store,r[0]) for r in store.db.execute('SELECT s.login FROM streamer_capture c JOIN streamers s ON s.id=c.streamer_id ORDER BY s.login')]


def discovery_state(store, streamer):
    if store.schema_version<11:return None
    row=store.db.execute("SELECT identity_json FROM streamer_capture WHERE streamer_id=? AND origin='discovered'",(streamer,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def save_identity(store, streamer, value):
    store.db.execute('UPDATE streamer_capture SET identity_json=? WHERE streamer_id=?',(json.dumps(value),streamer))


def validate_policy(store, value):
    for k in FLAGS+('experimental_neural_level','save_crops'):
        if type(value.get(k)) is not bool:raise ValueError(f'{k} must be an explicit boolean')
    for k,low,high in (('interval',5,300),('timeout',1,30),('max_age',1,30),('ocr_timeout',1,30)):
        n=value.get(k)
        if type(n) not in (int,float) or not math.isfinite(n) or not low<=n<=high:
            raise ValueError(f'{k} must be {low}..{high}')
    if not isinstance(value.get('quality'),str):raise ValueError('quality must be a named Twitch rendition')
    Source('twitch',value['channel'],value['quality']).streamlink_command()  # Syntax only, no network.
    existing=store.db.execute('SELECT id,selected_character_id FROM streamers WHERE login=?',(value['channel'],)).fetchone()
    identity=(adopted_state(store,existing['id']) or discovery_state(store,existing['id'])) if existing and store.schema_version>=10 else None
    if value['automatic_characters']:
        if value['interval']>60:raise ValueError('automatic name confirmation requires interval <=60s')
        if value['origin']=='existing' and not (identity and identity.get('type')=='existing_tracker_state'):
            raise ValueError('historical character identity needs explicit adoption before automatic OCR can be enabled')
    if value['tracking_enabled']:
        if not value['authorized']:raise ValueError('capture authorization is required before enabling tracking')
        if not value['automatic_characters']:
            if value['origin']=='discovered' and not (identity and identity['verified']):
                raise ValueError('unknown character requires automatic recognition before manual tracking')
            if identity and identity['started'] and (not identity['verified'] or identity['risk']):
                raise ValueError('identity is unresolved; enable automatic verification or keep tracking paused')


def preview(store, raw):
    if not ready(store):raise ValueError('initialize the database roster before editing')
    if not isinstance(raw,dict) or raw.keys()-{'action','channel','reason',*FLAGS,*DEFAULTS}:
        raise ValueError('invalid streamer configuration fields')
    action=raw.get('action'); login=raw.get('channel')
    if action not in ('roster_add','roster_update') or not isinstance(login,str) or not re.fullmatch('[A-Za-z0-9_]{1,25}',login):
        raise ValueError('use a Twitch login and a streamer add/update action')
    login=login.lower()
    reason=raw.get('reason','')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000 or any(ord(c)<32 for c in reason):
        raise ValueError('a single-line reason is required')
    before=entry(store,login)
    if action=='roster_add':
        if before:raise ValueError('streamer already has roster settings; edit it instead')
        historical=store.db.execute('SELECT id FROM streamers WHERE login=?',(login,)).fetchone()
        value=dict(channel=login,origin='existing' if historical else 'discovered',authorized=False,tracking_enabled=False,
                   public_visible=True,automatic_characters=not historical,**DEFAULTS)
    else:
        if not before:raise ValueError('streamer is not managed')
        value=dict(before)
    value.update({k:v for k,v in raw.items() if k in FLAGS or k in DEFAULTS})
    validate_policy(store,value)
    plan=dict(event_id='roster:'+uuid.uuid4().hex,channel=login,before=before,after=value,reason=reason)
    plan['fingerprint']=digest(plan)
    return plan


def commit(store, plan):
    if digest({k:v for k,v in plan.items() if k!='fingerprint'})!=plan['fingerprint']:raise ValueError('modified roster preview')
    with store._transaction():
        done=store.db.execute('SELECT * FROM streamer_roster_events WHERE event_id=?',(plan['event_id'],)).fetchone()
        if done:
            if done['fingerprint']!=plan['fingerprint']:raise ValueError('roster decision ID reused')
            return dict(saved=True,duplicate=True,configuration=json.loads(done['after_json']))
        if entry(store,plan['channel'])!=plan['before']:raise ValueError('streamer settings changed since preview; review again')
        value=plan['after']; validate_policy(store,value)
        sid=store.add_channel(plan['channel'])
        revision=(plan['before'] or {}).get('revision',0)+1
        identity=dict(type='character_discovery',scope_id=f'roster-discovery:{sid}',started=False,verified=False,risk=None)
        store.db.execute('''INSERT INTO streamer_capture VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(streamer_id) DO UPDATE SET authorized=excluded.authorized,tracking_enabled=excluded.tracking_enabled,
                public_visible=excluded.public_visible,automatic_characters=excluded.automatic_characters,
                settings_json=excluded.settings_json,revision=excluded.revision,updated_at=excluded.updated_at''',
            (sid,*[int(value[k]) for k in FLAGS],json.dumps({k:value[k] for k in DEFAULTS}),value['origin'],revision,utc(),
             json.dumps(identity) if value['origin']=='discovered' else None))
        after=entry(store,plan['channel'])
        store.db.execute('INSERT INTO streamer_roster_events VALUES(?,?,?,?,?,?,?)',(plan['event_id'],sid,plan['fingerprint'],
            json.dumps(plan['before']),json.dumps(after),plan['reason'],utc()))
        return dict(saved=True,duplicate=False,configuration=after)


def visible(store):
    if not ready(store):return {}
    return {r[0]:bool(r[1]) for r in store.db.execute('''SELECT s.login,COALESCE(c.public_visible,0)
        FROM streamers s LEFT JOIN streamer_capture c ON c.streamer_id=s.id''')}


def status(store):
    rows=entries(store)
    for row in rows:
        s=store._channel(row['channel']); cid=s['selected_character_id']
        character=store.db.execute('SELECT id,label FROM characters WHERE id=?',(cid,)).fetchone()
        runtime=store.db.execute('SELECT * FROM streamer_runtime WHERE streamer_id=?',(s['id'],)).fetchone()
        session=store._open_session(s['id'])
        latest=store.db.execute('''SELECT a.received_at,a.attempted_at FROM diagnostic_attempts a WHERE a.run_id=(
            SELECT run_id FROM diagnostic_runs WHERE session_id=? ORDER BY rowid DESC LIMIT 1) ORDER BY a.id DESC LIMIT 1''',
            (session['id'],)).fetchone() if session else None
        floor=store.db.execute('SELECT level FROM character_level_guard WHERE character_id=?',(cid,)).fetchone()
        row.update(character=dict(character) if character and character['label']!='PendingOCR' else None,
                   identity=adopted_state(store,s['id']) or discovery_state(store,s['id']),runtime=dict(runtime) if runtime else None,
                   validated_level=floor[0] if floor else None,
                   last_capture_at=(latest['received_at'] or latest['attempted_at']) if latest else None)
    return rows


def bootstrap_preview(path, rows, automatic, reason):
    path=Path(path).resolve(strict=True); info=ownership(path)
    if not isinstance(reason,str) or not reason.strip():raise ValueError('bootstrap reason is required')
    if not rows or not set(automatic)<={r['channel'] for r in rows}:
        raise ValueError('choose at least one configured channel and an explicit automatic subset')
    with Store(path,read_only=True) as source, source._transaction():
        if source.schema_version not in (9,10,11) or ready(source):raise ValueError('bootstrap supports schema 9..11 exactly once')
        proposed=[]
        for row in rows:
            if row['source']!='twitch':raise ValueError('database roster currently manages Twitch sources only')
            s=source._channel(row['channel'])
            if s['selected_character_id'] is None:raise ValueError('existing assignment has no selected character; review before bootstrap')
            value=dict(channel=row['channel'],origin='existing',authorized=row.get('authorized',False),
                tracking_enabled=row.get('enabled',True),public_visible=True,automatic_characters=row['channel'] in automatic,
                **{k:row.get(k,v) for k,v in DEFAULTS.items()})
            value['interval']=row.get('interval',15)  # Preserve the legacy capture default during import.
            validate_policy(source,value)
            proposed.append(value)
        plan=dict(version=1,database=str(path),marker=info,schema=source.schema_version,rows=proposed,
                  state_sha256=database_digest(source),reason=reason)
        plan['identities']=[dict(source.db.execute('''SELECT s.login AS channel,s.id AS streamer_id,c.id AS character_id,c.label AS character
            FROM streamers s JOIN characters c ON c.id=s.selected_character_id WHERE s.login=?''',(row['channel'],)).fetchone()) for row in rows]
        plan['fingerprint']=digest(plan)
        with tempfile.TemporaryDirectory(prefix='exp-roster-preview-') as folder:
            copied=Path(folder)/'preview.sqlite3'
            with closing(sqlite3.connect(copied)) as target:source.db.backup(target)
            with Store(copied) as target, target._transaction():bootstrap_change(target,plan)
        return plan


def bootstrap_change(store, plan):
    if store.schema_version==9:
        for statement in MIGRATION_10:store.db.execute(statement)
        store.schema_version=10
    if store.schema_version==10:
        for statement in MIGRATION_11:store.db.execute(statement)
        store.schema_version=11
    store.db.execute('PRAGMA user_version=11')
    if ready(store):raise ValueError('roster already bootstrapped')
    store.db.execute('INSERT INTO streamer_roster_bootstrap VALUES(1,?,?)',(plan['fingerprint'],utc()))
    for value in plan['rows']:
        raw=dict(action='roster_add',reason=plan['reason'],**{k:v for k,v in value.items() if k!='origin'})
        commit(store,preview(store,raw))


def bootstrap_apply(path, plan, *, confirm, backup):
    path=Path(path).resolve(strict=True)
    if (not isinstance(plan,dict) or plan.get('version')!=1 or plan.get('database')!=str(path) or
        digest({k:v for k,v in plan.items() if k!='fingerprint'})!=plan.get('fingerprint')):raise ValueError('modified or wrong database preview')
    if confirm!='bootstrap-roster:'+plan['fingerprint'][:16]:raise ValueError('exact bootstrap confirmation token required')
    info=ownership(path)
    with writer_lease(marker(path)) as lease, Store(path,read_only=True) as store:
        if json.load(lease)!=info or info!=plan['marker']:raise ValueError('ownership changed since preview')
        store.db.close();store.db=sqlite3.connect(path,isolation_level=None,timeout=0);store.db.row_factory=sqlite3.Row
        store.db.execute('PRAGMA foreign_keys=ON');store.read_only=False
        if store.db.execute('PRAGMA journal_mode').fetchone()[0]!='wal':raise ValueError('existing WAL database required')
        store.db.execute('BEGIN EXCLUSIVE')
        try:
            if ready(store):
                if store.db.execute('SELECT fingerprint FROM streamer_roster_bootstrap').fetchone()[0]==plan['fingerprint']:return dict(duplicate=True)
                raise ValueError('roster already bootstrapped')
            if database_digest(store)!=plan['state_sha256']:raise ValueError('stale bootstrap preview; review again while stopped')
            with Path(backup).open('xb'):pass
            with Store(path,read_only=True) as source, closing(sqlite3.connect(backup)) as target:source.db.backup(target)
            with Store(backup,read_only=True) as saved:
                if database_digest(saved)!=plan['state_sha256'] or saved.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('backup verification failed')
            bootstrap_change(store,plan)
            if store.db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('roster foreign key check failed')
            store.db.execute('COMMIT')
            return dict(duplicate=False,channels=len(plan['rows']),backup=str(Path(backup).resolve()))
        finally:
            if store.db.in_transaction:store.db.execute('ROLLBACK')
