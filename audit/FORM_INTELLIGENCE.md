# Evidence-safe form intelligence

Validated 2026-08-24 against the retained 211-organization scale cohort. The
analyzer is a read-only deterministic stage over already authorized page HTML.
It does not submit forms, execute JavaScript, fetch form actions, change quality
findings/readiness, or make legal, privacy, security, UX, or revenue conclusions.

## Architecture and model

`enrichment/forms.py` produces stable page, form, field, and observation IDs.
Ownership uses the crawler's durable `discovery.queue_domain` when present;
otherwise the page host must equal the organization. This preserves approved
network-location pages without allowing arbitrary sibling evidence to attach.

Each form records page/source identity, action/method/scope, neutral control
counts, labels/names/types, placeholders, autocomplete, requirement state,
semantic categories, page privacy links, minimum/explanatory text, HTTPS context,
and detector/version/observation metadata. Hidden fields are counted but their
names and values are not retained. No control value or submitted data is stored.

Neutral semantic categories are `NAME`, `ADDRESS`, `PHONE`, `EMAIL`,
`DATE_OF_BIRTH`, `PLACE_OF_BIRTH`, `FAMILY`, `MARITAL_STATUS`, `OCCUPATION`,
`EDUCATION`, `MILITARY`, `GOVERNMENT_IDENTIFIER`,
`INDIGENOUS_OR_TREATY_IDENTIFIER`, `RELIGION_OR_DENOMINATION`, `WILL_OR_ESTATE`,
`FINANCIAL_OR_PAYMENT`, `FUNERAL_PREFERENCE`, `DISPOSITION_PREFERENCE`,
`CEMETERY`, `FREE_TEXT`, and `UNKNOWN`. They describe visible form schema, not
people and not whether collection is necessary or lawful.

Requirement states remain separate: `HTML_REQUIRED`, `TEXT_STATED_OPTIONAL`, and
`UNSPECIFIED`. Missing `required` never means optional. First-party minimum or
explanatory wording is retained without changing other fields' requirement state.

## Safety and review candidates

Customer-safe observations include form presence, visible labels/categories,
and quoted first-party minimum wording. Counts and a suggestion to review clarity
need careful wording. Complexity heuristics and sensitive-category counts remain
internal. Claims that a form is excessive, unlawful, insecure, non-compliant,
high-friction, or losing conversions/revenue are forbidden without human evidence.

`FORM_FLOW_REVIEW`, `INTAKE_COMPLEXITY_REVIEW`,
`REQUIREMENT_CLARITY_REVIEW`, and `PRIVACY_CONTEXT_REVIEW` mean only “worth human
inspection.” They never affect CRM/outreach readiness, identity, confidence,
scoring, or automatic quality findings.

## Operator workflow

```bash
python form_cli.py analyze
python form_cli.py stats
python form_cli.py list --organization foothillsmemorialchapel.com
python form_cli.py show foothillsmemorialchapel.com
python form_cli.py review-candidates --reason REQUIREMENT_CLARITY_REVIEW
```

An explicitly authorized local HTML capture can be included without fetching or
submitting its action:

```bash
python form_cli.py analyze \
  --additional-html foothillsmemorialchapel.com \
  https://www.foothillsmemorialchapel.com/prearrangements-form \
  /path/to/authorized-capture.html \
  --observed-at 2026-08-24T00:00:00Z
```

Generated schemas live under ignored
`data/generated/forms/form_intelligence.json`.

## Foothills source review

Human observation `772fd5672817e019a5ec90af` is append-only and tied only to
Foothills' `/pre-arrangements` and `/prearrangements-form` pages. The extracted
intake form has 72 controls: 66 visible controls (65 data-entry fields plus one
submit), six hidden, 44 text-like, four selects, three textareas, and 14 radios.
Full Name and Telephone are the two HTML-required fields; the other 63 visible
data-entry fields are `UNSPECIFIED`, not
automatically optional. The page says name and telephone are the minimum. The
POST action is same-origin HTTPS and a privacy-policy link is present on the page.
Government-identifier, Indigenous/treaty, birth, family, marital, military,
religion, will/estate, and funeral/disposition categories are visibly represented.
No defect or compliance conclusion was created.

Foothills remains `CANDIDATE`, pre-send remains `REVIEW_REQUIRED`, and the
commercial hypothesis is a human review of how minimum and broader intake choices
are communicated and experienced. The prior arrangements-absence claim remains
suppressed.
