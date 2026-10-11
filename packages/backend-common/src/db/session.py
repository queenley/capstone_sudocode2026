from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.db.models import Base

SCHEMAS = [
    "commerce",
    "identity",
    "conversation",
    "memory",
    "improvement",
    "evaluation",
]


class Database:
    def __init__(self, url: str):
        sqlite = url.startswith("sqlite")
        options = (
            {"connect_args": {"check_same_thread": False}}
            if sqlite
            else {"pool_pre_ping": True}
        )
        if url in ("sqlite://", "sqlite:///:memory:"):
            options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        if sqlite:
            self.engine = self.engine.execution_options(
                schema_translate_map={s: None for s in SCHEMAS}
            )

            @event.listens_for(self.engine, "connect")
            def configure(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=10000")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self):
        if self.engine.dialect.name == "sqlite":
            Base.metadata.create_all(self.engine)
            return
        with self.engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(20261004)"))
            connection.commit()
            try:
                connection.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS public.schema_migrations (version text PRIMARY KEY)"
                    )
                )
                connection.commit()
                for path in sorted(
                    (Path(__file__).parents[2] / "migrations").glob("*.sql")
                ):
                    if connection.execute(
                        text("SELECT 1 FROM public.schema_migrations WHERE version=:v"),
                        {"v": path.name},
                    ).first():
                        connection.commit()
                        continue
                    connection.commit()
                    sql = (
                        path.read_text(encoding="utf-8")
                        .replace("BEGIN;", "")
                        .replace("COMMIT;", "")
                    )
                    with connection.begin():
                        connection.exec_driver_sql(sql)
                        connection.execute(
                            text("INSERT INTO public.schema_migrations VALUES (:v)"),
                            {"v": path.name},
                        )
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(20261004)"))
                connection.commit()
