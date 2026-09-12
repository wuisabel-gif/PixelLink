"""Bounded reads of regular local files; never open devices or wait on FIFOs."""
import os
import stat
from pathlib import Path


def read_regular(path, limit):
    """Read at most limit+1 bytes after validating the opened descriptor."""
    fd = os.open(Path(path), os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Input must be a regular file')
        if info.st_size > limit:
            raise ValueError('Input exceeds size limit')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Input exceeds size limit')
        if len(data) != info.st_size:
            raise ValueError('Input changed size while being read')
        return data
    finally:
        if fd is not None:
            os.close(fd)
