# Evaluation run history

Before selecting model-backed test cases, read `docs/evaluation/RUN-LEDGER.md`.
Prefer cases absent from completed runs and reserved holdouts. A paired R0/R1
retest is intentional: label it explicitly, keep the same cohort and grading,
and do not count it as new coverage.

After starting or finishing each model-backed run, update its entry in that
ledger with selected scenario IDs, configs, status and the evidence directory.
Preserve historical entries; missing evidence or billing remains INCOMPLETE.
Never commit raw conversations, keys or customer data into the ledger.

The imported `20261017-111459` is read-only evidence. The user explicitly
excluded its ten scenario IDs from this work's model runs; see the ledger.
