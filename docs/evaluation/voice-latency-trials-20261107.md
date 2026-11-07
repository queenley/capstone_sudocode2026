# Voice latency trials, 2026-11-07

Everything tried on the voice path on 2026-11-07: what ran, what it measured, what each technique did, and what is still open. **No configuration meets the organisers' targets.** Every run is small (one run per configuration), so the numbers show direction and are not p95. The organisers ask for at least 100 turns.

Raw data is local and not in git: `evaluation/runs/voice-matrix/` and `evaluation/runs/voice-text-bench/`. The code behind these trials is on `feature/agent-decisions-latency`; later results are in the [report](agent-decisions-latency-report-20261108.md). When these trials ran it was on `feature/agent-guard-rework` on top of `b5ab1f00`, uncommitted when this was written.

## Conclusions

1. `gpt-5.6-luna` was the fastest advisor per turn with no tool and per model call, compared with `gpt-6-luna` on the same text (one run each). Proposed: use `gpt-5.6-luna` on Chat Completions, effort `none`. Not decided yet. It costs twice as much.
2. Speaking the first sentence as soon as it exists is the technique with the clearest effect. PCM streaming helps moderately. `tts-1` was worse.
3. Voice techniques alone cannot reach 2.5 s. TTS takes about 1 s and a turn with a tool takes 3 to 4 s in the agent, so the number of tool rounds has to fall.
4. Which mode for skills (in the prompt or loaded on demand) is still open. So is the API (Responses is not recommended so far, see below).

## Measurement rules

From `BTC-Data-Vong1-TEAMS/eval/huong-dan-do-latency.md` and `GIAI-DAP-MENTOR.md` item 7:

| Metric | From | To | Target (p95) |
|---|---|---|---|
| TTFT | Request reaches the backend | First token generated | 3 s |
| Total | Request reaches the backend | Last token | 8 s |
| TTFA | VAD end of speech | First audio byte played | 2.5 s |

Also: measure at the backend boundary, drop 3 warm-up turns, report hardware, model and API. The guide excludes ASR time only for offline files. Whether ASR and end of speech count in live TTFA, and whether a filler counts as first audio, should be confirmed with a mentor.

**Environment:** Intel Core i9-9880H, 17 GB RAM, Docker with 16 CPUs and 8 GB. ASR is Zipformer on CPU. TTS is OpenAI `gpt-4o-mini-tts`, voice `coral`, unless stated. All trials ran on the real Docker Compose stack in the evening of 2026-11-07 (+07:00).

## Trial 1: baseline before any change

`gpt-4.1-mini`, spoken input from `scripts/dev/question.wav`, 3 turns, 2 of them warm-up.

| Turn | TTFA | TTFT | Agent turn | Tools |
|---|---|---|---|---|
| 1 | 6.07 s | 2.73 s | 3.49 s | 1 |
| 2 | 5.77 s | 2.62 s | 3.42 s | 1 |
| 3 | 8.19 s | 3.32 s | 4.87 s | 2 |

Turn 2 broke down as: end of speech 0.56 s, ASR 0.18 s, agent 3.44 s, TTS first audio 1.59 s.

Causes found in the code: the voice path waited for the whole turn before TTS, TTS gathered a whole sentence as MP3, and the filler was never spoken. A call also closed with code 1011 after a long sentence. The gateway's 256 KB frame limit is suspected, not confirmed.

## Trial 2: provider and endpoint check

Median of 3 TLS handshakes from this laptop. This measures connecting only, not generating tokens.

| Endpoint | TLS handshake |
|---|---|
| `generativelanguage.googleapis.com` | 0.07 s |
| `api.openai.com` | 0.11 s |
| `sg.api.openai.com` | 0.11 s |
| `integrate.api.nvidia.com` | 0.24 s |
| `api.typesafe.ai` | 0.27 s |
| `api.groq.com` | 0.27 s |

The network is small next to a 2 to 3 s turn. The Singapore endpoint was not faster at this layer and was not adopted.

From OpenAI's documentation: `langchain-openai` moves `gpt-6` models with tools to the Responses API on its own unless pinned. Chat Completions calls tools on `gpt-6-luna` only at effort `none`. Fast mode costs twice as much with no published latency figure. Ultrafast does not cover Luna. Cutting a prompt by half may gain only 1 to 5%, while cutting output by half may gain about 50%. No page gives a first-token figure.

## Trial 3: spoken input, six planned variants

`gpt-6-luna`, effort `none`, with first sentence streaming and PCM on. The container restarted before each variant, so each started cold, and warm-up turns were not dropped.

**This trial is confounded.** The same audio was recognised differently between variants ("e-c ích", "AirPure xá", "epir x"), so the questions, and probably the tools called, differed. The whole stack stopped at about 19:40 from a cause not found, so D lost a turn and E (`silence-500`) and F (filler on) never ran.

