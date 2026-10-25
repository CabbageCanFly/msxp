"""The closed job list: exact reads, snapped near-misses, and everything else rejected."""
import pytest

from exp_tracker.jobs import match, min_level, next_level, table, tier


@pytest.mark.parametrize('text,job', [
    ('Cleric', 'Cleric'), ('cleric ', 'Cleric'), ('Wizard (Ice,Lightning)', 'Wizard (Ice,Lightning)'),
    ('Wizard (Ice, Lightning)', 'Wizard (Ice,Lightning)'),  # Spaces are ignored.
    ('Clerlc', 'Cleric'), ('Assasin', 'Assassin'), ('Begirner', 'Beginner'), ('Wizard (lce,Lightning)', 'Wizard (Ice,Lightning)'),
])
def test_exact_and_near_reads_snap_to_one_job(text, job):
    assert match(text) == job


@pytest.mark.parametrize('text', [None, '', 'C', 'Alpha', 'Wizard', 'Clerxyz', 'Fighter Page', 'x' * 41,
                                  'Wizard (Fire,Lightningg)', 'Fihgter Paeg'])
def test_other_text_and_ambiguous_reads_are_rejected(text):
    assert match(text) is None


def test_tiers_and_levels_follow_the_table():
    assert table()['levels'] == {1: 8, 2: 30}
    assert (tier('Beginner'), tier('Magician'), tier('Cleric')) == (0, 1, 2)
    assert (min_level('Beginner'), min_level('Thief'), min_level('Hunter')) == (1, 8, 30)
    assert (next_level('Beginner'), next_level('Bowman'), next_level('Bandit')) == (8, 30, None)
    assert all(j['parent'] is None or tier(j['parent']) == j['tier'] - 1 for j in table()['jobs'].values())


def test_every_job_has_its_game_icon():
    """product.js loads web/jobs/<slug>.png for the profile header; the folder holds exactly one 64 px icon per job."""
    import json, re
    from pathlib import Path
    from PIL import Image
    data = Path(__file__).parents[1] / 'src' / 'exp_tracker'
    jobs = json.loads((data / 'data' / 'jobs.json').read_text(encoding='utf-8'))['jobs']
    slugs = {re.sub(r'[^a-z0-9]+', '-', j['name'].lower()).strip('-') for j in jobs}
    assert all(j['icon'] for j in jobs) and {p.stem for p in (data / 'web' / 'jobs').glob('*')} == slugs
    assert all(Image.open(data / 'web' / 'jobs' / f'{s}.png').size == (64, 64) for s in slugs)
