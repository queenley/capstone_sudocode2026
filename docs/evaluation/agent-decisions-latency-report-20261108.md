# OpenAI Decisions, tool mechanisms and latency, 2026-11-08

What changed since the agent rework of 2026-11-07 ([status](agent-rework-status-20261107.md), [voice trials](voice-latency-trials-20261107.md)), what it measured, and what is still open.

**Result.** The Jev guard is replaced by the OpenAI Decisions API and runs without failures. Cache, limiter, strict tools and the order flow now work on `gpt-5.6-luna`. On the four tool-heavy scenarios TSR stays at 3/4, with the failing call caused by its script. TTFT p95 is 3.69 s, **still above the 3 s target**, and Total p95 is 4.62 s, within the 8 s target.

**How far the numbers go.** Each configuration ran once on four scenarios and 36 turns (`SCN-GEN-0017`, `SCN-ADV-0137`, `SCN-ADV-0089`, `SCN-GEN-0011`, chosen because they use many tools). The organisers' latency guide asks for at least 100 turns, so these p95 values are indications. The extractor was off, so Repeat-Question Rate and Hallucination Rate were not measured. Raw runs are local, in `evaluation/runs/setup-new/`.

## Before and after

All runs: `gpt-5.6-luna`, effort `none`, skills in the prompt, three warm-up turns dropped.

| | Before setup rework | After setup (`six`) | After order and tool fixes (`eight-standard`) |
|---|---|---|---|
| TSR | 2/4 | 3/4 | 3/4 |
| Over-escalation | not compared | 2 | 1 |
| Context Carryover Rate | 32 | 16 | 28 |
| TTFT p50 / p95 | not compared / 10.8 s | 2.15 / 4.09 s | 2.08 / 3.69 s |
| Total p50 / p95 | not compared / 10.8 s | 2.88 / 4.71 s | 2.60 / 4.62 s |
| Wait in the limiter | 21.1 s | 0 s | 0 s |
| Tool calls / exact repeats | 96 / 34 | 51 / 4 | 47 / 3 |
| Model calls | 81 | 68 | 65 |
| Prompt cache read | 53% | 82% | 80% |
| Advisor cost | $0.082 | $0.034 | $0.035 |

- The limiter and repeated tools explain most of the first drop. The change between `six` and `eight-standard` is within the spread between runs, so it is not yet proof of a latency gain.
- Context Carryover moved between 16 and 32 across these runs and 20 to 28 across the three final ones. It is not stable enough to claim a gain, and the drop to 16 was not investigated.

## 1. From Jev to OpenAI Decisions

**What changed.** `llm/decisions.py` replaces `llm/jev.py`. The PolicyAgent calls `POST /v1/decisions` on `gpt-6-luna` through `client.decisions.create` (`openai==3.33.0`). `TYPESAFE_API_KEY`, `JEV_URL` and `AI_GATEWAY_API_KEY` are gone, and the guard uses `OPENAI_API_KEY`. `JEV_HEAD_START_MS` is now `REVIEW_HEAD_START_MS`.

**Prompt design.**

| Part | Choice | Why |
|---|---|---|
| Rules | `config/prompts/agent/policy_rules.md`, a developer message in Vietnamese with an explicit cache breakpoint | Stable, cached and readable. The rules are general and rest on the brief and the organisers' rule documents, not on single cases |
| Evidence | Settled evidence with its own breakpoint, then the sentence under review | Questions stay outside the shared prefix |
| Questions | One short predicate per rule, such as "Câu đang xét có vi phạm luật X không?" | The Decisions API returns a probability per predicate |
| Intents | Facts first, then the conversation by role, ending on the customer | With the facts last, a clear purchase read 0.00; with them first, 0.98 |
| Tool results | Passed with `ok` or the error | A refused tool means the action did not happen |
| Earlier documents | Passages read earlier in the call stay in the evidence (up to 9) | A correct statement based on an earlier passage could be flagged as unsourced. Internal or superseded passages are left out |

**Measured.**

