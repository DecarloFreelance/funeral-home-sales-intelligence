from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from canada_funeral_intel.people.agent_review import AgentReviewError, _response_text

PROMPT_VERSION = "website-discovery-v1"


def _brave_search(query: str, api_key: str) -> list[dict[str, str]]:
    endpoint = "https://api.search.brave.com/res/v1/web/search?" + urlencode(
        {"q": query, "country": "CA", "search_lang": "en", "count": 5}
    )
    request = Request(endpoint, headers={
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    })
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode())
    results = payload.get("web", {}).get("results", [])
    return [
        {
            "title": str(item.get("title", "")),
            "url": str(item.get("url", "")),
            "description": str(item.get("description", "")),
        }
        for item in results[:5]
        if item.get("url")
    ]


def _records(connection: sqlite3.Connection, limit: int) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT e.id AS entity_id,
               COALESCE(NULLIF(trim(e.canonical_name), ''), NULLIF(trim(MAX(CASE WHEN nv.field_name='business_name' THEN nv.original_value END)), '')) AS business_name,
               MAX(CASE WHEN nv.field_name='city' THEN nv.normalized_value END) AS city,
               MAX(CASE WHEN nv.field_name='province' THEN nv.normalized_value END) AS province,
               GROUP_CONCAT(DISTINCT w.url) AS existing_urls
        FROM entities e
        JOIN entity_source_records esr ON esr.entity_id=e.id
        JOIN normalized_values nv ON nv.source_record_id=esr.source_record_id
        LEFT JOIN websites w ON w.entity_id=e.id
        WHERE e.status='active'
          AND NOT EXISTS (SELECT 1 FROM websites w WHERE w.entity_id=e.id AND w.status = 'selected')
        GROUP BY e.id
        HAVING business_name IS NOT NULL AND trim(business_name) <> ''
        ORDER BY e.id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def discover_missing_websites(
    connection: sqlite3.Connection,
    *,
    model: str,
    provider: str,
    output_path: Path | None = None,
    entity_limit: int = 10,
    live_search: bool = False,
) -> dict[str, object]:
    if not 1 <= entity_limit <= 25:
        raise AgentReviewError("entity_limit must be between 1 and 25")
    records = _records(connection, entity_limit)
    search_evidence: list[dict[str, object]] = []
    if live_search and records:
        api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
        if not api_key:
            raise AgentReviewError("BRAVE_SEARCH_API_KEY is required with --live-search")
        for record in records:
            query = f"{record['business_name']} {record.get('city') or ''} {record.get('province') or ''} official website".strip()
            results = _brave_search(query, api_key)
            record["search_results"] = results
            search_evidence.append({"entity_id": record["entity_id"], "query": query, "results": results})
    if not records:
        result = {"agent": "website-discovery", "database_changed": False,
                  "entity_count": 0, "recommendations": [],
                  "model": model, "provider": provider,
                  "prompt_version": PROMPT_VERSION, "live_search": live_search,
                  "search_evidence": search_evidence}
    else:
        prompt = (
            "Identify likely official funeral-business websites for these Canadian entities. "
            "Use only the supplied business name and location. Return JSON with a recommendations "
            "array containing exactly one item per entity_id. Use fields entity_id, website_url, "
            "confidence, rationale, and search_query. website_url must be an https URL or null; "
            "do not repeat any URL in existing_urls and do not invent a URL when uncertain. confidence must be 0 to 1. This is discovery only: "
            "never claim verification, ownership, or affiliation. When search_results are supplied, "
            "choose URLs only from those results."
            + "\n\n" + json.dumps(records, ensure_ascii=False)
        )
        api_key = os.environ.get(f"{provider.upper()}_API_KEY", "").strip()
        endpoints = {
            "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
            "openai": "https://api.openai.com/v1/chat/completions",
        }
        endpoint = endpoints.get(provider)
        if endpoint is None or not api_key:
            raise AgentReviewError(f"{provider.upper()}_API_KEY is not set or provider unsupported")
        body = {"model": model, "max_tokens": max(2500, len(records) * 220),
                "temperature": 0.1,
                "messages": [{"role": "system", "content": "You are a conservative website discovery assistant."},
                             {"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}}
        request = Request(endpoint, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode())
        decoded = json.loads(_response_text(payload))
        recommendations = decoded.get("recommendations")
        expected = {int(row["entity_id"]) for row in records}
        if not isinstance(recommendations, list) or {item.get("entity_id") for item in recommendations} != expected:
            raise AgentReviewError("website-discovery response omitted or duplicated entity IDs")
        for item in recommendations:
            if set(item) != {"entity_id", "website_url", "confidence", "rationale", "search_query"}:
                raise AgentReviewError("website-discovery response failed schema validation")
            if item["website_url"] is not None and (not isinstance(item["website_url"], str) or not item["website_url"].startswith("https://")):
                raise AgentReviewError("website-discovery website_url must be https or null")
            if not isinstance(item["confidence"], (int, float)) or not 0 <= item["confidence"] <= 1:
                raise AgentReviewError("website-discovery confidence must be between 0 and 1")
        result = {"agent": "website-discovery", "database_changed": False,
                  "entity_count": len(records), "model": model, "provider": provider,
                  "prompt_version": PROMPT_VERSION, "live_search": live_search,
                  "search_evidence": search_evidence, "recommendations": recommendations}
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        result["output"] = str(output_path)
    return result
