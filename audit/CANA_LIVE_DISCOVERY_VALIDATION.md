# CANA Live Discovery Validation

Date: 2026-08-22
Source: Cremation Association of North America public member directory

## Scope and Controls

The connector fetched official country result pages for Canada and the United
States. Default filtering retained records categorized as a funeral home,
mortuary, or crematory and excluded suppliers or uncategorized members unless
the operator explicitly requests them.

The source pages are large: the United States response was approximately 13.8
MB. The connector uses the existing `lxml` dependency, a targeted parse filter,
and bounded request retries. The public source URL is:

`https://members.cremationassociation.org/canamembers/search`

## Directory Acquisition

| Measure | Canada | United States | Combined |
|---|---:|---:|---:|
| Target provider records | 235 | 2,194 | 2,429 |
| Records with websites | 187 (79.6%) | 1,790 (81.6%) | 1,977 (81.4%) |
| Records with phones | 232 (98.7%) | 2,175 (99.1%) | 2,407 (99.1%) |
| Records with named directory contacts | 230 (97.9%) | 2,166 (98.7%) | 2,396 (98.6%) |
| Unique normalized crawl domains | 162 | 1,643 | 1,804 |
| Website records merged by domain deduplication | 25 | 147 | 173 |

Canadian results cover ten provinces. United States results contain 54 distinct
state/territory region codes. One normalized website domain appears across the
country datasets. Domain deduplication retains branch locations, named directory
contacts, and source provenance rather than discarding duplicate business
records.

Named directory contacts are stored separately from role-verified people. They
are not treated as owners, funeral directors, or decision-makers unless website
or structured evidence provides a supported role.

## Controlled Website Retrieval

Two deterministic alphabetic samples were crawled with a maximum of ten domains,
two successful pages per domain, three attempts per domain, a 12-second request
timeout, and a 0.1-second delay.

| Measure | Canada outside Alberta | United States |
|---|---:|---:|
| Domains attempted | 10 | 10 |
| Domains with usable pages | 4 (40%) | 3 (30%) |
| Pages retained | 7 | 6 |
| Retrieved domains with email | 2 of 4 | 2 of 3 |
| Retrieved domains with phone | 4 of 4 | 3 of 3 |
| Retrieved domains with role-verified people | 0 | 0 |

Failures were retained in structured crawl reports. No access restriction was
bypassed, and no inference was used to manufacture missing contacts. The small
sample measures connector interoperability and failure handling; it is not a
statistically representative estimate of all North American funeral websites.

## Validation Outcome

- Official Canada and United States directory retrieval succeeded.
- Parser fixture, retry, target-category filtering, and large-page regression
  tests pass.
- Provider exports integrate with the existing normalized queue.
- Cross-domain deduplication and location/provenance retention are functioning.
- Controlled website samples exercise non-Alberta Canadian and U.S. retrieval.
- Contact yield is explicitly separated between directory evidence and website
  evidence.
