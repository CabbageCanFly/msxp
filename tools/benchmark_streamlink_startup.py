"""Offline Linux comparison of fresh Streamlink imports and forkserver preloading.

Resolves only whether a synthetic URL is supported: no Twitch requests, credentials,
video, database or tracker changes. Measures startup, not live capture throughput.
"""
import argparse
import multiprocessing
import statistics
import subprocess
import sys
import time


PROBE = ['--no-config', '--no-plugin-cache', '--no-plugin-sideloading',
         '--webbrowser', 'false', '--loglevel', 'error',
         '--can-handle-url-no-redirect', 'https://www.twitch.tv/streamer_a']


def probe(reply):
    """One fresh child runs the same CLI entry point; only imports can be inherited."""
    from streamlink_cli.main import main
    saved_argv, saved_stdout = sys.argv, sys.stdout
    code = 0
    try:
        sys.argv = ['streamlink', *PROBE]
        main()
    except SystemExit as error:
        code = error.code or 0
    finally:
        # Streamlink deletes sys.stdout on exit; multiprocessing still needs to flush it.
        sys.argv, sys.stdout = saved_argv, saved_stdout
    reply.send(dict(code=code, cpu_seconds=time.process_time()))
    reply.close()


def warm_attempt(context, *, timeout=30):
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=probe, args=(writer,))
    started = time.monotonic()
    try:
        process.start()
        writer.close()
        if not reader.poll(timeout):
            raise RuntimeError('Streamlink startup probe timed out')
        result = reader.recv()
        process.join(timeout=3)
        if process.is_alive() or process.exitcode != 0 or result['code'] != 0:
            raise RuntimeError('Streamlink startup probe failed')
        return dict(cpu_seconds=result['cpu_seconds'], wall_seconds=time.monotonic()-started)
    finally:
        if process.pid is not None and process.is_alive():
            process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
        writer.close()
        reader.close()
        if process.pid is not None and not process.is_alive():process.close()


def cold_attempt():
    import resource  # Linux only; capture children are direct children on this path.
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    result = subprocess.run([sys.executable, '-m', 'streamlink', *PROBE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if result.returncode != 0:raise RuntimeError('Streamlink startup probe failed')
    return dict(cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        wall_seconds=time.monotonic()-started)


def summary(rows):
    return {key: round(statistics.median(row[key] for row in rows), 4)
            for key in ('cpu_seconds', 'wall_seconds')}


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--count', type=int, default=5, help='1..20 paired offline probes')
    args = cli.parse_args(argv)
    if not 1 <= args.count <= 20:cli.error('--count must be 1..20')
    if sys.platform != 'linux' or 'forkserver' not in multiprocessing.get_all_start_methods():
        cli.error('This experiment requires Linux with forkserver support')
    multiprocessing.set_forkserver_preload(['__main__', 'streamlink_cli.main', 'streamlink.plugins.twitch'])
    context = multiprocessing.get_context('forkserver')
    first = warm_attempt(context)
    cold, warm = [], []
    for index in range(args.count):
        if index % 2:
            warm.append(warm_attempt(context));cold.append(cold_attempt())
        else:
            cold.append(cold_attempt());warm.append(warm_attempt(context))
    before, after = summary(cold), summary(warm)
    import json
    print(json.dumps(dict(offline_only=True, count=args.count, first_preloaded_wall_seconds=round(first['wall_seconds'], 4),
        cold=before, preloaded=after,
        startup_cpu_reduction_percent=round(100*(1-after['cpu_seconds']/before['cpu_seconds']), 1))))
    return 0


if __name__ == '__main__':raise SystemExit(main())
