"""Retention as a separate worker beside capture: short write locks, safe protection without a heartbeat."""
from datetime import timedelta
import json
import os
import sqlite3

import pytest

from exp_tracker import retention
from exp_tracker.retention import live_runs, maintenance_pass, prune, checkpoint
from exp_tracker.store import Store
from tests.test_product import tracking, NOW  # noqa: F401
from tests.test_diagnostic_history import config
from tests.test_retention import chain, metrics
from tests.test_tracked_exp_totals import save


def table(store, name, order):
    return [tuple(r) for r in store.db.execute(f'SELECT * FROM {name} ORDER BY {order}')]


def state(store):
    return dict(attempts=table(store, 'diagnostic_attempts', 'id'), runs=table(store, 'diagnostic_runs', 'rowid'),
        checkpoints=table(store, 'retention_state', 'character_id'), daily=table(store, 'daily_character_exp', 'character_id,utc_date'))


def test_compute_holds_no_write_lock_so_capture_can_commit_meanwhile(tracking, monkeypatch):
    path, store, d = tracking; now = chain(d)
    original = retention._checkpoint_value; commits = []
    def compute(*args):
        # A capture save with no patience: it would raise at once if retention held the write lock.
        with sqlite3.connect(path, timeout=0, isolation_level=None) as capture:
            capture.execute('BEGIN IMMEDIATE'); capture.execute('CREATE TABLE IF NOT EXISTS probe (n)')
            capture.execute('INSERT INTO probe VALUES (1)'); capture.execute('COMMIT')
        commits.append(1)
        return original(*args)
    monkeypatch.setattr(retention, '_checkpoint_value', compute)
    report = prune(store, now=now + timedelta(days=2), dry_run=False, active_runs=live_runs)
    assert commits and report['runs'] > 0 and report['max_lock_seconds'] < 1


def test_change_between_compute_and_write_discards_the_batch(tracking, monkeypatch):
    path, store, d = tracking; now = chain(d) + timedelta(days=2)
    before = state(store); original = retention._checkpoint_value
    def compute(*args):
        result = original(*args)
        with Store(path) as other, other._transaction():  # E.g. another pass or an operator revision.
            other.db.execute('UPDATE retention_meta SET revision=revision+1 WHERE id=1')
        return result
    monkeypatch.setattr(retention, '_checkpoint_value', compute)
    report = prune(store, now=now, dry_run=False, active_runs=live_runs)
    assert report['stale_snapshots'] == 1 and report['runs'] == 0 and report['batch_limit_reached']
    assert state(store) == before
    monkeypatch.undo()
    assert prune(store, now=now, dry_run=False, active_runs=live_runs)['runs'] > 0


def test_interrupted_pass_resumes_to_the_same_result_as_an_uninterrupted_one(tracking, tmp_path, monkeypatch):
    path, store, d = tracking; now = chain(d) + timedelta(days=2)
    with Store(tmp_path / 'reference.sqlite3') as reference:
        store.db.backup(reference.db)
        while prune(reference, now=now, dry_run=False, active_runs=live_runs, batch_runs=3)['batch_limit_reached']:pass
        expected = state(reference)
    calls = [0]; apply = retention._apply
    def crash(*args):
        calls[0] += 1
        if calls[0] == 2:apply(*args);raise KeyboardInterrupt  # Killed after writing, before its commit.
        apply(*args)
    monkeypatch.setattr(retention, '_apply', crash)
    with pytest.raises(KeyboardInterrupt):
        while prune(store, now=now, dry_run=False, active_runs=live_runs, batch_runs=3)['batch_limit_reached']:pass
    monkeypatch.undo()
    with Store(path) as restarted:  # A new process continues from what was committed.
        while prune(restarted, now=now, dry_run=False, active_runs=live_runs, batch_runs=3)['batch_limit_reached']:pass
        assert state(restarted) == expected
        assert not restarted.db.execute('PRAGMA foreign_key_check').fetchall()


