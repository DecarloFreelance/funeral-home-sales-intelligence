from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .database import transaction

_MIGRATION_FILENAME = re.compile(
    r"^(?P<version>[0-9]{4})_(?P<description>[a-z0-9]+(?:_[a-z0-9]+)*)\.sql$"
)
_SCHEMA_MIGRATIONS_TABLE = "schema_migrations"


class MigrationError(ValueError):
    """Raised when migration discovery, validation, or execution fails."""


@dataclass(frozen=True, slots=True)
class Migration:
    """A validated SQL migration discovered on disk."""

    version: int
    description: str
    path: Path
    checksum: str

    @property
    def name(self) -> str:
        """Return the migration filename."""
        return self.path.name


@dataclass(frozen=True, slots=True)
class AppliedMigration:
    """A migration recorded in the database."""

    version: int
    name: str
    checksum: str
    applied_at: str


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    """Current migration state."""

    discovered: tuple[Migration, ...]
    applied: tuple[AppliedMigration, ...]
    pending: tuple[Migration, ...]
    consistent: bool
    current_version: int


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Outcome of applying pending migrations."""

    applied: tuple[Migration, ...]
    status: MigrationStatus


def parse_migration_filename(filename: str) -> tuple[int, str]:
    """Parse a strict migration filename into version and description."""
    match = _MIGRATION_FILENAME.fullmatch(filename)
    if match is None:
        raise MigrationError(
            f"Invalid migration filename {filename!r}; "
            "expected NNNN_lowercase_description.sql"
        )

    version = int(match.group("version"))
    if version < 1:
        raise MigrationError("Migration version must be at least 0001")

    return version, match.group("description")


def parse_migration_version(filename: str) -> int:
    return parse_migration_filename(filename)[0]


def parse_migration_description(filename: str) -> str:
    return parse_migration_filename(filename)[1]


def is_valid_migration_filename(filename: str) -> bool:
    try:
        parse_migration_filename(filename)
    except MigrationError:
        return False
    return True


def generate_checksum(path: Path) -> str:
    if not path.is_file():
        raise MigrationError(f"Migration file not found: {path}")

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_migrations(migration_dir: Path) -> list[Migration]:
    if not migration_dir.is_dir():
        raise MigrationError(f"Migration directory not found: {migration_dir}")

    migrations: list[Migration] = []
    paths_by_version: dict[int, Path] = {}

    for path in sorted(migration_dir.iterdir(), key=lambda item: item.name):
        if path.name.startswith(".") or not path.is_file():
            continue

        version, description = parse_migration_filename(path.name)
        existing = paths_by_version.get(version)
        if existing is not None:
            raise MigrationError(
                f"Duplicate migration version {version:04d}: "
                f"{existing.name!r} and {path.name!r}"
            )

        paths_by_version[version] = path
        migrations.append(
            Migration(
                version=version,
                description=description,
                path=path,
                checksum=generate_checksum(path),
            )
        )

    migrations.sort(key=lambda migration: (migration.version, migration.name))
    return migrations


def get_migrations(migration_dir: Path) -> list[Migration]:
    return discover_migrations(migration_dir)


def _tracking_table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (_SCHEMA_MIGRATIONS_TABLE,),
    ).fetchone()
    return row is not None


def list_applied_migrations(
    connection: sqlite3.Connection,
) -> list[AppliedMigration]:
    if not _tracking_table_exists(connection):
        return []

    columns = {
        row["name"]
        for row in connection.execute(
            f"PRAGMA table_info({_SCHEMA_MIGRATIONS_TABLE})"
        ).fetchall()
    }
    required = {"version", "name", "checksum", "applied_at"}
    if columns != required:
        raise MigrationError(
            "schema_migrations has an unexpected schema; "
            f"expected {sorted(required)}, got {sorted(columns)}"
        )

    rows = connection.execute(
        "SELECT version, name, checksum, applied_at "
        "FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [
        AppliedMigration(
            version=row["version"],
            name=row["name"],
            checksum=row["checksum"],
            applied_at=row["applied_at"],
        )
        for row in rows
    ]


def migration_status(
    connection: sqlite3.Connection,
    migration_dir: Path,
) -> MigrationStatus:
    discovered = discover_migrations(migration_dir)
    applied = list_applied_migrations(connection)
    discovered_by_version = {migration.version: migration for migration in discovered}

    for record in applied:
        migration = discovered_by_version.get(record.version)
        if migration is None:
            raise MigrationError(
                f"Applied migration {record.version:04d} is missing from disk"
            )
        if migration.name != record.name:
            raise MigrationError(
                f"Applied migration {record.version:04d} was renamed: "
                f"database={record.name!r}, disk={migration.name!r}"
            )
        if migration.checksum != record.checksum:
            raise MigrationError(
                f"Applied migration {record.version:04d} checksum changed"
            )

    applied_versions = {record.version for record in applied}
    pending = tuple(
        migration
        for migration in discovered
        if migration.version not in applied_versions
    )
    return MigrationStatus(
        discovered=tuple(discovered),
        applied=tuple(applied),
        pending=pending,
        consistent=True,
        current_version=max(applied_versions, default=0),
    )


def _split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []

    for line in sql.splitlines(keepends=True):
        buffer.append(line)
        candidate = "".join(buffer).strip()
        if candidate and sqlite3.complete_statement(candidate):
            statements.append(candidate)
            buffer.clear()

    remainder = "".join(buffer).strip()
    if remainder:
        raise MigrationError("Migration contains an incomplete SQL statement")

    return statements


def _execute_sql(connection: sqlite3.Connection, sql: str) -> None:
    statements = _split_sql_statements(sql)
    if not statements:
        raise MigrationError("Migration SQL is empty")

    for statement in statements:
        normalized = statement.lstrip().upper()
        if normalized.startswith(
            ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE")
        ):
            raise MigrationError(
                "Migration files must not contain transaction-control statements"
            )
        connection.execute(statement)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def apply_pending_migrations(
    connection: sqlite3.Connection,
    migration_dir: Path,
) -> MigrationResult:
    initial_status = migration_status(connection, migration_dir)
    applied_now: list[Migration] = []

    for migration in initial_status.pending:
        sql = migration.path.read_text(encoding="utf-8")

        try:
            with transaction(connection):
                _execute_sql(connection, sql)

                if not _tracking_table_exists(connection):
                    raise MigrationError(
                        f"Migration {migration.name!r} did not create schema_migrations"
                    )

                connection.execute(
                    "INSERT INTO schema_migrations "
                    "(version, name, checksum, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        migration.version,
                        migration.name,
                        migration.checksum,
                        _utc_timestamp(),
                    ),
                )
        except sqlite3.Error as exc:
            raise MigrationError(
                f"Failed to apply migration {migration.name!r}: {exc}"
            ) from exc

        applied_now.append(migration)

    final_status = migration_status(connection, migration_dir)
    return MigrationResult(
        applied=tuple(applied_now),
        status=final_status,
    )
