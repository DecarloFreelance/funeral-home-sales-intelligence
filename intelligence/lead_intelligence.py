from dataclasses import dataclass, field
from typing import Any, Dict

from contact_cleaner import clean_contact_data
from contact_ranker import choose_email, choose_phone
from crm.status_engine import initial_status, follow_up_schedule

from intelligence.phone_intelligence import (
    phone_quality_score,
    verify_phones,
)
from intelligence.email_intelligence import validate_emails


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

        contacts = cls.build_contacts(result)
        outreach_priority = cls.build_outreach_priority(
            result,
            contacts
        )
        crm_state = cls.build_crm_state(
            result,
            outreach_priority["priority_level"],
            outreach_priority["best_contact_method"]
        )

        business_profile = result.get("business_profile", {})

        return cls(

            company={
                "domain": result.get("domain"),
                "lead_type": result.get("lead_type"),
                "prospect_type": result.get("prospect_type"),
                "name": business_profile.get("company"),
                "business_names": business_profile.get("business_names", []),
                "locations": business_profile.get("locations", []),
                "sources": business_profile.get("sources", []),
                "provenance": business_profile.get("provenance", []),
            },

            website={
                "pages": result.get("pages"),
                "found": result.get("found", []),
                "missing": result.get("missing", []),
                "evidence": result.get("evidence", {}),
            },

            contacts=contacts,

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
                **outreach_priority,
            },

            crm={
                "crm_status": result.get("crm_status"),
                "sales_lane": result.get("sales_lane"),
                **crm_state,
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

        extracted = result.get(
            "contact_intelligence",
            {}
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
        email_validation = extracted.get(
            "email_validation"
        ) or validate_emails(cleaned["emails"], domain)
        phone_verification = extracted.get(
            "phone_verification"
        ) or verify_phones(cleaned["phones"])

        return {
            "emails_found": cleaned["emails"],
            "phones_found": cleaned["phones"],

            "primary_email": primary_email,
            "email_confidence": email_confidence,
            "email_validation": email_validation,

            "primary_phone": primary_phone,
            "phone_confidence": phone_confidence,
            "phone_verification": phone_verification,

            "normalized_phone":
                phone_analysis["normalized"],

            "phone_region_score":
                phone_analysis["score"],

            "phone_reason":
                phone_analysis["reasons"],

            "business_names": extracted.get(
                "business_names", []
            ),

            "addresses": extracted.get(
                "addresses", []
            ),

            "people": extracted.get(
                "people", []
            ),

            "directory_contacts": extracted.get(
                "directory_contacts", []
            ),

            "completeness_score": extracted.get(
                "completeness_score", 0
            ),

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



    @classmethod
    def build_crm_state(
        cls,
        result,
        priority=None,
        method=None
    ):
        """
        Generate CRM workflow state.
        """

        priority = priority or result.get(
            "outreach_priority", ""
        )

        method = method or result.get(
            "outreach_channel", "email"
        )


        state = initial_status(
            priority,
            method
        )


        state["follow_up_date"] = follow_up_schedule(
            priority
        )

        state["attempt_count"] = 0

        state["engagement_score"] = result.get(
            "sales_readiness",
            0
        )


        return state


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
