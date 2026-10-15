"""Database engine and schema initialization for PerfAtlas."""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all PerfAtlas database models."""


def get_database_url() -> str:
    """Read the database URL from the environment."""
    url = os.getenv("DATABASE_URL")

    if not url:
        raise RuntimeError("DATABASE_URL is not set. Configure it before using the database.")

    return url


def create_engine_for_url(database_url: str) -> Engine:
    """Create an engine for PostgreSQL or a test SQLite database."""
    if not database_url:
        raise ValueError("database_url must not be empty.")

    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
    )


def initialize_database(engine: Engine) -> None:
    """Create all registered PerfAtlas tables."""
    # Import models so SQLAlchemy registers their tables with Base.metadata.
    from perfatlas import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def check_database_connection(engine: Engine) -> bool:
    """Return True when a simple database query succeeds."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return True
