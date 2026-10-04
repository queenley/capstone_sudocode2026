# Risk register

Score likelihood and impact from 1 (low) to 5 (high); score is their product.
Critical: 20–25, high: 12–19, medium: 6–11, low: 1–5. Owners are roles until
named people are assigned. Review open critical/high risks weekly.

| ID | Risk | L | I | Score | Existing control | Required treatment / closure evidence | Owner | Status |
|---|---|---:|---:|---:|---|---|---|---|
| R-001 | Advisor invents a price, promotion, stock value or delivery promise | 4 | 5 | 20 | Prompt rule and structured response | Current-turn tool provenance plus deterministic number/commitment guard; zero frozen-set violations | AI lead | open |
| R-002 | Customer data is disclosed before identity verification or across customers | 3 | 5 | Conversation ownership by app user | Customer identity tiers, memory isolation tests, field-level policy and deletion audit | Security/data | open |
| R-003 | Bearer token theft through browser script enables long-lived access | 3 | 4 | Single demo account, token expiry | HttpOnly refresh-cookie flow, CSP/XSS controls, revocation and auth threat model before real accounts | Backend lead | accepted-demo |
| R-004 | Missing memory ledger prevents the core continuity proposition | 5 | 4 | Last 20 raw messages replayed | Governed facts, provenance, freshness, brief rendering and memory-on/off evidence | AI lead | open |
| R-005 | Prompt-only safety fails under adversarial or unusual input | 4 | 5 | Hard rules in system prompt | Code-enforced policy, adversarial suite, tool permissions and guarded output boundary | AI lead | open |
| R-006 | Deployment is not reproducible because startup/config assumptions live in Azure | 3 | 4 | GitHub workflows, settings validation | Codify startup, environment contract, readiness and deployed smoke/rollback evidence | Platform | open |
| R-007 | Schema creation races or unversioned changes corrupt/block deployments | 3 | 4 | Idempotent DDL and duplicate-object handling | Versioned migrations, one release task, backup/restore drill | Backend lead | open |
| R-008 | Provider outage/quota exhaustion makes the only hot path unavailable | 4 | 3 | Multi-provider config, rate limiter, readable error | Evaluated fallback routing, circuit breaker, budgets and availability dashboard | AI/platform | open |
| R-009 | Process-local token/cost accounting under-reports multi-worker production use | 4 | 3 | Callback ledger and limiter stats | Durable per-turn usage, provider billing reconciliation and cost alerts | Platform | open |
| R-010 | PII enters model/provider or telemetry without policy enforcement | 3 | 5 | Regex masking for Langfuse | Intake classification/tokenisation, retention policy, DPA/data-flow review and leakage tests | Privacy | open |
| R-011 | Client-selected provider/model bypasses the intended evaluated route | 3 | 4 | Provider key and provider ID validation | Server-side pair allow-list, role policy and tests | Backend lead | open |
| R-012 | Partial SSE/provider failure leaves inconsistent conversation state | 3 | 3 | User turn persists; readable error event | Turn state machine, idempotency key, retry semantics and reconciliation tests | Backend lead | open |
| R-013 | Degraded `/health` returns HTTP 200 and masks an unusable instance | 4 | 3 | Diagnostic response body | Separate liveness/readiness; non-2xx readiness on DB failure; alert test | Platform | open |
| R-014 | Eval set is too small or contaminated, producing false confidence | 4 | 4 | Four dated provider probes | Versioned product scenarios, holdout set, provenance and human calibration | Eval owner | open |
| R-015 | Seed password re-hashing on every multi-worker startup increases load and complexity | 3 | 2 | Bcrypt and connection pool | Seed/rotate through a one-time admin or migration operation | Backend lead | open |

## Risk lifecycle

1. Add a risk when it can materially affect safety, privacy, correctness,
   availability, cost, delivery or reputation.
2. Link treatments to issues and pull requests; “monitor” requires a named
   metric and threshold.
3. Re-score after controls are proven. Do not lower a score because work began.
4. Close only with reproducible evidence and an owner accepting residual risk.
5. Reopen when an incident, provider change or architecture change invalidates
   the evidence.

## Escalation

- Critical: halt or disable the affected path; engineering and product owners
  decide on resumption from evidence.
- High: treatment must be planned with an owner and target milestone.
- Medium: review during milestone planning.
- Low: accept explicitly or batch with related maintenance.
