"""Operator recovery is tested on fresh disposable databases, never sample/live state."""
from datetime import timedelta
import hashlib
import json
import os
import sqlite3
from types import SimpleNamespace

import pytest

from exp_tracker import floor_repair as repair
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.manual_admin import main
from exp_tracker.product import player
from exp_tracker.retention import prune
from exp_tracker.store import Store, utc
from exp_tracker.writer_lock import writer_lease
from tests.test_autonomous_characters import AT, auto, config, record, sequence, named_low_exp_record  # noqa: F401
from tests.test_store import profile, reading  # noqa: F401

SINCE = AT + timedelta(seconds=45)
BASELINE = AT + timedelta(minutes=2)
REASON = 'Reviewed original footage: repeated 87 OCR was actually level 67.'


@pytest.fixture
def poisoned(auto):
    path, store, policy = auto
    sequence(auto, ['Alpha', 'Alpha'], levels=[67, 67])
    for index in (3, 4):
        value = record(index, level=87, bp=4000 + index * 10)
        value['neural_level'] = dict(level=87, text='87', status='numeric_candidate', score=.99, preprocessing='neutral4')
        policy.append('first', value, 'unused', config('unused'))
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0] == 87
    return auto


def preview(poisoned, **kwargs):
    path, store, _ = poisoned
    cid = store._channel('alpha')['selected_character_id']
    return repair.preview(path, 'alpha', cid, 'Alpha', **dict(
        dict(level=67, exp=1000, percentage_bp=None, since=SINCE, at=BASELINE, reason=REASON), **kwargs))


def apply(poisoned, plan, **kwargs):
    path, _, _ = poisoned
    return repair.apply(path, 'alpha', plan['character_id'], 'Alpha', plan,
        **dict(dict(confirm=repair.confirmation(plan), backup=path.parent/'backup.sqlite3'), **kwargs))


def test_preview_is_read_only_and_repair_resumes_without_erasing_history(poisoned):
    path, store, policy = poisoned
    before = repair.database_digest(store)
    originals = [tuple(r) for r in store.db.execute('SELECT * FROM diagnostic_attempts')]
    plan = preview(poisoned)
    assert repair.database_digest(store) == before
    assert plan['old_guard']['level'] == plan['old_proof']['level'] == 87
    assert len(plan['affected_readings']) == 2
    assert [r['identity'] for r in plan['affected_readings']] == ['first:3', 'first:4']
    receipt = apply(poisoned, plan)
    assert receipt['level'] == 67 and not receipt['duplicate']
    assert receipt['audit']['superseded_guard_sha256'] == plan['old_guard_sha256']
    assert receipt['audit']['superseded_proof_sha256'] == plan['old_proof_sha256']
    assert receipt['audit']['backup_sha256'] == hashlib.sha256((path.parent/'backup.sqlite3').read_bytes()).hexdigest()
    assert [tuple(r) for r in store.db.execute('SELECT * FROM diagnostic_attempts')] == originals
    assert store.db.execute('SELECT COUNT(*) FROM characters').fetchone()[0] == 1
    assert store.db.execute('SELECT COUNT(*) FROM reading_validity').fetchone()[0] == 2
    assert store.db.execute('SELECT COUNT(*) FROM character_renames').fetchone()[0] == 0
    with Store(path.parent/'backup.sqlite3', read_only=True) as backup:
        assert repair.database_digest(backup) == before
    old = Diagnostics(store).snapshot('alpha', session_id=1, now=BASELINE)
    assert old['observations'][1]['visual_level'] == 67
    assert all(r.get('reading_invalidated') for r in old['observations'][2:])
    retained = Diagnostics(store).rolling_history('alpha', now=BASELINE)
    assert retained['tracked_exp'] is None and retained['chart_intervals'] == []
    Diagnostics(store).begin('repaired', 'alpha', config('repaired'))
    for index in (1, 2, 3):
        result = policy.append('repaired', record(index, level=67, at=BASELINE+timedelta(seconds=index*15)),
                               'unused', config('unused'))
        assert result['record']['current']
    shown = player(Diagnostics(store).snapshot('alpha', now=BASELINE+timedelta(minutes=1)))
    assert shown['display_level']['value'] == 67
    with pytest.raises(sqlite3.IntegrityError, match='cannot regress'):
        store.db.execute('UPDATE character_level_guard SET level=66')
    result = policy.append('repaired', record(4, level=66, at=BASELINE+timedelta(minutes=1)), 'unused', config('unused'))
    assert result['record']['level_hold']['reason'] == 'level_regression'
    with Store(path, read_only=True) as reopened:
        assert reopened.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not reopened.db.execute('PRAGMA foreign_key_check').fetchall()
        assert reopened.db.execute('SELECT level FROM character_level_guard').fetchone()[0] == 67
    Diagnostics(store).append('repaired', dict(type='summary', trusted=False, attempts=4, interrupted=False))
    prune(store, now=BASELINE+timedelta(hours=26), dry_run=False)
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0] == 67
    assert len(store.manual_history('alpha')) == 1
    assert all(row[0] <= 67 for row in store.db.execute('SELECT level FROM daily_character_exp WHERE level IS NOT NULL'))
    assert apply(poisoned, plan)['duplicate']


