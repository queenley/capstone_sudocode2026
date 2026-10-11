"""Common runtime wiring for services extracted from the legacy API package."""

from src.core.config import Settings
from src.db.session import Database
from src.memory.service import WorkingMemory
from src.security.service import Security
from sqlalchemy import text


def configure_service(app):
    settings = Settings()
    settings.validate()
    database = Database(settings.database_url)
    app.state.settings = settings
    app.state.database = database
    app.state.security = Security(settings)
    app.state.working = WorkingMemory(settings.redis_url)
    return database


def database_ready(app):
    try:
        with app.state.database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
