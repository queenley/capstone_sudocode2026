# Knowledge Gap Loop proof set

The questions the organisers' 14 documents never cover (checked word by word: installation at home, gift wrapping,
picking up at the shop, a loyalty programme, a delivery time slot). The brief, C.5 mechanism 1: a question the agent
cannot answer is recorded, a person answers it, the answer joins the knowledge, and the next customer who asks it,
in other words, is answered.

| Folder | What | Count |
|---|---|---|
| `learn/scenarios` | two customers per topic: their unanswered questions become entries | 10 |
| `frozen/scenarios` | two other customers per topic, asking in other words; three controls | 13 |
| `answers.json` | what a consultant answers, one per topic, `"source": "consultant"` | 5 |
| `frozen.json` | the frozen ids, given to `harvest --frozen` | |

**The answers are new knowledge, written for the proof.** In an evaluation no consultant is on the line, so
`answers.json` stands in for one: plausible shop practice, in the form of the organisers' FAQ entries, with no
amount, promotion code or stock status (the gate of section 10.2 refuses those). The entry records
`source: consultant` and `approved_by: scripted-eval`, and a report must say so.

**How a call is checked.** A gap topic passes when the agent answers without transferring the call and says words
only the consultant's answer holds (`thiệp viết tay`, `kỹ thuật viên`), so "chưa có thông tin về gói quà" cannot pass.
The controls guard the harm: the radon question, which the documents say there is no information on (FAQ-03), must
still be refused and transferred; two policy questions (DT-04, LN-02) must still be answered from the documents.

**Offline mock (no model call).** With entries titled as the restate step would title them, all ten frozen questions
reach their entry in the five passages the advisor reads, the radon question still abstains, and the two policy
controls keep their section first.

**The risk to know.** The organisers' hidden set has out-of-document cases that pass only when the agent says it has
no information. An entry for a topic one of those cases asks would make it fail: the person who approves an entry
owns that risk, and topics the documents mark as having no information are never answered.

A round runs from the original agent and goes back to it ([docs/ai/06-vong-cai-tien.md](../../docs/ai/06-vong-cai-tien.md)):

```bash
export PYTHONPATH=apps/ai-agent-service/src:packages/backend-common
apps/ai-agent-service/.venv/bin/python -m ai_agent_service.pipeline.improve round --name gap-1 --learn data/gap-loop/learn/scenarios --frozen data/gap-loop/frozen/scenarios --frozen-ids data/gap-loop/frozen.json --answers data/gap-loop/answers.json --scripted
```
