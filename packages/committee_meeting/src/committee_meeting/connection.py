"""Database connection utilities for committee meeting data."""

from os import getenv
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import create_engine

_DEFAULT_DB_PATH = Path(__file__).parent.parent.parent.parent / "committee_meeting.db"


def get_database_url() -> str:
    """Get the database URL from environment or default to local SQLite.

    Returns:
        The database connection URL. Uses DATABASE_URL environment variable
        if set, otherwise returns a SQLite URL pointing to committee_meeting.db
        in the package root.
    """
    database_url = getenv("DATABASE_URL")
    if database_url is None:
        return f"sqlite:///{_DEFAULT_DB_PATH.resolve()}"
    return database_url


def initialize_connection() -> Engine:
    """Create and return a SQLAlchemy engine for database operations.

    Returns:
        A configured SQLAlchemy Engine instance connected to the database.
    """
    return create_engine(get_database_url())
