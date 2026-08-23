#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import re

from feature_detector import detect_features
from scoring import calculate_score, calculate_opportunity, priority, lead_value, calculate_revenue_opportunity
from ai_audit import generate_pitch
from report import print_report
from contact_cleaner import clean_contact_data
from contact_ranker import choose_email, choose_phone
from extraction.contact_extractor import extract_contact_intelligence
from enrichment.company import enrich_company
from enrichment.quality import evaluate_quality


parser = argparse.ArgumentParser(
    description="Score crawled funeral-home website pages."
)
parser.add_argument("--input", default="data/generated/campaign/leads.json")
parser.add_argument("--output", default="data/generated/campaign/results.json")
args = parser.parse_args()

INPUT = args.input
OUTPUT = args.output


FEATURES = [
    "contact_form",
    "appointment_booking",
    "online_planner",
    "pricing",
    "preplanning",
    "cremation",
    "burial",
    "lead_capture",
    "chat"
]


def clean_domain(url):

    url = re.sub(
        r"^https?://",
        "",
        url
    )

    return url.split("/")[0].replace(
        "www.",
        ""
    )


def merge_discovery_profile(profile, incoming):
    if not incoming:
        return

    for field in (
        "company", "city", "province", "country", "address", "phone", "email"
    ):
        if not profile.get(field) and incoming.get(field):
            profile[field] = incoming[field]

    for field in ("business_names", "sources", "provenance", "locations"):
        values = incoming.get(field) or []
        for value in values:
            if value not in profile[field]:
                profile[field].append(value)

companies = {}


with open(INPUT, "r", encoding="utf-8") as f:

    leads = json.load(f)



for lead in leads:

    domain = clean_domain(
        lead.get("url","")
    )

    if not domain:
        continue


    if domain not in companies:

        companies[domain] = {
            "pages":0,
            "documents":[],
            "business_profile": {
                "company": "",
                "city": "",
                "province": "",
                "country": "",
                "address": "",
                "phone": "",
                "email": "",
                "business_names": [],
                "sources": [],
                "provenance": [],
                "locations": [],
            }
        }


    companies[domain]["pages"] += 1

    merge_discovery_profile(
        companies[domain]["business_profile"],
        lead.get("discovery", {})
    )


    companies[domain]["documents"].append({

        "url": lead.get("url",""),

        "text": lead.get(
            "markdown",
            ""
        ),

        "metadata": lead.get("metadata", {}),

        "html": lead.get("html", ""),

        "discovery": lead.get("discovery", {})

    })


if leads and not companies:
    raise ValueError("No valid website domains were found in the crawl input")



results=[]