| Variant | Turn | TTFA (ms) | End of speech | ASR | Agent | TTS |
|---|---|---|---|---|---|---|
| A: Chat Completions, skills in prompt | Easy | 6,616 | 482 | 97 | 4,558 | 1,478 |
| | Medium | 8,339 | 447 | 98 | 6,672 | 1,121 |
| | Hard | 10,309 | 441 | 198 | 8,473 | 1,196 |
| B: Responses, skills in prompt | Easy | 4,446 | 457 | 62 | 2,663 | 1,263 |
| | Medium | 8,633 | 531 | 86 | 6,604 | 1,412 |
| | Hard | 15,492 | 449 | 305 | 13,581 | 1,154 |
| C: Chat Completions, skills loaded | Easy | 5,603 | 455 | 58 | 4,033 | 1,055 |
| | Medium | 5,557 | 454 | 78 | 3,745 | 1,279 |
| | Hard | 7,570 | 457 | 149 | 5,652 | 1,310 |
| D: A with `tts-1` | Easy | 6,918 | 443 | 52 | 4,135 | 2,286 |
| | Medium | 8,234 | 517 | 107 | 5,843 | 1,765 |

The parts add up to TTFA. The agent is 60 to 88% of it. An earlier trial of variant A with the filler on played the filler 2.7 to 4.9 s after end of speech.

## Trial 4: text bench without ASR

Text goes straight into the voice WebSocket (`bench_text`, only with `VOICE_BENCH=1`). TTFA here runs from the text arriving to first audio, **so it leaves out end of speech as well as ASR**. Each configuration is one call: 3 warm-up turns, then 5 measured turns. Same text, effort `none`, keep-alive on.

| Configuration | Easy | One lookup | Policy | Two lookups | Many lookups | Median |
|---|---|---|---|---|---|---|
| `gpt-5.6-luna`, Chat Completions, skills in prompt | 2.1 s | 4.9 s | 5.5 s | 6.1 s | 5.5 s | 5.5 s |
| `gpt-6-luna`, Chat Completions, skills loaded | 5.4 s | 5.2 s | 5.2 s | 13.5 s | 5.0 s | 5.2 s |
| `gpt-6-luna`, Chat Completions, skills in prompt | 5.6 s | 8.0 s | 7.9 s | 18.4 s | 6.5 s | 7.9 s |
| `gpt-6-luna`, Responses, skills in prompt | 3.6 s | 10.5 s | 8.4 s | 9.4 s | 8.8 s | 8.8 s |

Detail per turn, measured turns only:

| Configuration | Turn | TTFT (ms) | Total (ms) | Agent (ms) | TTS (ms) | Model calls | Tools | Regenerated |
|---|---|---|---|---|---|---|---|---|
| `gpt-5.6-luna`, skills in prompt | Easy | 978 | 1,770 | 1,031 | 1,067 | 1 | 0 | 0 |
| | One lookup | 3,766 | 5,121 | 4,012 | 879 | 3 | 3 | 0 |
| | Policy | 3,825 | 4,825 | 3,972 | 1,564 | 2 | 1 | 0 |
| | Two lookups | 4,765 | 9,777 | 4,940 | 1,111 | 2 | 5 | 1 |
| | Many lookups | 3,075 | 4,670 | 3,681 | 1,832 | 2 | 5 | 0 |
| `gpt-6-luna`, skills loaded | Easy | 4,494 | 5,172 | 4,518 | 894 | 2 | 1 | 0 |
| | One lookup | 3,760 | 4,967 | 4,169 | 1,019 | 3 | 2 | 0 |
| | Policy | 4,023 | 4,501 | 4,209 | 949 | 2 | 1 | 0 |
| | Two lookups | 11,780 | 12,892 | 12,429 | 1,033 | 3 | 6 | 1 |
| | Many lookups | 3,359 | 4,648 | 3,893 | 1,148 | 2 | 5 | 0 |
| `gpt-6-luna`, skills in prompt | Easy | 4,381 | 5,609 | 4,570 | 1,063 | 2 | 1 | 0 |
| | One lookup | 6,612 | 7,802 | 7,133 | 913 | 3 | 3 | 0 |
| | Policy | 6,048 | 13,056 | 6,519 | 1,417 | 2 | 3 | 1 |
| | Two lookups | 16,689 | 18,814 | 17,068 | 1,315 | 2 | 8 | 1 |
| | Many lookups | 4,484 | 7,530 | 5,205 | 1,316 | 2 | 5 | 0 |
| `gpt-6-luna`, Responses, skills in prompt | Easy | 1,841 | 3,428 | 2,786 | 858 | 1 | 0 | 0 |
| | One lookup | 8,172 | 9,997 | 9,199 | 1,297 | 4 | 3 | 0 |
| | Policy | 6,601 | 8,709 | 7,451 | 912 | 4 | 3 | 0 |
| | Two lookups | 8,350 | 10,355 | 8,485 | 922 | 4 | 6 | 0 |
| | Many lookups | 7,154 | 9,311 | 7,685 | 1,067 | 3 | 7 | 0 |

Model calls over all 9 turns of a call (opening and warm-up included): `gpt-5.6-luna` 14, `gpt-6-luna` 17 to 21.

### What it shows

