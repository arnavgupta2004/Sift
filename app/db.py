"""Shared SQLite engine/session access for the metadata store."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, create_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
# Everything generated or indexed at runtime (SQLite DB, Chroma indexes, synthetic corpus) lives
# under DATA_DIR. Override with SIFT_DATA_DIR to keep e.g. the test corpus separate from a real
# folder index in the default data/ directory.
DATA_DIR = (REPO_ROOT / Path(os.environ.get("SIFT_DATA_DIR", "data")).expanduser()).resolve()
DEFAULT_DB_PATH = DATA_DIR / "db.sqlite"


@lru_cache(maxsize=8)
def get_engine(db_path: Path = DEFAULT_DB_PATH):
    # WAL + a busy timeout let the background indexer write while queries read: the
    # default rollback journal would make every search wait on (or fail against) a write.
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine


def get_session(db_path: Path = DEFAULT_DB_PATH) -> Session:
    return Session(get_engine(db_path))
