from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.request import Request, urlopen

from canada_funeral_intel.people.agent_review import AgentReviewError, _response_text

PROMPT_VERSION = "website-candidate-review-v1"
DECISIONS = {"approved", "rejected", "deferred"}


def review_website_candidates(
    connection: sqlite3.Connection,
    *, model: str, provider: str, output_path: Path | None = None,
    queue_limit: int = 10,
) -> dict[str, object]:
    if not 1 <= queue_limit <= 25:
        raise AgentReviewError("queue_limit must be between 1 and 25")
    rows = connection.execute(
        """
        SELECT rq.id AS queue_id, w.id AS website_id, w.entity_id, w.url, w.domain,
               w.confidence, e.canonical_name,
               MAX(CASE WHEN nv.field_name='city' THEN nv.normalized_value END) AS city,
               MAX(CASE WHEN nv.field_name='province' THEN nv.normalized_value END) AS province,
               c.outcome, c.http_status_code, c.https_status_code, c.identity_score,
               c.final_url, c.error_message
        FROM website_review_queue rq
        JOIN websites w ON w.id=rq.website_id
        JOIN entities e ON e.id=w.entity_id
        LEFT JOIN entity_source_records esr ON esr.entity_id=e.id
        LEFT JOIN normalized_values nv ON nv.source_record_id=esr.source_record_id
        LEFT JOIN website_checks c ON c.id=(SELECT c2.id FROM website_checks c2 WHERE c2.website_id=w.id ORDER BY c2.checked_at DESC,c2.id DESC LIMIT 1)
        WHERE rq.status='pending'
        GROUP BY rq.id, w.id, w.entity_id, w.url, w.domain, w.confidence, e.canonical_name,
                 c.outcome, c.http_status_code, c.https_status_code, c.identity_score,
                 c.final_url, c.error_message
        ORDER BY rq.priority DESC, rq.id
        LIMIT ?
        """, (queue_limit,)
    ).fetchall()
    records = [dict(row) for row in rows]
    if not records:
        result = {"agent": "website-candidate-review", "database_changed": False,
                  "queue_count": 0, "recommendations": [], "model": model,
                  "provider": provider, "prompt_version": PROMPT_VERSION}
    else:
        prompt = (
            "Review pending website candidates conservatively. Compare the candidate URL and domain "
            "with the supplied business name and location. Use verification evidence when present. "
            "Return JSON with exactly one recommendation per queue_id. Fields: queue_id, decision, "
            "confidence, rationale, reviewer_note. decision must be approved, rejected, or deferred. "
            "Approve only when identity is sufficiently supported; otherwise defer. Never infer approval "
            "from URL plausibility alone.\n\n" + json.dumps(records, ensure_ascii=False)
        )
        api_key = os.environ.get(f"{provider.upper()}_API_KEY", "").strip()
        endpoint = {"nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
                    "openai": "https://api.openai.com/v1/chat/completions"}.get(provider)
        if endpoint is None or not api_key:
            raise AgentReviewError(f"{provider.upper()}_API_KEY is not set or provider unsupported")
        body = {"model": model, "max_tokens": max(2500, len(records) * 220),
                "temperature": 0.1,
                "messages": [{"role": "system", "content": "You are a conservative website identity reviewer."},
                             {"role": "user", "content": prompt}]}
        request = Request(endpoint, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode())
        response_text = _response_text(payload).strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[-1]
            if response_text.endswith("```"):
                response_text = response_text[:-3].rstrip()
        decoded = json.loads(response_text)
        for _ in range(3):
            if not isinstance(decoded, str):
                break
            nested = decoded.strip()
            if nested.startswith("```"):
                nested = nested.split("\n", 1)[-1]
                if nested.endswith("```"):
                    nested = nested[:-3].rstrip()
            try:
                decoded = json.loads(nested)
            except json.JSONDecodeError:
                break
        if isinstance(decoded, str):
            text = decoded.strip()
            starts = [position for position in (text.find("{"), text.find("[")) if position >= 0]
            if starts:
                candidate = text[min(starts):]
                try:
                    decoded, _ = json.JSONDecoder().raw_decode(candidate)
                except json.JSONDecodeError:
                    pass
        if isinstance(decoded, list):
            recommendations = decoded
        elif isinstance(decoded, dict):
            recommendations = decoded.get("recommendations")
            if recommendations is None:
                recommendations = decoded.get("decisions")
            if recommendations is None:
                recommendations = decoded.get("results")
            if recommendations is None:
                for key in (
                    "items", "reviews", "review", "recommendation",
                    "website_reviews", "review_recommendations", "data", "answer",
                ):
                    if decoded.get(key) is not None:
                        recommendations = decoded[key]
                        break
            if recommendations is None and ("queue_id" in decoded or "queueId" in decoded):
                recommendations = [decoded]
        else:
            recommendations = None
        expected = {int(row["queue_id"]) for row in records}
        if not isinstance(recommendations, list):
            if isinstance(decoded, dict):
                shape = ", ".join(
                    f"{key}={type(value).__name__}" for key, value in decoded.items()
                ) or "empty object"
                raise AgentReviewError(
                    "website-candidate-review response omitted recommendations "
                    f"(returned: {shape}; text={str(decoded)[:160]!r})"
                )
            raise AgentReviewError("website-candidate-review response omitted recommendations")
        normalized: list[dict[str, object]] = []
        for item in recommendations:
            if not isinstance(item, dict):
                raise AgentReviewError("website-candidate-review recommendation is not an object")
            queue_id = item.get("queue_id", item.get("queueId", item.get("id")))
            if isinstance(queue_id, str) and queue_id.strip().isdigit():
                item = {key: value for key, value in item.items() if key not in {"queueId", "id"}}
                item["queue_id"] = int(queue_id.strip())
            elif isinstance(queue_id, int) and "queue_id" not in item:
                item = {key: value for key, value in item.items() if key not in {"queueId", "id"}}
                item["queue_id"] = queue_id
            normalized.append(item)
        recommendations = normalized
        if {item.get("queue_id") for item in recommendations} != expected:
            raise AgentReviewError("website-candidate-review response omitted or duplicated queue IDs")
        for item in recommendations:
            if set(item) != {"queue_id", "decision", "confidence", "rationale", "reviewer_note"}:
                raise AgentReviewError("website-candidate-review response failed schema validation")
            if item["decision"] not in DECISIONS or not isinstance(item["rationale"], str) or not item["rationale"].strip():
                raise AgentReviewError("website-candidate-review recommendation is invalid")
            if not isinstance(item["confidence"], (int, float)) or not 0 <= item["confidence"] <= 1:
                raise AgentReviewError("website-candidate-review confidence is invalid")
        result = {"agent": "website-candidate-review", "database_changed": False,
                  "queue_count": len(records), "model": model, "provider": provider,
                  "prompt_version": PROMPT_VERSION, "recommendations": recommendations}
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        result["output"] = str(output_path)
    return result
