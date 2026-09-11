from __future__ import annotations

from contextlib import contextmanager
import os


@contextmanager
def exclusive(file_object, *, blocking=True):
    """Hold an exclusive lock on an open file across POSIX and Windows."""
    if os.name == "nt":
        import msvcrt

        file_object.seek(0)
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        try:
            msvcrt.locking(file_object.fileno(), mode, 1)
        except OSError as error:
            if not blocking:
                raise BlockingIOError(*error.args) from error
            raise
        try:
            yield file_object
        finally:
            file_object.seek(0)
            msvcrt.locking(file_object.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(file_object.fileno(), flags)
        try:
            yield file_object
        finally:
            fcntl.flock(file_object.fileno(), fcntl.LOCK_UN)
