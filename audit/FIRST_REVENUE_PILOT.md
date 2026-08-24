# Manually Controlled First Revenue Pilot

Validated 2026-08-24. This workflow turns the current evidence store into a
small operator-controlled sales experiment. It does not send outreach, write
external CRM records, infer pricing, or change source intelligence.

## Offer and content policy

The internal offer is **Funeral Home Digital Presence & Growth Audit**. Its
purpose is to present cited digital-presence observations, cautiously identify
possible improvements, and create a reason for a human conversation.

Customer audit content is structurally classified:

- `OBSERVED`: directly supported by a cited public fact.
- `NOT_DETECTED_IN_SCAN`: not observed in the bounded crawl; never absence.
- `INTERPRETATION`: a cautious opportunity interpretation tied to scan evidence.
- `RECOMMENDED_ACTION`: a practical suggestion without promised impact.
- `INTERNAL_ONLY`: ranking, uncertainty, warnings, and selection rationale;
  excluded from the customer-safe audit object.

Never expose legacy revenue/opportunity scores, tiers, generated pain points,
absolute missing-feature claims, mailbox/phone reachability claims, speculative
target roles, or conversion/revenue causality.

## Operator sequence

Generate the same ten-record cohort and customer-safe artifacts:

```bash
python commercial_readiness.py
python pilot_cli.py generate
python pilot_cli.py list
python pilot_cli.py show PILOT_OR_DOMAIN
python pilot_cli.py audit PILOT_OR_DOMAIN
```

Every new record begins in `CANDIDATE`. Generation creates a non-sendable draft
preview, not approval or contact activity. An operator must inspect the sources
and explicitly progress it:

```bash
python pilot_cli.py review DOMAIN --actor OPERATOR --note "Sources inspected"
python pilot_cli.py approve DOMAIN --actor OPERATOR --note "Claims and contact approved"
python pilot_cli.py draft DOMAIN --actor OPERATOR
```

`draft` requires `APPROVED_FOR_CONTACT`, writes `PREPARED_UNSENT`, and performs
no network or CRM operation. Contact is recorded only after the operator acts
outside this repository:

Approval re-reads the current enriched results, requires current CRM/outreach
readiness, and confirms that every fact referenced by the selected audit still
exists. A stale cohort cannot bypass a later quality or evidence change.

```bash
python pilot_cli.py transition DOMAIN CONTACTED --actor OPERATOR \
  --note "Manual contact completed" --activity-reference "manual-email-log:1"
python pilot_cli.py transition DOMAIN REPLIED --actor OPERATOR --reply-sentiment POSITIVE
python pilot_cli.py transition DOMAIN MEETING --actor OPERATOR
python pilot_cli.py transition DOMAIN PROPOSAL --actor OPERATOR
python pilot_cli.py offer DOMAIN AUDIT_PLUS_FIX --actor OPERATOR --quoted 1500
python pilot_cli.py offer DOMAIN AUDIT_PLUS_FIX --actor OPERATOR --quoted 1500 --accepted 1200
python pilot_cli.py transition DOMAIN WON --actor OPERATOR
```

Use `defer`, `disqualify`, `history`, and `stats` for the other outcomes.
Transitions and offer assignments are append-only and actor/timestamp audited.
The three manually priced variants are `AUDIT`, `AUDIT_PLUS_FIX`, and `MANAGED`.

## First cohort

The deterministic cohort penalizes directly evidenced parent relationships and
phone-only contact while never asserting that a business is independent merely
because no parent fact was found.

| Order | Organization | Recommended contact | Internal reason / warning |
|---:|---|---|---|
| 1 | `foothillsmemorialchapel.com` | `office@foothillsmemorialchapel.com` | strong contact and page evidence; multiple bounded opportunities |
| 2 | `gregorysfuneralhomes.com` | `office@gregorysfuneralhomes.com` | named/public contact depth and positive capability evidence |
| 3 | `fernhillcemetery.ca` | `info@fernhillcemetery.ca` | direct email, verified site, concise technology/opportunity evidence |
| 4 | `cornerstonefuneralhome.com` | `care@cornerstonefh.ca` | first-party-published contact evidence, social/livestream/service observations |
| 5 | `missionview.ca` | `info@missionview.ca` | direct email, social/service evidence, bounded opportunities |
| 6 | `beaverlodgefuneralservice.com` | `wecare@beaverlodgefuneralservice.com` | strong evidence; confirm local authority because a parent fact exists |
| 7 | `bowvalleyfuneral.ca` | `+14036881031` | strong identity but phone-only; separate human judgment required |
| 8 | `mccawfuneralservice.com` | `info@mccawfuneralservice.com` | direct contact and multiple observed services |
| 9 | `evergreenfh.ca` | `info@evergreenfh.ca` | direct contact and multiple observed services |
| 10 | `fostermcgarvey.com` | `info@fostermcgarvey.com` | direct contact, pre-planning/obituary evidence, bounded opportunities |

The strongest five for the first manual source review are the first five above.
Their leading customer-safe observations are:

- Foothills: verified website; observed pre-planning, obituary, and cremation
  information; online arrangements were not detected in the bounded scan.
- Gregory's: verified website; observed social link, online-arrangement language,
  and pre-planning information; livestream information was not detected.
- Fernhill: verified website and WordPress-consistent public indicators; online
  arrangement and livestream information were not detected.
- Cornerstone: verified website; observed social, livestream, and pre-planning
  information; online arrangements were not detected.
- Mission View: verified website; observed social, pre-planning, and obituary
  information; online arrangements were not detected.

Each generated record retains full fact IDs, scan-scope IDs, source URLs,
confidence/qualification, contact evidence, an internal rationale, warnings, and
a non-sendable draft preview under ignored `data/generated/pilot/cohort.json`.
No prospect is approved merely by appearing in this list.

## Outcomes and experiment interpretation

`pilot stats` reports cohort/review/approval/draft/contact/reply/meeting/proposal/
win/loss counts; positive and negative replies; descriptive funnel rates;
manually accepted and recurring amounts; offer variants; and observation
categories among contacted/won records. Rates are explicitly descriptive and
not statistically predictive.

Pilot success means at least one manually approved prospect enters a genuine
sales conversation with the audit claims remaining source-defensible. Failure
means the offer or message does not produce conversations after the operator has
recorded a reasonable first sample; it does not justify weakening evidence or
inventing stronger claims.