def test_newest_unfinished_run_per_streamer_is_protected_and_a_superseded_one_expires(tracking):
    path, store, d = tracking; now = chain(d)
    assert live_runs(store) == {'chain7'}  # The run a coordinator may still be writing.
    d.begin('restart', 'alpha', config('restart', interval=300))  # A new process; chain7 was never summarised.
    save(d, 'restart', 1, (8 * 60) * 300, 2000, level=65)
    assert live_runs(store) == {'restart'}
    later = now + timedelta(days=2)
    while prune(store, now=later, dry_run=False, active_runs=live_runs)['batch_limit_reached']:pass
    kept = {r[0] for r in store.db.execute('SELECT DISTINCT run_id FROM diagnostic_attempts')}
    assert kept == {'restart'} and checkpoint(store, 1)['through_run']
    # Without any protection rule the same expiry would never touch an unfinished run.
    assert prune(store, now=later, dry_run=True)['runs'] == 0


def test_pass_is_bounded_reports_and_is_idempotent(tracking, tmp_path):
    path, store, d = tracking; chain(d); store.db.close()
    bounded = maintenance_pass(path, batch_runs=1, max_seconds=0.001, pause_seconds=0, emit=lambda line:None)
    assert not bounded['complete'] and bounded['runs'] <= 1  # Time is up: the rest waits for the next pass.
    lines = []
    first = maintenance_pass(path, batch_runs=3, pause_seconds=0, emit=lines.append)
    chunks = [json.loads(line) for line in lines if '"chunk"' in line]
    assert first['complete'] and first['runs'] >= 7 and first['revision_bumped'] and len(chunks) >= 3
    assert all(c['lock_ms'] < 1000 for c in chunks) and first['max_lock_ms'] < 1000
    assert first['oldest_attempt_hours'] is not None and first['protected_runs'] == 1
    with Store(path, read_only=True) as reader:revision = reader.db.execute('SELECT revision FROM retention_meta').fetchone()[0]
    second = maintenance_pass(path, batch_runs=3, pause_seconds=0, emit=lambda line:None)
    assert second['complete'] and second['runs'] == 0 and not second['revision_bumped']
    with Store(path, read_only=True) as reader:
        assert reader.db.execute('SELECT revision FROM retention_meta').fetchone()[0] == revision  # Readers keep pages.


def test_cli_refuses_overlap_and_dry_run_writes_nothing(tracking, capsys):
    from exp_tracker.writer_lock import writer_lease
    path, store, d = tracking; chain(d); store.db.close()
    before = path.read_bytes()
    assert retention.main(['--db', str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['dry_run'] and report['runs'] > 0 and report['protected_runs'] == 1 and path.read_bytes() == before
    lock = path.with_suffix(path.suffix + '.retention.lock'); lock.touch()
    with writer_lease(lock):
        with pytest.raises(SystemExit) as exit:retention.main(['--db', str(path), '--apply'])
    assert exit.value.code == 75 and path.read_bytes() == before


def test_file_cleanup_keeps_live_logs_the_open_operator_log_and_files_in_use(tracking, tmp_path, monkeypatch):
    from pathlib import Path
    from exp_tracker.retention_files import cleanup, current_operator_log, own
    path, store, d = tracking; chain(d)
    root = tmp_path / 'logs'; old = NOW.timestamp()
    def directory(name):
        folder = root / name; folder.mkdir(parents=True); own(folder, path); return folder
    def log(folder, run):
        file = folder / 'alpha' / run / 'capture.jsonl'; file.parent.mkdir(parents=True)
        file.write_text(json.dumps(dict(type='configuration', run_id=run)) + '\n'); os.utime(file, (old, old)); return file
    first, newest = directory('20260101T000000Z-aaaaaaaa'), directory('20260102T000000Z-bbbbbbbb')
    expired, busy, live = log(first, 'gone-1'), log(first, 'gone-2'), log(newest, 'chain7')
    operators = [first / 'operator.jsonl', newest / 'operator.jsonl', newest / 'operator-20260102T01-1.jsonl']
    for number, file in enumerate(operators):
        file.write_text('{}\n'); os.utime(file, (old + number, old + number))
    assert current_operator_log(root, path) == [operators[-1]]
    unlink = Path.unlink
    def in_use(self, *args, **kwargs):
        if self == busy:raise PermissionError('in use')  # Windows refuses to delete an open file.
        return unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', in_use)
    report = cleanup(root, path, store, now=NOW + timedelta(days=10), dry_run=False,
        active_logs=current_operator_log(root, path), protected_runs=live_runs(store))
    assert report['errors'] == 1 and busy.exists() and live.exists() and operators[-1].exists()
    assert not expired.exists() and not operators[0].exists() and not operators[1].exists()
