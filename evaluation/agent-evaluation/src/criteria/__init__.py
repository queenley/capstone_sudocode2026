"""The criteria the Score step judges each call by, one module each.

BTC's official numbers (RQR, CCR, TSR, HR, guardrail violations, latency) come from the organisers'
``reference_eval.py`` unchanged (``src/steps/score/official.py``). The criteria here check what that script cannot see
or counts by a looser rule, from the evidence of the Collect step:

| Module | Criterion | Beside BTC's |
|---|---|---|
| ``coverage`` | every planned turn traced and extracted; the grading contract complete | — |
| ``tool_state`` | a tool's result is in the mock's state (orders, callbacks, tickets) | TSR |
| ``tool_accuracy`` | the agent's calls against the labelled calls (TP/FP/FN); a required tool succeeded | TSR |
| ``memory`` | memory integrity; ``memory_expectation`` holds after the call | memory_checks |
| ``carryover`` | each ``must_carry_over`` slot used with the right value | CCR |
| ``claims`` | each claim is in the ground truth and equal to it | HR |
| ``briefs`` | Call/Handoff Brief valid, about this customer, true | — |
| ``guardrail`` | no forbidden pattern in text, tool calls, memory writes | guardrail_violations |
| ``latency`` | p50/p95 without the warm-up turns | latency |
| ``calls_to_close`` | calls until an order proven in the mock | calls_to_close |
| ``assertions`` | runs the grading contract's assertions through the modules above | — |

Each criterion returns issues: ``agent_violation`` makes the verdict FAIL; ``missing_evidence``, ``dispute``,
``infra_error`` and ``schema_error`` make it UNDETERMINED. :class:`.evidence.CallEvidence` is what they all read.
"""
