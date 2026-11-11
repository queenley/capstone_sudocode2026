# Hard cases for the original agent

Five single-call scenarios in the organisers' format, each for one way the agent can go wrong whatever the product
or the wording: they are not copies of hidden cases and no code names them. Every expected price is the organisers'
mock's on the day of the call (`tests/agent/test_hard_cases.py`, no model call). They were written from failures seen
in real runs on 2026-11-11 and 2026-11-12, and have not been played by the agent yet.

| Scenario | What it checks | Seen in |
|---|---|---|
| SCN-HARD-01 | a short follow-up question keeps the passage read one turn before; no transfer | `SCN-ADV-0069`: "7–15 ngày" read out, then "chưa có thông tin" and a transfer |
| SCN-HARD-02 | a second product asked about by reference to the first; a price question never transfers | `SCN-WTY-F06`: a transfer asked in the same round as the catalogue search |
| SCN-HARD-03 | a benefit with a price condition (BH-05) is not offered below it | `SCN-WTY-F05`: the package offered for a 2,450,000d fan |
| SCN-HARD-04 | the same benefit above the condition: the rate and the time limit, no computed amount | the lesson of `data/reflection/warranty`, asked directly |
| SCN-HARD-05 | a tool question and a policy question in one turn, the second quoting the retired policy | the organisers' SAMPLE-07, joined with a price question |

Run them with the evaluation command, on the original agent:

```bash
export AGENT_PROFILE= PYTHONPATH=apps/ai-agent-service/src:packages/backend-common
apps/ai-agent-service/.venv/bin/python run_eval.py --scenarios data/hard-cases/scenarios --config full --out evaluation/runs/hard-cases/full.jsonl
```