- **Models.** Time per model call, tool time included, was about 1.7 s on `gpt-5.6-luna` and about 2.0 to 2.4 s on `gpt-6-luna`. `gpt-6-luna` also made more calls. `gpt-5.6-luna` was measured only with skills in the prompt.
- **Target.** Turns with no tool on `gpt-5.6-luna` came in at 2.1 to 2.5 s here. Adding about 0.45 s for end of speech gives roughly **2.55 to 2.95 s, close to the target and not meeting it**. Turns with a tool would be about 5.3 to 6.5 s.
- **Skills.** A load does cost a round: one turn with no tool on `gpt-6-luna` took 2 model calls and 3.7 s of TTFT, against 1.5 s for the same text with skills in the prompt. Over the whole bench, though, skills in the prompt were slower (7.9 s against 5.2 s). The cause is unknown. The sample is small and that configuration ran first.
- **APIs.** Responses was faster on the easy turn, made more model calls, and had the slowest median. It also said a raw `<ADDR_1>` token to the customer. Whether the API or the model caused that is not known.

### Problems found

- **Regenerations.** They were present in the worst turns. On two lookups, the blocked drafts of the two slowest turns both say "rẻ hơn 600.000đ", the difference between two quoted prices. The money check probably does not treat a difference as sourced. The reasons were not fully read, so this is not confirmed.
- **Needless tool call.** Asking whether the agent is a person made `gpt-6-luna` call `handoff.transfer` on Chat Completions, costing a round.
- **Answers to verify.** A blocked `gpt-5.6-luna` draft said both products were in stock, while other configurations said Xiaomi Smart 4 Pro was out of stock. The Responses answer gave AirPure X at 2,445,000đ, which needs checking against the promotion. This bench measures speed only, not correctness.

## Verdict on each technique

No technique was switched on and off alone, except `tts-1`, so the effects below are inferred.

| Technique | Verdict | Evidence | Decision |
|---|---|---|---|
| Speak the first sentence at once | Clearest effect | TTS began 0.7 to 1.1 s before the model finished on `gpt-5.6-luna`, and 4.8 s on one turn | Keep |
| Audio streaming, PCM, small frames | Moderate | First audio from 1.59 s (one turn) to usually about 0.9 to 1.3 s, less gain than predicted. No error in the bench, 1011 not confirmed gone | Keep |
| Keep-alive and opening the connection early | No visible effect | TTS looks the same before and after. The handshake bounds the gain at about 0.1 s | Keep, harmless |
| Filler | Good for the caller, no help for TTFA yet | Played 2.7 to 4.9 s after end of speech, since it comes after the first model round | Off (`VOICE_FILLER=0`), ask a mentor |
| `tts-1` | Worse | 1.8 to 2.3 s against 1.1 to 1.5 s, opening 5.4 s. Two turns plus the opening | Drop |
| `silence-500` endpointing | Not run | The current setting already takes about 0.45 s, so a gain is unlikely | Skip |
| Stable prompt prefix, `tool_choice: none` | Not measured | Cached token counts were not read, and `tool_choice` applies only to the last model call | Keep, harmless |

Not tried:

- A short first sentence, through the prompt.
- Playing the filler on arrival, which helps TTFA only if a mentor accepts it.
- Fetching known data from state before the model.
- Realtime, which is not recommended: local ASR is required in M1, and it would mean rewriting the voice path.

## Changes these trials rest on

- `gpt-6-luna` as the advisor in `config/models.yaml`, with `reasoning_effort` and `use_responses_api` as generation settings.
- `api/routes/voice.py`: sentences go to TTS as they are written, the filler has a switch, `ttfa_without_asr_ms` and `filler_ms` are reported, and `bench_text` exists behind `VOICE_BENCH=1`.
- `components/voice/tts.py`: PCM in quarter-second WAV chunks, keep-alive, and a connection opened early.
- `llm/factory.py`: keep-alive for OpenAI models.
- `pipeline/hot/nodes.py` and `pipeline/eval/runner.py`: TTFT is stamped at the first token of the sentence actually said and Total at the last token, as the organisers' guide says. The runner belongs to the evaluation owner, so that change needs their review.
- `llm/evaluation_budget.py` also allows `gpt-6-luna`, counted at `gpt-4.1-mini`'s higher rates. If the advisor moves to `gpt-5.6-luna`, this list has to allow it too. Those rates ($0.40 and $1.60) are still above its price ($0.20 and $1.20), so the cap stays on the safe side.

## Cost

OpenAI's cost figures cannot be read with this key, so these are estimates. The text bench cost about $0.10 to $0.17. The running total is about **$0.56 to $0.73** against a cap first set at $0.50 and then raised to about $0.70. Check the OpenAI usage page for the real figure.

## Open

1. Decide on `gpt-5.6-luna`.
2. Let the money check accept a difference between quoted prices, after confirming that is the reason for the block. Look at the needless `handoff.transfer`.
3. Fetch known data from state before the model, to cut tool rounds.
4. Ask a mentor whether end of speech and ASR count in live TTFA, and whether a filler counts as first audio.
5. Measure `gpt-5.6-luna` in both skill modes, then the same text several times, since one run cannot separate a real gain from noise.
