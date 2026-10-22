"""Expire only coordinator-owned JSONL and known optional OCR crops; never follow links."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import stat


def regular(path, root):
    """Check every component, including Windows junctions, before touching a file."""
    root=Path(root).absolute();path=Path(path).absolute()
    if root.resolve()!=root:return False
    if not path.is_relative_to(root):return False
    for component in (root,*reversed(path.relative_to(root).parents),path):
        target=component if component.is_absolute() else root/component
        if target.is_symlink() or getattr(target,'is_junction',lambda:False)():return False
    return stat.S_ISREG(path.stat().st_mode)


def header(path):
    with path.open('rb') as handle:data=handle.readline(65537)
    if len(data)>65536 or not data.endswith(b'\n'):return {}
    value=json.loads(data)
    return value if isinstance(value,dict) else {}


def own(directory, database):
    marker=directory/'.retention-owner.json'
    with marker.open('x',encoding='utf-8') as handle:json.dump(str(Path(database).resolve()),handle)


def register(root, database, store):
    """Adopt legacy coordinator directories only if every capture belongs to this DB."""
    root=Path(root)
    if not root.is_dir():return
    known={r[0] for r in store.db.execute('SELECT run_id FROM diagnostic_runs')}
    for directory in root.iterdir():
        if directory.is_symlink() or getattr(directory,'is_junction',lambda:False)() or not directory.is_dir():continue
        marker=directory/'.retention-owner.json'
        if marker.exists():continue
        logs=list(directory.glob('*/capture.jsonl'))+list(directory.glob('*/*/capture.jsonl'))
        try:
            if logs and all(regular(p,root) and header(p).get('run_id') in known for p in logs):own(directory,database)
        except (OSError,ValueError):
            continue  # Unrecognized legacy evidence must not block database retention.


def owned(root, database):
    """This database's coordinator directories under root, oldest first (names begin with a UTC stamp)."""
    root=Path(root).absolute()
    if not root.is_dir() or root.is_symlink() or getattr(root,'is_junction',lambda:False)():return []
    found=[]
    for directory in sorted(root.iterdir()):
        marker=directory/'.retention-owner.json'
        if marker.exists() and regular(marker,root) and json.loads(marker.read_text(encoding='utf-8'))==str(Path(database).resolve()):
            found.append(directory)
    return found


def current_operator_log(root, database):
    """A separate worker can't ask the coordinator which operator log is open; the newest one of the newest
    directory may be, even after a quiet day, so it is kept until a later coordinator directory replaces it."""
    directories=owned(root,database)
    logs=sorted(directories[-1].glob('operator*.jsonl'),key=lambda p:p.stat().st_mtime) if directories else []
    return logs[-1:]


def cleanup(root, database, store, *, now=None, dry_run=True, active_logs=(), protected_runs=()):
    """protected_runs: run IDs that may still be capturing; their logs and crops are never removed."""
    root=Path(root).absolute();now=now or datetime.now(timezone.utc)
    cutoff=(now-timedelta(hours=24,minutes=5)).timestamp();active={Path(p).absolute() for p in active_logs}
    report=dict(files=0,bytes=0,dry_run=dry_run,errors=0)
    for directory in owned(root,database):
        logs=list(directory.glob('*/capture.jsonl'))+list(directory.glob('*/*/capture.jsonl'))
        candidates=[]
        for path in logs:
            if path in active or not regular(path,root) or path.stat().st_mtime>=cutoff:continue
            run_id=header(path).get('run_id')
            if run_id in protected_runs:continue
            run=store.db.execute('''SELECT r.rowid,r.character_id,a.id FROM diagnostic_runs r
                LEFT JOIN diagnostic_attempts a ON a.run_id=r.run_id WHERE r.run_id=? LIMIT 1''',(run_id,)).fetchone()
            if run and run['id'] is not None:continue
            crops=path.with_suffix('')
            images=[p for name in ('exp.png','level.png') for p in crops.glob(f'[0-9][0-9][0-9][0-9]/{name}')]
            if any(not regular(p,root) or p.stat().st_mtime>=cutoff for p in images):continue
            candidates.extend([*images,path])
        candidates.extend(p for p in directory.glob('operator*.jsonl') if re.fullmatch(r'operator(?:-[0-9]{8}T[0-9]{2}(?:-[0-9]+)?)?\.jsonl',p.name))
        for path in candidates:
            if path in active or not regular(path,root) or path.stat().st_mtime>=cutoff:continue
            size=path.stat().st_size
            if not dry_run:
                try:path.unlink()
                except OSError:  # E.g. still open on Windows: left for a later pass, never forced.
                    report['errors']+=1;continue
            report['files']+=1;report['bytes']+=size
            if not dry_run:
                parent=path.parent
                while parent!=directory:
                    try:parent.rmdir()
                    except OSError:break
                    parent=parent.parent
        # Remove the ownership marker only when its directory is otherwise empty.
        marker=directory/'.retention-owner.json'
        if not dry_run and list(directory.iterdir())==[marker]:
            marker.unlink();directory.rmdir()
    return report


class OperatorLog:
    """Keep long-running operator logs in hourly segments with the existing JSONL format."""
    def __init__(self,directory,*,clock=None):
        self.directory=Path(directory);self.clock=clock or (lambda:datetime.now(timezone.utc));self.handle=None;self.hour=None;self.part=0

    @property
    def path(self):return Path(self.handle.name) if self.handle else None

    def write(self,value):
        hour=self.clock().strftime('%Y%m%dT%H')
        if hour!=self.hour:
            name='operator.jsonl' if self.handle is None else f'operator-{hour}-{self.part}.jsonl'
            if self.handle:self.handle.close()
            self.handle=(self.directory/name).open('x',encoding='utf-8');self.hour=hour;self.part+=1
        return self.handle.write(value)

    def flush(self):
        if self.handle:self.handle.flush()

    def __enter__(self):return self
    def __exit__(self,*args):
        if self.handle:self.handle.close()
