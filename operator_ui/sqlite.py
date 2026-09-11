from contextlib import contextmanager
import sqlite3


@contextmanager
def connection(*args, **kwargs):
    """Commit or roll back a SQLite transaction, then always close it."""
    database = sqlite3.connect(*args, **kwargs)
    try:
        with database:
            yield database
    finally:
        database.close()