from dataclasses import dataclass, field
from typing import Any, Dict

from contact_cleaner import clean_contact_data
from contact_ranker import choose_email, choose_phone

from intelligence.phone_intelligence import (
    phone_quality_score
)


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

            contacts=cls.build_contacts(result),

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
                **cls.build_outreach_priority(
                    result,
                    cls.build_contacts(result)
                ),
            },

            crm={
                "crm_status": result.get("crm_status"),
                "sales_lane": result.get("sales_lane"),
            }
        )



    @classmethod
    def build_contacts(cls, result: Dict[str, Any]):
        """
        Normalize, clean, and rank contact intelligence.
        """

        domain = result.get(
            "domain",
            ""
        )

        raw_emails = result.get(
            "emails_found",
            []
        )

        raw_phones = result.get(
            "phones_found",
            []
        )

        cleaned = clean_contact_data(
            raw_emails,
            raw_phones,
            domain
        )

        primary_email, email_confidence = choose_email(
            cleaned["emails"],
            domain
        )

        primary_phone, phone_confidence = choose_phone(
            cleaned["phones"]
        )

        phone_analysis = phone_quality_score(
            primary_phone
        )

        return {
            "emails_found": cleaned["emails"],
            "phones_found": cleaned["phones"],

            "primary_email": primary_email,
            "email_confidence": email_confidence,

            "primary_phone": primary_phone,
            "phone_confidence": phone_confidence,

            "normalized_phone":
                phone_analysis["normalized"],

            "phone_region_score":
                phone_analysis["score"],

            "phone_reason":
                phone_analysis["reasons"],

            "contact_quality_score": round(
                (
                    email_confidence * 0.35 +
                    phone_confidence * 0.35 +
                    phone_analysis["score"] * 0.30
                ),
                2
            )
        }




    @classmethod
    def build_outreach_priority(cls, result, contacts):
        """
        Generate actionable outreach priority intelligence.
        """

        score = 0

        sales_readiness = result.get(
            "sales_readiness",
            0
        )

        if isinstance(sales_readiness, (int, float)):
            score += sales_readiness


        score += contacts.get(
            "contact_quality_score",
            0
        )


        if contacts.get("primary_email"):
            score += 20


        if contacts.get("phone_region_score"):
            score += contacts.get(
                "phone_region_score",
                0
            ) / 10


        if score >= 180:
            level = "A1 - Immediate Outreach"

        elif score >= 120:
            level = "A2 - Priority Outreach"

        elif score >= 80:
            level = "B1 - Nurture"

        else:
            level = "Research Required"


        if contacts.get("email_confidence", 0) >= 80:
            method = "email"

        elif contacts.get("phone_confidence", 0) >= 80:
            method = "phone"

        else:
            method = "research"


        return {
            "priority_score": round(score,2),
            "priority_level": level,
            "best_contact_method": method
        }


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
