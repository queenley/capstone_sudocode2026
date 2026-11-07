# Agent rework status, 2026-11-07

What was changed after the seed-dev report of 2026-11-05 ([results](seed-dev-run-20261105.md), [fix plan](fix-plan-20261105.md)), what was measured, what is still open, and what to test next. All agent numbers are diagnostic: labels have no human review. The runs are local, in `evaluation/runs/` (not in git), through a local wrapper that skips the budget ledger.

**The code after the last run has not been measured.** Fixes marked "not measured" passed offline tests only. Gemini's free quota ran out on 2026-11-07, so the next run is on 2026-11-08 after 15:00 (+07:00).

## Measured so far

Same 15 scenarios, chosen because they were failing, on `gemini-3.5-flash-lite`, one run each. The agent's after run stopped at the last scenario (`GEN-0017`, 136 of 139 turns) and has no extractor labels, so RQR, HR and CCR are not comparable.

| Metric | Before | After guard and Jev rework |
|---|---|---|
| TSR | 13.3% (2/15) | **46.7% (7/15)** |
| TSR, hard cases | 25% | 75% (4 cases) |
| Failed calls | 18 | 11: 7 fixed, 0 newly failed |
| Regenerations | 30 | 21 |
| Turns ending on the safe line | 3 | 1 |
| Over-escalations | 3 | 3 |

The extractor labels do not explain the TSR gain: the before run stripped of labels also scores 13.3%. Without labels `forbidden_claims` cannot fail, so 46.7% is an upper estimate. Later runs covered 4 to 5 scenarios and are not comparable with this table.

## 1. Guards and purchase confirmation: fixed

Root cause: word matching. `order.create` passed 0/26; "vận chuyển ... máy lọc" read as a promise to transfer.

- The hard check keeps what has a fixed shape (raw personal data, internal terms, claiming to be human, what the tier forbids, a promotion not started) and what compares a number with data (money, days, weeks, months). Stock, order state, order placed and transfer promises moved to Jev.
- Jev reads every model sentence beside the stream, so a review does not delay the first token. A flag stops the stream, and at most one correction is spoken. The `RISK` regex that decided what Jev saw is gone.
- Tools with an effect wait for running reviews. Claims a later tool can make true (`false_transfer`, `unsupported_fact`, `unbacked_action`) are read again when the answer is out, so they do not block the tool they promise.
- Purchase agreement is read by Jev, intent `purchase`. No answer from Jev falls back to a plain yes to the exact read-back, otherwise no order. An agreed order is created and read back in the same turn.
- Code fills `price_vnd` from today's quote and the fields the customer already heard.
- Word lists removed from the customer's path: `RISK`, `NO`, `MUST_TRANSFER`, `ORDER_TALK`, the pronoun regex of `honorific`. The SKU check on read tools is gone: the tools report an unknown SKU themselves.

Known cost: a wrong sentence in the parallel path is heard and stays in the trace, so it still counts in HR. Measure it next.

## 2. Prompt and agent design: fixed, mostly not measured

| Cause | Fix |
|---|---|
| `NO_ANSWER` ordered a transfer on any retrieval miss | It states the fact and sends the model to the tools first |
| Jev saw no earlier results, so it flagged true statements | It reads the call's earlier tool results, known orders, quotes and policy amounts. `unsupported_fact` threshold raised to 0.9 |
| Model had no date | The prompt states today and tomorrow |
| No general rule against unbacked promises | Standing rule, plus the Jev question `unbacked_action` |
| Two conflicting rules numbered 12 | Merged, in `place-order` |
| Repeated read-back | Address case no longer changes the order's hash; a read-back stays open until its TTL or a change; the same order is not read twice |
| Basket totals blocked | The sum of today's quotes, this turn's included, counts as a source. So does the COD limit |
| Corrections forced transfers or invented facts | A correction neither repeats the sentence, nor transfers to fix the error, nor adds unsourced facts |
| Standing prompt too long | Seven skills loaded by the model: `place-order`, `change-order`, `order-lookup`, `schedule-callback`, `product-advice`, `objection-handling`, `data-request`. They are general by task and cover the organisers' 16 personas with the standing rules. Nothing is keyed to a persona, scenario or SKU, and a test checks it |
| Invented arguments, warranty stated with no purchase date | Standing rules |

Still open:

- `is_bridging` (`components/guardrails/fallback.py`) is a word list, and near-duplicate sentences can still be spoken.
- `ASKED_TO_DELETE` and `AGREED` still track the deletion question (`pipeline/hot/nodes.py`).
- Queries without diacritics matched poorly: 13 of 15 turns hit `no_match`, against 21 of 121 with diacritics. The turns sampled all come from one scenario (`ADV-0053`), so this needs more samples.
- A multi-item basket on `GEN-0017/2` still placed no order.

## 3. Weak models: reduced, not solved

