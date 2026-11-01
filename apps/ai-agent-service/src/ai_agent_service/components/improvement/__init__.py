"""Improvement, L6: the system gets better without retraining. ``docs/design.md`` section 10.

The brief's Case 4: QA hears about 2% of calls, so the script never learns
from the other 98%. Reflection (:mod:`.lessons`, :mod:`.playbook`) changes
how the bot applies a rule it has, through playbook entries; it learns from
the failures the organisers' grader finds on a learning run, fixed in
exploration, and an entry goes live after verification and a person's
approval. The Knowledge Gap Loop so far is its live step only: a consultant
saves the answer they gave as a Knowledge Gap Loop entry, which waits for a
person's approval (``runtime/calls.save_gap_entry``).

**The founding rule:** a lesson from one call may be true only for that
customer. One call is one vote of evidence, never a rule; an entry needs the
same failure fixed with several customers.

- :mod:`.signals`: the sources of the brief, and the grader's failures routed by code.
- :mod:`.lessons`: hints, cards, the deterministic screen, support.
- :mod:`.playbook`: from cards to one entry.
- :mod:`.review`: who approves what, and the improvement log.
- :mod:`.versions`: what is live, publishing, rollback, revocation.

The exploration that turns a failure into a verified hint plays calls, so it
is a pipeline, not a component: ``pipeline/improve``.
"""
