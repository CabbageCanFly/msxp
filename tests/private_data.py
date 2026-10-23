"""Private test data that is never in Git: live-capture crops, and saved recordings of real streams.

Code and docs use only placeholder names (streamer_a, CharA, ...). Where the recordings exist, the private
names.json maps each placeholder to its real name, and tests read an anonymized copy of the recordings, so
the placeholders match everywhere. The original recordings are never modified.
"""
from functools import cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIVE_CROPS = (ROOT / 'artifacts/live-benchmark', ROOT / 'artifacts/green-test-20261015-215403')
RECORDINGS = Path('private/test-fixtures/runs')
NAMES = ROOT / 'private/test-fixtures/names.json'
ANONYMIZED = Path('private/test-fixtures/runs-public-names')


def require_live_crops():
    """Skip, like other private-sample tests, when the crops these labels and banks were built from are absent."""
    missing = [path.name for path in LIVE_CROPS if not path.is_dir()]
    if missing:
        pytest.skip(f'Private live crops are absent ({", ".join(missing)}); see docs/private-test-data.md')


@cache
def _names():
    try:return {k: v for k, v in json.loads(NAMES.read_text(encoding='utf-8')).items() if not k.startswith('_')}
    except FileNotFoundError:return {}


def private_name(name):
    """The real name behind a placeholder, for private data that is read as-is (not the anonymized recordings)."""
    return _names().get(name, name)


def _public(text, names):
    for placeholder, real in sorted(names.items(), key=lambda item: -len(item[1])):
        text = re.sub(r'(?<![A-Za-z0-9])' + re.escape(real) + r'(?![A-Za-z0-9])', placeholder, text)
    return text


@cache
def recordings():
    """The saved recordings with placeholder names: built once from the originals, rebuilt when they change."""
    names = _names()
    source = ROOT / RECORDINGS
    if not names or not source.is_dir():return RECORDINGS
    files = sorted(p for p in source.rglob('*') if p.is_file())
    stamp = hashlib.sha256(json.dumps([names, [(str(p.relative_to(source)), p.stat().st_size, p.stat().st_mtime_ns)
                                                for p in files]]).encode()).hexdigest()
    target = ROOT / ANONYMIZED
    if (target / '.source').is_file() and (target / '.source').read_text() == stamp:return ANONYMIZED
    build = Path(tempfile.mkdtemp(prefix='runs-public-', dir=target.parent))
    for path in files:
        out = build / _public(str(path.relative_to(source)), names)
        out.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in ('.jsonl', '.json', '.txt'):out.write_text(_public(path.read_text(encoding='utf-8'), names), encoding='utf-8')
        else:shutil.copyfile(path, out)
    (build / '.source').write_text(stamp)
    try:
        if target.exists():shutil.rmtree(target)
        os.replace(build, target)
    except OSError:  # Another test worker finished the same copy first.
        shutil.rmtree(build, ignore_errors=True)
    return ANONYMIZED


def recorded(path):
    """A path into the saved recordings, read from the anonymized copy."""
    try:return recordings() / Path(path).relative_to(RECORDINGS)
    except ValueError:return Path(path)
