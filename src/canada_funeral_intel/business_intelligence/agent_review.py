from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from canada_funeral_intel.business_intelligence.storage import list_business_facts
from canada_funeral_intel.model_gateway import nvidia_chat_config
from canada_funeral_intel.people.agent_review import (
    AgentReviewError,
    RoundRobinKeys,
    _response_json,
)

PROMPT_VERSION = "business-facts-review-v1"
ALLOWED = {"keep", "flag", "reject"}


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
                "agent": "business-facts",
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
            ensure_ascii=False,
        )
        + "\n"
    )


def _validate(value: object, expected: set[int]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise AgentReviewError("business-facts recommendations must be an array")
    result = []
    seen: set[int] = set()
    required = {
        "fact_id",
        "disposition",
        "confidence",
        "rationale",
        "evidence_reference",
    }
    for item in value:
        if not isinstance(item, dict) or set(item) != required:
            raise AgentReviewError(
                "business-facts recommendation has unexpected or missing fields"
            )
        fact_id = item["fact_id"]
        if isinstance(fact_id, bool) or not isinstance(fact_id, int):
            raise AgentReviewError("business-facts fact_id must be an integer")
        if fact_id not in expected or fact_id in seen:
            raise AgentReviewError(
                "business-facts response contains an unknown or duplicate fact_id"
            )
        if item["disposition"] not in ALLOWED:
            raise AgentReviewError(
                "business-facts response contains an invalid disposition"
            )
        for field in ("rationale", "evidence_reference"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise AgentReviewError(f"business-facts {field} must be non-empty text")
        evidence_reference = item["evidence_reference"].strip()
        if not evidence_reference.startswith(
            ("http://", "https://", "website_page_id:")
        ):
            raise AgentReviewError(
                "business-facts evidence_reference must be a supplied URL "
                "or website_page_id reference"
            )
        confidence = item["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise AgentReviewError("business-facts confidence must be between 0 and 1")
        seen.add(fact_id)
        result.append(dict(item))
    if seen != expected:
        missing = sorted(expected - seen)
        raise AgentReviewError(
            f"business-facts response omitted fact_id(s): {', '.join(map(str, missing))}"
        )
    return result


def review_business_facts(
    connection: sqlite3.Connection,
    *,
    model: str,
    output_path: Path | None = None,
    provider: str = "openai",
    keys_file: Path | None = None,
    _records: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    request_model = model
    if _records is None:
        records = [
            {
                "fact_id": int(row["id"]),
                "website_page_id": int(row["website_page_id"]),
                "source_url": row["source_url"],
                "fact_key": row["fact_key"],
                "raw_value": row["raw_value"],
                "normalized_value": row["normalized_value"],
                "scope": row["scope"],
                "extractor_confidence": row["confidence"],
                "evidence_snippet": row["evidence_snippet"],
            }
            for row in list_business_facts(connection)
        ]
    else:
        records = _records
    if len(records) > 12:
        recommendations = []
        for offset in range(0, len(records), 12):
            batch = review_business_facts(
                connection,
                model=model,
                output_path=None,
                provider=provider,
                keys_file=keys_file,
                _records=records[offset : offset + 12],
            )
            recommendations.extend(batch["recommendations"])
        result = {
            "agent": "business-facts",
            "database_changed": False,
            "fact_count": len(records),
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "provider": provider,
            "recommendations": recommendations,
        }
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n"
            )
            result["output"] = str(output_path)
        return result
    prompt = (
        "Review these stored business-fact observations using only their supplied evidence. "
        "Return one JSON object with a recommendations array containing exactly one item "
        "for every fact_id. Use fields fact_id, disposition, confidence, rationale, and "
        "evidence_reference. evidence_reference must be the supplied source URL or "
        "website_page_id:<number>, never an evidence-snippet phrase. disposition must "
        "be keep, flag, or reject. Keep means the "
        "fact is directly supported; flag means it needs human review; reject means the "
        "extraction is unsupported or clearly wrong. Never invent facts.\n\n"
        + json.dumps(records, ensure_ascii=False)
    )
    if provider == "openrouter":
        keys = RoundRobinKeys(keys_file or Path("~/openrouter_keys.txt"))
        api_key = None
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
    elif provider == "nvidia":
        keys = None
        endpoint, request_model, api_key = nvidia_chat_config(model)
    elif provider == "openai":
        keys = None
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        endpoint = "https://api.openai.com/v1/chat/completions"
    else:
        raise AgentReviewError(f"unsupported provider: {provider}")
    if provider != "nvidia" and not api_key and keys is None:
        raise AgentReviewError(f"{provider.upper()}_API_KEY is not set")
    body = {
        "model": request_model,
        "max_tokens": max(3000, len(records) * 220),
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": "You are a conservative evidence-review assistant.",
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    last_error = ""
    attempts = 0
    for attempt in range(3):
        attempts = attempt + 1
        request = Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {keys.next() if keys else api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = f"{provider} API HTTP {exc.code}: {detail[:500]}"
            if exc.code not in {408, 409, 429, 500, 502, 503, 504, 529} or attempt == 2:
                _write_failure_artifact(
                    output_path,
                    model=model,
                    provider=provider,
                    error=last_error,
                    attempts=attempts,
                )
                raise AgentReviewError(last_error) from exc
            time.sleep(2**attempt)
        except (URLError, TimeoutError, OSError) as exc:
            last_error = f"{provider} API request failed: {exc}"
            if attempt == 2:
                _write_failure_artifact(
                    output_path,
                    model=model,
                    provider=provider,
                    error=last_error,
                    attempts=attempts,
                )
                raise AgentReviewError(last_error) from exc
            time.sleep(2**attempt)
    try:
        decoded = _response_json(payload)
        recommendations = _validate(
            decoded["recommendations"], {r["fact_id"] for r in records}
        )
    except AgentReviewError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentReviewError(
            "business-facts response did not match review schema"
        ) from exc
    result = {
        "agent": "business-facts",
        "database_changed": False,
        "fact_count": len(records),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "provider": provider,
        "recommendations": recommendations,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        result["output"] = str(output_path)
    return result
