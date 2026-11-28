"""Where the parts are put together, in the order a call needs them.

The composition root: the only place that knows the sequence. The logic of
each step lives in ``src/components`` (what the system can do) and
``src/agents`` (who judges); a pipeline builds each one's input from its
state, calls it, and writes the result back. Neither components nor agents
import from here.

- :mod:`.hot`: while a customer waits, one turn at a time.
- :mod:`.cold`: after the call, nobody waiting: remembering the customer
  (MemoryAgent) and scoring (QaAgent).
- :mod:`.eval`: the offline test that drives both over scenarios.
"""
