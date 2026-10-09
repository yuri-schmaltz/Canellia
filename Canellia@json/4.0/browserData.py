"""Bounded read-only SQLite snapshots, including committed WAL transactions."""
from pathlib import Path
import sqlite3
import time


def snapshot(path, timeout=3.0):
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    source = sqlite3.connect(uri, uri=True, timeout=0.25)
    destination = sqlite3.connect(':memory:')
    deadline = time.monotonic() + timeout

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError('Browser database snapshot timed out')

    try:
        source.backup(destination, pages=256, progress=progress, sleep=0.05)
    except Exception:
        destination.close()
        raise
    finally:
        source.close()
    return destination
