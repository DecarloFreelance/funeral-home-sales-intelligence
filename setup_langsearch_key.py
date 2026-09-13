#!/usr/bin/env python3
"""One-time local setup for the LangSearch API key.

Prompts for the key without echoing it and writes it into the local,
git-ignored `.env` file (the mechanism `.env.example` already documents).
`resolve_955_websites.py` loads that file via python-dotenv before
constructing `discovery.langsearch_provider`, so once this has been run, no
further export/setup is needed in later sessions. The key itself is never
printed, logged, or committed.
"""

from __future__ import annotations

import getpass
from pathlib import Path

ENV_PATH = Path(".env")
KEY_NAME = "LANGSEARCH_API_KEY"


def upsert_env_var(text: str, key: str, value: str) -> str:
    """Return `text` with `key=value` set, replacing any existing line for
    `key` in place and preserving every other line and its order."""
    lines = text.splitlines() if text else []
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{prefix}{value}"
            break
    else:
        lines.append(f"{prefix}{value}")
    return "\n".join(lines) + "\n"


def main() -> int:
    key = getpass.getpass(f"{KEY_NAME} (from https://langsearch.com/dashboard): ").strip()
    if not key:
        print("No key entered; .env was not changed.")
        return 1

    existing = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.is_file() else ""
    ENV_PATH.write_text(upsert_env_var(existing, KEY_NAME, key), encoding="utf-8")
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass  # best-effort; not every filesystem honors POSIX permission bits

    print(f"Saved {KEY_NAME} to {ENV_PATH} (not printed, not tracked by Git).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
