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
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'https://github.com/CabbageCanFly/msxp-test-data.git'


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


def expected(item):
    if not isinstance(item['size'], int) or item['size'] < 0:raise ValueError('Invalid fixture size')
    return item['sha256'], item['size']


def missing_files(entries, target, *, check=False):
    missing, destinations = [], set()
    for item in entries:
        relative = item.get('target')
        if relative is None:continue
        if not relative or PurePosixPath(relative).parts[0] not in ('samples', 'private', 'artifacts'):
            raise ValueError(f'Not a private fixture destination: {relative}')
        destination = inside(target, relative)
        if destination in destinations:raise ValueError(f'Duplicate fixture destination: {relative}')
        destinations.add(destination)
        value = expected(item)
        if destination.exists():
            if destination.stat().st_size != value[1] or fingerprint(destination) != value:
                raise ValueError(f'Refusing to overwrite different file: {destination}')
        elif check:raise ValueError(f'Restored fixture is missing: {destination}')
        else:missing.append(item)
    return missing, len(destinations)


def restore(data, target=ROOT, *, check=False):
    data, target = Path(data).resolve(), Path(target).resolve()
    entries = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))['files']
    for item in entries:
        source = inside(data, item['path'])
        if fingerprint(source, compressed=item.get('gzip', False), limit=expected(item)[1]) != expected(item):
            raise ValueError(f'Fixture checksum mismatch: {source}')
    copies, installed = missing_files(entries, target, check=check)
    for item in copies:
        source, destination = inside(data, item['path']), inside(target, item['target'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (gzip.open(source, 'rb') if item.get('gzip', False) else source.open('rb')) as incoming, destination.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        if fingerprint(destination) != expected(item):raise ValueError(f'Restored fixture checksum mismatch: {destination}')
    return dict(verified=len(entries), restored=len(copies), installed=installed)


def download(target=ROOT, *, check=False, repository=REPOSITORY):
    """Fetch the manifest and missing required blobs only; temporary Git storage is discarded."""
    target = Path(target).resolve()
    with tempfile.TemporaryDirectory(prefix='msxp-test-data-') as temporary:
        data = Path(temporary) / 'data'
        def git(*args, input=None):
            return subprocess.run(['git', '--literal-pathspecs', '-C', str(data), *args],
                                  input=input, stdout=subprocess.PIPE, check=True).stdout
        print('Reading the private test-data manifest (GitHub access required)...', flush=True)
        subprocess.run(['git', 'clone', '--quiet', '--config', 'core.autocrlf=false',
                        '--filter=blob:none', '--no-checkout', '--depth', '1',
                        repository, str(data)], check=True)
        entries = json.loads(git('show', 'HEAD:manifest.json'))['files']
        missing, installed = missing_files(entries, target, check=check)
        if not missing:return dict(verified=installed, restored=0, installed=installed)
        paths = sorted({item['path'] for item in missing})
        for relative in paths:inside(data, relative)
        tree = {}
        for record in git('ls-tree', '-rz', 'HEAD').split(b'\0'):
            if not record:continue
            meta, name = record.split(b'\t', 1)
            mode, kind, oid = meta.split()
            if mode in (b'100644', b'100755') and kind == b'blob':tree[name.decode('utf-8')] = oid
        absent = set(paths) - tree.keys()
        if absent:raise ValueError(f'Fixture missing from remote snapshot: {sorted(absent)[0]}')
        print(f'Downloading {len(paths)} missing test files; old research is excluded...', flush=True)
        objects = sorted({tree[p] for p in paths})
        # Fetch all needed blobs together instead of one network request per checkout file.
        git('-c', 'fetch.negotiationAlgorithm=noop', 'fetch', '--quiet', '--filter=blob:none', '--no-tags',
            '--no-write-fetch-head', '--stdin', 'origin', input=b'\n'.join(objects) + b'\n')
        git('restore', '--source=HEAD', '--worktree', '--pathspec-from-file=-', '--pathspec-file-nul',
            input=b'\0'.join(p.encode('utf-8') for p in paths) + b'\0')
        (data / 'manifest.json').write_text(json.dumps(dict(files=missing)), encoding='utf-8')
        result = restore(data, target)
        return dict(verified=installed, restored=result['restored'], installed=installed)


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument('data', type=Path, nargs='?', help='existing local data repository')
    cli.add_argument('--download', action='store_true', help='download only missing required files from the private repo')
    cli.add_argument('--target', type=Path, default=ROOT, help='fresh project checkout (defaults to this checkout)')
    cli.add_argument('--check', action='store_true', help='verify the data repository and restored files without writing')
    args = cli.parse_args(argv)
    if bool(args.data) == args.download:cli.error('choose a local data folder or --download')
    try:
        result = download(args.target, check=args.check) if args.download else restore(args.data, args.target, check=args.check)
        print(json.dumps(result));return 0
    except (OSError, EOFError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f'Fixtures not restored: {error}', file=sys.stderr);return 1


if __name__ == '__main__':raise SystemExit(main())
