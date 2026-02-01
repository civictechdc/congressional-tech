from os import getenv
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import create_engine

_DEFAULT_DB_PATH = Path(__file__).parent.parent.parent.parent / "committee_meeting.db"


def get_database_url() -> str:
    """Get database URL from environment or default to local SQLite."""
    database_url = getenv("DATABASE_URL")
    if database_url is None:
        return f"sqlite:///{_DEFAULT_DB_PATH.resolve()}"
    return database_url


def initialize_connection() -> Engine:
    return create_engine(get_database_url())
