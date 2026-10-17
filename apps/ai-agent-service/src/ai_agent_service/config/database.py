"""Where the agent's own tables live, and the secret its keys derive from.

The AI service owns one PostgreSQL schema, ``agent`` (``AGENT_DB_SCHEMA``):
the hot graph's checkpoints, the call projection and transcript, the PII
vault, the memory ledger (facts, episodes, identities), the knowledge chunks
and the organisers' mock state. Every connection the service, its MCP
servers and the checkpointer open sets ``search_path`` to that schema, so the
SQL ported from the reference project stays unqualified and never touches the
tables other services own (``docs/architecture/microservices-target-structure.md``:
"AI Agent owns AI runtime behavior and its retrieval/memory implementation").

The connection string is the platform's ``DATABASE_URL`` (SQLAlchemy form,
``postgresql+psycopg://``) unless ``AGENT_DATABASE_URL`` gives the agent a
database of its own.
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache

import psycopg
from psycopg.conninfo import make_conninfo

# Importing this loads .env once, before anything reads the environment.
from .config_manager import ROOT  # noqa: F401

URL_VARIABLES = ("AGENT_DATABASE_URL", "DATABASE_URL")
DEFAULT_SCHEMA = "agent"
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def schema() -> str:
    name = os.environ.get("AGENT_DB_SCHEMA", DEFAULT_SCHEMA).strip().lower()
    if not _SCHEMA_NAME.match(name):
        raise RuntimeError(f"AGENT_DB_SCHEMA must be a plain lowercase identifier, not {name!r}")
    return name


def _libpq_url(raw: str) -> str:
    """``postgresql+psycopg://`` (SQLAlchemy) -> ``postgresql://`` (libpq)."""
    value = raw.strip()
    if value.startswith("jdbc:"):
        value = value[len("jdbc:"):]
    return re.sub(r"^postgres(?:ql)?\+[a-z0-9_]+://", "postgresql://", value)


def database_url() -> tuple[str, str]:
    """The agent's connection string with ``search_path`` set, and the variable it came from.

    Raises a clear error when no PostgreSQL URL is configured: the agent's
    checkpointer, ledger and vault have no SQLite fallback.
    """
    for variable in URL_VARIABLES:
        raw = os.environ.get(variable, "")
        if raw and raw.lower().startswith(("postgres", "jdbc:postgres")):
            conninfo = make_conninfo(_libpq_url(raw), options=f"-c search_path={schema()},public")
            return conninfo, variable
    present = [v for v in URL_VARIABLES if os.environ.get(v)]
    raise RuntimeError(
        "The AI agent needs PostgreSQL: set AGENT_DATABASE_URL or DATABASE_URL to a postgresql:// URL"
        + (f" ({', '.join(present)} is set but is not PostgreSQL)" if present else "")
    )


def configured_url() -> tuple[str | None, str | None]:
    """The PostgreSQL URL configured for the agent, in libpq form and without the
    schema option, and the variable it came from; ``(None, None)`` when there is none."""
    for variable in URL_VARIABLES:
        raw = os.environ.get(variable, "")
        if raw and raw.lower().startswith(("postgres", "jdbc:postgres")):
            return _libpq_url(raw), variable
    return None, None


def ensure_schema() -> None:
    """Create the agent schema if it is missing. Safe to run on every start."""
    url, _ = database_url()
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema()}"')


@lru_cache(maxsize=1)
def app_secret() -> str:
    """The platform secret (``APP_SECRET``) the vault and identity keys derive from."""
    secret = os.environ.get("APP_SECRET", "")
    production = os.environ.get("ENVIRONMENT", "development") == "production"
    if len(secret.encode()) < 32:
        if production:
            raise RuntimeError("APP_SECRET must be at least 32 bytes in production")
        secret = secret or "local-development-secret-change-before-deploy"
    return secret


def derived_key(purpose: str) -> bytes:
    """A 32-byte key for one purpose (``pii-vault``, ``identity``), from the app secret."""
    return hashlib.sha256(f"{purpose}:".encode() + app_secret().encode()).digest()


# ── compatibility with the reference project's ``api.settings`` ───────────


class _Settings:
    """What ``mcp.server_base`` reads from the reference project's settings."""

    def require_database_url(self) -> tuple[str, str]:
        return database_url()


def get_settings() -> _Settings:
    return _Settings()
