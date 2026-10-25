"""The closed job list: exact reads, snapped near-misses, and everything else rejected."""
import pytest

from exp_tracker.jobs import match, min_level, next_level, table, tier


@pytest.mark.parametrize('text,job', [
    ('Cleric', 'Cleric'), ('cleric ', 'Cleric'), ('Wizard (Ice,Lightning)', 'Wizard (Ice,Lightning)'),
    ('Wizard (Ice, Lightning)', 'Wizard (Ice,Lightning)'),  # Spaces are ignored.
    ('Clerlc', 'Cleric'), ('Assasin', 'Assassin'), ('Begirner', 'Beginner'), ('Wizard (lce,Lightning)', 'Wizard (Ice,Lightning)'),
    ('Swordsman', 'Swordsman'), ('Swordman', 'Swordsman'), ('Archer', 'Archer'), ('Rogue', 'Rogue'),  # 1st jobs by their in-game names.
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
    assert (min_level('Beginner'), min_level('Rogue'), min_level('Hunter')) == (1, 8, 30)
    assert (next_level('Beginner'), next_level('Archer'), next_level('Bandit')) == (8, 30, None)
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


def test_home_job_filter_lists_every_job_under_its_class():
    """product.js's JOB_CLASSES (the homepage job filter) must follow jobs.json: each first job with its advancements."""
    import json, re
    from pathlib import Path
    source = (Path(__file__).parents[1] / 'src' / 'exp_tracker' / 'web' / 'product.js').read_text(encoding='utf-8')
    classes = json.loads(re.search(r'const JOB_CLASSES=(\[.*?\]);', source, re.S)[1])
    jobs = table()['jobs'].values()
    expected = {j['name']: [j['name'], *[k['name'] for k in jobs if k['parent'] == j['name']]] for j in jobs if j['tier'] == 1}
    assert {c['jobs'][0]: c['jobs'] for c in classes} == expected  # Classes keep their names (Thief); jobs use the in-game ones (Rogue).
    assert 'Beginner' in source and {j['name'] for j in jobs} == {'Beginner'} | {n for c in classes for n in c['jobs']}
    badges = Path(__file__).parents[1] / 'src' / 'exp_tracker' / 'web' / 'classes'
    assert {p.name for p in badges.iterdir()} == {'beginner.gif'} | {f"{c['class'].lower()}.gif" for c in classes}  # One old badge per top-level pick.
