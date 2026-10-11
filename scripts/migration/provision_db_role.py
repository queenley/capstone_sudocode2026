"""Provision a fixed runtime role that cannot read evaluation data."""

import getpass
import os
import psycopg
from psycopg import sql

if __name__ == "__main__":
    url = os.getenv("ADMIN_DATABASE_URL", "")
    if not url:
        raise SystemExit(
            "Set ADMIN_DATABASE_URL to a PostgreSQL owner connection string."
        )
    password = getpass.getpass("Runtime database role password (20+ characters): ")
    if len(password) < 20:
        raise SystemExit("Use at least 20 characters.")
    role = sql.Identifier("telesales_runtime")
    schemas = sql.SQL(", ").join(
        map(
            sql.Identifier,
            ["commerce", "conversation", "identity", "memory", "improvement"],
        )
    )
    with psycopg.connect(url) as connection:
        if connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='telesales_runtime'"
        ).fetchone():
            raise SystemExit(
                "Role already exists. Rotate its password through your secret-management procedure."
            )
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                role, sql.Literal(password)
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schemas, role)
        )
        connection.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}"
            ).format(schemas, role)
        )
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(schemas, role)
        )
        connection.execute("REVOKE ALL ON SCHEMA evaluation FROM PUBLIC")
    print(
        "Runtime role created. Use it in DATABASE_URL and keep migration credentials separate."
    )
