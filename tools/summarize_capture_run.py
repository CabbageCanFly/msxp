"""Summarize one finished multi_alpha run directory: stage means, cadence and HUD-region reuse.

Reads only the private capture.jsonl logs; never the database or the network.
"""

import argparse
import json
from pathlib import Path
import statistics


def summarize(directory):
    attempts = [record for path in sorted(Path(directory).rglob('capture.jsonl'))
                for line in path.read_text(encoding='utf-8').splitlines()
                if (record := json.loads(line)).get('type') == 'attempt']
    if not attempts:
        raise ValueError('No attempts under this run directory')

    def mean(values):
        values = [v for v in values if v is not None]
        return round(statistics.mean(values), 3) if values else None

    def stage(key, rows=attempts):
        return mean(r.get('timings', {}).get(key) for r in rows)

    cached = [r for r in attempts if any(c.get('search') == 'cached_region'
              for c in (r.get('localization') or {}).get('candidates', []))]
    resources = [r.get('resources', {}) for r in attempts if r.get('resources')]
    return dict(
        attempts=len(attempts),
        statuses={s: sum(r.get('status') == s for r in attempts) for s in sorted({str(r.get('status')) for r in attempts})},
        frames=sum(r.get('received_at') is not None for r in attempts),
        mean_work_seconds=mean(r.get('coordinator_attempt_seconds') for r in attempts),
        capture_seconds=stage('capture_and_close_seconds'),
        localization_seconds=stage('localization_seconds'),
        cached_region_attempts=len(cached),
        cached_localization_seconds=stage('localization_seconds', cached),
        neural_seconds=stage('neural_bridge_seconds'),
        visual_level_seconds=stage('visual_level_seconds'),
        mean_actual_interval_seconds=mean(r.get('actual_interval_seconds') for r in attempts),
        max_actual_interval_seconds=max((r.get('actual_interval_seconds') or 0 for r in attempts), default=None),
        max_scheduler_delay_seconds=max((r.get('scheduler_delay_seconds') or 0 for r in attempts), default=None),
        last_resources=resources[-1] if resources else None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='private/multi-alpha/runs/<run> printed as "Private capture logs"')
    print(json.dumps(summarize(parser.parse_args(argv).directory), indent=1))


if __name__ == '__main__':
    main()
