# Evaluation strategy

Provider probes answer “can this key reach this model, and how does it respond
to four generic prompts?” Product evaluation must instead answer “does the
whole system complete the advisory task safely, with useful memory, acceptable
latency and controlled cost?” Keep those two evidence types separate.

## Evaluation contract

Every run records an immutable manifest:

- run ID, timestamp and code revision;
- dataset and scenario versions;
- model/provider, prompt, tool schema and policy versions;
- feature flags and memory mode;
- virtual time and catalogue/tool snapshot;
- sampling parameters, retry policy and cache state;
- environment name and dependency lock hash.

The run produces machine-readable metrics and case-level errors. A Markdown
summary is a view, not the source of truth.

## Dataset structure

Each stable scenario should include:

```yaml
id: quote-expired-001
tags: [pricing, freshness, safety]
initial_state: {}
turns:
  - customer: "..."
    expected_lane: IN_SCOPE
    required_tools: [pricing.get_quote]
    forbidden_claims: [unsupported_price]
days_later: 8
assertions:
  quote_must_be_refreshed: true
  max_hard_violations: 0
```

Store tool/catalogue fixtures with the scenario or reference a content-addressed
snapshot. Use stable IDs; do not silently edit a case after it has informed a
release decision.

## Evaluation suites

| Suite | Purpose | Typical trigger |
|---|---|---|
| Smoke | Config, schemas and one happy path | Every PR |
| Safety | Price grounding, privacy, identity, promises, prompt injection | Every PR touching behaviour |
| Task | Search, quote, order and clarification success | Every behavioural PR |
| Memory | Later-call continuity, freshness, provenance and isolation | Memory changes |
| Handoff | Correct cause, brief and human-control state | Handoff/copilot changes |
| Resilience | Timeout, 429, malformed tools and partial failures | Adapter/runtime changes |
| Full regression | All frozen cases, repeated where stochastic | Release candidate/nightly |
| Production audit | Redacted, sampled real outcomes reviewed by humans | Ongoing |

## Metrics

### Hard gates

Count, do not average away:

- unsupported price/promotion/inventory/delivery claims;
- protected-data disclosure at an insufficient identity tier;
- unauthorised tool call or cross-customer memory retrieval;
- expired quote repeated as current;
- irreversible action without required confirmation;
- autonomous customer reply after human handoff.

The initial release threshold for every hard gate is **zero observed violations
in the frozen release set**. Production discovery triggers incident handling
and a permanent regression case.

### Quality and task metrics

- Task Success Rate (TSR).
- Correct Clarification Rate (CCR), reported on eligible turns.
- Repetition Question Rate (RQR), especially memory off versus on.
- Correct lane/tool selection and tool argument accuracy.
- Grounded factual-claim precision and provenance coverage.
- Correct handoff rate, false handoff rate and resolution rate.
- Human preference/score for helpfulness, relevance and Vietnamese tone.

Report denominators and confidence intervals; never compare percentages with
different eligible populations without stating that difference.

### Operational metrics

- time to filler and time to safe customer-visible content;
- end-to-end p50/p95/p99 latency by lane and provider;
- input/output tokens and estimated cost per turn and successful task;
- provider 429/5xx/timeout rate and fallback rate;
- guard block/regeneration counts;
- tool latency/error rate and database error rate.

## Scorers

Use scorers in this order:

1. exact deterministic assertions for state, tools, numbers and permissions;
2. programmatic semantic checks with explicit tolerances;
3. human review for policy nuance and experience;
4. LLM judge for scalable triage, calibrated against human labels.

An LLM judge cannot waive a deterministic safety failure. Judge prompts,
models and calibration sets are versioned just like product prompts.

## Candidate comparison

Run baseline and candidate against identical manifests. Report:

- absolute metrics and deltas;
- every hard-gate case;
- newly fixed and newly broken case IDs;
- repeated-run variance for nondeterministic outcomes;
- latency, token and cost deltas;
- error clusters, not only a global score.

Promotion requires no hard regression and an explicitly accepted trade-off for
any soft-metric regression. “The average improved” is insufficient.

## Production feedback

Only redacted, policy-approved production examples enter review. Human-labelled
failures first enter a quarantine set, then a reviewed regression set. Prevent
training/evaluation contamination by recording source, consent/retention class,
label author, review status and scenario version.
