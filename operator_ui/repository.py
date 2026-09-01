import json
import sqlite3
from operator_ui.outreach_actions import draft_id, load_approvals
from pathlib import Path


class OperatorRepository:
    def __init__(self, data_root: Path, crm_db: Path | None = None, findings_path: Path | None = None):
        self.data_root = Path(data_root).resolve()
        self.crm_db = Path(crm_db).resolve() if crm_db else self.data_root / "crm.sqlite"
        self.findings_path = Path(findings_path).resolve() if findings_path else None

    def _json(self, relative_path, default):
        path = (self.data_root / relative_path).resolve()
        if self.data_root not in path.parents:
            raise ValueError("Data path is outside the configured data directory")
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def queue(self):
        value = self._json("crawl_queue.json", [])
        return value if isinstance(value, list) else []

    def crawl_report(self):
        value = self._json("discovered_leads_report.json", {})
        return value if isinstance(value, dict) else {}

    def research(self):
        value = self._json("research_queue.json", [])
        if not isinstance(value, list):
            return []
        resolutions = self._json("generated/enrichment/research_resolution_results.json", [])
        by_domain = {
            item.get("domain"): item.get("research_resolution")
            for item in resolutions if isinstance(item, dict)
        } if isinstance(resolutions, list) else {}
        return [
            {**item, "research_resolution": by_domain.get(item.get("domain"))}
            for item in value
        ]

    def leads(self):
        value = self._json("generated/enrichment/results.json", None)
        if not isinstance(value, list):
            value = self._json("generated/campaign/results.json", None)
        if not isinstance(value, list):
            value = self._json("discovered_results.json", [])
        if not isinstance(value, list):
            return []
        return sorted(
            value,
            key=lambda item: item.get("executive_priority_score", item.get("sales_priority_score", 0)) or 0,
            reverse=True,
        )

    def lead(self, domain):
        return next((item for item in self.leads() if item.get("domain") == domain), None)

    def findings(self):
        if self.findings_path:
            try:
                payload = json.loads(self.findings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return [], {}
            records = payload.get("records") if isinstance(payload, dict) else []
            summary = payload.get("summary") if isinstance(payload, dict) else {}
            if isinstance(summary, dict) and isinstance(payload, dict) and payload.get("version"):
                summary = {**summary, "version": payload["version"]}
            return (
                records if isinstance(records, list) else [],
                summary if isinstance(summary, dict) else {},
            )
        records = self._json(
            "generated/directory_955/full_955_enrichment_v17/full_955_enrichment.json", []
        )
        summary = self._json(
            "generated/directory_955/full_955_enrichment_v17/summary.json", {}
        )
        # Read-only compatibility for development/test data roots not yet
        # materialized to V17. Production supplies an explicit V17 snapshot.
        if not records:
            records = self._json(
                "generated/directory_955/full_955_enrichment_v15/full_955_enrichment.json", []
            )
            summary = self._json(
                "generated/directory_955/full_955_enrichment_v15/summary.json", {}
            )
        if not isinstance(records, list):
            records = []
        if not isinstance(summary, dict):
            summary = {}
        findings = []
        for record in records:
            if not isinstance(record, dict):
                continue
            enrichment = record.get("branch_safe_enrichment") or {}
            findings.append({
                "directory_record_id": record.get("directory_record_id", ""),
                "company": record.get("company", ""),
                "city": record.get("city", ""),
                "province": record.get("province", ""),
                "website": record.get("website", ""),
                "website_verification": record.get("website_status", ""),
                "emails": enrichment.get("emails") or [],
                "phones": enrichment.get("phones") or [],
                "staff": enrichment.get("staff") or [],
                "decision_makers": enrichment.get("decision_makers") or [],
                "has_any_contact": bool(enrichment.get("has_any_contact")),
            })
        return findings, summary

    def finding(self, record_id):
        records, _summary = self.findings()
        return next((row for row in records if row.get("directory_record_id") == record_id), None)

    def quality_review(self):
        value = self._json("generated/enrichment/review_queue.json", [])
        if not isinstance(value, list):
            return []
        resolutions = self._json("generated/enrichment/research_resolution_results.json", [])
        by_domain = {
            item.get("domain"): item.get("research_resolution")
            for item in resolutions if isinstance(item, dict)
        } if isinstance(resolutions, list) else {}
        return [
            {**item, "research_resolution": by_domain.get(item.get("domain"))}
            for item in value
        ]

    def candidates(self):
        value = self._json("generated/platform/platform_candidate_results.json", [])
        if not isinstance(value, list):
            return []
        return sorted(value, key=lambda item: item.get("priority_score", 0) or 0, reverse=True)

    def drafts(self):
        value = self._json("generated/platform/platform_candidate_outreach.json", [])
        if not isinstance(value, list):
            return []
        candidates = self.candidates()
        usable = {
            str(email).strip().lower()
            for candidate in candidates
            for email in candidate.get("usable_emails", [])
        }
        try:
            approvals = {
                item.get("draft_id"): item
                for item in load_approvals(self.data_root)
            }
        except (OSError, json.JSONDecodeError):
            approvals = {}
        records = []
        for draft in value:
            identifier = draft_id(draft)
            recipient = str(draft.get("to", "")).strip().lower()
            records.append({
                **draft,
                "draft_id": identifier,
                "approval": approvals.get(identifier),
                "approval_eligible": bool(recipient and recipient in usable),
            })
        return records

    def crm_actions(self):
        if not self.crm_db.is_file():
            return []
        try:
            with sqlite3.connect(self.crm_db) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT id, domain, action_type, priority, status, due_date,
                           notes, created_at, started_at, completed_at
                    FROM action_queue
                    ORDER BY
                        CASE status WHEN 'IN_PROGRESS' THEN 1 WHEN 'OPEN' THEN 2 ELSE 3 END,
                        due_date,
                        id
                    """
                ).fetchall()
            return [dict(row) for row in rows]
        except (sqlite3.Error, OSError):
            return []

    def crm_has_lead(self, domain):
        if not self.crm_db.is_file():
            return False
        try:
            with sqlite3.connect(self.crm_db) as connection:
                return connection.execute(
                    "SELECT 1 FROM leads WHERE domain=?", (domain,)
                ).fetchone() is not None
        except (sqlite3.Error, OSError):
            return False

    def summary(self):
        queue = self.queue()
        report = self.crawl_report()
        actions = self.crm_actions()
        return {
            "queued": len(queue),
            "crawled": report.get("successful_domains", 0),
            "failed": len(report.get("failed_domains", [])),
            "research": len(self.research()),
            "leads": len(self.leads()),
            "quality_review": len(self.quality_review()),
            "candidates": len(self.candidates()),
            "drafts": len(self.drafts()),
            "open_actions": sum(action.get("status") in {"OPEN", "IN_PROGRESS"} for action in actions),
        }
