"""Published provisional requirements, separate from recognizing a valid level."""

from functools import cache
from importlib.resources import files
import hashlib
import json


@cache
def community_table():
    payload = files('exp_tracker').joinpath('data/community-exp-v2.json').read_bytes()
    data = json.loads(payload)
    if (set(map(int, data['to_next'])) != set(range(1, 90)) or
            any(type(n) is not int or n <= 0 for n in data['to_next'].values()) or
            set(map(int, data['disputed_to_next'])) != set(range(90, 100)) or
            data['missing_levels'] != list(range(100, 201))):
        raise ValueError('Invalid versioned community EXP dataset')
    return data, hashlib.sha256(payload).hexdigest()


def requirement(level):
    """Missing/disputed requirements never invalidate a recognized 1–200 level."""
    data, sha = community_table()
    result = dict(level=level, version=data['version'], sha256=sha, to_next=None,
                  published_alternatives={}, trusted=False, authoritative=False)
    if type(level) is not int or not 1 <= level <= 200:
        return {**result, 'status': 'invalid_or_unavailable_level'}
    if str(level) in data['to_next']:
        return {**result, 'status': 'community_provisional', 'to_next': data['to_next'][str(level)]}
    if str(level) in data['disputed_to_next']:
        return {**result, 'status': 'source_disagreement',
                'published_alternatives': data['disputed_to_next'][str(level)]}
    return {**result, 'status': 'missing_requirement'}
