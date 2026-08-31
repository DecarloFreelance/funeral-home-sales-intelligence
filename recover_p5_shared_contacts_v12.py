#!/usr/bin/env python3
"""Materialize the second explicit-location P5 shared-domain phone batch."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json

BASE = Path("data/generated/directory_955")
PAGES = Path("data/generated/batches/4a7aa3af0c4f8a44/pages.json")
REVIEW = BASE / "offline_recovery_p5_shared_contacts_v1/review_businesses.json"
V11 = BASE / "full_955_enrichment_v11/full_955_enrichment.json"
OUT = BASE / "offline_recovery_p5_shared_contacts_v2"
V12 = BASE / "full_955_enrichment_v12"
CRM = Path("data/crm.sqlite")

RECOVERIES = [
    ("CFI-0552", "https://maccoubrey.com/contact", "+19053552829", "Colborne\n11 King St. W. Box 204\nColborne, ON K0K 1S0\n(905) 355-2829"),
    ("CFI-0553", "https://maccoubrey.com/contact", "+19053725132", "Cobourg\n30 King St. E.\nCobourg, ON K9A 1K7\n(905) 372-5132"),
    ("CFI-0652", "https://narfasons.com/33/Contact-Us.html", "+13062723212", "Narfason's Funeral Chapel of Foam Lake\n410 Royal St.\nFoam Lake, Saskatchewan\nS0A 1A0\nGet Directions\nPhone:\n(306) 272-3212"),
    ("CFI-0653", "https://narfasons.com/33/Contact-Us.html", "+13063382251", "102 First St. NW\nWadena, Saskatchewan\nS0A 4J0\nEmail:\nnarfasonfuneralchapel@gmail.com\nPhone:\n(306) 338-2251"),
    ("CFI-0654", "https://narfasons.com/33/Contact-Us.html", "+13065543535", "Narfason's Funeral Chapel of Wynyard\n317 Ave A East\nWynyard, Saskatchewan\nS0A 4T0\nGet Directions\nPhone:\n(306) 554-3535"),
    ("CFI-0646", "https://www.munromorris.com/contact-us", "+16133473629", "Munro & Morris Funeral Homes - Lancaster\n46 Oak Street\nLancaster\nON\nK0C 1N0\nPhone:\n613-347-3629"),
    ("CFI-0647", "https://www.munromorris.com/contact-us", "+16135272898", "Munro & Morris Funeral Homes - Maxville\n20 Main St. South\nMaxville\nON\nK0C 1T0\nPhone:\n613-527-2898"),
    ("CFI-0648", "https://www.munromorris.com/contact-us", "+16135252772", "Munro & Morris Funeral Homes - Alexandria\n114 Main St. South\nAlexandria\nON\nK0C 1A0\nPhone:\n613-525-2772"),
    ("CFI-0717", "https://www.peacefultransition.ca/contact/", "+17057390139", "BARRIE\nOffice:\n1-705-739-0139\nFax:\n1-705-739-9895\nE-Mail:\ninfo@ptsimcoe.ca\nAddress:\n431 Bayview Dr. Unit 16, Barrie, ON L4N 8Y2"),
    ("CFI-0718", "https://www.peacefultransition.ca/contact/", "+19058411900", "AURORA\nNOW OPEN!\nPhone:\n1-\n905-841-1900\nE-Mail:\ninfo@ptyork.ca\nAddress:\n15236 Yonge St. Unit 2, Aurora, ON L4G 1L9"),
    ("CFI-0750", "https://www.riversidefuneralhome.ca/about-us/our-location", "+15198876336", "Riverside Funeral Home Brussels Chapel\n401 Albert Street Box 340\nBrussels, Ontario\nN0G 1H0\nP: (519) 887-6336"),
    ("CFI-0751", "https://www.riversidefuneralhome.ca/about-us/our-location", "+15195234577", "Riverside Funeral Home Blyth Chapel\n407 Queen Street Box 199\nBlyth, Ontario\nN0M 1H0\nP: (519) 523-4577"),
    ("CFI-0759", "https://www.rushnellfuneralhomes.com/contact-us", "+16134732833", "Madoc\n(FE-269)\n112 Durham Street South, Madoc, ON K0K 2K0 Ph:\n613-473-2833"),
    ("CFI-0760", "https://www.rushnellfuneralhomes.com/contact-us", "+16134722531", "Marmora (FE-272)\n9 Bursthall Street, Marmora, ON K0K 2M0 Ph:\n613-472-2531"),
    ("CFI-0761", "https://www.rushnellfuneralhomes.com/contact-us", "+16139685588", "Belleville (FE-035)\n80 Highland Avenue, Belleville, ON K8P 3R4 Ph:\n613-968-5588"),
    ("CFI-0763", "https://www.rushnellfuneralhomes.com/contact-us", "+16134783535", "Tweed (FE-484)\n137 Colborne Street, Tweed, ON K0K 3J0 Ph:\n613-478-3535"),
    ("CFI-0764", "https://www.rushnellfuneralhomes.com/contact-us", "+16134752121", "Brighton (FE-573)\n130 Main Street, Brighton, ON K0K 1H0 Ph:\n613-475-2121"),
    ("CFI-0765", "https://www.rushnellfuneralhomes.com/contact-us", "+16133922111", "Trenton (FE-627)\n60 Division Street, Trenton, ON K8V 4W5 Ph:\n613-392-2111"),
    ("CFI-0864", "https://tjtracey.funeraltechweb.com/46/Contact-Us.html", "+19028354212", "71 McQuade Lake Crescent,\nHalifax, NS\nB4A 1A4\nP: 902.835.4212"),
    ("CFI-0865", "https://tjtracey.funeraltechweb.com/46/Contact-Us.html", "+19025397175", "Sydney:\n902.539.7175"),
    ("CFI-0866", "https://tjtracey.funeraltechweb.com/46/Contact-Us.html", "+19028494199", "T.J. Tracey Cremation & Burial Specialists\n370 Reserve St., Glace Bay, NS\n​B1A 4X2\nP: 902.849.4199"),
    ("CFI-0910", "https://www.wartmanfuneralhomes.com/contact-us", "+16133543722", "Napanee Chapel\n448 Camden Rd\nNapanee ,  ON\nK7R 1G1\n613-354-3722"),
    ("CFI-0911", "https://www.wartmanfuneralhomes.com/contact-us", "+16136343722", "Kingston Chapel\n980 Collins Bay Rd\nKingstonON\nK7M 5H2\n613-634-3722"),
    ("CFI-0914", "https://weaverfuneralhomes.tributecenteronline.com/contact/campbellfordon", "+17056531179", "Campbellford Location\n77 Second Street, Box 1179\nCampbellford, ON K0L 1L0\nPHONE:\n(705) 653-1179"),
]

def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    prior_review = json.loads(REVIEW.read_text())
    prior_ids = {row["directory_record_id"] for row in prior_review}
    pages = {page["url"]: page for page in json.loads(PAGES.read_text())}
    canonical = json.loads(V11.read_text())
    by_id = {record["directory_record_id"]: record for record in canonical}
    safe = []
    for record_id, url, value, marker in RECOVERIES:
        assert record_id in prior_ids
        page = pages[url]
        assert marker in page["text"]
        record = by_id[record_id]
        safe.append({
            "directory_record_id": record_id, "company": record["company"],
            "city": record["city"], "province": record["province"],
            "type": "phone", "value": value, "source_url": url,
            "source_file": str(PAGES),
            "source_text_sha256": hashlib.sha256(page["text"].encode()).hexdigest(),
            "source_html_sha256": hashlib.sha256(page["html"].encode()).hexdigest(),
            "classification": "BRANCH_SAFE", "evidence_marker": marker,
            "branch_attribution": "Phone is inside the target location name and address block.",
        })
    safe_ids = {row["directory_record_id"] for row in safe}
    assert len(safe) == 24 and len(safe_ids) == 24
    review = [row for row in prior_review if row["directory_record_id"] not in safe_ids]
    assert len(review) == 73 and len(safe) + len(review) == 97
    shared = [
        {"domain": domain, "classification": "ORGANIZATION_SHARED", "reason": reason}
        for domain, reason in [
            ("maccoubrey.com", "same email used for Cobourg and Colborne"),
            ("narfasons.com", "same email used across all locations"),
            ("munromorris.com", "same email and fax repeated across three locations"),
            ("rushnellfuneralhomes.com", "general organization emails not branch-isolated"),
            ("tjtracey.funeraltechweb.com", "same service email used across locations"),
            ("wartmanfuneralhomes.com", "same email used for Kingston and Napanee"),
        ]
    ]
    write_json(OUT / "branch_safe_contacts.json", safe)
    write_json(OUT / "review_businesses.json", review)
    write_json(OUT / "organization_shared_contacts.json", shared)

    before = metrics(canonical)
    assert before == {
        "businesses_with_email": 158, "businesses_with_phone": 281,
        "businesses_with_staff": 138, "businesses_with_decision_maker": 111,
        "businesses_with_any_safe_contact": 282, "email_values": 270,
        "phone_values": 580, "named_staff": 705, "named_decision_makers": 270,
    }
    output = deepcopy(canonical)
    out_by_id = {record["directory_record_id"]: record for record in output}
    changed = []
    for item in safe:
        record = out_by_id[item["directory_record_id"]]
        enrichment = record["branch_safe_enrichment"]
        assert not enrichment["has_any_contact"]
        phone = {
            "value": item["value"], "source_url": item["source_url"],
            "source_file": item["source_file"], "source_text_sha256": item["source_text_sha256"],
            "source_html_sha256": item["source_html_sha256"],
            "evidence_class": "explicit_branch_contact_block",
            "reason": "phone_inside_target_location_and_address_block",
        }
        enrichment["phones"] = [phone]
        enrichment["has_phone"] = True
        enrichment["has_any_contact"] = True
        enrichment["recovery_provenance"] = [{
            "pipeline": "offline_recovery_p5_shared_contacts_v2",
            "classification": "BRANCH_SAFE", "method": "cached_explicit_location_block",
        }]
        changed.append({
            "directory_record_id": record["directory_record_id"], "company": record["company"],
            "city": record["city"], "province": record["province"],
            "added_emails": [], "added_phones": [phone], "staff_added": [], "decision_makers_added": [],
        })
    after = metrics(output)
    expected = dict(before)
    expected.update({"businesses_with_phone": 305, "businesses_with_any_safe_contact": 306, "phone_values": 604})
    assert after == expected
    unresolved = [record for record in output if not record["branch_safe_enrichment"]["has_any_contact"]]
    assert len(output) == 955 and len({r["directory_record_id"] for r in output}) == 955
    assert len(unresolved) == 649 and 306 + len(unresolved) == 955
    summary = {
        "master_records": 955, "source": "full_955_enrichment_v11",
        "merge_source": "offline_recovery_p5_shared_contacts_v2",
        "input_review_businesses": 97, "branch_safe_businesses": 24,
        "remaining_review_businesses": 73, "merged_records": sorted(safe_ids),
        "before": before, "after": after,
        "net_gain": {key: after[key] - before[key] for key in before},
        "remaining_without_branch_safe_contact_or_staff": 649,
        "network_requests": 0, "langsearch_requests": 0, "crm_writes": 0,
        "invariants": {
            "master_is_955": True, "unique_directory_record_ids": True,
            "review_conservation_24_safe_plus_73_review": True,
            "shared_emails_not_merged": True, "only_explicit_location_blocks_merged": True,
            "staff_unchanged": True, "decision_makers_unchanged": True,
            "resolved_plus_unresolved_is_955": True,
        },
    }
    write_json(OUT / "summary.json", summary)
    write_json(V12 / "full_955_enrichment.json", output)
    write_json(V12 / "changed_records.json", changed)
    write_json(V12 / "organization_shared_contacts.json", shared)
    write_json(V12 / "summary.json", summary)
    write_json(V12 / "unresolved_after_merge.json", unresolved)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"summary": summary, "crm_sha256": crm_after}, indent=2))

if __name__ == "__main__":
    main()
