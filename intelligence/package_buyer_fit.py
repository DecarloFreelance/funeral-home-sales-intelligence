from typing import Any, Dict, Iterable, List


CORPORATE_DOMAINS = {"arbormemorial.ca", "dignitymemorial.com"}


def _bounded(value: Any) -> float:
    try:
        return max(0.0, min(100.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def score_package_buyer(result: Dict[str, Any]) -> Dict[str, Any]:
    """Rank organizations for a software/site purchase, license, or partnership."""
    domain = result.get("domain", "")
    profile = result.get("business_profile") or {}
    contacts = result.get("contact_intelligence") or {}
    locations = profile.get("locations") or []
    missing = set(result.get("missing") or [])
    digital = _bounded(result.get("digital_opportunity_score"))
    contact = _bounded(result.get("contact_quality_score"))
    readiness = _bounded(result.get("sales_readiness"))
    revenue = _bounded(result.get("revenue_opportunity_score"))
    people = contacts.get("people") or []
    independent = domain not in CORPORATE_DOMAINS
    conversion_gaps = len(missing & {
        "appointment_booking", "contact_form", "lead_capture", "online_planner",
        "pricing", "chat",
    })

    direct = (
        digital * .35 + contact * .25 + readiness * .20 +
        min(10, conversion_gaps * 2) + (10 if independent else 2)
    )
    license_fit = (
        digital * .20 + contact * .20 + revenue * .20 +
        min(30, len(locations) * 7.5) + (10 if people else 0)
    )
    partnership = (
        contact * .30 + readiness * .20 + revenue * .20 +
        min(20, len(locations) * 5) + (10 if people else 0)
    )
    scores = {
        "DIRECT_PURCHASE": round(min(100, direct), 1),
        "LICENSE": round(min(100, license_fit), 1),
        "PARTNERSHIP": round(min(100, partnership), 1),
    }
    motion = max(scores, key=scores.get)

    reasons = []
    if digital >= 70:
        reasons.append("large digital conversion gap")
    if conversion_gaps >= 3:
        reasons.append(f"{conversion_gaps} package-relevant website gaps")
    if len(locations) >= 2:
        reasons.append(f"{len(locations)} locations increase licensing value")
    if people:
        reasons.append("named decision-maker evidence available")
    if contact >= 70:
        reasons.append("strong contact coverage")
    if not independent:
        reasons.append("corporate operator requires enterprise sales motion")

    return {
        "domain": domain,
        "company": profile.get("company") or domain,
        "recommended_motion": motion,
        "buyer_fit_score": scores[motion],
        "motion_scores": scores,
        "reasons": reasons,
        "primary_email": result.get("primary_email", ""),
        "primary_phone": result.get("primary_phone", ""),
        "decision_makers": people,
        "locations": locations,
        "package": "Funeral-sector lead intelligence, outreach CRM, and website system",
        "next_step": (
            "Validate decision-maker and request a discovery call about their growth workflow"
        ),
    }


def rank_package_buyers(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = [score_package_buyer(result) for result in results]
    return sorted(ranked, key=lambda item: item["buyer_fit_score"], reverse=True)
