"""Loaded by every Python process of an evaluation run (``agent/launch.py`` puts
this folder on ``PYTHONPATH``), the MCP servers included.

On Windows the default Proactor event loop is refused by async psycopg, which
the memory, knowledge and BTC servers use; the selector loop is accepted, and
the ``mcp`` client falls back to ``Popen`` for its subprocesses under it.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
