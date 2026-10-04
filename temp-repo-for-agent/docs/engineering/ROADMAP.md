# Delivery roadmap

This roadmap closes risk in dependency order. It is intentionally organised as
vertical, demonstrable slices rather than by folder or agent name.

## Milestone 0 — establish the safety floor

**Status:** `not-started`
**Goal:** make every subsequent AI change measurable and safe to merge.

Deliverables:

- Add pull-request CI for backend tests, frontend build and static checks.
- Add tests for auth boundaries, conversation ownership, SSE framing, model
  allow-list validation, configuration failure and trace PII masking.
- Add deterministic `guard_hard` tests before connecting any pricing tool.
- Resolve the missing backend startup command and contradictory deployment
  comments/documentation.
- Define a versioned database migration path and a readiness endpoint whose
  status code reflects database availability.
- Create the first small golden set with stable IDs and expected safety/tool
  outcomes; no LLM judge is required for the first gate.

Exit evidence:

- Required checks run on every pull request and block merge on failure.
- The same backend and frontend commands pass locally and in CI.
- A deliberately unsupported price is rejected by a deterministic test.
- Deployment smoke test proves `/health`, login and one authenticated read.

## Milestone 1 — tool-grounded advisory vertical slice

**Status:** `not-started`
**Goal:** answer one real product/price question without inventing facts.

Deliverables:

- Introduce typed hot state, a virtual `now` and explicit turn/run IDs.
- Implement the minimum router lanes needed for in-scope, clarification and
  out-of-scope turns.
- Add catalogue search, inventory check and `pricing.get_quote` through the
  approved tool boundary; persist tool inputs/outputs and `quote_id`.
- Bind tools by lane and reject client-supplied provider/model pairs outside
  the server allow-list.
- Implement deterministic checks for numbers, quote freshness, identity tier
  and unsupported commitments before emitting the customer-visible event.
- Persist latency, token, model, prompt/config version and outcome metadata.

Exit evidence:

- Golden cases prove every stated price comes from the current turn's tool
  result and an expired quote cannot be repeated.
- Tool-denied lanes produce zero tool calls by construction.
- p95 customer-visible latency and per-turn token cost are reported, not
  estimated.
- Provider failure produces a recorded failed turn and a controlled fallback.

## Milestone 2 — memory and customer continuity

**Status:** `not-started`
**Goal:** improve a later conversation using governed, attributable memory.

Deliverables:

- Add customer identity tiers distinct from application authentication.
- Implement append-only facts, provenance, validity and current-fact views.
- Implement retrieval, Call Brief rendering, freshness checks and the cold-path
  write gate.
- Add memory-off and memory-on feature switches to the same evaluation runner.
- Add deletion/retention procedures and tests for cross-customer isolation.

Exit evidence:

- Two-call golden scenarios show lower repetition with memory enabled.
- Every brief line resolves to a source turn/tool record.
- Unverified identity cannot reveal protected remembered fields.
- Expired facts are excluded or explicitly marked stale under a virtual clock.

## Milestone 3 — handoff, copilot and operational readiness

**Status:** `not-started`
**Goal:** make failure and uncertainty safe for customers and useful for humans.

Deliverables:

- Implement the four handoff causes, a single handoff state machine and a
  provenance-rich Handoff Brief.
- Add human queue/claim/resolve actions and a copilot draft-review-send path.
- Add QA review, feedback capture and error-cluster reporting.
- Add service-level dashboards, alerts, backups, restore drill, rollback drill
  and incident ownership.
- Threat-model prompt injection, tool abuse, PII exposure and tenancy.

Exit evidence:

- Handoff tests prove no autonomous customer reply is sent after human control
  is established.
- Restore and rollback drills have dated artefacts.
- Alert routes and on-call ownership are tested.
- High risks in `RISK_REGISTER.md` have residual scores accepted by an owner.

## Milestone 4 — controlled improvement loop

**Status:** `deferred`
**Goal:** improve quality without allowing self-modification to bypass review.

Deliverables:

- Mine knowledge gaps and failure clusters from reviewed production evidence.
- Curate exemplars and playbook proposals with versioning and approval.
- Run shadow/canary comparisons against a frozen baseline and manifest.
- Promote only changes that pass safety, quality, latency and cost gates.

Exit evidence:

- Every promoted change has dataset version, baseline, candidate, manifest and
  rollback target.
- No production prompt, tool policy or exemplar changes itself automatically.

## Work-item template

Use this in an issue or pull request:

```md
### Outcome
<observable user or operator result>

### Specification
<section/figure links; say "implementation-only" if no behaviour changes>

### Acceptance criteria
- [ ] <deterministic, testable condition>

### Evaluation impact
<cases added/changed, expected metric movement, regression set>

### Risks and rollback
<risk IDs, feature flag, data migration, rollback method>

### Evidence
<tests, eval report, trace, latency/cost result, screenshots if relevant>
```

## Prioritisation rule

Rank work by `(safety + customer impact + learning value) / delivery cost`.
Security, privacy, financial-claim correctness and data-integrity failures
override that formula and are fixed before feature work.