def test_named_levelup_with_long_support_gap_remains_reviewable_and_repairable(auto):
    path,store,policy=auto
    sequence(auto,['Alpha','Alpha'],levels=[50,50])
    for index,seconds in ((3,45),(4,300)):
        policy.append('first',named_low_exp_record(index,51,27,0,seconds),'unused',config())
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==51
    cid=store._channel('alpha')['selected_character_id']
    plan=repair.preview(path,'alpha',cid,'Alpha',level=50,exp=1000,percentage_bp=None,
        since=SINCE,at=AT+timedelta(seconds=600),reason='Synthetic review of a misread next-level badge.')
    assert plan['old_proof']['basis']=='named_normal_level_up'
    repair.apply(path,'alpha',cid,'Alpha',plan,confirm=repair.confirmation(plan),backup=path.parent/'backup.sqlite3')
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0]==50


@pytest.mark.parametrize('phase', ['before-baseline', 'after-replacement'])
def test_mid_repair_exception_rolls_back_every_table(poisoned, monkeypatch, phase):
    _, store, _ = poisoned
    plan = preview(poisoned)
    before = repair.database_digest(store)
    original = repair.change
    def fail(*args):
        original(*args)
        raise OSError('synthetic failure after floor replacement')
    def fail_baseline(*args, **kwargs):
        assert args[0].db.execute('SELECT * FROM character_level_guard').fetchone() is None
        raise OSError('synthetic failure before baseline')
    if phase=='after-replacement':monkeypatch.setattr(repair, 'change', fail)
    else:monkeypatch.setattr(Store, 'correct_manual', fail_baseline)
    with pytest.raises(OSError, match='synthetic failure'):
        apply(poisoned, plan)
    assert repair.database_digest(store) == before
    monkeypatch.undo()
    assert apply(poisoned, plan, backup=poisoned[0].parent/'retry-backup.sqlite3')['level'] == 67


def test_sqlite_commit_failure_rolls_back_recovery(poisoned, monkeypatch):
    _, store, _ = poisoned
    plan = preview(poisoned)
    before = repair.database_digest(store)
    connect = sqlite3.connect
    def guarded_connect(*args, **kwargs):
        db = connect(*args, **kwargs)
        if kwargs.get('timeout') == 0:
            db.set_authorizer(lambda op, action, *rest: sqlite3.SQLITE_DENY
                if op==sqlite3.SQLITE_TRANSACTION and action=='COMMIT' else sqlite3.SQLITE_OK)
        return db
    monkeypatch.setattr(sqlite3, 'connect', guarded_connect)
    with pytest.raises(sqlite3.DatabaseError, match='authorized'):apply(poisoned, plan)
    assert repair.database_digest(store) == before


def test_conflicting_manual_points_and_baselines_are_audited_not_deleted(poisoned):
    _, store, _ = poisoned
    cid = store._channel('alpha')['selected_character_id']
    baseline = store.correct_manual('alpha', 'wrong-baseline', cid, level=87, current_exp=1000,
                                   effective_at=AT+timedelta(seconds=61), reason='Wrong reviewed baseline')
    point = store.correct_manual('alpha', 'wrong-point', cid, level=87, current_exp=1000,
                                effective_at=AT+timedelta(seconds=60), kind='point',
                                target_kind='diagnostic', target_event_id='first:4', reason='Wrong reviewed point')
    plan = preview(poisoned)
    assert {e['id'] for e in plan['manual_assertions']} == {baseline['id'], point['id']}
    apply(poisoned, plan)
    events = store.manual_history('alpha')
    assert len(events) == 5
    assert not next(e for e in events if e['id'] == point['id'])['active']
    assert not next(e for e in events if e['id'] == baseline['id'])['active']
    assert [e['level'] for e in store.manual_history('alpha', active_only=True)] == [67]


