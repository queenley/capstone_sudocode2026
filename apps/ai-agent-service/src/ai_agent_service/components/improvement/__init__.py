"""Improvement, L6: the system gets better without retraining. ``docs/design.md`` section 10.

The brief's Case 4: QA hears about 2% of calls, so the script never learns
from the other 98%. Reflection (:mod:`.lessons`, :mod:`.playbook`) changes
how the bot applies a rule it has, through playbook entries; it learns from
the failures the organisers' grader finds on a learning run, fixed in
exploration, and an entry goes live after verification and a person's
approval. The Knowledge Gap Loop so far is its live step only: a consultant
saves the answer they gave as a FAQ entry (``runtime/calls.save_faq``).

**The founding rule:** a lesson from one call may be true only for that
customer. One call is one vote of evidence, never a rule; an entry needs the
same failure fixed with several customers.

- :mod:`.signals`: the sources of the brief, and the grader's failures routed by code.
- :mod:`.lessons`: what counts as evidence and what a change may never say.
- :mod:`.skill_versions`: skills, one sentence at a time, version by version.
- :mod:`.review`: who approves what, and the improvement log.
- :mod:`.versions`: what is live, publishing, rollback, revocation.

The commands are in ``pipeline/improve``.
"""
