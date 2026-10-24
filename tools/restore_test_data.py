"""Restore checksum-verified private fixtures without overwriting different local files.

    python tools/restore_test_data.py ../msxp-test-data
    python tools/restore_test_data.py ../msxp-test-data --check
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def inside(root, relative):
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or '..' in path.parts or '\\' in relative or ':' in relative:
        raise ValueError(f'Unsafe fixture path: {relative}')
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):raise ValueError(f'Fixture path escapes its directory: {relative}')
    return resolved


def fingerprint(path, *, compressed=False, limit=None):
    result, size = hashlib.sha256(), 0
    with (gzip.open(path, 'rb') if compressed else path.open('rb')) as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            size += len(chunk)
            if limit is not None and size > limit:raise ValueError(f'Fixture exceeds its recorded size: {path}')
            result.update(chunk)
    return result.hexdigest(), size


def restore(data, target=ROOT, *, check=False):
    data, target = Path(data).resolve(), Path(target).resolve()
    entries = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))['files']
    copies, destinations = [], set()
    for item in entries:
        source = inside(data, item['path'])
        if not isinstance(item['size'], int) or item['size'] < 0:raise ValueError('Invalid fixture size')
        expected = item['sha256'], item['size']
        if fingerprint(source, compressed=item.get('gzip', False), limit=item['size']) != expected:
            raise ValueError(f'Fixture checksum mismatch: {source}')
        relative = item.get('target')
        if relative is None:continue  # Research evidence is preserved in the data repo, not installed into the app.
        if not relative or PurePosixPath(relative).parts[0] not in ('samples', 'private', 'artifacts'):
            raise ValueError(f'Not a private fixture destination: {relative}')
        destination = inside(target, relative)
        if destination in destinations:raise ValueError(f'Duplicate fixture destination: {relative}')
        destinations.add(destination)
        if destination.exists():
            if fingerprint(destination) != expected:raise ValueError(f'Refusing to overwrite different file: {destination}')
        elif check:raise ValueError(f'Restored fixture is missing: {destination}')
        else:copies.append((source, destination, item.get('gzip', False), expected))
    for source, destination, compressed, expected in copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (gzip.open(source, 'rb') if compressed else source.open('rb')) as incoming, destination.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        if fingerprint(destination) != expected:raise ValueError(f'Restored fixture checksum mismatch: {destination}')
    return dict(verified=len(entries), restored=len(copies), installed=len(destinations))


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument('data', type=Path)
    cli.add_argument('--target', type=Path, default=ROOT, help='fresh project checkout (defaults to this checkout)')
    cli.add_argument('--check', action='store_true', help='verify the data repository and restored files without writing')
    args = cli.parse_args(argv)
    try:print(json.dumps(restore(args.data, args.target, check=args.check)));return 0
    except (OSError, EOFError, ValueError, KeyError, TypeError) as error:
        print(f'Fixtures not restored: {error}', file=sys.stderr);return 1


if __name__ == '__main__':raise SystemExit(main())
