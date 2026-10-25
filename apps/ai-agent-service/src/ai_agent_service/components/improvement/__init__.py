"""Improvement, L6: the system gets better without retraining. ``docs/design.md`` section 10.

The brief's Case 4: QA hears about 2% of calls, so the script never learns
from the other 98%. Two mechanisms, each changing one thing and fed by its
own signal, so signals never overlap:

| Mechanism | Changes | Learns from | Goes live |
|---|---|---|---|
| Knowledge Gap Loop (:mod:`.gaps`) | what the bot knows: FAQ entries | questions the bot could not answer | after a person approves it |
| Reflection (:mod:`.lessons`, :mod:`.playbook`) | how the bot applies a rule it has: playbook entries | failures the organisers' grader finds on a learning run, fixed in exploration | after verification and a person's approval |

**The founding rule:** a lesson from one call may be true only for that
customer. One call is one vote of evidence, never a rule; an entry needs the
same failure fixed with several customers.

- :mod:`.signals`: the sources of the brief, and the grader's failures routed by code.
- :mod:`.lessons`: hints, cards, the deterministic screen, support.
- :mod:`.playbook`: from cards to one entry.
- :mod:`.review`: who approves what, and the improvement log.
- :mod:`.versions`: what is live, publishing, rollback, revocation.

The exploration that turns a failure into a verified hint plays calls, so it
is a pipeline, not a component: ``pipeline/improve``. Status: Reflection and
versions built; the Gap Loop (:mod:`.gaps`) is not.
"""
