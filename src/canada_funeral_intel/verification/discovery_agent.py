from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from canada_funeral_intel.model_gateway import nvidia_chat_config
from canada_funeral_intel.people.agent_review import AgentReviewError, _response_json

PROMPT_VERSION = "website-discovery-v1"


def _network_error(exc: BaseException, provider: str) -> AgentReviewError:
    if isinstance(exc, HTTPError):
        return AgentReviewError(
            f"{provider} returned HTTP {exc.code}; retry later"
        )
    return AgentReviewError(f"{provider} search failed: {exc}")


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


def _searxng_search(query: str, base_url: str) -> list[dict[str, str]]:
    queries = [query]
    fallback_query = query.removesuffix(" official website").strip()
    if fallback_query and fallback_query != query:
        queries.append(fallback_query)
    unavailable_engines: list[str] = []
    for search_query in queries:
        endpoint = base_url.rstrip("/") + "/search?" + urlencode(
            {
                "q": search_query,
                "format": "json",
                "categories": "general",
                "language": "en",
            }
        )
        request = Request(endpoint, headers={"Accept": "application/json"})
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
        for engine in payload.get("unresponsive_engines", []):
            if isinstance(engine, list) and engine:
                unavailable_engines.append(": ".join(map(str, engine)))
            elif engine:
                unavailable_engines.append(str(engine))
        results = payload.get("results", [])
        normalized = [
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "description": str(item.get("content", item.get("description", ""))),
            }
            for item in results[:5]
            if item.get("url")
        ]
        if normalized:
            return normalized
    if unavailable_engines:
        engines = ", ".join(dict.fromkeys(unavailable_engines))
        raise AgentReviewError(
            "SearXNG returned no results because search engines are unavailable: "
            + engines
        )
    return []


def _records(connection: sqlite3.Connection, limit: int, offset: int) -> list[dict[str, object]]:
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
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


def discover_missing_websites(
    connection: sqlite3.Connection,
    *,
    model: str,
    provider: str,
    output_path: Path | None = None,
    entity_limit: int = 10,
    entity_offset: int = 0,
    live_search: bool = False,
    search_provider: str = "searxng",
) -> dict[str, object]:
    if not 1 <= entity_limit <= 25:
        raise AgentReviewError("entity_limit must be between 1 and 25")
    if entity_offset < 0:
        raise AgentReviewError("entity_offset must be zero or greater")
    records = _records(connection, entity_limit, entity_offset)
    search_evidence: list[dict[str, object]] = []
    if live_search and records:
        if search_provider not in {"brave", "searxng"}:
            raise AgentReviewError("search_provider must be brave or searxng")
        api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
        searxng_url = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8080").strip()
        if search_provider == "brave" and not api_key:
            raise AgentReviewError("BRAVE_SEARCH_API_KEY is required with --search-provider brave")
        if search_provider == "searxng" and not searxng_url:
            raise AgentReviewError("SEARXNG_URL is required with --search-provider searxng")
        for record in records:
            query = f"{record['business_name']} {record.get('city') or ''} {record.get('province') or ''} official website".strip()
            try:
                results = (
                    _brave_search(query, api_key)
                    if search_provider == "brave"
                    else _searxng_search(query, searxng_url)
                )
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                raise _network_error(exc, search_provider) from exc
            record["search_results"] = results
            search_evidence.append({"entity_id": record["entity_id"], "query": query, "results": results})
    if not records:
        result = {"agent": "website-discovery", "database_changed": False,
                  "entity_count": 0, "recommendations": [],
                  "model": model, "provider": provider,
                  "prompt_version": PROMPT_VERSION, "live_search": live_search,
                  "search_provider": search_provider,
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
            "openai": "https://api.openai.com/v1/chat/completions",
        }
        if provider == "nvidia":
            endpoint, request_model, api_key = nvidia_chat_config(model)
        else:
            endpoint = endpoints.get(provider)
            request_model = model
        if endpoint is None or (provider != "nvidia" and not api_key):
            raise AgentReviewError(f"{provider.upper()}_API_KEY is not set or provider unsupported")
        body = {"model": request_model, "max_tokens": max(2500, len(records) * 220),
                "temperature": 0.1,
                "messages": [{"role": "system", "content": "You are a conservative website discovery assistant."},
                             {"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}}
        request = Request(endpoint, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=90) as response:
                raw_response = response.read().decode(errors="replace")
                try:
                    payload = json.loads(raw_response)
                except json.JSONDecodeError as exc:
                    preview = raw_response[:300] or "<empty response>"
                    raise AgentReviewError(
                        f"{provider} returned invalid JSON from {endpoint}: {preview}"
                    ) from exc
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise _network_error(exc, provider) from exc
        decoded = _response_json(payload)
        recommendations = decoded.get("recommendations")
        expected = {int(row["entity_id"]) for row in records}
        if isinstance(recommendations, list):
            for item in recommendations:
                if isinstance(item, dict) and isinstance(item.get("entity_id"), str):
                    try:
                        item["entity_id"] = int(item["entity_id"])
                    except ValueError:
                        pass
        by_entity: dict[int, dict[str, object]] = {}
        duplicate_entities: set[int] = set()
        if isinstance(recommendations, list):
            for item in recommendations:
                if not isinstance(item, dict):
                    continue
                try:
                    entity_id = int(item.get("entity_id"))
                except (TypeError, ValueError):
                    continue
                if entity_id in by_entity:
                    duplicate_entities.add(entity_id)
                else:
                    by_entity[entity_id] = item
        records_by_entity = {int(row["entity_id"]): row for row in records}
        normalized: list[dict[str, object]] = []
        for entity_id in sorted(expected):
            if entity_id not in by_entity or entity_id in duplicate_entities:
                row = records_by_entity[entity_id]
                normalized.append({
                    "entity_id": entity_id,
                    "website_url": None,
                    "confidence": 0.0,
                    "rationale": "Model response was missing or duplicated this entity; no URL accepted.",
                    "search_query": f"{row['business_name']} {row.get('city') or ''} {row.get('province') or ''} official website".strip(),
                })
            else:
                normalized.append(by_entity[entity_id])
        recommendations = normalized
        required_fields = {"entity_id", "website_url", "confidence", "rationale", "search_query"}
        for index, item in enumerate(recommendations):
            if not required_fields.issubset(item):
                raise AgentReviewError("website-discovery response failed schema validation")
            item = {field: item[field] for field in required_fields}
            recommendations[index] = item
            if isinstance(item["website_url"], str) and item["website_url"].startswith("http://"):
                item["website_url"] = "https://" + item["website_url"][len("http://"):]
            if item["website_url"] is not None and (not isinstance(item["website_url"], str) or not item["website_url"].startswith("https://")):
                raise AgentReviewError("website-discovery website_url must be https or null")
            if not isinstance(item["confidence"], (int, float)) or not 0 <= item["confidence"] <= 1:
                raise AgentReviewError("website-discovery confidence must be between 0 and 1")
        result = {"agent": "website-discovery", "database_changed": False,
                  "entity_count": len(records), "model": model, "provider": provider,
                  "prompt_version": PROMPT_VERSION, "live_search": live_search,
                  "search_provider": search_provider,
                  "search_evidence": search_evidence, "recommendations": recommendations}
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        result["output"] = str(output_path)
    return result
