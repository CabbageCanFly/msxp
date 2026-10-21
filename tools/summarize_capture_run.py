"""Summarize one finished multi_alpha run directory: stage means, cadence and HUD-region reuse.

Reads only the private capture.jsonl logs; never the database or the network.
"""

import argparse
import json
from pathlib import Path
import statistics


def summarize(directory):
    attempts, skipped = [], {}
    for path in sorted(Path(directory).rglob('capture.jsonl')):
        channel = path.relative_to(directory).parts[0]  # Rotated/switched runs nest under their channel.
        for line in path.read_text(encoding='utf-8').splitlines():
            record = json.loads(line)
            if record.get('type') == 'attempt':
                attempts.append(record)
            # Cumulative per channel for the whole process. finish() can add skips after an attempt
            # was written, so the final summary is authoritative; rotation/switch summaries omit it.
            if record.get('type') in ('attempt', 'summary'):
                skipped[channel] = max(skipped.get(channel, 0), record.get('skipped_deadlines') or 0)
    if not attempts:
        raise ValueError('No attempts under this run directory')

    def mean(values):
        values = [v for v in values if v is not None]
        return round(statistics.mean(values), 3) if values else None

    def original(record):
        # Identity holds nest the attempt's own status and frame age under identity_hold.evidence.
        return (record.get('identity_hold') or {}).get('evidence') or record

    def p95(values):
        values = sorted(v for v in values if v is not None)
        return round(values[int(.95 * (len(values) - 1))], 3) if values else None

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
        p95_actual_interval_seconds=p95(r.get('actual_interval_seconds') for r in attempts),
        skipped_deadlines=sum(skipped.values()),
        mean_scheduler_delay_seconds=mean(r.get('scheduler_delay_seconds') for r in attempts),
        max_scheduler_delay_seconds=max((r.get('scheduler_delay_seconds') or 0 for r in attempts), default=None),
        p95_local_age_seconds=p95(original(r).get('local_age_seconds') for r in attempts),
        max_local_age_seconds=max((original(r).get('local_age_seconds') or 0 for r in attempts), default=None),
        stale_local_frames=sum(original(r).get('status') == 'stale_local_frame' for r in attempts),
        identity_held_attempts=sum('identity_hold' in r for r in attempts),
        last_resources=resources[-1] if resources else None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='private/multi-alpha/runs/<run> printed as "Private capture logs"')
    print(json.dumps(summarize(parser.parse_args(argv).directory), indent=1))


if __name__ == '__main__':
    main()
