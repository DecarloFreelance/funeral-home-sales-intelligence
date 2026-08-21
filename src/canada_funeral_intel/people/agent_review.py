from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from canada_funeral_intel.model_gateway import nvidia_chat_config
from canada_funeral_intel.people.models import PersonReviewStatus
from canada_funeral_intel.people.resolution import list_person_review_queue


class AgentReviewError(RuntimeError):
    """Raised when API-assisted review cannot complete safely."""


_PROMPT_VERSION = "people-review-v6"


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
                "agent": "people-review",
                "database_changed": False,
                "model": model,
                "provider": provider,
                "prompt_version": _PROMPT_VERSION,
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


class RoundRobinKeys:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        try:
            raw_lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise AgentReviewError(f"Cannot read OpenRouter key file: {exc}") from exc
        self.keys = tuple(
            line.strip().split("=", 1)[-1].strip().strip("\"'")
            for line in raw_lines
            if line.strip() and not line.lstrip().startswith("#")
        )
        if not self.keys:
            raise AgentReviewError("OpenRouter key file contains no usable keys")
        self._position = 0
        self._lock = threading.Lock()

    def next(self) -> str:
        with self._lock:
            key = self.keys[self._position % len(self.keys)]
            self._position += 1
            return key


_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "queue_id": {"type": "integer"},
                    "recommendation": {
                        "type": "string",
                        "enum": ["accept_candidate", "defer", "reject", "no_change"],
                    },
                    "cleaned_name": {"type": "string"},
                    "cleaned_role": {"type": "string"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                    "evidence_reference": {"type": "string"},
                },
                "required": [
                    "queue_id",
                    "recommendation",
                    "cleaned_name",
                    "cleaned_role",
                    "confidence",
                    "rationale",
                    "evidence_reference",
                ],
            },
        }
    },
    "required": ["recommendations"],
}


