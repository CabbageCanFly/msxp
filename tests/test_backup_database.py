import sqlite3

import pytest

from tools.backup_database import backup
from exp_tracker.store import Store


def test_backup_includes_committed_wal_while_writer_stays_open(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    source=tmp_path/'private/source.sqlite3';source.parent.mkdir()
    with Store(source) as store:
        store.add_channel('alpha')
        result=backup(source,tmp_path/'private/backups/snapshot.sqlite3')
        with Store(result,read_only=True) as restored: assert restored._channel('alpha')['login']=='alpha'
        store.add_channel('beta')
        with Store(result,read_only=True) as restored:
            with pytest.raises(ValueError):restored._channel('beta')
    before=result.read_bytes()
    with pytest.raises(FileExistsError):backup(source,result)
    assert before==result.read_bytes()
    with pytest.raises(ValueError):backup(source,tmp_path/'public.sqlite3')


def test_failed_backup_never_overwrites_existing_file(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):backup(tmp_path/'missing',tmp_path/'private/new.sqlite3')
    assert not (tmp_path/'private/new.sqlite3').exists()
