from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, SoupStrainer


DETECTOR = "public_form_intelligence"
VERSION = "1.0.0"
SEMANTIC_PATTERNS = [
    ("INDIGENOUS_OR_TREATY_IDENTIFIER", r"\b(?:first nations?|treaty)\b"),
    ("GOVERNMENT_IDENTIFIER", r"\b(?:sin|social insurance|government id)\b"),
    ("DATE_OF_BIRTH", r"\b(?:date of birth|birth date|dob)\b"),
    ("PLACE_OF_BIRTH", r"\b(?:place of birth|birthplace|parents? place of birth)\b"),
    ("WILL_OR_ESTATE", r"\b(?:will|estate|executor|next of kin)\b"),
    ("MILITARY", r"\b(?:military|service number|regiment|rank|discharge|insignia)\b"),
    ("RELIGION_OR_DENOMINATION", r"\b(?:religion|religious|denomination|place of worship|church)\b"),
    ("DISPOSITION_PREFERENCE", r"\b(?:burial|cremation|disposition|entombment|i prefer)\b"),
    ("CEMETERY", r"\b(?:cemetery|grave|lot|section)\b"),
    ("FUNERAL_PREFERENCE", r"\b(?:funeral|memorial|place of service|visitation|final arrangements?|additional instructions|donations?)\b"),
    ("FINANCIAL_OR_PAYMENT", r"\b(?:payment|credit card|bank|billing|price|cost)\b"),
    ("MARITAL_STATUS", r"\b(?:marital|spouse|marriage|maiden)\b"),
    ("FAMILY", r"\b(?:fathers?|mothers?|parents?|family members?)\b"),
    ("EDUCATION", r"\b(?:education|school|degree)\b"),
    ("OCCUPATION", r"\b(?:occupation|company|business field|employer)\b"),
    ("EMAIL", r"\b(?:email|e-mail)\b"),
    ("PHONE", r"\b(?:phone|telephone|mobile|cell)\b"),
    ("ADDRESS", r"\b(?:address|street|city|province|state|postal|zip)\b"),
    ("NAME", r"\b(?:full name|first name|last name|your name|person in charge)\b"),
]
SENSITIVE_CATEGORIES = {
    "DATE_OF_BIRTH", "PLACE_OF_BIRTH", "FAMILY", "MARITAL_STATUS", "MILITARY",
    "GOVERNMENT_IDENTIFIER", "INDIGENOUS_OR_TREATY_IDENTIFIER",
    "RELIGION_OR_DENOMINATION", "WILL_OR_ESTATE", "FINANCIAL_OR_PAYMENT",
}
def _stable(*values: Any) -> str:
    raw = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _host(value: str) -> str:
    return (urlsplit(value).hostname or "").lower().removeprefix("www.")


def _normalize(text: Any) -> str:
    return re.sub(r"[_-]+", " ", re.sub(r"\s+", " ", str(text or ""))).strip()


def classify_semantic(label: str, name: str = "", control_type: str = "") -> str:
    material = _normalize(f"{label} {name}").casefold()
    for category, pattern in SEMANTIC_PATTERNS:
        if re.search(pattern, material, re.I):
            return category
    if control_type == "textarea" or re.search(r"\b(?:message|comments?|notes?|details?)\b", material):
        return "FREE_TEXT"
    return "UNKNOWN"


def _label(form, control) -> str:
    identifier = control.get("id")
    label = form.find("label", attrs={"for": identifier}) if identifier else None
    if not label:
        label = control.find_parent("label")
    return _normalize(
        label.get_text(" ", strip=True) if label else
        control.get("aria-label") or control.get("placeholder") or control.get("name") or ""
    )


def _requirement(label: str, control) -> str:
    if control.has_attr("required") or str(control.get("aria-required", "")).lower() == "true":
        return "HTML_REQUIRED"
    if re.search(r"\boptional\b", label, re.I):
        return "TEXT_STATED_OPTIONAL"
    return "UNSPECIFIED"


