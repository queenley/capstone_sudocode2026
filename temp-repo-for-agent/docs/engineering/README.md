# Engineering control centre

This directory is the operating layer for developing Agent Core. It does not
replace the product specification. It turns the specification into a baseline,
priorities, quality gates, evaluation rules, operational procedures and an
auditable decision trail.

**Baseline:** commit `5a1c8ee` on `main`, reviewed 2026-09-19.

## Document map

| Document | Question it answers | Update cadence |
|---|---|---|
| [SYSTEM_BASELINE.md](SYSTEM_BASELINE.md) | What exists now, what is only specified, and where are the gaps? | After a material implementation change |
| [ROADMAP.md](ROADMAP.md) | What should be built next, in what order, and how is completion proved? | At planning and after each merged slice |
| [DELIVERY_WORKFLOW.md](DELIVERY_WORKFLOW.md) | How does an idea move safely from issue to production? | When the delivery process changes |
| [QUALITY_GATES.md](QUALITY_GATES.md) | What must pass before merge, release and production promotion? | When a new failure mode is found |
| [EVALUATION.md](EVALUATION.md) | How are model and system quality measured and compared? | With every eval-set or metric change |
| [OPERATIONS.md](OPERATIONS.md) | How is the system run, observed, diagnosed and rolled back? | After every incident or deployment change |
| [RISK_REGISTER.md](RISK_REGISTER.md) | Which risks are open, who owns them, and what evidence closes them? | Weekly |
| [DECISIONS.md](DECISIONS.md) | Which engineering decisions are active and why? | When a durable decision is made or superseded |

## Source-of-truth hierarchy

When documents disagree, use this order:

1. `docs/flow.md` and `docs/diagrams.md` define intended product behaviour.
2. Automated tests and executable configuration define verified behaviour.
3. Source code defines current, possibly unverified behaviour.
4. This directory records delivery status and controls.
5. Provider reports are dated observations, not permanent guarantees.

The specification files are binding and paired. Change them only through the
`spec` workflow in `CONTRIBUTING.md`; do not hide a product decision in a code
or general documentation pull request.

## Current status at a glance

The repository is an **MVP shell, not yet the specified advisory system**.
Authentication, persisted conversations, a configurable advisor, rate
limiting, token accounting, optional Langfuse tracing, provider probes, a React
chat UI and two Azure deployment workflows exist. The memory ledger, customer
identity, orchestration lanes, deterministic guardrail, MCP business tools,
handoff/copilot and golden-scenario evaluation harness do not yet exist.

The immediate delivery priority is to establish reliable CI and deterministic
safety tests, then implement the minimum vertical slice that retrieves a
customer fact, obtains a tool-backed quote, blocks an unsupported number and
records enough provenance to evaluate the result. See `ROADMAP.md`.

## Operating rhythm

### For every issue

1. Link the relevant specification section and risk, if any.
2. Define acceptance criteria and an evaluation case before implementation.
3. Ship the smallest vertical slice behind a feature flag when behaviour is
   incomplete or high-risk.
4. Attach test, eval, latency and cost evidence to the pull request.
5. Update the baseline, roadmap, risk or decision record only when the merged
   change materially affects it.

### Weekly engineering review

Review in this order:

1. Production health and open incidents.
2. Regression/evaluation trend and failure clusters.
3. High and critical risks without owners or due dates.
4. Current roadmap exit criteria and blockers.
5. Model/provider changes, token use and cost drift.
6. Decisions that need acceptance or supersession.

## Status vocabulary

Use only these values in tracking tables:

- `not-started`: no implementation is merged.
- `in-progress`: implementation exists on an active branch or is incomplete.
- `partial`: useful behaviour is on `main`, but the stated contract is not met.
- `blocked`: a named external dependency prevents progress.
- `done`: acceptance criteria have reproducible evidence on `main`.
- `deferred`: intentionally outside the current milestone.

“Done” never means “the code was written.” It means the applicable gates in
`QUALITY_GATES.md` passed and the evidence is linked.
