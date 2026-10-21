"""The coordinator's OS-released lease, also used by exceptional offline recovery."""
from contextlib import contextmanager
import os


@contextmanager
def writer_lease(marker, *, message='Another coordinator owns this shared database'):
    with marker.open('r+b') as handle:
        if os.name == 'nt':
            import msvcrt
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
        try:
            acquire()
        except OSError:
            raise ValueError(message) from None
        try:
            yield handle
        finally:
            handle.seek(0)
            release()
