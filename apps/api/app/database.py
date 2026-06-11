from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_sqlite_path() -> Path:
    state_dir = Path(os.getenv("NASUS_STATE_DIR", _repo_root() / ".nasus" / "state"))
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "nasus.db"


DATABASE_URL = os.getenv("NASUS_DATABASE_URL", f"sqlite+pysqlite:///{_default_sqlite_path()}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
Base = declarative_base()


def get_database_url() -> str:
    return DATABASE_URL


def init_database() -> None:
    from . import db_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
