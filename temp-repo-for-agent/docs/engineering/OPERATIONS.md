# Operations and incident runbook

## Local startup

Backend prerequisites are Python 3.12, Docker and at least one configured model
provider key.

```sh
cd backend
docker compose up -d
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python setup.py
uvicorn src.api.app:app --reload
```

In another shell:

```sh
cd frontend
npm ci
cp .env.example .env
npm run dev
```

Do not put a secret in a `VITE_*` variable; Vite embeds it in public browser
assets.

## Basic verification

```sh
curl -fsS http://127.0.0.1:8000/health
cd backend && source .venv/bin/activate && python -m pytest tests/ -q
cd ../frontend && npm run build
```

A healthy `/health` body is currently `{"status":"ok"}`. A degraded body still
uses HTTP 200, so inspect the JSON until a separate readiness contract is
implemented.

## Production topology

- API: Azure App Service, workflow `.github/workflows/main_sudo-code.yml`.
- Browser app: Azure Static Web Apps, workflow
  `.github/workflows/azure-static-web-apps-red-mushroom-0c2892f00.yml`.
- Database: PostgreSQL, resolved from supported Azure or `DATABASE_URL`
  environment variables.
- LLM providers: selected from committed YAML; credentials remain in the
  environment.
- Tracing: optional Langfuse; PostgreSQL and application logs remain required
  evidence because telemetry export can fail.

The repository currently has no `backend/startup.sh` despite a README reference
to it. Before the next production release, capture the actual App Service
startup command as code or documented environment configuration.

## Deployment checklist

- [ ] Revision and release owner recorded.
- [ ] Required quality/evaluation gates passed.
- [ ] Effective provider/model and environment variables validated by name.
- [ ] Database migration and backward compatibility verified.
- [ ] CORS frontend origin and frontend API origin match from opposite sides.
- [ ] Health/readiness, login and authenticated API smoke checks pass.
- [ ] Logs and traces contain the release/run identifier without raw PII.
- [ ] Previous healthy revision and rollback instructions are known.
- [ ] Observation window and abort thresholds are active.

## Triage sequence

1. Stop customer harm: disable the affected feature/model/tool or roll back.
2. Preserve evidence: revision, request/turn IDs, redacted logs, trace, tool
   records, timestamps and configuration version.
3. Classify: security/privacy, unsupported fact, data integrity, availability,
   latency/cost or experience.
4. Determine blast radius and whether persisted state must be quarantined.
5. Restore service through rollback/fallback before attempting a broad fix.
6. Validate with a targeted smoke/regression case.
7. Write the incident follow-up and permanent test/eval case.

Never paste access tokens, API keys, database URLs, raw customer messages or
unredacted traces into tickets or chat.

## Common failure playbooks

### Database unavailable

1. Read `/health` and capture `source`, `host`, `resolved_ip` and the redacted
   error detail.
2. Check private DNS/VNet integration when resolution is absent or unexpected.
3. Check firewall and `sslmode=require` for public connectivity.
4. Check connection exhaustion and pool timeouts.
5. After recovery, verify login, conversation listing and a write/read cycle.

### Provider 429, timeout or 5xx

1. Confirm the affected provider/model and rate-limiter statistics.
2. Disable it in the offered model list or route to an evaluated fallback.
3. Respect provider retry guidance; do not add invisible SDK retries.
4. Compare error, latency, token and cost rates before re-enabling.

### Unsafe or unsupported answer

1. Disable the affected lane/model/tool path if exposure can continue.
2. Preserve the turn, current-turn tool results, quote ID and guard outcome.
3. Determine whether the cause is missing enforcement, bad tool data, stale
   memory, routing, prompt/schema drift or model behaviour.
4. Add a deterministic guard/test where possible and a permanent eval case.
5. Re-run the full safety suite before rollout.

### Trace export missing

1. Keep serving traffic if core safety and persistence remain healthy.
2. Run the Langfuse auth check and inspect exporter errors.
3. Reconcile a sample against PostgreSQL/application logs.
4. Do not claim observability coverage for the missing window.

## Rollback

Prefer application rollback or feature disablement. Do not roll a database
schema backward destructively under live traffic. Use expand/migrate/contract
so the prior application revision remains compatible during the observation
window. After rollback, repeat smoke checks and record any data written by the
failed revision that needs quarantine or repair.

## Incident record minimum

Record impact, start/detect/mitigate/end times, severity, affected revisions
and features, customer/data scope, proximate and systemic causes, recovery,
evidence links, follow-up owners/dates and the regression case ID.
