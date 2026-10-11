"""Bootstrap an admin via a hidden password prompt; no default production passwords."""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/backend-common"))
from src.db.session import Database
from src.core.config import Settings
from src.db.models import StaffUser
from src.security.auth import password_hash
from sqlalchemy import select

if __name__ == "__main__":
    username = input("Admin username: ").strip()
    password = getpass.getpass("Password (12+ characters): ")
    if len(username) < 3 or len(password) < 12:
        raise SystemExit("Username needs 3 characters; password needs 12.")
    database = Database(Settings().database_url)
    database.migrate()
    with database.sessions() as db:
        if db.scalar(select(StaffUser).where(StaffUser.username == username)):
            raise SystemExit("Username already exists")
        db.add(
            StaffUser(
                username=username, password_hash=password_hash(password), role="admin"
            )
        )
        db.commit()
    print("Admin created.")