| Model | Evidence |
|---|---|
| `gpt-4o-mini` | 3 correct skill loads in 41 turns. Promises without calling the tool (`ADV-0089/2`, `ADV-0129/2`). Says "no information", then recites the passage (`ADV-0141/2`) |
| `gemini-3.5-flash-lite` | 16 skill loads over 4 scenarios, some of them repeats |

Rules and Jev catch part of this after the fact, but they do not make a small model disciplined. The first proposal below addresses the rest.

## 4. Dataset and labels: not ours to fix

Owned by whoever keeps the dataset; details in [seed-dev-dataset-issues-20261105.md](seed-dev-dataset-issues-20261105.md). These make correct behaviour score as wrong, so TSR and HR are understated on some cases, by an amount not yet separated.

- 74 `order.create` calls lost the customer's final confirmation.
- `price_vnd` is one value per call, and the grader does not check which product a claim is about (`GEN-0017/1`: the right price of the right model counts as wrong).
- 15 of 78 Zalo identities are not in the CRM (`ADV-0070`).
- A label forbids the transfer the organisers require for out-of-document questions (`ADV-0129/1`).
- 243 review items are not approved.

## 5. Latency: not solved

`gpt-4o-mini`, 41 turns: TTFT p50 1.8 s, p95 7.2 s against 3 s; total p95 11.3 s against 8 s. Each tool before the first sentence adds about 1 s. Gemini numbers on the free tier include our own queueing (at most 51 to 67% of summed TTFT), so they do not measure the model.

The end-of-turn wait for Jev went from 6 s to 2 s, not yet measured. Fetching known data ahead of the model is not done.

Skill-discipline probe, 6 prompts, first decision only, real system prompt:

| Model | Correct | Seconds per prompt |
|---|---|---|
| `gemini-3.5-flash` | **6/6** | 3 to 9 |
| `gemini-3.5-flash-lite` | 5/6 | 1 to 2, one at 8 |
| `gemini-3.1-flash-lite` | 5/6 | 1 to 3, one at 11 |
| `nemotron-3.5-lightning` | 3/6 | 2 to 20 |

Groq models hit 429 after 2 or 3 prompts because the prompt is large. On real calls `gemini-3.5-flash` had TTFT of 11 to 78 s and hit its rate limit after 6 turns, so it passes the probe but is too slow and too limited as it stands. The probe is too small to rank the two lite models.

## Improvement loop: reduced, not yet run

Only the Knowledge Gap Loop and Reflection remain, per the decision of 2026-11-07. Removed: the LATS exploration, the playbook, and the simulator measurement commands. A/B was never implemented and is dropped. `agents/simulator.py` stays for the organisers' M2 simulator.

- **Gap Loop:** a model restates each question as a standalone one with other ways to ask it, questions are joined by embedding, and the answer comes from a person or, in an evaluation, a scripted file.
- **Reflection:** behaviour failures shared by at least 3 customers produce a change of one sentence in one skill. A change must cite an existing rule and carries no amount, promise or case. Versions are in `data/skills`, and going back is a pointer.
- **Approval in an evaluation is scripted** and recorded as `scripted-eval`. The brief asks for a person, so a report must say this was scripted. Have a person approve at least one change before submitting.
- `data/improvement/frozen.json` predates `seed-dev`; check it before measuring. Scripted answers must not come from the frozen set: nothing enforces this.
- Not yet run on a real model: `reflect`, `restate`, reading skills from `data/skills`.

## Proposals, for decision after testing

The goal is a **sweet point** between speed and discipline. No model tried is both fast enough and disciplined enough yet.

1. **Put every skill in the prompt.** There are only seven, and small models skip loading them; each load also costs a model round. Reflection would then edit the file and the service reload it. `ADVISOR_SKILLS=0` already keeps every body in the prompt, but `load_skill` stays offered, and a reload is not built. Cost: more input tokens per call (the bodies are about 5.5 KB). Compare both modes.
2. **Turn thinking down** on the Gemini advisor to protect the first token. Check it first on one call; the setting for these models is not verified.
3. **Pick the model on the 15 scenarios, not the probe:** `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`, then one stronger model only if quota allows.
4. **Fetch known data ahead of the model**, from state only (products in the brief or already shown), never by guessing from the customer's words.

## Test plan, 2026-11-08 after 15:00

Stay on the free Gemini key. OpenAI spend so far is about $0.13 of the $0.50 cap.

1. Run the same 15 scenarios with the extractor, and compare with `gemini-before-15` using `compare`: TSR, HR, RQR, CCR, violations, calls fixed and broken. One run uses most of a day's 500 requests.
2. Read the new logs: Jev's probabilities, passages shown, prompt cuts, skills loaded per turn.
3. Next day, proposal 1 against the same scenarios.
4. Check `frozen.json`, then R0, one improvement round, R1.

`docs/design.md` sections 4.4, 4.5, 4.8 and 10 and figure F still describe the old design; they are not tracked in this repository.
