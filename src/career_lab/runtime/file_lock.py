"""Advisory file locks on an open stream: ``flock`` on POSIX, ``msvcrt.locking`` on Windows.

The journals and stores that share a file between the API and the workers lock it for the
duration of one append or one critical section. On POSIX that is ``fcntl.flock``; Windows
has no ``fcntl``, so the same two calls lock the first byte of the file through ``msvcrt``.
Both release the lock when the stream is closed.
"""

from __future__ import annotations

import sys
from typing import IO

if sys.platform == "win32":
    import msvcrt

    def flock(stream: IO, *, blocking: bool = True) -> None:
        """Take an exclusive lock; ``BlockingIOError`` when held elsewhere and not blocking."""
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise BlockingIOError(str(error)) from error

    def funlock(stream: IO) -> None:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            # Closing the stream releases the lock as well.
            pass

else:
    import fcntl

    def flock(stream: IO, *, blocking: bool = True) -> None:
        """Take an exclusive lock; ``BlockingIOError`` when held elsewhere and not blocking."""
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))

    def funlock(stream: IO) -> None:
        fcntl.flock(stream, fcntl.LOCK_UN)