| | Value |
|---|---|
| Calls in a run (`six`) | 84, none failed, no limiter wait |
| Turns reviewed | 35 of 36, no check skipped for lack of an answer. The other turn was not investigated |
| Review time | p50 about 0.40 s, maximum 0.75 s (labelled cases, called alone) |
| Intent time | p50 about 0.30 s (labelled cases, called alone) |
| Review input read from cache | 41% (`six`) |
| Cost in a run | At most $0.03. The figure uses the full input price, so cached tokens make it lower |
| Labelled cases | 27 review and 14 intent cases correct, then 11 of 12 on a harder set. The one miss is the ambiguous hotline sentence below |

The labelled sets ran before the last wording changes to `purchase`, `change` and `handoff`. Those changes were rechecked on reproduced conversations only.

**Stable, but sensitive to context.** The same input gave the same reading four times in a row. A sentence that read 0.18 to 0.41 in one run and above 0.95 in another differed by the read-back before it, not by chance. Rewording the `purchase` rule brought both to 0.98 or above.

**Still provisional.**

- The thresholds in `agents/policy.py` were set on Jev. They need calibrating on labelled data.
- "Bought earlier, now gives the remaining details" read 0.65 on one reproduced conversation, under the 0.7 threshold. The agent reads the order back once more, so it costs a turn and causes no error.
- `docs/design.md` is kept outside this repository and still describes Jev.

## 2. Modes tried on `gpt-5.6-luna`

### Per request

40 requests per mode on the same five replayed requests, in round robin so that drift falls on every mode alike.

| Mode | First chunk p50 / p90 | Whole round p50 / p90 | Output tokens p50 | Tier in the response |
|---|---|---|---|---|
| Standard | 1.34 / 1.99 s | 1.59 / 2.48 s | 66 | `default` |
| `service_tier: fast` | **1.10 / 1.40 s** | **1.26 / 1.79 s** | 59 | `priority` |
| `verbosity: low` | 1.27 / 1.85 s | 1.55 / 2.30 s | 56.5 | `default` |
| Both | 1.06 / 1.64 s | 1.27 / 2.08 s | 59 | `priority` |

### On whole conversations

Same four scenarios, run one after the other, with the same warm-up.

| | Standard | `fast` only | `verbosity: low` only |
|---|---|---|---|
| TSR | 3/4 | 3/4 | 3/4 |
| Context Carryover Rate | 28 | 20 | 24 |
| Over-escalation | 1 | 1 | 1 |
| TTFT p50 / p95 | 2.08 / 3.69 s | 2.09 / 3.33 s | 2.54 / 4.08 s |
| Total p50 / p95 | 2.60 / 4.62 s | 2.39 / 4.13 s | 3.05 / 4.95 s |
| Turns with TTFT above 3 s | 3 of 36 | 4 of 36 | 8 of 36 |
| Model calls | 65 | 69 | 67 |
| Tool calls / exact repeats | 47 / 3 | 53 / 4 | 46 / 4 |
| Regenerations | 0 | 0 | 1 |
| Prompt cache read (Langfuse) | 80% | **0%** | 80% |
| Advisor cost | $0.035 | $0.07 to $0.22 (estimate) | $0.035 |

### Decisions

| Option | Decision | Reason |
|---|---|---|
| `verbosity` | **Removed** | No gain per request and slower in the conversation run, though that gap may be noise. Replies were already short |
| `service_tier: fast` | **Available, off** | Clear per-request gain and a smaller one in conversations, but TTFT p95 stays above 3 s and the cost at least doubles. Langfuse shows no cache reads under this tier, on the same code that shows 80% at standard. Whether the API truly skips the cache or only reports it differently is unknown. Explain that before turning it on |
| `reasoning_effort: none` | Already on | OpenAI's documents do not state that `none` means no reasoning tokens at all on this model |
| `ultrafast` | Not available | Documented only for `gpt-6-astra` and `gpt-6.1-sol` |
| Predicted outputs | Not available | Documented only for GPT-4o and GPT-4.1 models, and not with function calling |
| Flex | Rejected | OpenAI describes it as slower |

### Other models

Accuracy first, then speed. Same setup, warm, four scenarios, one run each, before the order fixes in section 3.

