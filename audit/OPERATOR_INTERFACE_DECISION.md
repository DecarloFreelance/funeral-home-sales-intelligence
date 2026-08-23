# Operator Interface Decision

Date: 2026-08-22
Status: Accepted

## Decision

Build a local, server-rendered web application using Flask and Jinja templates.
The application will bind to the loopback interface by default and operate on
the repository's existing generated files and SQLite CRM database.

## Why This Model

- The workflow contains evidence-rich tables, detail views, filters, forms, and
  long-running crawl progress that are more usable in a browser than a terminal.
- Server-rendered pages keep the first milestone small: no separate JavaScript
  application, API deployment, or duplicated client-side state model.
- Flask can call the existing Python workflow functions directly instead of
  spawning CLI subprocesses.
- Local-only operation keeps private campaign data and CRM records on the
  operator's machine and does not introduce hosting, authentication, or cloud
  storage requirements.
- The HTTP boundary leaves room for a richer client later without requiring the
  discovery, scoring, or CRM layers to change.

## Initial Architecture

```text
Browser on localhost
        |
Flask routes + Jinja views
        |
Operator service layer
        |
Existing discovery, scoring, outreach, and CRM functions
        |
data/generated + data/private + SQLite CRM
```

The route layer handles HTTP concerns only. A small operator service layer loads
and summarizes records, validates requested paths and parameters, and invokes
existing application functions. Business rules stay in their current modules.

## First Read-Only Routes

- `/` — workflow status and dataset summary
- `/queues` — normalized crawl queues and progress
- `/research` — unresolved domains and failure evidence
- `/leads` — ranked campaign leads
- `/leads/<domain>` — contact evidence and scoring detail
- `/candidates` — platform candidates, kept separate from campaign leads
- `/drafts` — generated, unsent outreach drafts
- `/crm/actions` — CRM action queue and current state

Missing optional data files produce an empty-state page, not an application
failure.

## Guarded Actions for the Following Increment

- Preview and confirm an import
- Start or resume a controlled crawl
- Apply a reviewed domain resolution
- Approve an unsent outreach draft
- Start and complete a CRM action

Every output replacement and CRM mutation requires explicit confirmation.
Sending email is outside this interface boundary.

## Runtime and Dependency Choice

- Add Flask as the only new runtime dependency for the first interface increment.
- Use Jinja, static CSS, and minimal browser JavaScript shipped with the app.
- Do not add a frontend build system, Node dependency tree, task queue, or ORM.
- Use Flask's development server for local operation only; it is not a production
  deployment configuration.

## Security Boundary

- Bind to `127.0.0.1` by default.
- Do not expose a public-listen option in the first milestone.
- Resolve data paths from an allowlist of application-owned locations rather
  than accepting arbitrary filesystem paths from requests.
- Escape displayed source content through Jinja's default HTML escaping.
- Use POST plus confirmation and CSRF protection for future mutations.
- Never display environment variables, credentials, or private correspondence.

## Rejected Alternatives

### Terminal-only interface

The existing commands remain useful for automation, but a terminal interface
does not adequately support evidence comparison, filtering, drill-down, draft
review, and visible workflow state.

### Desktop GUI toolkit

A desktop toolkit adds packaging and platform-specific behavior without a clear
benefit over a loopback web application.

### Separate single-page application and API

This would add a frontend toolchain, API versioning, and duplicated state
management before the single-operator workflow has been validated.

### Hosted web service

Hosting would introduce authentication, authorization, tenancy, deployment,
and private-data controls that are explicitly outside the first milestone.

## Revisit Conditions

Reconsider this decision if the product requires concurrent operators, remote
access, background jobs that survive application shutdown, or a supported
hosted deployment. Those requirements would justify a production application
server, authentication, persistent job queue, and a stricter service API.
