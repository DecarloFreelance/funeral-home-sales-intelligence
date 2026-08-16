from __future__ import annotations

import sqlite3

from .registry import get_profile, list_profiles
from .storage import assign_membership, list_memberships, seed_verticals


def profiles_payload() -> list[dict[str, object]]:
    return [
        {
            "vertical_key": p.key,
            "display_name": p.display_name,
            "profile_version": p.profile_version,
            "aliases": list(p.aliases),
            "page_keywords": list(p.page_keywords),
            "role_keywords": list(p.role_keywords),
            "excluded_content": list(p.excluded_content),
            "fact_keys": list(p.fact_keys),
        }
        for p in list_profiles()
    ]


def profile_payload(key: str) -> dict[str, object]:
    profile = get_profile(key)
    return {
        "vertical_key": profile.key,
        "display_name": profile.display_name,
        "profile_version": profile.profile_version,
        "aliases": list(profile.aliases),
        "page_keywords": list(profile.page_keywords),
        "role_keywords": list(profile.role_keywords),
        "excluded_content": list(profile.excluded_content),
        "fact_keys": list(profile.fact_keys),
    }


def run_verticals_seed(connection: sqlite3.Connection):
    return seed_verticals(connection)


def run_verticals_assign(connection: sqlite3.Connection, **kwargs):
    return assign_membership(connection, **kwargs)


def run_verticals_entities(connection: sqlite3.Connection, vertical_key: str):
    return list_memberships(connection, vertical_key)
