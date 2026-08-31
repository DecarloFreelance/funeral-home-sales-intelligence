from __future__ import annotations

import argparse
import getpass
import sqlite3
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash


ALLOWED_USERS = ("Alex", "Todd")
DUMMY_HASH = generate_password_hash("not-a-real-password")


class AuthStore:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()

    def initialize(self, password: str) -> None:
        if len(password) < 7:
            raise ValueError("Password must contain at least 7 characters")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS users (
                       username_key TEXT PRIMARY KEY,
                       display_name TEXT NOT NULL UNIQUE,
                       password_hash TEXT NOT NULL,
                       is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
                   )"""
            )
            for username in ALLOWED_USERS:
                connection.execute(
                    """INSERT INTO users(username_key, display_name, password_hash, is_active)
                       VALUES (?, ?, ?, 1)
                       ON CONFLICT(username_key) DO UPDATE SET
                         display_name=excluded.display_name,
                         password_hash=excluded.password_hash,
                         is_active=1""",
                    (username.casefold(), username, generate_password_hash(password)),
                )
            placeholders = ",".join("?" for _ in ALLOWED_USERS)
            connection.execute(
                f"DELETE FROM users WHERE username_key NOT IN ({placeholders})",
                tuple(username.casefold() for username in ALLOWED_USERS),
            )
        self.path.chmod(0o600)

    def authenticate(self, username: str, password: str) -> str | None:
        row = None
        if self.path.is_file():
            try:
                with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as connection:
                    row = connection.execute(
                        "SELECT display_name, password_hash, is_active FROM users WHERE username_key=?",
                        (str(username or "").strip().casefold(),),
                    ).fetchone()
            except sqlite3.Error:
                row = None
        password_hash = row[1] if row else DUMMY_HASH
        valid = check_password_hash(password_hash, str(password or ""))
        return row[0] if row and row[2] and valid else None

    def users(self) -> list[str]:
        if not self.path.is_file():
            return []
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as connection:
            return [row[0] for row in connection.execute(
                "SELECT display_name FROM users WHERE is_active=1 ORDER BY username_key"
            )]


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the local operator UI credential store.")
    parser.add_argument("--database", type=Path, default=Path("instance/operator_auth.sqlite"))
    args = parser.parse_args()
    password = getpass.getpass("Shared initial password for Alex and Todd: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match")
    store = AuthStore(args.database)
    store.initialize(password)
    print(f"Provisioned {', '.join(store.users())} in {args.database}; no plaintext password was stored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