@pytest.mark.parametrize('case', ['wrong-id', 'wrong-name', 'wrong-channel', 'confirmation', 'tampered', 'stale', 'backup', 'missing-backup-parent', 'marker'])
def test_unsafe_apply_fails_without_mutation(poisoned, case):
    path, store, _ = poisoned
    plan = preview(poisoned)
    args = dict(path=path, channel='alpha', cid=plan['character_id'], label='Alpha', plan=plan,
                confirm=repair.confirmation(plan), backup=path.parent/'backup.sqlite3')
    if case == 'wrong-id': args['cid'] += 1
    if case == 'wrong-name': args['label'] = 'Beta'
    if case == 'wrong-channel': args['channel'] = 'beta'
    if case == 'confirmation': args['confirm'] = 'yes'
    if case == 'tampered': plan['level'] = 66
    if case == 'stale': store.add_character('alpha', 'Beta')
    if case == 'backup': args['backup'].write_text('do not overwrite')
    if case == 'missing-backup-parent': args['backup'] = path.parent/'missing'/'backup.sqlite3'
    if case == 'marker': path.with_suffix(path.suffix+'.multi-alpha.json').write_text('[]')
    before = repair.database_digest(store)
    with pytest.raises((ValueError, OSError)):
        repair.apply(**args)
    assert repair.database_digest(store) == before
    if case == 'backup': assert args['backup'].read_text() == 'do not overwrite'


@pytest.mark.parametrize('case', ['short-reason', 'bad-exp', 'bad-percentage', 'late-since', 'early-baseline', 'frozen', 'daily', 'trusted-frozen', 'expired'])
def test_unsafe_preview_fails_closed(poisoned, case):
    _, store, _ = poisoned
    cid = store._channel('alpha')['selected_character_id']
    options = {}
    if case == 'short-reason': options['reason'] = 'oops'
    if case == 'bad-exp': options['exp'] = 10**12
    if case == 'bad-percentage': options['percentage_bp'] = 9900
    if case == 'late-since': options['since'] = SINCE+timedelta(seconds=1)
    if case == 'early-baseline': options['at'] = AT+timedelta(seconds=60)
    if case == 'frozen': store.db.execute('INSERT INTO retention_state VALUES(?,?,?)', (cid, utc(AT), json.dumps(dict(display=dict(level=87)))))
    if case == 'daily': store.db.execute("INSERT INTO daily_character_exp(character_id,utc_date,observed_at,level,current_exp,source) VALUES(?,?,?,?,?,'diagnostic')", (cid, utc(AT)[:10], utc(AT), 87, 1000))
    if case == 'trusted-frozen': store.db.execute("INSERT INTO trusted_checkpoints VALUES(1,1,'{}',1000,0)")
    if case == 'expired':
        Diagnostics(store).append('first', dict(type='summary', trusted=False, attempts=4, interrupted=False))
        prune(store, now=AT+timedelta(hours=26), dry_run=False)
    before = repair.database_digest(store)
    with pytest.raises(ValueError): preview(poisoned, **options)
    assert repair.database_digest(store) == before


def test_both_writer_locks_are_required(poisoned):
    path, store, _ = poisoned
    plan = preview(poisoned)
    marker = path.with_suffix(path.suffix+'.multi-alpha.json')
    marker.write_text(json.dumps(dict(application='multi_alpha_v1')))
    before = repair.database_digest(store)
    with writer_lease(marker), pytest.raises(ValueError, match='coordinator'):
        apply(poisoned, plan)
    with store._transaction(), pytest.raises(sqlite3.OperationalError, match='locked'):
        apply(poisoned, plan)
    assert repair.database_digest(store) == before
    assert not (path.parent/'backup.sqlite3').exists()


