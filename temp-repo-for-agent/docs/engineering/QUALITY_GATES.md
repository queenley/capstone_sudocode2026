# Quality gates

These gates are cumulative. A pull request passing its merge gate is not by
itself ready for production.

## Gate A — local change gate

Required before requesting review:

- scope matches one issue and, where applicable, one prior spec decision;
- secrets, personal data, generated builds and local environments are absent
  from the diff;
- new behaviour has deterministic tests and relevant eval cases;
- errors are bounded, actionable and do not expose provider internals to users;
- logs/traces carry run and turn identifiers and apply PII controls;
- migrations are forward compatible and rollback is documented.

Current executable checks:

```sh
# Backend: use Python 3.12, matching CI
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q

# Frontend
cd ../frontend
npm ci
npm run build
```

## Gate B — pull-request merge gate

Required checks should include:

| Check | Current state | Target |
|---|---|---|
| Backend install and tests on Python 3.12 | Runs in backend deployment workflow | Required for every relevant PR |
| Frontend clean install and production build | Runs as part of deployment action | Separate required PR check |
| Python lint/format/type checks | absent | Required |
| Frontend lint and component tests | absent | Required |
| API integration tests with PostgreSQL | absent | Required |
| Secret/dependency/code scanning | absent | Required |
| Spec pair check (`flow.md` with `diagrams.md`) | manual | Automated |
| Golden deterministic safety set | absent | Required once harness exists |

Merge is blocked when any required check fails, a high-risk change lacks a
rollback, a behavioural change has no eval evidence, or a specification file
is changed outside its paired `spec` workflow.

## Gate C — release candidate

A release candidate must have:

- immutable code revision and dependency lock evidence;
- environment/config validation without printing secret values;
- successful migrations against a production-like database snapshot;
- passing contract, auth/ownership, tool-failure and SSE tests;
- baseline-versus-candidate evaluation manifest;
- no hard safety regression;
- latency and cost within accepted budgets;
- smoke, readiness, observability and rollback checks;
- named release owner and observation window.

## Gate D — production promotion

Promote only after canary evidence shows:

- no critical security, privacy, identity or unsupported-price event;
- error, fallback, handoff, latency and provider-limit rates remain within the
  release's abort thresholds;
- persistence and trace records reconcile for sampled turns;
- the previous healthy version and backward-compatible schema remain usable.

Any hard-gate breach aborts rollout immediately; averages do not override it.

## Definition of done

A capability is `done` when:

1. its acceptance criteria pass on `main`;
2. required tests and evals are reproducible in CI;
3. telemetry can distinguish success, failure, guard block and fallback;
4. operator and rollback procedures exist;
5. relevant risks and decisions are updated;
6. user-facing and engineering documentation matches actual behaviour.

## Required test layers

- **Unit:** parsing, policies, guards, rate limits, state transitions.
- **Contract:** request/response schemas, tool schemas and provider adapters.
- **Integration:** API + PostgreSQL + fake tools/provider, including auth and
  ownership boundaries.
- **Evaluation:** multi-turn task and safety scenarios with frozen inputs.
- **End-to-end smoke:** deployed login, conversation, safe response and trace.
- **Resilience:** timeout, 429, malformed tool output, provider failure,
  duplicate request, database restart and partial stream.

Live paid-provider tests are scheduled or manual diagnostics, not merge gates;
merge gates must be deterministic and runnable with fakes or recorded fixtures.