| | `gpt-5.6-luna` | `gpt-6-luna` | `gpt-6.1-terra` |
|---|---|---|---|
| TSR | 3/4 | 2/4 | 1/4 |
| TTFT p50 / p95 | 2.15 / 4.09 s | 2.68 / 4.85 s | 1.79 / 6.10 s |
| Total p50 / p95 | 2.88 / 4.71 s | 3.14 / 5.52 s | 3.04 / 6.10 s |
| Model calls | 68 | 79 | 65 |
| Tool calls / exact repeats | 51 / 4 | 65 / 13 | 40 / 2 |
| Advisor cost | $0.034 | $0.021 | $0.133 |

Most failures of `gpt-6-luna` and `gpt-6.1-terra` went through our guards and order flow, so this table does not prove they are less accurate. Their comparison should be repeated on the fixed code before any final ranking. `gpt-5.6-luna` stays as the advisor.

| Other provider | Finding |
|---|---|
| `gpt-oss-120b` on Groq | A round took 1.1 to 2.0 s with one of 21.7 s, not faster on this tier, limited to about 8,000 tokens per minute |
| `qwen3.8-27b` on Groq | 0.9 to 1.6 s with skill bodies removed to fit the limit. It answered a two-product comparison without calling a tool |
| Nemotron Lightning on NVIDIA | TSR 1/4, TTFT p50 about 17 s |
| DeepSeek, MiniMax and GLM through NVIDIA | Timed out |
| Kimi and Nemotron Super through NVIDIA | 404 |
| Cerebras, `claude-haiku-5.5`, DeepSeek direct | Not measured, no key |

## 3. Tool and order mechanisms

Each round costs about 1.3 s and each tool about 20 ms, so the number of rounds decides latency in chat.

| Mechanism | What it does | Where | Effect seen |
|---|---|---|---|
| Strict tools | Strict schemas, system-filled arguments hidden from the model, typed handoff brief | `mcp/tools.py` | No malformed tool calls in these runs |
| Nulls removed | Nulls that strict mode requires are dropped before a tool runs | `without_nulls` | Tool errors 0 |
| Chained lookup | A search that finds one product brings its price and stock with no model round | `ChainLookupMiddleware` | Saves a round on 6 to 10 of 36 turns, see below |
| Results reused in the call | A prompt section holds the latest result per tool and subject | `reusable_results`, `_earlier_block` | Exact repeats from 34 to 3 |
| Basket total by code | The system adds the basket; the model never does | `_basket_after`, `_basket_block` | Told totals correct |
| Own product out of the basket | A quote no longer treats its own SKU as a second item | `other_products_only` | Fixes a wrong second-item discount |
| Missing address by state | Supplying the address that a just-created order lacks needs no second agreement, and asks no model | `no_address`, `_intents` | Updates succeed in all three runs; they were blocked before |
| COD limit on the whole basket | VC-03 counts the basket the order goes with, not one line | `_cod_order` | The agent states the 10M limit instead of placing part of an order. One of three runs did not reach this path |
| Read-back by name | Says names, never codes, drops empty promo lines, and gives the whole basket's total | `purchase.draft` | SKU leaks from 1 turn to 0 |
| Price heard first | No order until the customer has heard the price (PB-09). This does not ask the Decisions API | `ActionGuard` | Does not spend a call on an order that must wait anyway |
| Placeholder cleanup | A literal `[Bn]` is stripped like any citation | `MARKS` | Leaks from 2 turns to 0 |
| No codes aloud | Rule 2: codes are for tools only | `advisor/rules.md` | Leaks 0 in these runs |
| Earlier results for transfers | The transfer check also sees what the call already knows; the "no passage" note points to earlier results first | `_intents`, `NO_ANSWER` | The needless refund transfer stopped |
| Unaccented money | `5 trieu ruoi` is read as money | `intake/itn.py` | Stops blocking a customer's own budget |

### Grouping tool calls and chaining them

A turn with tools needs at least two model rounds: one to ask for the tools and one to write the answer. In `eight-standard`, TTFT p50 is 2.24 s on turns with tools (24 turns) and 0.92 s on turns without (12 turns). Each round saved is worth about 1.3 s, so lookups are arranged by what depends on what.

