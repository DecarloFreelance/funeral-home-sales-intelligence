# Data Extraction Audit

## Extraction Architecture

The platform extracts intelligence from previously collected funeral home website data. The extraction pipeline operates on structured lead data stored under the `data/` directory and transforms raw website information into structured sales intelligence.

### Extraction Components

Relevant extraction-related capabilities include:

- Feature detection for identifying website capabilities and missing conversion features.
- Contact processing components responsible for cleaning and ranking extracted contact information.
- Lead scoring components that evaluate extracted website signals and business opportunities.

### Input Sources

The primary extraction input is:

- `data/leads.json`

This file contains collected website intelligence used by downstream analysis processes.

Additional structured outputs include:

- `data/results.json`
- Outreach-related CSV exports under `data/`

### Extracted Information

The system processes information including:

- Website contact signals.
- Email and phone information when available from collected website content.
- Digital business features such as:
  - Contact forms.
  - Appointment functionality.
  - Online planning tools.
  - Pricing information.
  - Other conversion-related website capabilities.
- Intelligence scoring fields including:
  - Conversion scoring.
  - Opportunity scoring.
  - Revenue opportunity indicators.
  - Sales readiness indicators.

---

## Data Processing Workflow

### 1. Raw Input

Website intelligence data is loaded from structured lead datasets containing:

- Business URLs.
- Website content.
- Collected page information.
- Existing contact signals.

### 2. Extraction

The extraction layer identifies:

- Website capabilities.
- Contact information patterns.
- Sales-relevant website signals.

### 3. Normalization

Extracted information is cleaned and standardized before being passed into scoring and analysis workflows.

Examples include:

- Removing invalid contact values.
- Normalizing contact formats.
- Filtering low-quality extracted records.

### 4. Validation

Validation currently focuses on filtering malformed or unusable extracted values.

Current limitations:

- Validation does not guarantee that extracted contacts belong to the correct decision makers.
- External verification is not currently part of the extraction workflow.

### 5. Storage

Processed intelligence is stored in:

- `data/results.json`

This output feeds downstream scoring and outreach preparation workflows.

---

## Extraction Capability Assessment

### Strengths

The current extraction architecture provides:

- Structured processing of collected funeral home website data.
- Automated identification of website conversion opportunities.
- Contact signal processing.
- Integration with lead scoring workflows.

### Limitations

Current limitations include:

- Extraction depends on already discovered websites.
- Contact discovery is limited to information available from collected sources.
- External enrichment is not integrated.
- Decision-maker identification remains limited.

---

## Identified Gaps

### Contact Enrichment

Missing capabilities:

- External business directory enrichment.
- Owner/director identification.
- Professional profile enrichment.
- Additional verification sources.

### Validation Reliability

Areas requiring improvement:

- Email verification.
- Phone validation.
- Duplicate contact detection.
- Confidence scoring.

### Extraction Coverage

The current system does not independently discover missing information outside collected website data.

---

## Recommendations

1. **High Priority:** Add external contact enrichment capabilities to improve decision-maker discovery.

2. **High Priority:** Improve email and phone validation using stronger verification methods.

3. **Medium Priority:** Expand extraction logic beyond pattern matching into contextual analysis.

4. **Medium Priority:** Integrate additional business intelligence sources for richer lead profiles.

5. **Low Priority:** Improve duplicate detection and extraction confidence scoring.

---

## Phase Completion

Phase 4 — Data Extraction Audit completed.

No implementation changes should begin until all audit phases are complete and findings have been consolidated.
