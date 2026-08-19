from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from canada_funeral_intel.model_gateway import nvidia_chat_config
from canada_funeral_intel.people.agent_review import (
    AgentReviewError,
    RoundRobinKeys,
    _response_json,
)

PROMPT_VERSION = "website-quality-review-v1"
CLASSES = {
    "usable",
    "limited",
    "blocked",
    "retry",
    "duplicate_shared_domain",
    "manual_lookup",
}
METHODS = {"http", "playwright", "targeted_page", "manual_lookup", "none"}


def _write_failure_artifact(
    output_path: Path | None,
    *,
    model: str,
    provider: str,
    error: str,
    attempts: int,
) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "agent": "website-quality",
                "database_changed": False,
                "model": model,
                "provider": provider,
                "prompt_version": PROMPT_VERSION,
                "status": "failed",
                "attempts": attempts,
                "error": error,
                "recommendations": [],
            },
            indent=2,
        )
        + "\n"
    )


def review_websites(
    connection: sqlite3.Connection,
    *,
    model: str,
    provider: str,
    output_path: Path | None = None,
    keys_file: Path | None = None,
) -> dict[str, object]:
    rows = connection.execute(
        """
        SELECT w.id AS website_id, w.url AS requested_url,
          c.outcome, c.dns_status, c.tls_status, c.http_status_code,
          c.https_status_code, c.soft_404, c.parked_or_for_sale,
          c.identity_score, c.final_url, c.error_message,
          (SELECT COUNT(*) FROM website_pages p WHERE p.website_id=w.id) AS page_count,
          (SELECT COUNT(*) FROM website_pages p WHERE p.website_id=w.id AND p.last_status_code BETWEEN 200 AND 299) AS successful_pages,
          (SELECT COUNT(*) FROM website_pages p WHERE p.website_id=w.id AND (p.last_status_code IS NULL OR p.last_status_code NOT BETWEEN 200 AND 299)) AS failed_or_unfetched_pages,
          (SELECT COUNT(*) FROM website_pages p WHERE p.website_id=w.id AND p.last_content_type LIKE 'text/html%') AS html_pages
        FROM websites w
        LEFT JOIN website_checks c ON c.id=(SELECT c2.id FROM website_checks c2 WHERE c2.website_id=w.id ORDER BY c2.checked_at DESC,c2.id DESC LIMIT 1)
        ORDER BY w.id
        """
    ).fetchall()
    records = [dict(row) for row in rows]
    recommendations: list[dict[str, object]] = []
    for offset in range(0, len(records), 12):
        batch = records[offset : offset + 12]
        prompt = (
            "Review website acquisition evidence. Return one JSON object with a "
            "recommendations array containing exactly one item per website_id. "
            "Use fields website_id, classification, next_method, confidence, "
            "rationale, and evidence_reference. classification must be usable, "
            "limited, blocked, retry, duplicate_shared_domain, or manual_lookup. next_method must be http, "
            "playwright, targeted_page, manual_lookup, or none. Use only supplied "
            "evidence and never change records. evidence_reference must be website_id:<number> "
            "or a supplied URL.\n\n" + json.dumps(batch, ensure_ascii=False)
        )
        api_key = (
            os.environ.get("NVIDIA_API_KEY", "").strip()
            if provider == "nvidia"
            else os.environ.get("OPENAI_API_KEY", "").strip()
        )
        keys = (
            RoundRobinKeys(keys_file or Path("~/openrouter_keys.txt"))
            if provider == "openrouter"
            else None
        )
        if provider == "nvidia":
            endpoint, request_model, api_key = nvidia_chat_config(model)
        else:
            endpoint = {
                "openrouter": "https://openrouter.ai/api/v1/chat/completions",
                "openai": "https://api.openai.com/v1/chat/completions",
            }.get(provider)
            request_model = model
        if endpoint is None or (provider != "nvidia" and not api_key and keys is None):
            raise AgentReviewError(
                f"{provider.upper()}_API_KEY is not set or provider unsupported"
            )
        body = {
            "model": request_model,
            "max_tokens": max(2500, len(batch) * 220),
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a conservative website-quality reviewer.",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        for attempt in range(3):
            request = Request(
                endpoint,
                data=json.dumps(body).encode(),
                headers={
                    "Authorization": f"Bearer {keys.next() if keys else api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=90) as response:
                    payload = json.loads(response.read().decode())
                break
            except HTTPError as exc:
                detail = exc.read().decode(errors="replace")
                if exc.code not in {408, 429, 500, 502, 503, 504, 529} or attempt == 2:
                    error = f"{provider} API HTTP {exc.code}: {detail[:500]}"
                    _write_failure_artifact(
                        output_path,
                        model=model,
                        provider=provider,
                        error=error,
                        attempts=attempt + 1,
                    )
                    raise AgentReviewError(
                        error
                    ) from exc
                time.sleep(2**attempt)
            except (URLError, TimeoutError, OSError) as exc:
                if attempt == 2:
                    error = f"{provider} API request failed: {exc}"
                    _write_failure_artifact(
                        output_path,
                        model=model,
                        provider=provider,
                        error=error,
                        attempts=attempt + 1,
                    )
                    raise AgentReviewError(
                        error
                    ) from exc
                time.sleep(2**attempt)
        try:
            items = _response_json(payload)["recommendations"]
            expected = {int(item["website_id"]) for item in batch}
            if (
                not isinstance(items, list)
                or {item.get("website_id") for item in items} != expected
            ):
                raise AgentReviewError(
                    "website-quality response omitted or duplicated website IDs"
                )
            for item in items:
                if (
                    set(item)
                    != {
                        "website_id",
                        "classification",
                        "next_method",
                        "confidence",
                        "rationale",
                        "evidence_reference",
                    }
                    or item["classification"] not in CLASSES
                    or item["next_method"] not in METHODS
                    or not isinstance(item["rationale"], str)
                    or not isinstance(item["evidence_reference"], str)
                    or not 0 <= item["confidence"] <= 1
                ):
                    raise AgentReviewError(
                        "website-quality response failed schema validation"
                    )
            recommendations.extend(items)
        except AgentReviewError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AgentReviewError(
                "website-quality response did not match schema"
            ) from exc
    result = {
        "agent": "website-quality",
        "database_changed": False,
        "website_count": len(records),
        "model": model,
        "provider": provider,
        "prompt_version": PROMPT_VERSION,
        "recommendations": recommendations,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n")
        result["output"] = str(output_path)
    return result
