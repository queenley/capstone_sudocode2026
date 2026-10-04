# Engineering decision log

The product specification records intended behaviour. This log records durable
engineering choices used to implement and operate it. Add a new entry; do not
rewrite history. A later entry supersedes an earlier one.

## Decision index

| ID | Decision | State | Evidence |
|---|---|---|---|
| ED-001 | Deploy API and browser app separately | accepted | Azure workflows and `docs/flow.md` section 2 |
| ED-002 | Use SSE for guarded turn delivery | accepted | `backend/src/api/chat.py`, `docs/flow.md` section 2/8.4 |
| ED-003 | Keep secrets in environment and non-secret routing in YAML | accepted | `backend/src/config/config_manager.py` |
| ED-004 | Share rate limiting per provider account | accepted | `backend/src/llm/factory.py`, rate-limiter tests |
| ED-005 | Treat PostgreSQL as durable evidence and Langfuse as optional telemetry | accepted | `backend/src/llm/tracing.py`, `docs/flow.md` section 16 |
| ED-006 | Use one seeded bearer-token account for the demo only | temporary | `backend/src/api/auth.py` |

## ED-001 — separate API and browser deployments

- **State:** accepted
- **Context:** the API requires Python, provider credentials and PostgreSQL;
  the browser app is a static Vite build.
- **Decision:** deploy FastAPI to Azure App Service and the browser bundle to
  Azure Static Web Apps. Configure exact cross-origin access.
- **Consequences:** API/base URL and CORS origins must agree; deployments and
  rollback are independent; end-to-end smoke tests must cover both origins.

## ED-002 — SSE after complete-answer safety processing

- **State:** accepted
- **Context:** customer-visible content must be checked as a complete answer;
  raw schema-constrained model tokens are not safe prose.
- **Decision:** send a bounded filler event and then the complete guarded reply
  over SSE. Do not expose raw model token streaming.
- **Consequences:** measure both filler latency and safe-content latency;
  buffering and partial-stream failure need explicit tests.

## ED-003 — environment secrets, committed routing

- **State:** accepted
- **Decision:** keep keys and credentials in environment variables; keep model
  names, routing and rate assumptions in committed YAML.
- **Consequences:** startup/preflight must validate required names; changing an
  effective model remains reviewable in version control.

## ED-004 — provider-account rate-limit scope

- **State:** accepted
- **Decision:** all models using one provider account share one in-process
  sliding-window limiter; failed attempts consume request capacity and 429s
  trigger cooldown.
- **Consequences:** correct within one process, but not globally across workers;
  distributed enforcement remains open under R-008/R-009.

## ED-005 — durable evidence versus optional telemetry

- **State:** accepted
- **Decision:** core run/turn/tool/provenance data belongs in project storage;
  Langfuse is an optional observability view and may have retention/export gaps.
- **Consequences:** the current message-only schema is insufficient and must be
  expanded before traceability can be considered complete.

## ED-006 — demo authentication boundary

- **State:** temporary; revisit before external user accounts
- **Decision:** seed one account and store a long-lived bearer token in browser
  storage, with no server-side revocation.
- **Consequences:** acceptable only for the constrained demo stated in the
  source; production identity requires the treatment in R-003.

## New decision template

```md
## ED-NNN — concise title

- **State:** proposed | accepted | superseded by ED-NNN | rejected
- **Date:** YYYY-MM-DD
- **Owners:** <roles or names>
- **Context:** <forces, constraints, evidence>
- **Decision:** <one clear choice>
- **Alternatives:** <serious options and why not selected>
- **Consequences:** <benefits, costs, risks, migration and rollback>
- **Review trigger:** <date, scale threshold, incident or dependency change>
```
