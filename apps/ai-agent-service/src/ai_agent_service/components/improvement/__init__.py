"""Improvement, L6: the system gets better without retraining. ``docs/design.md`` section 10.

The brief's Case 4: QA hears about 2% of calls, so the script never learns
from the other 98%. **Reflection** (C.5 mechanism 3) changes the skills the
advisor follows, and only where a skill does not say what to do: the QaAgent
scores each call of a learning run and diagnoses each failure, the
ReflectionAgent writes a lesson card per call, screened before it is stored,
and drafts one sentence of a skill where several customers share a lesson; the
PolicyAgent checks it and a person approves it. A failure a skill already
covers is product work, never a lesson. The **Knowledge Gap Loop** changes the
knowledge base: a consultant's answer to an unanswered question becomes an entry.

**The founding rule:** a lesson from one call may be true only for that
customer. One call is one vote of evidence, never a rule; a change needs the
same lesson, in the same situation, from several customers.

- :mod:`.signals`: the grader's failures and the rubric's, routed by code, and what each check means.
- :mod:`.lessons`: the screens, the store of lessons, what counts as shared, what the models read of a call.
- :mod:`.answers`: the loop's model answers on disk, so the same request is paid for once.
- :mod:`.skill_versions`: skills, one sentence at a time, version by version.
- :mod:`.review`: who approves what, and the improvement log.
- :mod:`.versions`: the knowledge base's versions, publishing, revocation.

The commands are in ``pipeline/improve``.
"""
