import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from perfatlas.db import initialize_database


@pytest.fixture
def engine():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    initialize_database(test_engine)

    yield test_engine

    test_engine.dispose()
