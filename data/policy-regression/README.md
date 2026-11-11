# Policy regression sets

What the organisers' documents already say, the agent must do right from R0: these sets test the product, not the
improvement loop. They come from the first proof of 2026-11-09, which showed both cases are product work:

| Folder | What it checks | The fix it guards |
|---|---|---|
| `paraphrase/` | a customer asks a policy question in their own words (delivery attempts, confirmation calls, tracking, checking COD goods, hotline hours, refusing a parcel); the answering section must reach the advisor and the agent must answer, not transfer | the questions each section answers, indexed with it (`components/knowledge/expand.py`, `data/kb/questions.jsonl`) |
| `after-sale-and-delivery/` | a return past its window or of an opened item, and a bulky product to an island, beside valid exchanges and mainland orders as controls | the after-sale and delivery rules of the skills |

The scenarios use the organisers' format; each folder's `learn/` and `frozen/` halves are kept as written, and both
halves are regression cases here. Offline, `tests/agent/test_reflection_dataset.py` checks they load and that every
expected price and stock state is the organisers' mock's on the day of the call.

Run one as any evaluation, with the spend watched (`llm/spend_guard.py`):

```bash
apps/ai-agent-service/.venv/bin/python run_eval.py --scenarios data/policy-regression/paraphrase/frozen/scenarios --config full --out evaluation/runs/policy-paraphrase/full.jsonl
```