def test_cli_preview_confirmation_apply_retry(poisoned, capsys):
    path, store, _ = poisoned
    cid = store._channel('alpha')['selected_character_id']
    review = path.parent/'private-review.json'
    command = ['--db', str(path), '--channel', 'alpha', 'repair-floor']
    scope = ['--character-id', str(cid), '--character', 'Alpha', '--preview', str(review)]
    assert main(command+['preview']+scope+['--since', SINCE.isoformat(), '--at', BASELINE.isoformat(),
        '--level', '67', '--exp', '1000', '--reason', REASON]) == 0
    result = json.loads(capsys.readouterr().out)
    apply_args = command+['apply']+scope+['--confirm', result['confirmation'], '--backup', str(path.parent/'backup.sqlite3')]
    assert main(apply_args) == 0
    assert not json.loads(capsys.readouterr().out)['duplicate']
    assert main(apply_args) == 0
    assert json.loads(capsys.readouterr().out)['duplicate']


def test_manual_only_floor_repair_keeps_earlier_legitimate_assertion(auto):
    path, store, _ = auto
    sequence(auto, ['Alpha', 'Alpha'], levels=[67, 67])
    cid = store._channel('alpha')['selected_character_id']
    legitimate = store.correct_manual('alpha', 'legitimate', cid, level=67, current_exp=1000,
                                      effective_at=AT+timedelta(seconds=20), reason='Reviewed legitimate history')
    bad = store.correct_manual('alpha', 'incorrect', cid, level=87, current_exp=1000,
                              effective_at=SINCE, reason='Incorrect operator level assertion')
    plan = preview(auto)
    assert plan['affected_readings'] == []
    assert [e['id'] for e in plan['manual_assertions']] == [bad['id']]
    result = apply(auto, plan)
    assert result['audit']['invalidation_batch'] is None
    assert {e['id'] for e in store.manual_history('alpha', active_only=True)} == {legitimate['id'], result['baseline_id']}
    with Store(path, read_only=True) as cold:
        assert cold.db.execute('SELECT level FROM character_level_guard').fetchone()[0] == 67


def test_trusted_observation_is_excluded_and_new_session_resumes(poisoned, profile):
    _, store, _ = poisoned
    sid = store._open_session(store._channel('alpha')['id'])['id']
    bad = store.ingest('alpha', 'wrong-trusted', AT+timedelta(seconds=65), reading(1000, 1, level=87),
                       profile=profile, session_id=sid)
    assert bad['outcome'] == 'baseline'
    plan = preview(poisoned)
    assert any(r['kind'] == 'observation' and r['identity'] == str(bad['id']) for r in plan['affected_readings'])
    result = apply(poisoned, plan)
    assert store.state('alpha', as_of=BASELINE)['last_trusted'] is None
    valid = store.ingest('alpha', 'correct-trusted', BASELINE+timedelta(seconds=15), reading(1000, 1, level=67),
                         profile=profile, session_id=result['session_id'])
    assert valid['outcome'] == 'baseline' and valid['gained_exp'] is None
    assert store.db.execute('SELECT level FROM observations WHERE id=?', (bad['id'],)).fetchone()[0] == 87


@pytest.mark.parametrize('case', ['wrong-id', 'wrong-name', 'unselected', 'missing-proof', 'null-proof', 'invalid-proof', 'changed-trigger', 'old-schema'])
def test_preview_requires_unambiguous_identity_proof_and_schema(poisoned, case):
    path, store, _ = poisoned
    cid, label = store._channel('alpha')['selected_character_id'], 'Alpha'
    if case == 'wrong-id': cid += 1
    if case == 'wrong-name': label = 'Beta'
    if case == 'unselected': store.select_character('alpha', store.add_character('alpha', 'Beta'), at=BASELINE)
    if case == 'missing-proof': store.db.execute('DELETE FROM diagnostic_attempts WHERE attempt_index=3')
    if case == 'null-proof': store.db.execute('UPDATE character_level_guard SET proof_json=NULL')
    if case == 'invalid-proof': store.db.execute("UPDATE character_level_guard SET proof_json='[]'")
    if case == 'changed-trigger': store.db.execute('DROP TRIGGER character_level_no_regression')
    if case == 'old-schema': store.db.execute('PRAGMA user_version=9')
    before = repair.database_digest(store)
    with pytest.raises(ValueError):
        repair.preview(path, 'alpha', cid, label, level=67, exp=1000, percentage_bp=None,
                       since=SINCE, at=BASELINE, reason=REASON)
    assert repair.database_digest(store) == before