for domain,data in companies.items():


    detected=set()

    feature_scores={}

    evidence={}


    for page in data["documents"]:


        features = detect_features(
            page["text"]
        )


        for feature,score in features.items():

            feature_scores[feature] = max(
                feature_scores.get(feature,0),
                score
            )


            # only count meaningful conversion signals
            if score >= 3:
                detected.add(feature)


                if feature not in evidence:

                    evidence[feature] = {

                        "url": page["url"],

                        "snippet":
                            page["text"][:300]
                    }



    missing = sorted(

        set(FEATURES)

        -

        detected

    )


    # weighted conversion maturity score
    # conversion score only counts revenue infrastructure
    conversion_features = detected.intersection({
        "online_planner",
        "appointment_booking",
        "pricing",
        "lead_capture",
        "chat",
        "contact_form"
    })


    conversion = calculate_score(
        conversion_features
    )


    # final conversion score
    # only revenue infrastructure counts

    conversion = min(
        conversion,
        15
    )


    opportunity = calculate_opportunity(
        missing
    )


    value = lead_value(
        conversion,
        opportunity
    )


    combined_text = " ".join(
        doc["text"]
        for doc in data["documents"]
    )


    contact_intelligence = extract_contact_intelligence(
        data["documents"],
        domain,
        check_email_dns=True,
    )

    enrichment = enrich_company(
        domain,
        data["documents"],
        data["business_profile"],
        contact_intelligence,
    )

    emails_found = contact_intelligence["emails"]

    phones_found = contact_intelligence["phones"]


    contact_confidence = 0


    if emails_found:
        contact_confidence += 50

    if phones_found:
        contact_confidence += 30

    if "contact_form" in detected:
        contact_confidence += 20


    contact_confidence = min(
        contact_confidence,
        100
    )


    outreach_priority = (
        value
        +
        (data["pages"] / 10)
    )


    if outreach_priority >= 35:
        outreach_level = "Immediate Outreach"

    elif outreach_priority >= 25:
        outreach_level = "High Priority Outreach"

    elif outreach_priority >= 15:
        outreach_level = "Standard Outreach"

    else:
        outreach_level = "Nurture"


    if value >= 25 and conversion <= 8:
        lead_type = "Digital Transformation Candidate"
        package = "Complete Digital Funeral Funnel"
        services = [
            "AI grief assistant",
            "Online arrangement workflow",
            "Lead capture system",
            "Appointment automation"
        ]
        reason = [
            "High conversion opportunity",
            "Missing revenue infrastructure",
            "Strong upgrade potential"
        ]

    elif value >= 20:
        lead_type = "Conversion Improvement Candidate"
        package = "Conversion Optimization Package"
        services = [
            "AI website assistant",
            "Lead conversion improvements",
            "Booking automation"
        ]
        reason = [
            "Existing digital foundation",
            "Conversion gaps detected",
            "Optimization opportunity"
        ]

    else:
        lead_type = "Low Priority / Maintenance"
        package = "Digital Optimization Review"
        services = [
            "Performance audit",
            "Automation consultation"
        ]
        reason = [
            "Strong digital maturity",
            "Limited immediate opportunity"
        ]


    value = lead_value(
        conversion,
        opportunity
    )


    contact_confidence = 0


    if emails_found:
        contact_confidence += 50

    if phones_found:
        contact_confidence += 30

    if "contact_form" in detected:
        contact_confidence += 20


    contact_confidence = min(
        contact_confidence,
        100
    )


    outreach_priority = (
        value
        +
        (data["pages"] / 10)
    )


    if outreach_priority >= 35:
        outreach_level = "Immediate Outreach"

    elif outreach_priority >= 25:
        outreach_level = "High Priority Outreach"

    elif outreach_priority >= 15:
        outreach_level = "Standard Outreach"

    else:
        outreach_level = "Nurture"



    sales_readiness = 0

    if contact_confidence >= 80:
        sales_readiness += 20

    if "contact_form" in detected:
        sales_readiness += 15

    if "phone" in detected:
        sales_readiness += 15

    if "team" in detected or "about" in detected:
        sales_readiness += 10

    if value >= 25:
        sales_readiness += 20

    if "lead_capture" in missing:
        sales_readiness += 10

    if "appointment_booking" in missing:
        sales_readiness += 10


    if sales_readiness >= 90:
        sales_stage = "Hot Prospect"

    elif sales_readiness >= 70:
        sales_stage = "Sales Qualified Lead"

    elif sales_readiness >= 50:
        sales_stage = "Nurture Candidate"

    else:
        sales_stage = "Research Required"



    pain_points = []

    if "appointment_booking" in missing:
        pain_points.append("No online appointment booking")

    if "lead_capture" in missing:
        pain_points.append("Limited lead capture system")

    if "online_planner" in missing:
        pain_points.append("No online planning workflow")

    if "chat" in missing:
        pain_points.append("No instant visitor engagement")


    if contact_confidence >= 80:
        recommended_contact_method = "Email + Phone"

    elif contact_confidence >= 50:
        recommended_contact_method = "Email"

    else:
        recommended_contact_method = "Research Required"


    if lead_type == "Digital Transformation Candidate":
        email_angle = "Increase online funeral arrangement enquiries"

        opening_hook = (
            "I noticed your website has strong visibility "
            "but several opportunities exist to improve online conversions."
        )

    elif lead_type == "Conversion Improvement Candidate":
        email_angle = "Improve website conversion performance"

        opening_hook = (
            "I noticed your website is established, "
            "but there are opportunities to capture more enquiries."
        )

    else:
        email_angle = "Digital optimization review"

        opening_hook = (
            "I reviewed your online presence and found "
            "a few areas that may improve customer experience."
        )


    email_subject = (
        "Improving online enquiries for "
        + domain
    )



    # Todd Campaign Intelligence

    seminar_fit = 0
    association_fit = 0


    seminar_text = combined_text.lower()


    community_fit = 0
    education_fit = 0


    seminar_keywords = [
        "seminar",
        "workshop",
        "training",
        "speaker",
        "presentation",
        "webinar",
        "continuing education",
        "professional development"
    ]


    community_keywords = [
        "grief support",
        "grief group",
        "support group",
        "community event",
        "community outreach",
        "remembrance",
        "memorial event",
        "celebration of life",
        "family resources",
        "aftercare",
        "bereavement"
    ]


    education_keywords = [
        "resources",
        "planning guide",
        "preplanning guide",
        "educational resources",
        "learn more",
        "information center",
        "family education"
    ]


    for keyword in seminar_keywords:
        if keyword in seminar_text:
            seminar_fit += 20


    for keyword in community_keywords:
        if keyword in seminar_text:
            community_fit += 15


    for keyword in education_keywords:
        if keyword in seminar_text:
            education_fit += 10


    event_keywords = [
        "upcoming events",
        "event calendar",
        "community events"
    ]


    for keyword in event_keywords:
        if keyword in seminar_text:
            community_fit += 10


    if "association" in seminar_text:
        seminar_fit += 20


    seminar_fit = min(seminar_fit, 100)
    community_fit = min(community_fit, 100)
    education_fit = min(education_fit, 100)


    seminar_fit = min(seminar_fit, 100)


    association_text = combined_text.lower()


    funeral_context = [
        "funeral",
        "mortuary",
        "cremation",
        "cemetery",
        "memorial",
        "chapel",
        "preplanning",
        "obituary"
    ]


    association_keywords = [
        "association",
        "society",
        "chapter",
        "membership",
        "board member",
        "annual meeting",
        "conference",
        "expo",
        "summit"
    ]


    funeral_detected = any(
        keyword in association_text
        for keyword in funeral_context
    )


    if not funeral_detected:

        for keyword in association_keywords:
            if keyword in association_text:
                association_fit += 20

    else:
        association_fit = 0


    seminar_fit = min(seminar_fit, 100)
    association_fit = min(association_fit, 100)


    if seminar_fit >= 70:
        campaign_priority = "High Value Seminar Prospect"

        recommended_message = (
            "Invite funeral leadership to a grief education seminar "
            "designed to support families and staff."
        )

    elif seminar_fit >= 40:
        campaign_priority = "Qualified Seminar Prospect"

        recommended_message = (
            "Introduce grief education resources "
            "and explore partnership opportunities."
        )

    else:
        campaign_priority = "General Funeral Industry Prospect"

        recommended_message = (
            "Introduce Todd's funeral industry education programs."
        )


    classification_text = (
        combined_text.lower()
        + " "
        + domain.lower()
    )


    funeral_indicators = [
        "funeral home",
        "funeral service",
        "funeral services",
        "funeral director",
        "mortuary",
        "chapel",
        "cremation",
        "cemetery",
        "memorial service"
    ]


    association_indicators = [
        "association",
        "society",
        "membership",
        "chapter",
        "annual meeting",
        "conference",
        "expo",
        "summit"
    ]


    is_funeral_home = any(
        indicator in classification_text
        for indicator in funeral_indicators
    )


    is_association = any(
        indicator in classification_text
        for indicator in association_indicators
    )


    if is_funeral_home:
        prospect_type = "Funeral Home Prospect"

    elif is_association:
        prospect_type = "Association / Event Opportunity"

    else:
        prospect_type = "Funeral Industry Prospect"



    cleaned_contacts = clean_contact_data(
        emails_found,
        phones_found,
        domain
    )


    emails_found = cleaned_contacts["emails"]

    phones_found = cleaned_contacts["phones"]


    # Todd Outreach Campaign Intelligence

    if seminar_fit >= 70:

        campaign_type = "High Priority Grief Seminar Prospect"

        recommended_subject = (
            "Grief information seminar opportunity for your families"
        )

        first_email_angle = (
            "Offer educational grief resources and support seminars "
            "for families served by the funeral home"
        )

        follow_up_days = 3

        follow_up_priority = "High"


    elif seminar_fit >= 40:

        campaign_type = "Qualified Funeral Industry Prospect"

        recommended_subject = (
            "Community grief education partnership opportunity"
        )

        first_email_angle = (
            "Introduce grief education seminars as an added family support resource"
        )

        follow_up_days = 7

        follow_up_priority = "Medium"


    else:

        campaign_type = "Research Prospect"

        recommended_subject = (
            "Funeral industry education opportunity"
        )

        first_email_angle = (
            "Explore potential partnership opportunities"
        )

        follow_up_days = 14

        follow_up_priority = "Low"



    # Todd Outreach Intelligence Layer v32

    # Build searchable text for Todd intelligence scoring
    searchable_text = ""

    if "combined_text" in locals():
        searchable_text = combined_text.lower()

    elif "text" in locals():
        searchable_text = str(text).lower()


    target_contact_role = "Funeral Home Decision Maker"

    if "owner" in searchable_text:
        target_contact_role = "Owner / Funeral Director"

    elif "director" in searchable_text:
        target_contact_role = "Funeral Director"

    elif "association" in searchable_text:
        target_contact_role = "Association Contact"


    seminar_angle = (
        "Offer grief education seminars as a post-service family support resource"
    )

    association_angle = (
        "Offer convention presentation topics and professional education sessions"
    )

    training_angle = (
        "Promote celebrant training opportunities through funeral industry networks"
    )


    if seminar_fit >= 70:

        campaign_priority = "Priority Grief Seminar Outreach"

    elif seminar_fit >= 50:

        campaign_priority = "Qualified Seminar Outreach"

    else:

        campaign_priority = "Industry Relationship Outreach"


    if emails_found:

        best_contact_channel = "Email"

        email_confidence = 85

    elif phones_found:

        best_contact_channel = "Phone"

        email_confidence = 25

    else:

        best_contact_channel = "Research Required"

        email_confidence = 0


    phone_confidence = 70 if phones_found else 0



    # Todd Outreach Personalization Layer v33

    priority_score = 0

    if seminar_fit >= 80:
        priority_score += 50

    elif seminar_fit >= 50:
        priority_score += 30

    else:
        priority_score += 15


    if campaign_type == "High Priority Grief Seminar Prospect":
        decision_maker_reason = (
            "High potential fit for grief education partnerships "
            "and family support initiatives"
        )

        opening_hook = (
            "Your funeral home appears well positioned to provide "
            "additional grief support resources after services"
        )

        campaign_sequence = "Immediate Outreach"

    elif campaign_type == "Qualified Funeral Industry Prospect":

        decision_maker_reason = (
            "Potential partnership opportunity based on funeral "
            "service operations and community reach"
        )

        opening_hook = (
            "We identified an opportunity to help funeral homes "
            "extend support beyond the immediate service period"
        )

        campaign_sequence = "7 Day Nurture"

    else:

        decision_maker_reason = (
            "Requires additional research before direct outreach"
        )

        opening_hook = (
            "Introducing community support resources for funeral providers"
        )

        campaign_sequence = "Research Queue"


    email_personalization = (
        f"{opening_hook}. "
        f"Recommended contact: {target_contact_role}. "
        f"Primary angle: {seminar_angle}"
    )


    call_script_angle = (
        f"Ask about existing family support programs. "
        f"Position seminar partnership as additional value. "
        f"Contact role: {target_contact_role}"
    )





    # Todd CRM Contact Intelligence v34

    primary_email, email_confidence = choose_email(
        emails_found,
        domain
    )

    if email_confidence < 50:
        primary_email = ""


    primary_phone, phone_confidence = choose_phone(
        phones_found
    )


    contact_quality_score = (
        email_confidence * 0.6
        +
        phone_confidence * 0.4
    )


    # v34.10 Revenue Intelligence Layer

    revenue_opportunity_score, revenue_tier, revenue_reason = calculate_revenue_opportunity(
        missing,
        community_fit,
        seminar_fit,
        education_fit,
        contact_quality_score,
        opportunity
    )


    # v34.11 Lead Ranking Engine

    digital_opportunity_score = min(
        (
            opportunity / 15 * 60
            +
            (15 - conversion) / 15 * 40
        ),
        100
    )


    partnership_opportunity_score = min(
        (
            community_fit * 0.35
            +
            seminar_fit * 0.35
            +
            education_fit * 0.20
            +
            contact_quality_score * 0.10
        ),
        100
    )


    sales_priority_score = round(
        (
            digital_opportunity_score * 0.55
            +
            partnership_opportunity_score * 0.45
        ),
        1
    )


    if digital_opportunity_score >= 70 and partnership_opportunity_score >= 70:

        sales_lane = "Digital + Partnership"

        recommended_pitch = (
            "Online family engagement upgrade + "
            "community grief education partnership"
        )


    elif partnership_opportunity_score >= 70:

        sales_lane = "Partnership"

        recommended_pitch = (
            "Grief education seminars and "
            "funeral industry community partnership"
        )


    elif digital_opportunity_score >= 70:

        sales_lane = "Digital"

        recommended_pitch = (
            "Online arrangement system, "
            "lead capture, and consultation improvements"
        )


    else:

        sales_lane = "Nurture"

        recommended_pitch = (
            "Relationship building and future opportunity"
        )


    # v34.13 Executive Priority Ranking

    tier_multiplier = {
        "Tier 1": 1.25,
        "Tier 2": 1.10,
        "Tier 3": 1.00
    }.get(
        revenue_tier,
        1.00
    )


    executive_priority_score = round(
        min(
            (
                sales_priority_score
                *
                tier_multiplier
                *
                (
                    0.7
                    +
                    (contact_quality_score / 100 * 0.3)
                )
            ),
            100
        ),
        1
    )



    # v34.14 Executive Decision Layer


    if executive_priority_score >= 80:

        executive_action = "Immediate Executive Outreach"

        executive_summary = (
            "High revenue opportunity with strong "
            "conversion gaps and partnership potential"
        )


    elif executive_priority_score >= 60:

        executive_action = "Priority Sales Sequence"

        executive_summary = (
            "Qualified opportunity requiring "
            "targeted outreach"
        )


    elif executive_priority_score >= 45:

        executive_action = "Nurture Campaign"

        executive_summary = (
            "Potential opportunity requiring "
            "relationship development"
        )


    else:

        executive_action = "Monitor"

        executive_summary = (
            "Low immediate conversion opportunity"
        )




    # v34.15 Outreach Intelligence Layer


    if executive_action == "Immediate Executive Outreach":

        outreach_priority_level = "P1"

        outreach_channel = (
            "Direct email + phone follow-up"
        )

        first_contact_strategy = (
            "Lead with revenue opportunity "
            "and missed digital conversion points"
        )

        offer_angle = (
            "Custom funeral technology modernization plan"
        )

        estimated_sales_motion = (
            "High-touch executive sales cycle"
        )


    elif executive_action == "Priority Sales Sequence":

        outreach_priority_level = "P2"

        outreach_channel = (
            "Personalized executive email campaign"
        )

        first_contact_strategy = (
            "Present conversion improvements "
            "and consultation workflow upgrades"
        )

        offer_angle = (
            "Digital conversion optimization package"
        )

        estimated_sales_motion = (
            "Consultative sales sequence"
        )


    elif executive_action == "Nurture Campaign":

        outreach_priority_level = "P3"

        outreach_channel = (
            "Email nurture campaign"
        )

        first_contact_strategy = (
            "Build relationship and provide value"
        )

        offer_angle = (
            "Future digital partnership opportunity"
        )

        estimated_sales_motion = (
            "Long-term relationship development"
        )


    else:

        outreach_priority_level = "P4"

        outreach_channel = (
            "Monitor"
        )

        first_contact_strategy = (
            "No immediate outreach required"
        )

        offer_angle = (
            "Future opportunity review"
        )

        estimated_sales_motion = (
            "Passive monitoring"
        )


    # v34.12 Revenue Tier Override FINAL AUTHORITY

    if revenue_tier == "Tier 1" and sales_priority_score >= 55:

        sales_lane = "Priority Outreach"

        recommended_pitch = (
            "High-value digital conversion upgrade "
            "with partnership opportunity"
        )


    elif revenue_tier == "Tier 2" and sales_priority_score >= 60:

        sales_lane = "Qualified Outreach"


    if contact_quality_score >= 70:
        crm_status = "Ready For Outreach"

    elif not primary_email and phone_confidence < 50:
        crm_status = "No Valid Contact Found"

    elif contact_quality_score >= 30:
        crm_status = "Needs Verification"

    else:
        crm_status = "Research Required"




    # v34.9 Outreach Intelligence Layer

    outreach_readiness_score = 0

    if contact_quality_score >= 70:
        outreach_readiness_score += 30
    elif contact_quality_score >= 40:
        outreach_readiness_score += 20

    if seminar_fit >= 70:
        outreach_readiness_score += 25
    elif seminar_fit >= 40:
        outreach_readiness_score += 15

    if community_fit >= 70:
        outreach_readiness_score += 20

    if opportunity >= 10:
        outreach_readiness_score += 15

    outreach_readiness_score = min(outreach_readiness_score, 100)

    if outreach_readiness_score >= 75:
        lead_temperature = "HOT"
        outreach_strategy = (
            "Direct decision maker outreach with partnership proposal"
        )

    elif outreach_readiness_score >= 45:
        lead_temperature = "WARM"
        outreach_strategy = (
            "Relationship-first outreach using education/community angle"
        )

    else:
        lead_temperature = "COLD"
        outreach_strategy = (
            "Long-term nurture and awareness campaign"
        )

    recommended_first_touch = (
        best_contact_channel
        + " | "
        + target_contact_role
    )



    # v34.16 Sales Message Alignment Layer

    if executive_action == "Immediate Executive Outreach":

        sales_message_angle = (
            "Executive digital modernization opportunity"
        )

    elif executive_action == "Priority Sales Sequence":

        sales_message_angle = (
            "Conversion improvement opportunity"
        )

    elif executive_action == "Nurture Campaign":

        sales_message_angle = (
            "Relationship development opportunity"
        )

    else:

        sales_message_angle = (
            "Future opportunity monitoring"
        )



    # v34.17 Executive Lead Brief Generator

    if executive_action == "Immediate Executive Outreach":

        executive_brief = {

            "why_now": (
                "High-value prospect with strong revenue potential "
                "and immediate digital modernization opportunity"
            ),

            "primary_pain": (
                "Missed online conversion opportunities "
                "and outdated customer acquisition workflows"
            ),

            "recommended_first_message": (
                "Introduce a customized digital modernization "
                "assessment focused on increasing family inquiries"
            ),

            "expected_objection": (
                "Concern about implementation complexity "
                "or disruption to existing operations"
            ),

            "response_strategy": (
                "Position solution as a phased improvement "
                "with measurable conversion gains"
            )
        }


    elif executive_action == "Priority Sales Sequence":

        executive_brief = {

            "why_now": (
                "Qualified opportunity with identifiable "
                "conversion improvements available"
            ),

            "primary_pain": (
                "Website experience gaps reducing "
                "potential family engagement"
            ),

            "recommended_first_message": (
                "Offer a conversion review highlighting "
                "specific improvement opportunities"
            ),

            "expected_objection": (
                "Need to evaluate timing and budget"
            ),

            "response_strategy": (
                "Focus on ROI, efficiency, and low-friction upgrades"
            )
        }


    elif executive_action == "Nurture Campaign":

        executive_brief = {

            "why_now": (
                "Potential future opportunity requiring "
                "relationship development"
            ),

            "primary_pain": (
                "Limited urgency but possible future digital needs"
            ),

            "recommended_first_message": (
                "Provide value-first insights and industry resources"
            ),

            "expected_objection": (
                "No immediate priority for change"
            ),

            "response_strategy": (
                "Maintain engagement and revisit opportunity triggers"
            )
        }


    else:

        executive_brief = {

            "why_now": (
                "No immediate sales trigger identified"
            ),

            "primary_pain": (
                "Insufficient evidence of urgent opportunity"
            ),

            "recommended_first_message": (
                "Monitor and collect additional intelligence"
            ),

            "expected_objection": (
                "Low motivation to engage"
            ),

            "response_strategy": (
                "Maintain passive monitoring"
            )
        }



    # v34.18 Outreach Asset Generator


    if executive_action == "Immediate Executive Outreach":

        outreach_assets = {

            "email_subject": (
                "Digital modernization opportunity for "
                + domain
            ),

            "opening_line": (
                "I noticed several opportunities where "
                "your online family inquiry process could "
                "be improved."
            ),

            "first_email_body": (
                "We help funeral organizations improve "
                "digital conversion, online arrangements, "
                "and family engagement workflows. "
                "I prepared a short modernization review "
                "highlighting potential improvements."
            ),

            "phone_opener": (
                "I was reviewing your online family "
                "experience and identified a few areas "
                "where additional inquiries may be captured."
            ),

            "follow_up_day_3": (
                "Following up with the digital improvement "
                "opportunities I identified."
            ),

            "follow_up_day_7": (
                "I would be happy to share the conversion "
                "assessment and discuss possible next steps."
            )
        }


    elif executive_action == "Priority Sales Sequence":

        outreach_assets = {

            "email_subject": (
                "Conversion improvement opportunities for "
                + domain
            ),

            "opening_line": (
                "I reviewed your website experience and "
                "identified a few areas that may improve "
                "family inquiries."
            ),

            "first_email_body": (
                "We specialize in helping funeral homes "
                "improve online consultation workflows, "
                "lead capture, and digital family support."
            ),

            "phone_opener": (
                "I found some opportunities to improve "
                "how families connect with your team online."
            ),

            "follow_up_day_3": (
                "Checking whether improving online inquiries "
                "is something your team is currently exploring."
            ),

            "follow_up_day_7": (
                "Happy to provide the findings from the "
                "conversion review."
            )
        }


    elif executive_action == "Nurture Campaign":

        outreach_assets = {

            "email_subject": (
                "Future digital opportunities for "
                + domain
            ),

            "opening_line": (
                "I came across your organization while "
                "researching funeral service technology trends."
            ),

            "first_email_body": (
                "I wanted to introduce our digital "
                "modernization services and share ideas "
                "that may support future growth."
            ),

            "phone_opener": (
                "I wanted to introduce myself and learn "
                "how your team approaches digital growth."
            ),

            "follow_up_day_3": (
                "Sharing a few ideas that may be useful "
                "for future planning."
            ),

            "follow_up_day_7": (
                "Keeping the conversation open for future "
                "digital initiatives."
            )
        }


    else:

        outreach_assets = {

            "email_subject": (
                "Digital opportunities for " + domain
            ),

            "opening_line": (
                "I wanted to connect regarding future "
                "digital improvement opportunities."
            ),

            "first_email_body": (
                "We support organizations looking to "
                "improve digital engagement."
            ),

            "phone_opener": (
                "I wanted to introduce our services "
                "and stay connected for future needs."
            ),

            "follow_up_day_3": (
                "Following up and keeping the connection open."
            ),

            "follow_up_day_7": (
                "Available whenever digital improvements "
                "become a priority."
            )
        }




    # v34.19 Contact Intelligence + Personalization Engine


    website_observations = []


    if "online_planner" in missing:
        website_observations.append(
            "No visible online planning workflow"
        )

    if "appointment_booking" in missing:
        website_observations.append(
            "No visible appointment scheduling workflow"
        )

    if "chat" in missing:
        website_observations.append(
            "No visible live chat or immediate family support channel"
        )

    if "lead_capture" in missing:
        website_observations.append(
            "Limited online lead capture opportunities identified"
        )

    if "contact_form" in missing:
        website_observations.append(
            "Limited conversion-focused contact pathways identified"
        )


    if not website_observations:
        website_observations.append(
            "Website conversion experience appears comparatively mature"
        )


    if executive_action == "Immediate Executive Outreach":

        custom_opening = (
            "I noticed your organization has strong market presence, "
            "and identified several opportunities where digital "
            "modernization could increase family inquiries."
        )


    elif executive_action == "Priority Sales Sequence":

        custom_opening = (
            "I reviewed your online family experience and found "
            "several areas where improving conversion pathways "
            "could make it easier for families to connect."
        )


    elif executive_action == "Nurture Campaign":

        custom_opening = (
            "I came across your organization while researching "
            "digital trends in funeral services and wanted to "
            "share a few future growth opportunities."
        )


    else:

        custom_opening = (
            "I wanted to introduce our digital support services "
            "and stay connected for future opportunities."
        )


    personalization_profile = {

        "website_observations": website_observations,

        "business_context": {

            "pages_indexed": data["pages"],

            "digital_gap_score": opportunity,

            "revenue_tier": revenue_tier,

            "executive_priority_score":
                executive_priority_score
        },


        "custom_opening": custom_opening,


        "recommended_angle":
            sales_message_angle
    }




    # v34.20 Outreach Execution Package


    outreach_package = {

        "email": {

            "subject": outreach_assets["email_subject"],

            "opening": outreach_assets["opening_line"],

            "body": outreach_assets["first_email_body"],

            "angle": email_angle,

            "cta": offer_angle

        },


        "phone": {

            "opening": outreach_assets["phone_opener"],

            "strategy": first_contact_strategy,

            "message_angle": sales_message_angle

        },


        "follow_up": {

            "day_3": outreach_assets["follow_up_day_3"],

            "day_7": outreach_assets["follow_up_day_7"]

        },


        "crm": {

            "executive_action": executive_action,

            "sales_motion": estimated_sales_motion,

            "campaign_sequence": campaign_sequence,

            "next_action": recommended_first_touch

        }

    }


    result = {

        "domain":domain,

        "pages":data["pages"],

        "conversion":conversion,

        "opportunity":opportunity,

        "lead_value":value,

        "emails_found":emails_found,

        "phones_found":phones_found,

        "contact_intelligence":contact_intelligence,

        "enrichment":enrichment,

        "business_profile":data["business_profile"],

        "contact_confidence":contact_confidence,

        "outreach_priority":round(outreach_priority,1),

        "outreach_priority_level":outreach_priority_level,

        "outreach_level":outreach_level,

        "sales_readiness":sales_readiness,

        "sales_stage":sales_stage,

        "recommended_contact_method":recommended_contact_method,

        "email_subject":email_subject,

        "email_angle":email_angle,

        "opening_hook":opening_hook,

        "pain_points":pain_points,

        "lead_type":lead_type,

        "campaign":"Toddthecelebrant.com",

        "prospect_type":prospect_type,

        "seminar_fit":seminar_fit,
        "community_fit":community_fit,
        "education_fit":education_fit,

        "association_fit":association_fit,

        "campaign_priority":campaign_priority,

        "campaign_type":campaign_type,

        "target_contact_role":target_contact_role,

        "seminar_angle":seminar_angle,

        "association_angle":association_angle,

        "training_angle":training_angle,

        "best_contact_channel":best_contact_channel,

        "priority_score":priority_score,

        "decision_maker_reason":decision_maker_reason,

        "opening_hook":opening_hook,

        "email_personalization":email_personalization,

        "call_script_angle":call_script_angle,

        "campaign_sequence":campaign_sequence,

        "outreach_readiness_score":outreach_readiness_score,

        "lead_temperature":lead_temperature,

        "outreach_strategy":outreach_strategy,

        "recommended_first_touch":recommended_first_touch,

        "primary_email":primary_email,

        "primary_phone":primary_phone,

        "email_confidence":email_confidence,

        "phone_confidence":phone_confidence,

        "contact_quality_score":contact_quality_score,

        "revenue_opportunity_score":revenue_opportunity_score,

        "revenue_tier":revenue_tier,

        "revenue_reason":revenue_reason,

        "digital_opportunity_score":round(digital_opportunity_score,1),

        "partnership_opportunity_score":round(partnership_opportunity_score,1),

        "sales_priority_score":sales_priority_score,

        "executive_priority_score":executive_priority_score,

        "executive_action":executive_action,

        "executive_summary":executive_summary,

        "outreach_priority":outreach_priority,

        "outreach_channel":outreach_channel,

        "first_contact_strategy":first_contact_strategy,

        "offer_angle":offer_angle,

        "estimated_sales_motion":estimated_sales_motion,

        "sales_message_angle":sales_message_angle,

        "executive_brief":executive_brief,


        "outreach_package":outreach_package,
        "outreach_assets":outreach_assets,

        "personalization_profile":personalization_profile,

        "sales_lane":sales_lane,

        "recommended_pitch":recommended_pitch,

        "crm_status":crm_status,

        "email_confidence":email_confidence,

        "phone_confidence":phone_confidence,

        "campaign_priority":campaign_priority,

        "recommended_subject":recommended_subject,

        "first_email_angle":first_email_angle,

        "follow_up_days":follow_up_days,

        "follow_up_priority":follow_up_priority,

        "recommended_message":recommended_message,

        "classification_reason":reason,

        "recommended_package":package,

        "recommended_services":services,

        "lead_value":value,

        "emails_found":emails_found,

        "phones_found":phones_found,

        "contact_confidence":contact_confidence,

        "priority":
            priority(opportunity),

        "found":
            sorted(list(detected)),

        "missing":
            missing,

        "evidence":
            evidence,

        "pitch":
            generate_pitch(missing)

    }

    result["quality_control"] = evaluate_quality(result)
    results.append(result)



results.sort(
    key=lambda x: x["outreach_priority"],
    reverse=True
)


for index, item in enumerate(results, start=1):

    item["outreach_rank"] = index




print_report(results)

Path(OUTPUT).parent.mkdir(parents=True, exist_ok=True)



with open(
    OUTPUT,
    "w",
    encoding="utf-8"
) as f:


    json.dump(

        results,

        f,

        indent=4

    )


print()
print(
    f"Saved audit results: {OUTPUT}"
)

print(
    f"Companies analysed: {len(results)}"
)