def analyze_page_forms(
    organization_id: str,
    page: Dict[str, Any],
    default_observed_at: str = "UNKNOWN",
) -> List[Dict[str, Any]]:
    page_url = str(page.get("url") or "")
    queue_domain = str((page.get("discovery") or {}).get("queue_domain") or "").lower().removeprefix("www.")
    if queue_domain:
        owned = queue_domain == organization_id.lower().removeprefix("www.")
    else:
        owned = _host(page_url) == organization_id.lower().removeprefix("www.")
    if not owned:
        raise ValueError("Form page does not belong to organization")
    html = str(page.get("html") or "")
    if not html or not re.search(r"<form\b", html, re.I):
        return []
    soup = BeautifulSoup(html, "html.parser", parse_only=SoupStrainer(["form", "a"]))
    page_text = _normalize(page.get("text") or page.get("markdown") or soup.get_text(" ", strip=True))
    observed_at = (page.get("crawl") or {}).get("observedAt") or default_observed_at
    page_id = _stable("page", organization_id, page_url)
    privacy_links = sorted({urljoin(page_url, anchor.get("href")) for anchor in soup.find_all("a", href=True)
                            if re.search(r"privacy", anchor.get_text(" ", strip=True) + " " + anchor.get("href", ""), re.I)})
    minimum_text = next((match.group(0) for pattern in (
        r"at (?:a )?minimum[^.]{0,240}", r"minimum information[^.]{0,240}", r"(?:only|required)[^.]{0,120}(?:name|telephone|phone)[^.]{0,120}"
    ) if (match := re.search(pattern, page_text, re.I))), None)
    explanation = next((match.group(0) for pattern in (
        r"information[^.]{0,180}(?:required for|used for|used to)[^.]{0,180}",
        r"fill in as much as you are comfortable with[^.]{0,180}",
        r"as much or as little detail as you wish[^.]{0,180}",
    ) if (match := re.search(pattern, page_text, re.I))), None)
    results = []
    for index, form in enumerate(soup.find_all("form")):
        controls = form.find_all(["input", "select", "textarea", "button"])
        section_headings = []
        for heading in form.find_all(["legend", "h1", "h2", "h3", "h4", "h5", "h6"]):
            value = _normalize(heading.get_text(" ", strip=True))
            if value and value not in section_headings:
                section_headings.append(value)
        hidden = [control for control in controls if control.name == "input" and str(control.get("type", "text")).lower() == "hidden"]
        visible = [control for control in controls if control not in hidden]
        fields = []
        for position, control in enumerate(visible):
            control_type = (str(control.get("type") or control.name).lower())
            label = _label(form, control)
            semantic = classify_semantic(label, str(control.get("name") or ""), control_type)
            fields.append({
                "field_id": _stable(organization_id, page_url, index, position, control.name,
                                    control.get("name"), control_type, label),
                "position": position, "element": control.name, "input_type": control_type,
                "name": str(control.get("name") or ""), "label": label,
                "placeholder": str(control.get("placeholder") or ""),
                "autocomplete": str(control.get("autocomplete") or ""),
                "requirement_state": _requirement(label, control), "semantic_category": semantic,
            })
        action_raw = str(form.get("action") or "")
        action = urljoin(page_url, action_raw) if action_raw else ""
        action_scope = "NO_ACTION" if not action else ("SAME_ORIGIN" if _host(action) == _host(page_url) else "CROSS_ORIGIN")
        data_fields = [field for field in fields if field["input_type"] not in {"submit", "reset", "button"}]
        counts = Counter(field["input_type"] for field in fields)
        categories = Counter(field["semantic_category"] for field in data_fields)
        sensitive = sorted(set(categories) & SENSITIVE_CATEGORIES)
        form_text = _normalize(form.get_text(" ", strip=True))
        appointment = bool(re.search(r"(?:appointment|contact me|set up a meeting)", form_text, re.I))
        information_request = bool(re.search(r"send me information|more information|information about", form_text, re.I))
        if len(data_fields) >= 15:
            form_type = "DETAILED_INTAKE_FORM"
        elif set(categories) <= {"NAME", "EMAIL", "PHONE", "ADDRESS", "FREE_TEXT", "UNKNOWN"} and len(data_fields) <= 12:
            form_type = "CONTACT_ONLY_FORM"
        else:
            form_type = "GENERAL_FORM"
        review_reasons = []
        if form_type == "DETAILED_INTAKE_FORM": review_reasons.append("INTAKE_COMPLEXITY_REVIEW")
        if len(data_fields) >= 10 and sum(field["requirement_state"] == "HTML_REQUIRED" for field in data_fields) < 3:
            review_reasons.append("REQUIREMENT_CLARITY_REVIEW")
        if sensitive and not privacy_links: review_reasons.append("PRIVACY_CONTEXT_REVIEW")
        if action_scope == "CROSS_ORIGIN" or appointment or information_request: review_reasons.append("FORM_FLOW_REVIEW")
        result = {
            "schema_version": 1, "organization_id": organization_id, "page_id": page_id,
            "page_url": page_url, "page_title": (page.get("metadata") or {}).get("title"),
            "form_id": _stable("form", VERSION, organization_id, page_url, index, form.get("id"), form.get("name")),
            "form_index": index, "form_name": str(form.get("name") or ""), "html_id": str(form.get("id") or ""),
            "form_action": action, "form_method": str(form.get("method") or "GET").upper(),
            "action_scope": action_scope, "control_count": len(controls), "visible_control_count": len(fields),
            "visible_field_count": len(data_fields),
            "section_count": len(section_headings), "section_headings": section_headings,
            "hidden_field_count": len(hidden), "text_like_count": sum(f["input_type"] in {"text", "email", "tel", "date", "number", "url"} for f in fields),
            "select_count": counts["select"], "textarea_count": counts["textarea"],
            "checkbox_count": counts["checkbox"], "radio_count": counts["radio"],
            "submit_count": counts["submit"], "password_field_present": bool(counts["password"]),
            "file_upload_present": bool(counts["file"]), "fields": fields,
            "semantic_category_counts": dict(sorted(categories.items())), "sensitive_semantic_categories": sensitive,
            "html_required_count": sum(f["requirement_state"] == "HTML_REQUIRED" for f in data_fields),
            "text_stated_optional_count": sum(f["requirement_state"] == "TEXT_STATED_OPTIONAL" for f in data_fields),
            "unspecified_requirement_count": sum(f["requirement_state"] == "UNSPECIFIED" for f in data_fields),
            "explicit_minimum_fields_text": minimum_text, "required_optional_explanation": explanation,
            "privacy_policy_links": privacy_links, "consent_checkbox_present": any(
                f["input_type"] == "checkbox" and re.search(r"consent|agree|permission", f["label"], re.I) for f in fields),
            "antispam_field_present": any(re.search(r"captcha|honeypot|anti.?spam", str(control.get("name") or ""), re.I) for control in controls),
            "https_page": urlsplit(page_url).scheme == "https", "appointment_request_option_present": appointment,
            "information_request_option_present": information_request, "free_text_field_present": bool(counts["textarea"]),
            "form_type": form_type, "review_candidate_reasons": sorted(set(review_reasons)),
            "detector": DETECTOR, "detector_version": VERSION, "observed_at": observed_at,
            "verification_state": "DIRECTLY_OBSERVED", "confidence": 0.95,
            "safety": {"form_submitted": False, "action_fetched": False, "quality_defect_created": False,
                       "readiness_changed": False, "legal_or_privacy_conclusion": False},
        }
        result["observation_id"] = _stable(result)
        results.append(result)
    return results


