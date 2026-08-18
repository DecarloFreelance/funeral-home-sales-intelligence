# Enrichment agent pipeline

The enrichment workflow is staged. Agent suggestions never become public
directory data by themselves.

## 1. Discover missing websites

Generate a bounded, local artifact for entities without a non-rejected website:

```bash
python -m canada_funeral_intel website agent-discover \
  --model deepseek-ai/deepseek-v4-flash-0731 \
  --provider nvidia \
  --live-search \
  --entity-limit 10 \
  --output exports/website-discovery.json
```

Live mode requires `BRAVE_SEARCH_API_KEY` and records the returned search URLs,
titles, and snippets in the artifact. Without `--live-search`, discovery is
model-only and must not be treated as web search.

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
