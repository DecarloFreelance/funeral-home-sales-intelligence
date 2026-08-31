from __future__ import annotations

import re
from pathlib import Path

from persistence.postgres import PsqlRunner


MIGRATIONS = Path(__file__).with_name("sql")
MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def migration_files(directory: Path = MIGRATIONS) -> list[Path]:
    files = sorted(path for path in directory.glob("*.sql") if MIGRATION_NAME.match(path.name))
    versions = [path.name.split("_", 1)[0] for path in files]
    if len(versions) != len(set(versions)):
        raise ValueError("Duplicate PostgreSQL migration version")
    return files


def applied_versions(runner: PsqlRunner) -> set[str]:
    exists = runner.run(
        "SELECT to_regclass('fhsi.schema_migrations') IS NOT NULL;",
        tuples_only=True,
    )
    if exists.strip() != "t":
        return set()
    rows = runner.run("SELECT version FROM fhsi.schema_migrations ORDER BY version;", tuples_only=True)
    return {row.strip() for row in rows.splitlines() if row.strip()}


def status(runner: PsqlRunner) -> list[dict[str, str]]:
    applied = applied_versions(runner)
    return [
        {"version": path.name.split("_", 1)[0], "file": path.name,
         "status": "applied" if path.name.split("_", 1)[0] in applied else "pending"}
        for path in migration_files()
    ]


def migrate(runner: PsqlRunner) -> list[str]:
    applied = applied_versions(runner)
    completed = []
    for path in migration_files():
        version = path.name.split("_", 1)[0]
        if version in applied:
            continue
        label = path.name.replace("'", "''")
        sql = (
            "BEGIN;\n"
            + path.read_text(encoding="utf-8")
            + f"\nINSERT INTO fhsi.schema_migrations(version, name) VALUES ('{version}', '{label}');\n"
            + "COMMIT;\n"
        )
        runner.run(sql)
        completed.append(version)
    return completed
