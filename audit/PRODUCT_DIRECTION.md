# Product Direction

Date: 2026-08-21

## Reference Client

Todd Reinholt is the reference client, not merely a lead in the funeral-home
database. His two brands demonstrate the two-sided structure of the product:

- `toddthecelebrant.com`: grief seminars, funeral celebrancy, public education,
  and funeral-convention speaking
- `lifecelebrantsinternational.com`: funeral-celebrant training and
  certification, delivered online and in person, plus a celebrant directory

Todd's downstream audiences are funeral homes and funeral associations across
Canada and the United States. The existing Alberta funeral-home dataset is an
initial campaign asset for this client and a working demonstration of the
platform.

## Product Being Sold

The reusable product is a branded funeral-sector business-development system:

1. A client website or website refresh
2. A niche prospect database built for the client's offer and territory
3. Controlled website crawling and public contact enrichment
4. Buyer-fit and campaign-fit scoring
5. Decision-maker research and verification queues
6. CRM actions, outreach sequences, and follow-up tracking
7. Ongoing data and website maintenance

The database alone is less defensible than the complete operating workflow.
The strongest positioning is therefore a managed growth system for businesses
that sell products, education, or professional services into funeral service.

## Candidate Types

Primary candidates for another branded installation:

- Funeral-service educators and convention speakers
- Grief educators, grief-recovery trainers, and bereavement-program providers
- Celebrant and officiant training organizations
- Funeral-home consultants and succession advisers
- Funeral-sector technology, merchandising, and service suppliers
- Independent marketing agencies specializing in death care
- Associations that want a member/vendor intelligence and communication system

Funeral homes and multi-location operators remain potential direct software or
website buyers, but they are a separate sales lane from the Todd-style reseller
or managed-service candidate.

## Commercial Models

Recommended starting model:

- One-time setup fee for the branded website, offer model, data sources, and CRM
- Monthly managed license for crawling, enrichment, scoring, exports, and upkeep
- Usage or territory limits stated in the agreement
- Client retains access to its campaign data; reusable platform code remains
  licensed rather than transferred

Additional models:

- White-label license for agencies or consultants with their own clients
- Revenue-share partnership only where lead attribution and collection are
  reliable
- Full custom sale only at a premium that accounts for lost recurring revenue

The managed setup plus monthly license is the easiest initial offer because it
keeps implementation controlled and avoids transferring the entire codebase.

## Immediate Product Work

The platform must keep two records separate:

- `platform_candidate`: someone who may buy, license, or partner on the system
- `campaign_lead`: an organization targeted on behalf of a platform client

The next discovery expansion should build a North American
`platform_candidate` dataset for funeral-sector educators, trainers,
consultants, suppliers, speakers, and specialist agencies. The existing funeral
home and association discovery feeds remain campaign-lead sources.

## Website Findings

The client crawl retrieved nine pages across both brands. It confirmed the
offers above and also found an apparent preview-domain support email on the Life
Celebrants International contact page. That address should be reviewed before
using the site for a campaign because it differs from the primary
`todd@lifecelebrantsinternational.com` address shown elsewhere.

## Initial Platform-Candidate Validation

The first candidate research pass produced 18 evidence-backed North American
organizations across education, grief training, funeral consulting, celebrant
certification, and specialist marketing. The controlled verification crawl
retrieved 58 pages across 14 candidate domains. Four inaccessible sites remain
evidence-only and require manual verification.

The strongest initial managed-license candidates are:

1. AG Associates
2. Jason Troyer
3. Philotimo Life
4. Kari the Mortician
5. Omega Funeral Consulting
6. Lisa Baue
7. International Grief Institute

InSight Books/InSight Institute and American Funeral Consultants currently rank
as data-partnership candidates. Specialist funeral marketing agencies are kept
in a white-label partnership lane because they may be partners or competitors,
not ordinary managed-service customers.

Generated records:

- `data/seeds/platform_candidates.json`: reviewed research seeds and evidence
- `data/generated/platform/platform_candidate_queue.json`: normalized crawl queue
- `data/generated/platform/platform_candidate_crawl.json`: verified website pages
- `data/generated/platform/platform_candidate_results.json`: ranked candidates

### Refined Dataset Status

Fit and data confidence are now scored separately. A strong business-model match
can no longer hide missing crawl or contact evidence. Current results:

- 27 reviewed platform candidates
- 21 site-verified and 6 evidence-only records
- 15 managed-license, 6 data-partnership, and 6 white-label candidates
- 17 ready for person-level review
- 11 with a usable email and 14 with a public phone
- 9 with named-person evidence
- 6 specialist agencies explicitly marked for competitive-overlap review

The second research pass added Mortuary Training, The Gary O'Sullivan Company,
MyFuneralCareer, Funeral Business Builder, Impart, Graystone Associates, The
System University, Dead Ringers, and AFMAP Marketing. Evidence-only and
phone-only candidates remain in research workflows; the platform does not infer
or manufacture email addresses.

AG Associates remains a strong fit, but its published
`greg@agassoicates.org` address does not match `agassociates.org` and is flagged
instead of being treated as outreach-ready.

### Client Email Validation

The preview-domain issue is confirmed on the Life Celebrants International
contact page, not on `toddthecelebrant.com`. Both
`todd@lifecelebrantsinternational.com` and
`todd@lifecelebrantsinternational-com.preview-domain.com` are visible on that
page. The second address should be replaced with the first in the WordPress
contact-page content or page-builder module. Todd's own site exposes the
domain-aligned `todd@toddthecelebrant.com` address and no preview-domain address.
