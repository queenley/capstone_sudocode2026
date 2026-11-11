# Reflection proof sets

Reflection (the brief, C.5 mechanism 3) learns how the agent conducts calls, not what the policy says: what the
documents say the agent must do right from R0 (`data/policy-regression`), and what they never say is the Knowledge
Gap Loop's (`data/gap-loop`). Every check here is one the organisers' grader makes in code.

Three sets, each with `learn/`, `frozen/`, `frozen.json` and `expected.yaml`. They are text scenarios in the organisers' format, played without ASR:

- `conduct/`: how the agent conducts a call (below).
- `warranty/`: a customer worried a product will break. The shop's policy already holds the answer the agent was
  never taught to give: the 12-month extended warranty of BH-05, for home appliances over 3,000,000d only. Four
  learning customers; three frozen cases where it must be offered (`must_say_any`) and three controls under
  3,000,000d where offering it is a false claim (`forbidden_claims`), so a lesson that offers it to everyone shows as
  harm. The grader matches phrases, so the labels hold the wordings an offer takes ("mua thêm gói bảo hành", "thêm 12
  tháng bảo hành") and a control forbids what only an offer says ("có thể mua thêm", "8% giá sản phẩm"), not the
  package's name: saying a product is not eligible is true and passes (corrected 2026-11-11, after the original
  agent offered the package in other words and failed; `tests/agent/test_approval_agent.py` holds the sentences).
  A worry does not retrieve BH-05, and the advisor states a policy only from the passages of its turn (rule 3): the
  rule a published lesson cites therefore comes along with every turn's passages (`components/context/skills.py`,
  `learned_cites`). Without that the lesson was followed in one frozen call of three.
- `budget/`: the organisers' persona `khach_mua_nhieu_mon` expects to be told when an order of several products
  passes the budget they named ("nếu tổng tiền vượt ngân sách mà nhân viên không nói, bạn hỏi 'thế là bao nhiêu tất
  cả?'"); no skill says it. Four learning customers; three frozen orders over budget (`must_say_any`) and three
  under it where saying so is false (`forbidden_claims`). Totals are the mock's `pricing.quote_order`.

`expected.yaml` holds, per situation, the lesson we accept (`accept`). The ReflectionAgent never reads it. The
ApprovalAgent (`agents/approval.py`) takes the reviewer's place: it reads the accepted lesson of the situation a change
was learned from and, in one call, accepts the change when it teaches the same lesson (in other words or not) and
refuses it otherwise. A set with accepted lessons also lets its failures routed to review (a phrase the grader did not
find) reach Reflection, since the ApprovalAgent checks what comes out. Reflection and the ApprovalAgent run on
`gpt-6.1-terra` (`config/models.yaml`; `gpt-6.1-sol` until 2026-11-12).

## conduct

| Situation | What the agent must not do | Checked by | Learning | Frozen |
|---|---|---|---|---|
| a returning customer out of patience asks to order what was advised | ask again for anything known; ask more than once | `must_not_ask` (RQR, the brief's KPI 1), `max_agent_questions: 1`, the order | 4 | 3 |
| a returning customer asks one more thing about the product advised | ask again what is known | `must_not_ask`, `max_agent_questions: 1`, the answer | 4 | 3 |
| a customer gives every order detail in one message | confirm twice | `max_agent_questions: 1`, the order | 4 | 3 |

Each frozen call also has to finish its task (the order placed, the question answered), so a lesson that makes the
agent quieter by doing less shows as harm.

**How Reflection learns it.** The QaAgent scores each learning call and diagnoses each conduct failure: the skill says
nothing (`skill_gap`), or a skill or fixed rule already says it and was not followed (`not_followed`, most conduct
failures: rule 14 already says not to ask again what the Call Brief has). The ReflectionAgent writes a card per call.
Where three customers share one, it writes one sentence: it rewrites, more concretely, the sentence of a skill that
was not followed, or adds to the `conversation` skill how to keep a fixed rule in that situation. Fixed rules are
never changed. The screen and the PolicyAgent check it, and a person approves it.

`tests/agent/test_reflection_dataset.py` checks, with no model call, that every scenario loads, every expected price
is the organisers' mock's on the day, and what may not be asked again was established in an earlier call.

Run a round from the original agent; it goes back to the original agent when it ends. The spend guard
(`llm/spend_guard.py`) watches only a run an assistant starts on its own (`SPEND_SINCE` set):

```bash
export PYTHONPATH=apps/ai-agent-service/src:packages/backend-common
apps/ai-agent-service/.venv/bin/python -m ai_agent_service.pipeline.improve round --name warranty-1 --learn data/reflection/warranty/learn/scenarios --frozen data/reflection/warranty/frozen/scenarios --frozen-ids data/reflection/warranty/frozen.json --scripted
```
