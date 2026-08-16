from __future__ import annotations

import hashlib
import json
from typing import Any

from . import REFRESH_POLICY_VERSION


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: dict[str, Any]) -> str:
    payload = {"policy_version": REFRESH_POLICY_VERSION, **value}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def page_observation(
    *,
    website_id: int,
    normalized_url: str,
    page_kind: str,
    content_hash: str,
    status_code: int | None,
    content_type: str | None,
) -> tuple[str, str]:
    key = f"website:{website_id}|url:{normalized_url}"
    return key, fingerprint(
        {
            "subject_type": "website_page",
            "website_id": website_id,
            "normalized_url": normalized_url,
            "page_kind": page_kind,
            "content_hash": content_hash,
            "status_code": status_code,
            "content_type": content_type,
        }
    )


def person_observation(
    *,
    page_id: int,
    normalized_name: str,
    normalized_role: str,
    normalized_email: str,
    normalized_phone: str,
    branch_context: str | None,
) -> tuple[str, str]:
    key = f"page:{page_id}|name:{normalized_name}|role:{normalized_role}|email:{normalized_email}|phone:{normalized_phone}"
    return key, fingerprint(
        {
            "subject_type": "person_observation",
            "page_id": page_id,
            "normalized_name": normalized_name,
            "normalized_role": normalized_role,
            "normalized_email": normalized_email,
            "normalized_phone": normalized_phone,
            "branch_context": branch_context or "",
        }
    )


def business_fact(
    *,
    page_id: int,
    fact_key: str,
    scope: str,
    scope_entity_id: int | None,
    normalized_value: str,
    value_kind: str,
    content_hash: str,
) -> tuple[str, str]:
    key = f"page:{page_id}|fact:{fact_key}|scope:{scope}|scope_entity:{scope_entity_id or ''}|value:{normalized_value}"
    return key, fingerprint(
        {
            "subject_type": "business_fact",
            "page_id": page_id,
            "fact_key": fact_key,
            "scope": scope,
            "scope_entity_id": scope_entity_id,
            "normalized_value": normalized_value,
            "value_kind": value_kind,
            "content_hash": content_hash,
        }
    )
