"""The environment every evaluation-side agent process starts from.

Imported first by :mod:`.bridge` and :mod:`.extract_command` (and by the
harness's settings query), before anything from ``ai_agent_service``:

- ``apps/ai-agent-service/src`` goes on the import path, as the service's
  README sets ``PYTHONPATH`` for a local run;
- the repository's ``.env`` is loaded (the service itself only reads
  ``apps/ai-agent-service/.env``), without overriding the shell;
- ``GEMINI_API_KEY`` stands in for ``GOOGLE_API_KEY`` when only the first is
  set: the agent's ``google_genai`` provider reads the second;
- without any database URL, the compose stack's Postgres on localhost is used;
- the agent's tables go to a schema of their own, ``agent_eval``
  (``EVAL_DB_SCHEMA``), which :func:`.runner.reset` empties per scenario;
- on Windows, every process of the run (this one and the MCP servers it
  starts) uses the selector event loop, the only one async psycopg accepts.
  ``_site/sitecustomize.py`` does it for the children.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

EVALUATION = Path(__file__).resolve().parents[1]
REPOSITORY = EVALUATION.parents[1]
SERVICE = REPOSITORY / "apps" / "ai-agent-service"
SITE = Path(__file__).resolve().parent / "_site"

DEFAULT_SCHEMA = "agent_eval"
# 127.0.0.1, not localhost: compose publishes the port on IPv4 only, and on
# Windows "localhost" tries ::1 first, which costs each MCP server minutes.
LOCAL_DATABASE = "postgresql://postgres:{password}@127.0.0.1:5432/app_db"


def python() -> Path:
    """The interpreter the agent runs under: ``AGENT_PYTHON``, else the service's venv."""
    if os.environ.get("AGENT_PYTHON"):
        return Path(os.environ["AGENT_PYTHON"]).resolve()
    venv = SERVICE / ".venv"
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _prepend_path(variable: str, *entries: Path) -> None:
    parts = [str(e) for e in entries] + [p for p in os.environ.get(variable, "").split(os.pathsep) if p]
    os.environ[variable] = os.pathsep.join(dict.fromkeys(parts))


def prepare() -> str:
    """Set the process up for the agent; returns the evaluation schema's name."""
    from dotenv import load_dotenv

    load_dotenv(REPOSITORY / ".env", override=False)
    load_dotenv(SERVICE / ".env", override=False)
    if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

    if os.environ.get("EVAL_DATABASE_URL"):
        os.environ["AGENT_DATABASE_URL"] = os.environ["EVAL_DATABASE_URL"]
    elif not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
        password = os.environ.get("POSTGRES_PASSWORD") or "local-postgres-change-me"
        os.environ["DATABASE_URL"] = LOCAL_DATABASE.format(password=password)

    schema = os.environ.get("EVAL_DB_SCHEMA", DEFAULT_SCHEMA).strip().lower()
    if not schema.endswith("_eval"):
        raise RuntimeError("EVAL_DB_SCHEMA must end in _eval: the run empties its tables")
    os.environ["AGENT_DB_SCHEMA"] = schema

    os.environ["MCP_TRANSPORT"] = "stdio"
    os.environ.setdefault("PYTHONUTF8", "1")
    # The MCP servers inherit this: the service's package, and the loop policy.
    _prepend_path("PYTHONPATH", SITE, SERVICE / "src")
    for entry in (SERVICE / "src",):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        # The OpenAI SDK's HTTP client (httpx2) checks certificates through
        # `truststore`, which calls Windows via ctypes; with several processes
        # connecting at once (parallel extraction) that call sometimes crashes
        # with "access violation" and the request fails as a connection error.
        # A CA bundle file makes it use plain OpenSSL instead.
        if not (os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR")):
            try:
                import certifi
            except ImportError:
                pass
            else:
                os.environ["SSL_CERT_FILE"] = certifi.where()
    return schema
