"""The agents.

| Agent | When | Reads | Returns |
|---|---|---|---|
| ``AdvisorAgent`` | every turn | its slice of the state | a draft, tool results |
| ``PolicyAgent`` (Decisions API) | every turn | draft, tool results, policy | violations |
| ``MemoryAgent`` | after the call | transcript, current facts | what to write |
| ``QaAgent`` | after the call | candidates, a failure | tags, hints |
| ``SimulatorAgent`` | evaluation only | persona, outline | the customer's turns |

None of them holds state: the hot graph owns it, and hands each a slice.
The router is not here: ``route`` is rules in the harness.
"""

#: Structured-output classes that may appear in a checkpoint. None since the
#: advisor answers in plain text and holds no checkpoint of its own.
CHECKPOINTED_TYPES: tuple[type, ...] = ()