def test_second_repair_requires_new_preview_and_old_receipt_survives_floor_advance(poisoned):
    _, store, _ = poisoned
    plan = preview(poisoned)
    apply(poisoned, plan)
    with pytest.raises(ValueError, match='lower an existing'):
        preview(poisoned)
    cid = plan['character_id']
    store.correct_manual('alpha', 'later-legitimate-level', cid, level=68, current_exp=1000,
                         effective_at=BASELINE+timedelta(seconds=15), reason='Later legitimate level confirmed')
    assert apply(poisoned, plan)['duplicate']
    assert store.db.execute('SELECT level FROM character_level_guard').fetchone()[0] == 68


def test_earlier_legitimate_exp_and_public_history_are_preserved(auto):
    path, store, _ = auto
    sequence(auto, ['Alpha']*5, levels=[67, 67, 67, 87, 87])
    cid = store._channel('alpha')['selected_character_id']
    plan = preview(auto, since=AT+timedelta(seconds=60))
    apply(auto, plan)
    history = Diagnostics(store).rolling_history('alpha', now=BASELINE)
    gain = record(3, level=67, bp=4030)['candidate'][0]-record(2, level=67, bp=4020)['candidate'][0]
    assert history['tracked_exp']['approximate'] == gain
    assert history['windows']['5']['gain']['approximate'] == gain
    assert history['windows']['5']['rate']['approximate'] == gain*12
    assert {row['level'] for row in history['chart_intervals']} == {67}
    with Store(path, read_only=True) as cold:
        assert Diagnostics(cold).rolling_history('alpha', now=BASELINE) == history
    assert store.db.execute('SELECT character_id FROM character_level_guard').fetchone()[0] == cid


def test_good_interleaved_reading_and_manual_assertion_survive_the_error_period(auto):
    _, store, _ = auto
    sequence(auto, ['Alpha']*6, levels=[67, 67, 87, 67, 87, 87])
    cid = store._channel('alpha')['selected_character_id']
    # Point correction predates the bad floor's proof; its correct level must survive repair.
    good = store.correct_manual('alpha', 'good-point', cid, level=67, current_exp=1000,
                                effective_at=AT+timedelta(seconds=60), kind='point', target_kind='diagnostic',
                                target_event_id='first:4', reason='Reviewed valid level 67 frame')
    plan = preview(auto)
    assert plan['sources'] == [['diagnostic','first:3'], ['diagnostic','first:5'], ['diagnostic','first:6']]
    assert plan['manual_assertions'] == []
    apply(auto, plan)
    assert next(e for e in store.manual_history('alpha') if e['id']==good['id'])['active']
    old = Diagnostics(store).snapshot('alpha', session_id=1, now=BASELINE)
    assert old['observations'][3].get('reading_invalidated') is None
    assert old['observations'][3]['manual_point']['id'] == good['id']


def test_hardlinked_database_alias_cannot_bypass_writer_lease(poisoned):
    path, store, _ = poisoned
    plan = preview(poisoned)
    alias = path.parent/'alias.sqlite3'
    try:os.link(path, alias)
    except PermissionError:pytest.skip('OS does not permit creating test hard links; refusal guard is tested synthetically')
    before = repair.database_digest(store)
    with pytest.raises(ValueError, match='hard-linked'):
        repair.preview(alias, 'alpha', plan['character_id'], 'Alpha', level=67, exp=1000, percentage_bp=None,
                       since=SINCE, at=BASELINE, reason=REASON)
    with pytest.raises(ValueError, match='hard-linked'):apply(poisoned, plan)
    assert repair.database_digest(store) == before


def test_hardlink_guard_refuses_before_any_database_operation(poisoned, monkeypatch):
    path, store, _ = poisoned
    plan = preview(poisoned)
    before = repair.database_digest(store)
    stat = repair.Path.stat
    monkeypatch.setattr(repair.Path, 'stat', lambda self, *args, **kwargs:
        SimpleNamespace(st_nlink=2) if self==path else stat(self, *args, **kwargs))
    with pytest.raises(ValueError, match='hard-linked'):preview(poisoned)
    with pytest.raises(ValueError, match='hard-linked'):apply(poisoned, plan)
    assert repair.database_digest(store) == before
