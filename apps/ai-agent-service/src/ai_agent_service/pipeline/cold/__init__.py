"""After the call, nobody waiting.

Hanging up hands the call to ``runtime/jobs.py``: with ``JOBS_QUEUE_URL`` set (a
deployment) it goes to the SQS queue and ``ai_agent_service.worker`` runs
:func:`.after_call.after_call`; without it (local, tests) it runs as a task in
the API's own process. Two branches over the
same tokenised transcript and tool log (scoring a call on the rubric and
reflecting on it run in the improvement loop, ``pipeline/improve``):

| Branch | Agent | Writes |
|---|---|---|
| remember this customer | ``MemoryAgent``: extract, gate, commit, summarize | the ledger, through ``memory_writer`` |
| tag | ``QaAgent``: the call's situation and outcome, by rule | the call's tags |

If it fails, the call stays marked as not remembered and the one-minute sweep
runs it again. The evaluation runner calls the same function, synchronously,
between two calls of a scenario.
"""
