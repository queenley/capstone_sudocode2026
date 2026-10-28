"""The capstone agent behind the evaluation harness (``evaluation/agent-evaluation``).

The agent itself is ``apps/ai-agent-service`` and is not changed for the
evaluation; this package only assembles it the way the harness needs:

- :mod:`.launch`: the environment (import path, ``.env``, database schema,
  event loop) every process of the run starts from;
- :mod:`.runner`: the agent assembled for a run, and its database;
- :mod:`.bridge`: the agent behind the harness's adapter, one process per
  scenario and configuration, JSON lines over a pipe;
- :mod:`.extract_command`: the extraction call the harness makes per turn.
"""