def analyze_dataset(
    records: Iterable[Dict[str, Any]],
    pages: Iterable[Dict[str, Any]],
    default_observed_at: str = "UNKNOWN",
) -> Dict[str, Any]:
    records = list(records); pages = list(pages)
    valid = {str(record.get("domain") or "") for record in records}
    forms = []
    for page in pages:
        discovery = page.get("discovery") or {}
        organization_id = str(discovery.get("queue_domain") or _host(str(page.get("url") or ""))).lower().removeprefix("www.")
        if organization_id not in valid:
            continue
        forms.extend(analyze_page_forms(organization_id, page, default_observed_at))
    forms.sort(key=lambda item: (item["organization_id"], item["page_url"], item["form_index"]))
    orgs = {form["organization_id"] for form in forms}
    candidates = [{"organization_id": form["organization_id"], "form_id": form["form_id"],
                   "page_url": form["page_url"], "candidate_reasons": form["review_candidate_reasons"],
                   "status": "HUMAN_REVIEW_CANDIDATE_NOT_A_DEFECT"}
                  for form in forms if form["review_candidate_reasons"]]
    semantic = Counter(category for form in forms for category, count in form["semantic_category_counts"].items() for _ in range(count))
    reasons = Counter(reason for item in candidates for reason in item["candidate_reasons"])
    return {
        "schema_version": 1, "detector": DETECTOR, "detector_version": VERSION,
        "organization_count": len(records), "organizations_with_forms": len(orgs), "total_forms": len(forms),
        "metrics": {
            "forms_by_type": dict(sorted(Counter(form["form_type"] for form in forms).items())),
            "semantic_fields": dict(sorted(semantic.items())),
            "same_origin_actions": sum(form["action_scope"] == "SAME_ORIGIN" for form in forms),
            "cross_origin_actions": sum(form["action_scope"] == "CROSS_ORIGIN" for form in forms),
            "no_action": sum(form["action_scope"] == "NO_ACTION" for form in forms),
            "forms_with_html_required": sum(bool(form["html_required_count"]) for form in forms),
            "forms_with_no_requirement_indicators": sum(not form["html_required_count"] and not form["text_stated_optional_count"] and not form["explicit_minimum_fields_text"] for form in forms),
            "forms_with_privacy_links": sum(bool(form["privacy_policy_links"]) for form in forms),
            "organizations_with_contact_forms": len({form["organization_id"] for form in forms if form["form_type"] == "CONTACT_ONLY_FORM"}),
            "organizations_with_detailed_intake_forms": len({form["organization_id"] for form in forms if form["form_type"] == "DETAILED_INTAKE_FORM"}),
            "organizations_with_appointment_request_forms": len({form["organization_id"] for form in forms if form["appointment_request_option_present"]}),
            "organizations_with_government_identifier": len({form["organization_id"] for form in forms if "GOVERNMENT_IDENTIFIER" in form["semantic_category_counts"]}),
            "organizations_with_date_of_birth": len({form["organization_id"] for form in forms if "DATE_OF_BIRTH" in form["semantic_category_counts"]}),
            "organizations_with_will_or_estate": len({form["organization_id"] for form in forms if "WILL_OR_ESTATE" in form["semantic_category_counts"]}),
            "organizations_with_military": len({form["organization_id"] for form in forms if "MILITARY" in form["semantic_category_counts"]}),
            "unknown_fields": semantic["UNKNOWN"],
            "review_candidates_by_reason": dict(sorted(reasons.items())),
        },
        "forms": forms, "review_candidates": candidates,
        "safety_policy": {
            "CUSTOMER_SAFE_OBSERVATION": ["form presence", "visible labels", "first-party textual minimum"],
            "CUSTOMER_SAFE_WITH_WORDING": ["visible field count", "personal-information categories", "human review suggestion"],
            "INTERNAL_ONLY": ["complexity heuristics", "sensitive-category counts", "review priority"],
            "UNSAFE_WITHOUT_HUMAN_REVIEW": ["excessive collection", "privacy or legal defect", "insecurity", "abandonment", "conversion or revenue impact"],
        },
    }
