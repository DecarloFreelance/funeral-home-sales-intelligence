from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class DatabaseConfigurationError(RuntimeError):
    pass


class DatabaseCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    sslmode: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "PostgresConfig":
        values = environment or os.environ
        required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGSSLMODE")
        missing = [name for name in required if not values.get(name)]
        if missing:
            raise DatabaseConfigurationError(
                "Missing PostgreSQL environment settings: " + ", ".join(missing)
            )
        try:
            port = int(values["PGPORT"])
        except ValueError as error:
            raise DatabaseConfigurationError("PGPORT must be an integer") from error
        sslmode = values["PGSSLMODE"].lower()
        if sslmode not in {"require", "verify-ca", "verify-full"}:
            raise DatabaseConfigurationError(
                "PGSSLMODE must require TLS (require, verify-ca, or verify-full)"
            )
        return cls(values["PGHOST"], port, values["PGDATABASE"], values["PGUSER"], sslmode)


class PsqlRunner:
    """Single credential-safe PostgreSQL command boundary.

    libpq reads PG* variables and ~/.pgpass itself. Credentials are never put in
    argv, SQL, logs, or repository files.
    """

    def __init__(self, config: PostgresConfig | None = None, executable: str = "psql"):
        self.config = config or PostgresConfig.from_environment()
        resolved = shutil.which(executable)
        if not resolved:
            raise DatabaseConfigurationError(f"PostgreSQL client not found: {executable}")
        self.executable = resolved

    def run(
        self,
        sql: str,
        *,
        tuples_only: bool = False,
        variables: Mapping[str, str] | None = None,
    ) -> str:
        command: list[str] = [
            self.executable,
            "-X",
            "--no-psqlrc",
            "--set=ON_ERROR_STOP=1",
            "--dbname",
            self.config.database,
        ]
        if tuples_only:
            command.extend(("--tuples-only", "--no-align"))
        for name, value in sorted((variables or {}).items()):
            command.append(f"--set={name}={value}")
        environment = os.environ.copy()
        environment.update({
            "PGHOST": self.config.host,
            "PGPORT": str(self.config.port),
            "PGDATABASE": self.config.database,
            "PGUSER": self.config.user,
            "PGSSLMODE": self.config.sslmode,
        })
        result = subprocess.run(
            command,
            input=sql,
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        if result.returncode:
            # psql/libpq do not echo passwords; keep the exception bounded to
            # stderr and never include the inherited environment or argv.
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown error"
            raise DatabaseCommandError(f"PostgreSQL command failed: {detail}")
        return result.stdout.strip()

    def run_file(self, path: Path) -> str:
        return self.run(path.read_text(encoding="utf-8"))