def _response_text(payload: dict[str, object]) -> str:
    def content_text(value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            for key in ("text", "content", "reasoning_content", "reasoning"):
                text = content_text(value.get(key))
                if text is not None:
                    return text
        if isinstance(value, list):
            parts = [content_text(item) for item in value]
            joined = "".join(part for part in parts if part)
            if joined.strip():
                return joined
        return None

    text = payload.get("output_text")
    if isinstance(text, str) and text.strip():
        return text
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            text = content_text(message.get("content"))
            if text is not None:
                return text
            text = content_text(message.get("reasoning_content"))
            if text is not None:
                return text
        if isinstance(choices[0], dict):
            text = content_text(choices[0].get("text"))
            if text is not None:
                return text
            text = content_text(choices[0].get("reasoning_content"))
            if text is not None:
                return text
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for key in ("content", "text", "output_text", "reasoning_content", "reasoning"):
            text = content_text(item.get(key))
            if text is not None:
                return text
    nested = payload.get("response")
    if isinstance(nested, dict):
        try:
            return _response_text(nested)
        except AgentReviewError:
            pass
    for key in ("result", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            try:
                return _response_text(nested)
            except AgentReviewError:
                pass
        elif isinstance(nested, list):
            text = content_text(nested)
            if text is not None:
                return text
    # Some compatible gateways wrap the OpenAI response in a top-level
    # message or return a response object as a JSON string.
    for key in ("message", "response", "result", "data"):
        value = payload.get(key)
        text = content_text(value)
        if text is not None:
            return text
    keys = ", ".join(sorted(str(key) for key in payload))
    choices = payload.get("choices")
    choice_shape = ""
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice_shape = "; choice keys=" + ", ".join(sorted(str(key) for key in choices[0]))
        message = choices[0].get("message")
        if isinstance(message, dict):
            choice_shape += "; message keys=" + ", ".join(sorted(str(key) for key in message))
    raise AgentReviewError(
        "Responses API returned no text output"
        f" (top-level keys={keys or 'none'}{choice_shape})"
    )


def _response_json(payload: dict[str, object]) -> object:
    """Decode JSON returned by chat models, including fenced JSON replies."""

    text = _response_text(payload).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        starts = sorted(
            position
            for position in (text.find("{"), text.find("["))
            if position >= 0
        )
        for start in starts:
            try:
                decoded, _ = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            return decoded
        raise


def _validate_recommendations(
    value: object,
    expected_queue_ids: set[int],
) -> list[dict[str, object]]:
    """Validate model output before it can become an operator artifact."""
    if not isinstance(value, list):
        raise AgentReviewError("agent response recommendations must be an array")

    recommendations: list[dict[str, object]] = []
    seen: set[int] = set()
    allowed = {"accept_candidate", "defer", "reject", "no_change"}
    for item in value:
        if not isinstance(item, dict):
            raise AgentReviewError(
                "agent response contains a non-object recommendation"
            )
        required = {
            "queue_id",
            "recommendation",
            "cleaned_name",
            "cleaned_role",
            "confidence",
            "rationale",
            "evidence_reference",
        }
        if set(item) != required:
            raise AgentReviewError(
                "agent response recommendation has unexpected or missing fields"
            )
        queue_id = item["queue_id"]
        if isinstance(queue_id, bool) or not isinstance(queue_id, int):
            raise AgentReviewError("agent response queue_id must be an integer")
        if queue_id not in expected_queue_ids or queue_id in seen:
            raise AgentReviewError(
                "agent response contains an unknown or duplicate queue_id"
            )
        recommendation = item["recommendation"]
        if not isinstance(recommendation, str) or recommendation not in allowed:
            raise AgentReviewError("agent response contains an invalid recommendation")
        for field in ("rationale", "evidence_reference"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise AgentReviewError(f"agent response {field} must be non-empty text")
        if recommendation == "accept_candidate":
            for field in ("cleaned_name", "cleaned_role"):
                if not isinstance(item[field], str) or not item[field].strip():
                    raise AgentReviewError(
                        f"accepted candidate {field} must be non-empty text"
                    )
        confidence = item["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise AgentReviewError("agent response confidence must be between 0 and 1")
        seen.add(queue_id)
        recommendations.append(dict(item))

    if seen != expected_queue_ids:
        missing = sorted(expected_queue_ids - seen)
        raise AgentReviewError(
            f"agent response omitted queue_id(s): {', '.join(map(str, missing))}"
        )
    return recommendations


def review_deferred_people(
    connection: sqlite3.Connection,
    *,
    model: str,
    output_path: Path | None = None,
    provider: str = "openai",
    keys_file: Path | None = None,
    agent: str = "people-review",
    queue_limit: int = 10,
    apply_safe: bool = False,
    minimum_confidence: float = 0.95,
) -> dict[str, object]:
    if not 1 <= queue_limit <= 25:
        raise AgentReviewError("queue_limit must be between 1 and 25")
    if not 0 <= minimum_confidence <= 1:
        raise AgentReviewError("minimum_confidence must be between 0 and 1")
    request_model = model
    if provider == "openrouter":
        if keys_file is None:
            keys_file = Path("~/openrouter_keys.txt")
        keys = RoundRobinKeys(keys_file)
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
    elif provider == "nvidia":
        endpoint, request_model, api_key = nvidia_chat_config(model)
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise AgentReviewError("OPENAI_API_KEY is not set")
        endpoint = "https://api.openai.com/v1/responses"
        request_model = model

    rows = [
        row
        for row in list_person_review_queue(connection, status=None)
        if row["status"]
        in {PersonReviewStatus.PENDING.value, PersonReviewStatus.DEFERRED.value}
        and "history" not in str(row["source_url"]).casefold()
    ][:queue_limit]
    records = [
        {
            "queue_id": int(row["queue_id"]),
            "observed_name": row["observed_name"],
            "role_title": row["role_title"],
            "normalized_role": row["normalized_role"],
            "source_url": row["source_url"],
            "evidence_snippet": row["evidence_snippet"],
        }
        for row in rows
    ]
    if not records:
        result = {
            "model": model,
            "provider": provider,
            "agent": agent,
            "prompt_version": _PROMPT_VERSION,
            "pending_or_deferred_considered": 0,
            "deferred_considered": 0,
            "recommendations": [],
            "database_changed": False,
        }
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n"
            )
            result["output"] = str(output_path)
        return result
    prompt = (
        "Review these pending or deferred funeral-home people observations. Use only the supplied "
        "evidence. Recommend, do not execute, a disposition. Accept_candidate is "
        "allowed only when the evidence clearly identifies a real named person; "
        "historical people from history pages should be rejected for the current "
        "personnel dataset, not accepted as current staff. Never invent contact data. "
        "For malformed names, provide the likely cleaned name only when directly "
        "supported by the evidence. Return a single JSON object whose only top-level "
        "field is recommendations. recommendations must be an array containing "
        "exactly one object for every queue_id. "
        "Use the exact field names queue_id, recommendation, cleaned_name, "
        "cleaned_role, confidence, rationale, and evidence_reference. For reject "
        "or no_change, cleaned_name and cleaned_role may be empty strings; "
        "accepted candidates must have both fields populated. "
        "evidence_reference must identify a supplied source URL or page/observation "
        "identifier. recommendation must be one of "
        "accept_candidate, defer, reject, or no_change. confidence must be 0 to 1.\n\n"
        + json.dumps(records, ensure_ascii=False)
    )
    if provider in {"openrouter", "nvidia"}:
        body = {
            "model": request_model,
            "max_tokens": max(3000, len(records) * 320),
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
        attempts = min(len(keys.keys), 3) if provider == "openrouter" else 3
        last_error = ""
        for attempt in range(attempts):
            headers = {
                "Authorization": f"Bearer {keys.next() if provider == 'openrouter' else api_key}",
                "Content-Type": "application/json",
            }
            if provider == "openrouter":
                headers.update(
                    {
                        "HTTP-Referer": "https://github.com/canada-funeral-intel",
                        "X-OpenRouter-Title": "Canada Funeral Intel",
                    }
                )
            request = Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urlopen(request, timeout=90) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = f"{provider} API HTTP {exc.code}: {detail[:500]}"
                if exc.code not in {408, 409, 429, 500, 502, 503, 504, 529}:
                    _write_failure_artifact(
                        output_path,
                        model=model,
                        provider=provider,
                        error=last_error,
                        attempts=attempt + 1,
                    )
                    raise AgentReviewError(last_error) from exc
                if attempt + 1 < attempts:
                    time.sleep(2**attempt)
            except (URLError, TimeoutError, OSError) as exc:
                last_error = f"{provider} API request failed: {exc}"
                if attempt + 1 < attempts:
                    time.sleep(2**attempt)
        else:
            _write_failure_artifact(
                output_path,
                model=model,
                provider=provider,
                error=last_error,
                attempts=attempts,
            )
            raise AgentReviewError(last_error)
    else:
        body = {
            "model": model,
            "store": False,
            "input": [
                {
                    "role": "system",
                    "content": "You are a conservative evidence-review assistant.",
                },
                {"role": "user", "content": prompt},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "people_review_recommendations",
                    "strict": True,
                    "schema": _SCHEMA,
                }
            },
        }
        attempts = 0
        last_error = ""
        for attempt in range(3):
            attempts = attempt + 1
            request = Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
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
                last_error = f"OpenAI API HTTP {exc.code}: {detail[:500]}"
                if exc.code not in {408, 409, 429, 500, 502, 503, 504, 529}:
                    _write_failure_artifact(
                        output_path,
                        model=model,
                        provider=provider,
                        error=last_error,
                        attempts=attempts,
                    )
                    raise AgentReviewError(last_error) from exc
                if attempt < 2:
                    time.sleep(2**attempt)
            except (URLError, TimeoutError, OSError) as exc:
                last_error = f"OpenAI API request failed: {exc}"
                if attempt < 2:
                    time.sleep(2**attempt)
        else:
            _write_failure_artifact(
                output_path,
                model=model,
                provider=provider,
                error=last_error,
                attempts=attempts,
            )
            raise AgentReviewError(last_error)

    try:
        decoded = _response_json(payload)
        recommendations = _validate_recommendations(
            decoded["recommendations"],
            {record["queue_id"] for record in records},
        )
    except AgentReviewError:
        raise
    except KeyError as exc:
        available = (
            ", ".join(sorted(decoded.keys()))
            if isinstance(decoded, dict)
            else type(decoded).__name__
        )
        raise AgentReviewError(
            f"agent response is missing top-level field: {exc.args[0]} "
            f"(available: {available or 'none'})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise AgentReviewError(
            f"agent response was not valid JSON at character {exc.pos}"
        ) from exc
    except TypeError as exc:
        raise AgentReviewError(
            f"agent response has invalid JSON structure: {exc}"
        ) from exc
    except ValueError as exc:
        raise AgentReviewError(f"agent response has invalid value: {exc}") from exc

    result = {
        "model": model,
        "provider": provider,
        "agent": agent,
        "prompt_version": _PROMPT_VERSION,
        "pending_or_deferred_considered": len(records),
        "deferred_considered": sum(
            1 for row in rows if row["status"] == PersonReviewStatus.DEFERRED.value
        ),
        "recommendations": recommendations,
        "database_changed": False,
        "safe_apply": apply_safe,
        "minimum_confidence": minimum_confidence,
    }
    applied: list[int] = []
    if apply_safe:
        from canada_funeral_intel.people.resolution import apply_person_review_decision

        rows_by_queue = {int(row["queue_id"]): row for row in rows}
        for item in recommendations:
            if float(item["confidence"]) < minimum_confidence:
                continue
            recommendation = str(item["recommendation"])
            if recommendation == "accept_candidate":
                source_url = str(rows_by_queue[int(item["queue_id"])] ["source_url"])
                if "history" in source_url.casefold():
                    continue
                status = PersonReviewStatus.ACCEPTED
            elif recommendation == "reject":
                status = PersonReviewStatus.REJECTED
            elif recommendation == "defer":
                status = PersonReviewStatus.DEFERRED
            else:
                continue
            apply_person_review_decision(
                connection,
                queue_id=int(item["queue_id"]),
                status=status,
                reviewer_note=(
                    f"Safe agent apply ({minimum_confidence:.2f}+ confidence): "
                    f"{item['rationale']}"
                ),
            )
            applied.append(int(item["queue_id"]))
        result["applied_queue_ids"] = applied
        result["applied"] = len(applied)
        result["database_changed"] = bool(applied)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        result["output"] = str(output_path)
    return result
