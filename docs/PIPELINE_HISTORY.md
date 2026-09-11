# Pipeline History: V14–V19 (retired) vs. the live dataset

Retired: 2026-09-11, confirmed by the project owner.

## What's actually live

`data/portal_findings.json` is the source of truth for the deployed Render
portal. As of this writing it's labeled `"V26"`, holds 1,302 businesses
across all 13 Canadian provinces/territories, and uses province-prefixed
record IDs (`AB-0001`, `NS-0001`, ...). It is maintained by directly editing
that file and committing the diff (see e.g. commit `68e0f30`, "feat: publish
V26 portal enrichment batch") — an intentionally evolving, hand-curated
dataset, not the output of a fixed pipeline. Later "V" numbers (V20 through
V26 and beyond) refer to batches of this direct-edit process, unrelated to
the V14–V19 numbering described below.

## What's retired

An earlier body of work built a hash-chained enrichment pipeline over a
different, 955-record dataset using sequential `CFI-####` IDs:

```
full_955_enrichment_v14 -> recover_zero_page_staff_v15.py -> v15
                         -> sanitize_staff_precision_v16.py -> v16
                         -> materialize_v17_verified_recovery.py -> v17
                         -> materialize_v18_branch_attribution.py -> v18
                         -> materialize_v19_langsearch_contacts.py -> v19
                         -> export_portal_findings.py -> instance/portal_findings.json
```

Each stage pins the SHA-256 of its expected input and fails closed
(`ValueError: V15 source drift detected`, etc.) if that input doesn't match
byte-for-byte — real provenance discipline, not decorative. But as of
2026-09-11:

- The chain has already drifted from its own pins at more than one stage
  (V14's hash doesn't match what `recover_zero_page_staff_v15.py` expects;
  neither does V15's, checked against `sanitize_staff_precision_v16.py`).
- `export_portal_findings.py` — the script that was supposed to be this
  pipeline's connection to the deployed portal — still targets the 955-record
  `full_955_enrichment_v18` source and a hardcoded `"V18"` label. It has no
  relationship to `data/portal_findings.json` / "V26". Nothing currently
  deploys this pipeline's output.

Fixing the drift or restoring missing intermediate files (as
`AUDIT-2026-075`, `AUDIT-2026-081`, and part of `GAP-2026-063` in `todo.md`
originally asked) would repair a pipeline that doesn't feed the live
product. The decision made instead: leave the V14–V19 scripts and their
tests in place as historical/reference material (they demonstrate a
provenance-checking pattern worth reusing if a future dataset needs it), but
stop tracking their gaps as open work. They're removed from
`automation/task_manifest.json`.

## What this means for GAP-2026-065/066/067

These three items (recovering missing websites via LangSearch) were
originally scoped against the old pipeline's numbers: "V18 shows 342/955
with websites, 613 gaps." Retiring that pipeline doesn't retire the
underlying problem — the live V26 dataset has the same kind of gap, just
different numbers: **937 of 1,302 businesses have no website on file (871
have no website, phone, email, staff, or decision-maker evidence at all)**.
`resolve_955_websites.py` (the LangSearch discovery script) is
dataset-agnostic — it takes any `--input` JSON list of records with
`company`/`city`/`province`/`directory_record_id` — so it works unmodified
against V26-shaped input. It just needs to be pointed at a queue built from
`data/portal_findings.json`, not the old V18 file, once `LANGSEARCH_API_KEY`
is available.
