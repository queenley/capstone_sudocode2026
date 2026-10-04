# AI engineering delivery workflow

This workflow is the path from a problem statement to an observable, reversible
production change. It complements the branch, commit and specification rules in
`CONTRIBUTING.md`.

## 1. Frame the change

Write an outcome, not a component task. Identify the affected user, expected
behaviour, specification sections, data touched, model/tool dependencies and
failure modes. If intended behaviour changes, land the paired specification
change first in a separate `spec/*` pull request.

Definition of ready:

- acceptance criteria are observable and testable;
- baseline behaviour is measured or explicitly unknown;
- safety/privacy/data risks and rollback are named;
- an owner is accountable for delivery and post-release observation;
- evaluation cases exist or are part of the work item;
- external API/provider assumptions have a captured date and fallback.

## 2. Design the smallest vertical slice

Prefer one end-to-end path over several disconnected foundations. Define:

- typed inputs, outputs and errors;
- state ownership and persistence boundaries;
- tool permissions and idempotency behaviour;
- prompt/config/schema versions included in traces;
- feature flag or kill switch for risky behaviour;
- migration and backward-compatibility plan;
- latency and token budgets.

Use an entry in `DECISIONS.md` when the choice is durable, cross-cutting,
expensive to reverse or changes an interface. Routine implementation details do
not need a decision record.

## 3. Build with tests and evals

The minimum evidence depends on the change:

| Change | Required evidence |
|---|---|
| Pure deterministic code | Unit and boundary tests |
| API/data contract | Unit, integration, auth/ownership and migration tests |
| Prompt/model/routing | Frozen regression set, candidate comparison, latency and token report |
| Tool use | Schema, permission, timeout, retry/idempotency and bad-result tests |
| Memory | Provenance, isolation, freshness, deletion and memory-off/on cases |
| Safety policy | Adversarial cases plus deterministic enforcement tests |
| Deployment/config | Build, smoke, rollback and secret/config validation |

LLM output must never be the sole enforcement mechanism for price, privacy,
identity, permission or irreversible action.

## 4. Review the pull request

The author supplies:

- linked issue, spec section and risk IDs;
- concise design and explicit non-goals;
- evidence from the applicable quality gates;
- eval manifest and failure analysis for behavioural changes;
- screenshots only for visible UI changes, never as a substitute for tests;
- migration, rollout, monitoring and rollback notes.

The reviewer checks contracts and failure modes before style. A model answer
that “looks good” is anecdotal; the reviewer needs reproducible cases and the
full distribution, including failures.

## 5. Merge and release

Use a small, identifiable release unit. Apply migrations before code only when
they are backward compatible; otherwise use expand/migrate/contract. Deploy
behind a disabled or limited flag when uncertainty is material.

Promotion order:

1. local deterministic tests;
2. pull-request CI;
3. isolated integration/evaluation environment;
4. shadow traffic where possible;
5. internal or allow-listed canary;
6. gradual production rollout;
7. full promotion after the observation window.

Never use a provider/model alias that can change behaviour without a repository
change. Pin the effective model ID and record it in the eval/run manifest.

## 6. Observe and close

During the release window, compare against the baseline:

- safety violations and guard blocks;
- task success, handoff and fallback rates;
- tool errors and unsupported factual claims;
- p50/p95/p99 time to safe content;
- input/output tokens and cost per successful task;
- database/API errors and provider 429/5xx rates.

Close the work only after acceptance evidence is attached, dashboards are
healthy for the agreed window, relevant living documents are updated and a
rollback target remains identifiable.

## Model or prompt change protocol

1. Freeze the baseline model, prompt, config and dataset versions.
2. Run baseline and candidate with the same cases, virtual time and tool
   snapshots.
3. Inspect every safety regression and a sample of apparent improvements.
4. Reject a candidate that improves an average while violating any hard gate.
5. Record quality, latency, token and cost deltas with confidence intervals or
   repeated-run variance where stochasticity matters.
6. Canary with an explicit abort threshold and owner.

## Incident feedback loop

Every escaped AI failure becomes one or more of:

- a deterministic regression test;
- a stable evaluation case;
- a new guard or tool contract;
- a risk-register update;
- a runbook improvement;
- a documented decision if architecture or policy changes.

Fix the system boundary that allowed the failure, not only the observed wording.
