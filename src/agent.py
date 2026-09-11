"""Constrained local agent helpers.

This module intentionally has no model, shell, network, database, or write
capability. A supervising application may consume the read-only tool contract
and provide its own separately reviewed model integration.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT_PATH = Path(__file__).resolve().with_name("prompt_system.md")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    function: Callable[[str], str]
    description: str


def _confined_path(path: str) -> Path:
    candidate = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError as error:
        raise ValueError("Path must remain inside the repository") from error
    if not candidate.is_file():
        raise FileNotFoundError(path)
    return candidate


def read_file(path: str) -> str:
    """Read one existing UTF-8 file beneath the repository root."""
    return _confined_path(path).read_text(encoding="utf-8")


TOOLS = (
    ToolSpec("read_file", read_file, "Read an existing UTF-8 file in the repository."),
)


def build_prompt(message: str) -> list[dict[str, str]]:
    """Build a side-effect-free prompt payload for an external supervisor."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")},
        {"role": "user", "content": message},
    ]


def runtime_state() -> dict[str, object]:
    return {
        "working_directory": str(ROOT),
        "os": os.name,
        "available_tools": [tool.name for tool in TOOLS],
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m src.agent \\\"user query\\\"")
    print(json.dumps({"state": runtime_state(), "prompt": build_prompt(sys.argv[1])}, indent=2))
