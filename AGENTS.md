# Evaluation

Before changing or running anything under `evaluation/`, read `evaluation/README.md`, especially its rules. The only
evaluation command is `run_eval.py` at the repository root; how a number is produced is in
`docs/evaluation/scoring-flow.md`.

- Every model-backed run spends money. Set `EVAL_BUDGET_DB` to the budget ledger (`evaluation/runs/20261024-work/budget.sqlite`)
  and never recreate the ledger to get past a cap. Try one scenario before a cohort.
- Changing the extractor (`config/prompts/evaluation/extractor.txt`, `scorers.py`) changes the instrument: compare numbers
  only between runs of the same `extractor_version`, and use `run_eval.py --relabel` to compare extractors on the same replies.
- The organisers' pack (`apps/ai-agent-service/data/btc`) is read-only; `tests/agent/test_btc_pack.py` pins it.
- Changing a scenario or a ground-truth label follows `evaluation/datasets/ground-truth-review/SKILL.md`.
- Never commit raw conversations, keys or customer data. `evaluation/runs/` is not in git.
