from __future__ import annotations

import sqlite3

from .models import RefreshObservation
from .storage import (
    begin_run,
    complete_run,
    fail_run,
    list_changes,
    list_runs,
    record_observation,
    show_run,
)


def run_refresh_begin(connection: sqlite3.Connection, **kwargs): return {"run_id": begin_run(connection, **kwargs)}
def run_refresh_record(connection: sqlite3.Connection, *, run_id: int, subject_type: str, subject_key: str, semantic_fingerprint: str, reference_id: int | None, metadata_json: str): return record_observation(connection, run_id=run_id, observation=RefreshObservation(subject_type, subject_key, semantic_fingerprint, reference_id, metadata_json))
def run_refresh_complete(connection: sqlite3.Connection, run_id: int): return complete_run(connection, run_id)
def run_refresh_fail(connection: sqlite3.Connection, **kwargs): return fail_run(connection, **kwargs)
def run_refresh_runs(connection: sqlite3.Connection, **kwargs): return list_runs(connection, **kwargs)
def run_refresh_changes(connection: sqlite3.Connection, **kwargs): return list_changes(connection, **kwargs)
def run_refresh_show(connection: sqlite3.Connection, run_id: int): return show_run(connection, run_id)
