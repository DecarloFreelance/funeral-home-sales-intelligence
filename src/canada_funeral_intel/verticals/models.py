from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerticalProfile:
    key: str
    display_name: str
    profile_version: str
    aliases: tuple[str, ...]
    page_keywords: tuple[str, ...]
    role_keywords: tuple[str, ...]
    excluded_content: tuple[str, ...]
    fact_keys: tuple[str, ...]
