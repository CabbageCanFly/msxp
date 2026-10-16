"""Relocation checks use invented files, not private calibration assets."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def resolve(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools'))
    return importlib.import_module('exp_digits').bank_source


def test_normal_relative_and_absolute_references_are_unchanged(resolve, tmp_path):
    bank = tmp_path/'bank.json'
    assert resolve(bank, 'image.png') == tmp_path/'image.png'
    assert resolve(bank, str(tmp_path/'profile.json')) == tmp_path/'profile.json'


def test_explicit_map_preserves_bank_bytes_and_is_relative_to_manifest(resolve, tmp_path, monkeypatch):
    bank = tmp_path/'bank.json'
    original = r'H:\former\repository\image.png'
    bank.write_text(json.dumps(dict(image=original)))
    source = tmp_path/'image.png'
    source.write_bytes(b'verified development image')
    sidecar = bank.with_suffix('.paths.json')
    sidecar.write_text(json.dumps({original:dict(path='image.png', sha256=hashlib.sha256(source.read_bytes()).hexdigest())}))
    before = {p:p.read_bytes() for p in (bank, sidecar, source)}
    monkeypatch.chdir(tmp_path.parent)
    assert resolve(bank, original) == source
    assert all(p.read_bytes() == value for p,value in before.items())
    assert resolve(bank, 'unmapped.png') == tmp_path/'unmapped.png'


@pytest.mark.parametrize('problem', ['changed', 'missing', 'absolute'])
def test_bad_remapping_never_falls_back_to_original(resolve, tmp_path, problem):
    bank = tmp_path/'bank.json'
    original = tmp_path/'original.png'
    original.write_bytes(b'old location still exists')
    relocated = tmp_path/'relocated.png'
    relocated.write_bytes(b'expected contents')
    entry = dict(path=relocated.name, sha256=hashlib.sha256(relocated.read_bytes()).hexdigest())
    if problem == 'changed':
        relocated.write_bytes(b'different contents')
    elif problem == 'missing':
        entry['path'] = 'missing.png'
    else:
        entry['path'] = str(relocated)
    bank.with_suffix('.paths.json').write_text(json.dumps({str(original):entry}))
    with pytest.raises(FileNotFoundError if problem == 'missing' else ValueError):
        resolve(bank, str(original))