```
catalog_search --(exactly one product, no successor)--> pricing_get_quote + inventory_check   by the harness, no model round
pricing_get_quote, inventory_check, delivery_estimate    independent once the code is known: one model round, together
order_create, order_update, handoff_transfer             never chained: guarded writes, the model asks for them
```

| Case | How it runs | Where |
|---|---|---|
| Independent lookups | The model asks for them in one round, and they run at the same time. `parallel_tool_calls` is not set, so OpenAI's default (on) applies | `advisor/rules.md`, `ToolNode` |
| Dependent lookups | A quote needs the code a search returns, which would take a round of its own | |
| Search finds one product | The harness calls price and stock itself, at the same time, then gives the model real tool messages to read | `chained_lookups`, `ChainLookupMiddleware` |
| Several searches in one round | Each one that found a single product is chained, so a two-product question stays in one extra step | `chained_lookups` |
| Search finds several products, or one with a successor | No chain: the model has to choose | `chained_lookups` |
| Already asked this run | Not called again, and earlier turns' results are reused (above) | `chained_lookups`, `reusable_results` |

Chained calls pass through `ToolGuardMiddleware` like any other, so system arguments are filled and internal fields removed. They carry a `chained` mark and do not count as model calls. The chain does not depend on the customer's words, only on what the search returned.

**Measured.** From Langfuse, one run each. Rounds include warm-up and opening turns, so there are more than the measured model calls above. "Turns chained" counts measured turns that start with search, quote and stock, which also matches the rare turn where the model asked for all three itself.

| | `six` | `eight-standard` | `eight-fast` | `eight-low` |
|---|---|---|---|---|
| Model rounds | 74 | 71 | 74 | 72 |
| Rounds with no tool | 38 | 39 | 37 | 38 |
| Rounds with one tool | 31 | 26 | 30 | 28 |
| Rounds with two or more tools | 5 | 6 | 7 | 6 |
| Turns chained, of 36 | 10 | 6 | 7 | 9 |

- **Chaining works and saves a round on 6 to 10 of 36 turns.** The saving was never measured with the chain switched off, so about 1.3 s per chained turn is an estimate from the round time.
- **The model rarely groups calls on its own.** In `eight-standard`, only 6 of 32 rounds with tools asked for more than one. Many turns need only one lookup, so this does not show how many rounds were lost. That was not analysed.
- **The cost of the chain:** stock is fetched even when the customer asked only for the price. That adds about 20 ms and some prompt tokens on the next round, against one round saved.

**Not done.**

- The answer round after tools remains. Skipping it means template replies, which are hard when the customer also asks something else.
- `delivery_estimate` is not chained, since it needs an address and not every turn wants it.
- Planning a whole graph of tools ahead (LLMCompiler) was rejected as heavier than this problem: the common dependency is one step, and the chain already covers it.

**The address is not mandatory before an order.** A rough keyword count finds that in 63 of 235 `order.create` calls in `seed-dev`, and 3 of 5 in `public_sample`, the customer never gives an address. Fixed customer turns could then never produce the order. An order may be created first and completed when the address arrives.

### Failed cases that were not real agent errors

| Case | Finding | Action |
|---|---|---|
| `SCN-GEN-0017` `call_2`, all runs | Expects `order.create` for four items, total 10.86M. The fixed turns ask for cash, give no address and never confirm, and the facts say `payment: bank`. Following QT-01 cannot reach it | Left alone; the dataset owner should look at it |
| `SCN-GEN-0011` `call_1` turn 4, "gọi hotline hỏi thêm" | The label counts a transfer as over-escalation, but the sentence is ambiguous. It is the one over-escalation left | Left alone |

### Remaining behaviour

- The model still sometimes tries `handoff.transfer` or `order.update` too early. The guard blocks it correctly, but it costs a round. The slowest standard turn (3.98 s) was one of these.
- One `verbosity: low` turn regenerated with "em xin đính chính" and took 6.85 s. This was not analysed.

## 4. Prompt cache, limiter and clock

