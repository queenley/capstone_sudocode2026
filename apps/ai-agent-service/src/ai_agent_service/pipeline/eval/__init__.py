"""The agent under evaluation. ``docs/design.md`` section 9, figure H.

The organisers' command, ``python -m ai_agent_service.pipeline.eval.cli``
(:mod:`.cli`), runs scenarios in their format through the agent, writes their
trace and prints their table, with retrieval measured on their labelled
questions (:mod:`.rag`). :mod:`.relabel` labels a finished run's replies again
with today's extractor, without running the agent.

The modules:

- :mod:`.scenarios`: a scenario in the organisers' format, planned call by
  call: days, keys, turns, prior sessions;
- :mod:`.runner`: the agent assembled for a run, its database, and one call
  through it (:class:`~.runner.CallSession`), connect to hang-up;
- :mod:`.trace`: one line of the organisers' trace per agent turn;
- :mod:`.report`: what voids a run, its manifest, the organisers' grader, the
  failures to analyse;
- :mod:`.cli`: the organisers' command;
- :mod:`.rag`: retrieval on the organisers' 60 labelled questions, and θ.
"""
