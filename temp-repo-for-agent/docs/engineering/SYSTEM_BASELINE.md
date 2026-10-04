# System baseline and gap analysis

This is the as-built view at commit `5a1c8ee` (2026-09-19). It separates
implemented behaviour from the target architecture in `docs/flow.md`.

## As-built request path

1. The React client logs one seeded user in and stores a bearer token in
   `localStorage`.
2. The client creates a PostgreSQL-backed conversation and posts a message.
3. The API persists the user message, replays the last 20 messages and selects
   a cached `AdvisorAgent` for the requested provider/model.
4. LangChain invokes a schema-constrained advisor. Provider-scoped rate limits,
   token callbacks and optional Langfuse callbacks are attached by the factory.
5. The API immediately emits an SSE filler event, persists the complete answer,
   then emits `message` and latency-bearing `done` events.
6. No business tool or deterministic output guard runs in this path today.

## Implemented inventory

| Area | Current implementation | Evidence | Status |
|---|---|---|---|
| Web UI | Login, conversation list, model picker, chat composer and SSE reader | `frontend/src/` | partial |
| Authentication | One seeded account, HS256 access token, protected endpoints | `backend/src/api/auth.py` | partial |
| Persistence | Users, conversations and messages in PostgreSQL; startup schema application | `backend/src/api/db.py` | partial |
| Advisor | LangChain agent with structured `AdvisorDraft` and hard rules in the prompt | `backend/src/agents/` | partial |
| Provider routing | Google, Groq and NVIDIA configured through YAML and environment keys | `backend/config/models.yaml` | done |
| Quota control | Provider-shared sliding-window limiter and 429 cooldown | `backend/src/llm/rate_limiter.py` | partial |
| Usage tracking | Process-local token ledger and limiter statistics | `backend/src/llm/token_ledger.py` | partial |
| Observability | Structured logs, degraded health diagnostics, optional Langfuse callback | `backend/src/api/app.py`, `backend/src/llm/tracing.py` | partial |
| Provider evaluation | Probe prompts, structured scoring and dated reports | `backend/examples/probe_providers.py`, `backend/reports/` | partial |
| Delivery | Independent Azure workflows for API and static web app | `.github/workflows/` | partial |
| Automated tests | Nine rate-limiter tests | `backend/tests/test_rate_limiter.py` | partial |

## Specification coverage

| Spec section | Capability | State | Material gap |
|---|---|---|---|
| 1–2 | Product/deployment overview | partial | Deployed topology exists, but no environment validation or end-to-end smoke gate is encoded. |
| 3 | `HotState` and resource boundaries | not-started | No typed shared state, projection or write-authority enforcement. |
| 4 | Intake, ASR, ITN and PII | not-started | Text enters directly; PII masking only protects traces. |
| 5 | Customer identity | not-started | App-user authentication is not customer identity verification. |
| 6–7 | Memory ledger, retrieval, freshness and write gate | not-started | Only raw conversation history is stored and the prompt window is capped at 20 messages. |
| 8 | Hot-path harness | not-started | No graph nodes, virtual clock, feature switches or regeneration budget. |
| 9 | Orchestrator lanes | not-started | The request always goes directly to the advisor. |
| 10 | Advisor ReAct subgraph | partial | Schema and base agent exist; the tool set is empty and API calls `invoke` directly rather than `process`. |
| 11 | Guardrails and warnings | not-started | Safety is prompt-only; no deterministic number/provenance check or warning surface. |
| 12 | Fallback | partial | Provider errors become readable messages; policy and business fallback do not exist. |
| 13–14 | Human handoff and copilot | not-started | No handoff state, brief, queue or human approval path. |
| 15 | MCP tools and permissions | not-started | No catalogue, pricing, inventory, CRM, order or knowledge adapters. |
| 16 | Traceability and QA review | partial | Langfuse and basic message storage exist; no durable turn/tool/provenance schema or QA UI. |
| 17 | Golden evaluation | not-started | Provider probes are not the product evaluation suite described by the spec. |
| 18 | Improvement loop | not-started | No gap mining, exemplar bank, reflection or playbook lifecycle. |
| 19 | Product interface | partial | Customer chat exists; warning, handoff, copilot and QA surfaces do not. |
| 20–21 | Agent interaction/inventory | partial | Only `AdvisorAgent` is implemented. |

## Verified baseline

| Check | Result on 2026-09-19 | Interpretation |
|---|---|---|
| `npm ci` | passed; 97 packages audited, 0 reported vulnerabilities | Frontend lockfile installs cleanly in the review environment. |
| `npm run build` | passed; Vite produced `dist/` | Frontend compiles successfully. |
| Python 3.12 virtualenv, `pip install -r requirements.txt`, `python -m pytest tests/ -q` | passed; 9 tests in 2.00s | The existing backend suite is green, but covers only the rate limiter. |
| Working tree before documentation | clean | Baseline observations refer to upstream state. |

Generated `frontend/node_modules/` and `frontend/dist/` are ignored and are not
part of the documentation change.

## Known inconsistencies and control gaps

1. `README.md` lists `backend/startup.sh`, but that file is absent. The backend
   deployment depends on platform startup inference/settings that are not
   captured in the repository.
2. Some frontend comments still say FastAPI serves the built SPA, while the
   actual workflows and API comments deploy frontend and backend separately.
3. CI runs backend tests, but there is no frontend build/test job for ordinary
   pull requests that do not trigger the deployment workflow, no lint/type
   gate and no product evaluation gate.
4. Startup intentionally serves a degraded API when the database is down, yet
   `/health` still responds HTTP 200. A platform probe can therefore treat an
   unusable instance as healthy.
5. The selected `provider` and `model` are accepted as independent input.
   `BaseAgent` validates the provider but does not verify that an overridden
   model belongs to that provider's configured allow-list.
6. User messages are persisted before model execution; provider failure leaves
   an unmatched user turn. There is no turn status or idempotency key.
7. Output safety relies on a prompt. The system can state prices or promises
   without tool evidence because no deterministic guard exists.
8. Token and cost totals are process-local. Multiple workers, restarts and
   deployments fragment accounting.
9. Database schema mutation and seed-password hashing happen on every worker
   startup. There is no versioned migration or one-time release task.
10. Production readiness is not reproducible locally because deployment
    configuration, smoke tests, backup/restore evidence and rollback checks are
    not codified.

## Baseline update rule

Update this document only from evidence on `main`: file/commit references,
test or eval artefacts, deployment records, dashboards or incident reports.
Move a capability to `done` only when its acceptance criteria and relevant
quality gates are reproducible by someone other than its author.
