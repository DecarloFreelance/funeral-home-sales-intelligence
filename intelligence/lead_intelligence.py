from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class LeadIntelligence:
    """
    Canonical intelligence container.

    Normalizes existing lead scoring output into
    a stable internal structure.
    """

    company: Dict[str, Any] = field(default_factory=dict)
    website: Dict[str, Any] = field(default_factory=dict)
    contacts: Dict[str, Any] = field(default_factory=dict)
    scoring: Dict[str, Any] = field(default_factory=dict)
    opportunity: Dict[str, Any] = field(default_factory=dict)
    outreach: Dict[str, Any] = field(default_factory=dict)
    crm: Dict[str, Any] = field(default_factory=dict)


    @classmethod
    def from_result(cls, result: Dict[str, Any]):
        """
        Convert existing results.json records
        into canonical intelligence format.
        """

        return cls(

            company={
                "domain": result.get("domain"),
                "lead_type": result.get("lead_type"),
                "prospect_type": result.get("prospect_type"),
            },

            website={
                "pages": result.get("pages"),
                "found": result.get("found", []),
                "missing": result.get("missing", []),
                "evidence": result.get("evidence", {}),
            },

            contacts={
                "emails_found": result.get("emails_found", []),
                "phones_found": result.get("phones_found", []),
                "primary_email": result.get("primary_email"),
                "primary_phone": result.get("primary_phone"),
                "email_confidence": result.get("email_confidence"),
                "phone_confidence": result.get("phone_confidence"),
                "contact_quality_score": result.get(
                    "contact_quality_score"
                ),
            },

            scoring={
                "conversion": result.get("conversion"),
                "opportunity": result.get("opportunity"),
                "lead_value": result.get("lead_value"),
                "priority": result.get("priority"),
                "sales_readiness": result.get("sales_readiness"),
                "sales_stage": result.get("sales_stage"),
                "executive_priority_score": result.get(
                    "executive_priority_score"
                ),
            },

            opportunity={
                "revenue_opportunity_score": result.get(
                    "revenue_opportunity_score"
                ),
                "revenue_tier": result.get("revenue_tier"),
                "revenue_reason": result.get("revenue_reason"),
                "digital_opportunity_score": result.get(
                    "digital_opportunity_score"
                ),
                "partnership_opportunity_score": result.get(
                    "partnership_opportunity_score"
                ),
            },

            outreach={
                "campaign": result.get("campaign"),
                "campaign_type": result.get("campaign_type"),
                "outreach_priority": result.get(
                    "outreach_priority"
                ),
                "outreach_channel": result.get(
                    "outreach_channel"
                ),
                "recommended_pitch": result.get(
                    "recommended_pitch"
                ),
                "outreach_package": result.get(
                    "outreach_package"
                ),
                "personalization_profile": result.get(
                    "personalization_profile"
                ),
            },

            crm={
                "crm_status": result.get("crm_status"),
                "sales_lane": result.get("sales_lane"),
            }
        )


    def to_dict(self):
        return {
            "company": self.company,
            "website": self.website,
            "contacts": self.contacts,
            "scoring": self.scoring,
            "opportunity": self.opportunity,
            "outreach": self.outreach,
            "crm": self.crm,
        }
