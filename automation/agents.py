from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from enrichment.company import VERSION as ENRICHMENT_VERSION, enrich_company
from enrichment.quality import VERSION as QUALITY_VERSION, evaluate_quality


class RecordAgent(ABC):
    name: str
    version: str
    max_attempts: int = 3

    @abstractmethod
    def fingerprint_payload(self, context: Dict[str, Any]) -> Any:
        """Return only inputs that determine this agent's output."""

    @abstractmethod
    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return a bounded, JSON-serializable output patch."""


class EnrichmentAgent(RecordAgent):
    name = "enrichment"
    version = ENRICHMENT_VERSION

    def fingerprint_payload(self, context):
        return {
            "domain": context["domain"],
            "pages": context.get("pages", []),
            "business_profile": context.get("record", {}).get("business_profile", {}),
            "contact_intelligence": context.get("record", {}).get("contact_intelligence", {}),
        }

    def run(self, context):
        record = context.get("record", {})
        return {"enrichment": enrich_company(
            context["domain"], context.get("pages", []),
            record.get("business_profile", {}), record.get("contact_intelligence", {}),
        )}


class QualityControlAgent(RecordAgent):
    name = "quality_control"
    version = QUALITY_VERSION

    def fingerprint_payload(self, context):
        record = context.get("record", {})
        return {
            "domain": context["domain"],
            "enrichment": record.get("enrichment", {}),
            "contact_intelligence": record.get("contact_intelligence", {}),
            "executive_priority_score": record.get("executive_priority_score"),
            "sales_priority_score": record.get("sales_priority_score"),
        }

    def run(self, context):
        return {"quality_control": evaluate_quality(context["record"])}