| Area | Now | Basis |
|---|---|---|
| Static prefix | The system message holds only rules and skills. The turn's context comes right after the customer's last message (OpenAI only) | From GPT-5.6 a cache lookup stops only at boundaries. Reads went from 53% to about 80% |
| Skills | In the prompt by default (`ADVISOR_SKILLS=0`). All runs here had 0 `load_skill` | Loading took 28% more model calls |
| Usage reporting | `stream_usage` on | A client of our own had turned it off, so streamed calls reported no tokens |
| Settings per model | Effort and API settings go to `gpt-5*` and `gpt-6*` only, tier to OpenAI only | Settings follow an agent when it moves model |
| Limiter | OpenAI ceilings set from this key's headers | The organisers' clock starts at the request's arrival, so a limiter wait counts. Waits are now 0 |
| Latency | TTFT and Total are stamped per the organisers' guide; Total ends at the last token | TTFT counts planning and tool rounds, as the guide requires |

**Comparison rule.** Every bench states whether the prompt cache was warm, and warm runs are compared only with warm runs.

## 5. Warm-up at service start

Not changed in this work. The evaluation's warm-up turns warm the prompt cache, but a service that has just started does not.

| Component | Warm at start | Note |
|---|---|---|
| Database, checkpointer | Yes | |
| MCP connections, graph, agents | Yes | Retries on the first turn if it failed |
| ASR, VAD, Smart Turn | Yes | In the background, so a very early call can arrive first |
| TTS connection | Yes | Kept open 120 s |
| `kb_search` embedding | Unclear | First call of a run took 46 to 210 ms, later ones about 20 ms |
| **Advisor prompt cache** | **No** | The first customer pays a cold prompt. Measured first-chunk times, hit against miss: 1.23 against 1.30 s on `gpt-5.6-luna` |
| **HTTP connection to the advisor** | **No** | About 0.1 s for the first handshake |
| **Decisions cache and connection** | **No** | Reviews run beside the stream, so this does not delay the first token |

Prewarming is documented for the Responses API only, and we use Chat Completions. The simple option is one real request at startup, at about $0.0015.

## 6. Latency techniques

| Technique | Status | Evidence |
|---|---|---|
| Speak the first sentence at once | Applied | Clearest voice effect ([voice trials](voice-latency-trials-20261107.md)) |
| PCM in small chunks, keep-alive | Applied | Moderate |
| Reviews beside the stream | Applied | Decisions does not delay the first token |
| Grouped and chained tools, reuse within a call | Applied | Section 3, "Grouping tool calls and chaining them" |
| Skills in the prompt, effort `none` | Applied | Section 4 |
| Filler or short line before a tool | Rejected | Team decision: it is penalised and is not the answer's first audio |
| LLMCompiler, Responses or WebSocket, Realtime, routing model | Rejected | Heavier than the problem, or slower when measured |
| Fewer wasted rounds from early `transfer` and `update` | **Next for chat** | Section 3 |
| Faster TTS | **Next for voice** | TTS takes about 1.1 s, the largest cut left. Needs a provider key |
| Shorter first sentence, split by clause | Not tried | |
| Warm-up at service start | Not done | Section 5 |
| Template replies for pure business tools | Not tried | Harder when the customer asks a follow-up |

## 7. Open

1. Run at least 100 turns, with the extractor on, against the baseline. Until then TTFT p95, RQR and HR have no valid value here.
2. Write `ttfa_ms` to the trace and bench voice with real end-of-speech and ASR timing. Measured TTFA does not exist yet in the evaluation output.
3. Find out why `fast` shows no cache reads, then decide on `fast`.
4. Calibrate the Decisions thresholds on labelled data.
5. Reduce the early `transfer` and `update` attempts.
6. Decide whether to report `said_first_ms` beside TTFT: the organisers' table says the token is generated, rule 1 says emitted. We stamp generation.
7. Repeat the comparison of `gpt-6-luna` on the fixed code if another advisor is still of interest.

## Review needed

- **Evaluation owner:** `pipeline/eval/cli.py` (one import, `jev` to `decisions`), `pipeline/eval/runner.py` (Total stamped at the last token), and the extractor (`product-extractor-v9`: strict schema without offsets, `scorers.py`, `extractor.txt`; `extractor-implementation.json` is `pending_review`). The extractor was not run on this code.
- **Dataset owner:** the two cases in section 3.
