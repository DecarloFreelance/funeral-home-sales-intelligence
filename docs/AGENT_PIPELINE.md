# Enrichment agent pipeline

The enrichment workflow is staged. Agent suggestions never become public
directory data by themselves.

## Visible checkpointed runner

Use `agent-pipeline` when you want one terminal session to show the complete
agent workflow. It prints every stage as it finishes and writes a timestamped
artifact directory under `--output-dir`.

The default is a dry run: agents may perform live search/model calls and write
artifacts, but database decisions are not applied.

```bash
python -m canada_funeral_intel agent-pipeline --model deepseek-ai/deepseek-v4-flash-0731 --provider nvidia --search-provider searxng --output-dir exports/agent-pipeline
```

After inspecting the dry-run output, enable database changes explicitly. The
`--process-approved` option additionally crawls websites approved at or above
the default 0.85 confidence threshold.

```bash
python -m canada_funeral_intel agent-pipeline --model deepseek-ai/deepseek-v4-flash-0731 --provider nvidia --search-provider searxng --apply --process-approved --output-dir exports/agent-pipeline
```

Add `--review-facts` when you intentionally want the full business-facts
review/apply stage. People review remains artifact-only in this runner; it does
not automatically accept or reject people observations.

For terminals that split pasted lines, define short aliases first:

```bash
MODEL=deepseek-ai/deepseek-v4-flash-0731
alias arun='python -m canada_funeral_intel agent-pipeline'
```

Then run the dry pass with one short line:

```bash
arun --model "$MODEL" --output-dir exports/agent-pipeline
```

The run directory contains `website-discovery.json`, `website-review.json`,
`website-review-effective.json`, and `people-review.json`; the business-facts
artifact is added when `--review-facts` is used. A failed run leaves its prior
artifacts intact, so the terminal output and timestamped directory provide a
checkpoint for review before rerunning.

## 1. Discover missing websites

Generate a bounded, local artifact for entities without a non-rejected website:

```bash
python -m canada_funeral_intel website agent-discover \
  --model deepseek-ai/deepseek-v4-flash-0731 \
  --provider nvidia \
  --live-search \
  --search-provider searxng \
  --entity-limit 10 \
  --output exports/website-discovery.json
```

SearXNG live mode uses the free local/self-hosted search endpoint in
`SEARXNG_URL` (default `http://127.0.0.1:8080`) and records the returned search
URLs, titles, and snippets in the artifact. Use `--search-provider brave` only
when `BRAVE_SEARCH_API_KEY` is configured. Without `--live-search`, discovery
is model-only and must not be treated as web search.

Inspect the artifact. Suggestions with `website_url: null` are retained as
unresolved discovery results and are not inserted.

## 2. Agent-review candidate identity

Review the pending candidate queue:

```bash
python -m canada_funeral_intel website agent-review \
  --model deepseek-ai/deepseek-v4-flash-0731 \
  --provider nvidia \
  --queue-limit 10 \
  --output exports/website-candidate-review.json
```

Inspect the recommendations, then apply them explicitly:

```bash
python -m canada_funeral_intel website agent-review-apply \
  --input exports/website-candidate-review.json \
  --apply
```

The agent approves only identity-supported candidates; uncertain candidates
should be deferred.

## 3. Queue candidates for verification

```bash
python -m canada_funeral_intel website agent-discovery-apply \
  --input exports/website-discovery.json \
  --apply
```

This creates candidate websites with `agent_discovery` provenance and places
them in the existing website review queue. Approve only candidates that match
the business and location.

## 4. Verify and process approved websites

```bash
python -m canada_funeral_intel website batch-verify \
  --allow-network --entity-limit 10 --candidate-limit 1 \
  --host-delay 2 --progress

python -m canada_funeral_intel website process-approved \
  --limit 10 --engine http
```

The normal review and identity checks remain the gate before a site is
processed. 403, DNS, and identity failures are acquisition signals, not proof
that the business is invalid.

## 5. Extract and review enrichment

```bash
python -m canada_funeral_intel website extract-people --website-id WEBSITE_ID
python -m canada_funeral_intel business-facts extract --website-id WEBSITE_ID
python -m canada_funeral_intel people people-review populate
python -m canada_funeral_intel people people-review agent-review \
  --agent people-review --output exports/people-review.json
```

Business-facts review artifacts must cover the complete current fact set before
they can be applied. People and website agent outputs are recommendations and
must be reviewed before resolution or approval.
