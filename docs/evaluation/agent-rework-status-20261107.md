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

### Measurement against the organisers' rules

Checked against `eval/huong-dan-do-latency.md` and `GIAI-DAP-MENTOR.md` item 7. **Treat the latency numbers above as raw: TTFT and total are over-measured, and small runs have no meaningful p95.** Nothing here is corrected yet.

| The organisers ask | We do | Effect |
|---|---|---|
| TTFT ends at the first token generated | Stamped in `_say`, after the whole first sentence is generated and passes the hard check (`pipeline/hot/nodes.py`) | Over-measured, inferred at 0.2 to 0.7 s a turn, not measured |
| Total ends at the last token | `total_ms` spans the whole graph turn (`pipeline/eval/runner.py:436`), including the wait for Jev and saving state | Over-measured, up to 6 to 8 s on some turns before the wait was shortened |
| Drop 3 warm-up turns | The 15-scenario runs do; the small runs used `--warmup 0`, Luna and `gpt-4o-mini` included | Mistake in those runs: connection time counted in the first turn |
| At least 100 turns | Luna 33, `gpt-4o-mini` 41 | p95 not meaningful; the grader warns too |
| Same hardware, API and model when comparing | Models compared across runs, some under free-tier limits | Absolute numbers do not compare between free Gemini and OpenAI |

Correct already: the start of the clock (`runner.py:430`), the filler not counting toward TTFT, `after_call` outside the timer.

Over-measuring does not mean the target is met: each tool round before the answer is real time, about 1 s.

Proposed: stamp the first token of the sentence actually said (a blocked sentence does not count), stamp the last token for total, log separately when the customer really sees the first sentence, and stop using `--warmup 0`. The total needs a change in `pipeline/eval/runner.py` and `trace.py`, which belong to the evaluation owner, so it waits for that decision.

### Voice bench from text, 2026-11-07

Text sent straight into the voice WebSocket (`VOICE_BENCH=1`), so end of speech and ASR are excluded: TTFA runs from the text arriving to the first audio byte. Three warm-up turns, then five measured turns in one call per configuration. One run each, so this shows direction and is not a p95. The real stack, reasoning effort `none`, TTS `gpt-4o-mini-tts`.

| Configuration | Easy | One lookup | Policy | Two lookups | Many lookups | Median TTFA |
|---|---|---|---|---|---|---|
| `gpt-5.6-luna`, Chat Completions, skills in prompt | **2.1 s** | 4.9 s | 5.5 s | 6.1 s | 5.5 s | **5.5 s** |
| `gpt-6-luna`, Chat Completions, skills loaded | 5.4 s | 5.2 s | 5.2 s | 13.5 s | 5.0 s | 5.2 s |
| `gpt-6-luna`, Chat Completions, skills in prompt | 5.6 s | 8.0 s | 7.9 s | 18.4 s | 6.5 s | 7.9 s |
| `gpt-6-luna`, Responses, skills in prompt | 3.6 s | 10.5 s | 8.4 s | 9.4 s | 8.8 s | 8.8 s |

Turns with no tool on `gpt-5.6-luna` reached 2.1 to 2.5 s, the only turns under the target. First audio from TTS was 0.9 to 1.8 s in most turns, which leaves about 1.4 s for the agent. Regenerations explain the worst turns (13.5 s and 18.4 s).

## Setup rework, late 2026-11-07

Measured on 2026-11-08: see the [report](agent-decisions-latency-report-20261108.md). The text below is what stood before those runs.

Checked by offline tests only, one of them a whole run against a fake OpenAI endpoint. No model has run on this code. Analysis behind it: five runs in `evaluation/runs/toolheavy/` on `GEN-0017`, `ADV-0137`, `ADV-0089`, `GEN-0011`.

| Area | Change | Why |
|---|---|---|
| Prompt cache | The system message holds only rules and skills; the turn's context comes right after the customer's last message (`agents/advisor.py`, OpenAI only) | From GPT-5.6 a lookup stops only at boundaries, such as the end of the first run of developer messages. The old layout hit 45 to 61% and paid 1.25 times to write the rest |
| Limiter | OpenAI limits set to this key's headers | Waits of up to 10 s fell into TTFT and made up the p95 tail |
| Tools | Strict mode, system-filled arguments hidden, a typed handoff brief, nulls removed before a tool runs (`mcp/tools.py`) | OpenAI recommends strict mode, and it is off by default on Chat Completions. `BAD_ENVELOPE` came from a flat brief |
| Usage | `stream_usage` on | A client of our own turned it off, so streamed calls reported no tokens |
| Per model | Effort and API settings sent only to `gpt-5*` and `gpt-6*`, temperature 0 otherwise | An agent's settings follow it when it moves to another model |
| Earlier results | A prompt section with the latest result per tool and subject; the money check accepts what quotes and orders returned earlier | Results were dropped between turns, so 15 to 26% of calls repeated and a true refund was withdrawn |
| Basket | The system adds up the total | Models added it wrong (11.86M for 10.86M) |
| Chained lookup | A search that finds one product brings its price and stock without a model round (`ChainLookupMiddleware`) | A round costs about 1.5 s and a tool 20 ms |
| Rules and skills | Reuse within the call, transfer only after the tool, narrower rules 4 and 6, no arithmetic by the model, one tool per need | Contradictions in the prompt caused regenerations and over-escalations |
| ITN | Money without diacritics is read (`5 trieu ruoi`) | A customer's own budget was blocked and answered with the safe line |
| Skills | In the prompt by default | Loading took 28% more model calls |
| Advisor | `gpt-5.6-luna` | Same TSR as `gpt-6-luna` on those scenarios, with fewer over-escalations and rounds |
| Soft guard | OpenAI Decisions API on `gpt-6-luna` replaces Jev (`llm/decisions.py`) | The user's decision |

To check on the first run:

- **Thresholds in `agents/policy.py` were set on Jev.** Probabilities from another model need not mean the same, so they are provisional until labelled examples set them.
- Whether the context after the customer's message changes behaviour; one replay of a similar layout did.
- `waited_s` near zero, and cached share of input.
- `pipeline/eval/cli.py` changed by one import (`jev` to `decisions`): it belongs to the evaluation owner, so it needs their review.
- `docs/design.md` still describes Jev.

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
