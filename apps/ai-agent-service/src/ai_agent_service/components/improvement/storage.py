"""Cross-process local file transactions, using only the standard library."""
from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path
import sqlite3
import tempfile


@contextmanager
def locked(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(folder / ".write-lock.sqlite", timeout=15)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield
        connection.commit()
    finally:
        connection.close()


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def version_write(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        from ...config.config_manager import kb_dir
        folder = Path(kwargs.get("directory") or kb_dir())
        with locked(folder):
            return fn(*args, **kwargs)
    return run
