"""MapleStory Classic jobs as printed in the status panel.

The list is closed, so a slightly misread job can snap to the one job it is clearly
closest to; nothing outside the list is ever accepted.
"""
from functools import lru_cache
from importlib.resources import files
import json


@lru_cache(maxsize=1)
def table():
    data = json.loads(files('exp_tracker').joinpath('data/jobs.json').read_bytes())
    return {'version': data['version'], 'levels': {int(k): v for k, v in data['advancement_levels'].items()},
            'jobs': {j['name']: j for j in data['jobs']}}


def _key(text):
    return ''.join(text.split()).lower()


def _distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ca != cb))
    return row[-1]


def match(text):
    """The known job for OCR text, or None: exact (ignoring case and spaces), else the one job
    within max(1, len // 8) edits that is at least 2 edits closer than every other job."""
    if not isinstance(text, str) or not 2 <= len(text.strip()) <= 40:
        return None
    key = _key(text)
    ranked = sorted((_distance(key, _key(name)), name) for name in table()['jobs'])
    best, name = ranked[0]
    if best == 0:
        return name
    if best <= max(1, len(_key(name)) // 8) and ranked[1][0] >= best + 2:
        return name
    return None


def tier(job):
    return table()['jobs'][job]['tier']


def min_level(job):
    """Lowest level that can hold this job; a read above the character's level is impossible."""
    return table()['levels'].get(tier(job), 1)


def next_level(job):
    """The level from which this job can advance, or None when no further job is known."""
    return table()['levels'].get(tier(job) + 1)
