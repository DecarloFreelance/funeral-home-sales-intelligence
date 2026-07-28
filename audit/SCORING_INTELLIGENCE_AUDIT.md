# Scoring Intelligence Audit

## Overview

This audit evaluates the scoring, intelligence, prioritization, and decision-making layers of the Funeral Home Sales Intelligence platform.

The system transforms extracted website intelligence into commercial opportunity scores, outreach priorities, and sales recommendations.

---

# Intelligence Architecture

Current processing flow:

Website Intelligence
|
v
Feature Detection
|
v
Conversion Scoring
|
v
Opportunity Scoring
|
v
Lead Value Calculation
|
v
Revenue Opportunity Analysis
|
v
Sales Readiness Classification
|
v
Executive Prioritization
|
v
Outreach Recommendations


---

# Scoring Components

## Conversion Score

The conversion scoring engine evaluates detected website capabilities.

Current weighted features include:

- Online planner
- Appointment booking
- Lead capture
- Pricing
- Chat
- Preplanning
- Contact forms

The scoring system uses fixed weights defined in `scoring.py`.

---

## Opportunity Score

Opportunity scoring evaluates missing digital capabilities.

The system identifies gaps that represent possible modernization opportunities.

Examples:

- Missing online planning systems.
- Missing appointment workflows.
- Missing lead capture infrastructure.

---

## Lead Value

Lead value combines:

- Existing conversion maturity.
- Missing opportunity signals.

Current calculation:

Opportunity value is weighted higher than existing conversion capability.

---

## Revenue Opportunity Intelligence

The revenue scoring layer evaluates:

- Website conversion gaps.
- Partnership indicators.
- Community signals.
- Contact quality.
- Digital improvement opportunities.

Outputs include:

- Revenue opportunity score.
- Revenue tier classification.
- Reason explanations.

---

# Intelligence Outputs

Verified output fields include:

- Conversion score.
- Opportunity score.
- Lead value.
- Sales readiness.
- Sales stage.
- Revenue opportunity score.
- Executive priority score.
- Sales priority score.
- Lead temperature.
- Outreach priority.

The system produces structured sales intelligence in:

`data/results.json`

---

# Strengths

## Multi-layer Intelligence

The platform goes beyond basic website auditing.

It combines:

- Technical website analysis.
- Commercial opportunity scoring.
- Sales classification.
- Outreach planning.

## Explainable Recommendations

The system provides reasons behind recommendations.

Examples:

- Missing online planning system.
- Missing lead capture infrastructure.
- Missing consultation booking.

---

# Identified Gaps

## Scoring Fragmentation

Multiple scoring systems exist:

- Lead value.
- Priority score.
- Sales priority score.
- Executive priority score.
- Revenue opportunity score.
- Digital opportunity score.

Future development should consolidate scoring ownership to avoid conflicting rankings.

---

## Static Weighting

Current weights are manually defined.

Limitations:

- No historical sales feedback loop.
- No machine-learning adjustment.
- No conversion outcome optimization.

---

## Sales Readiness Assumptions

Sales readiness currently uses rule-based signals.

Examples:

- Contact availability.
- Website opportunity.
- Missing features.

These signals may not always represent true buying intent.

---

## Contact Quality Dependency

Opportunity scores can remain high even when contact quality is moderate.

Future scoring should include stronger contact confidence weighting.

---

# Recommendations

1. Consolidate scoring models into a unified intelligence score.

2. Add historical performance feedback to improve weighting accuracy.

3. Introduce confidence scoring for every intelligence output.

4. Separate opportunity potential from sales readiness.

5. Add outcome tracking after outreach campaigns.

---

# Phase Completion

Phase 5 — Scoring Intelligence Audit completed.

No implementation changes should begin until all audit phases are completed and findings are consolidated.
