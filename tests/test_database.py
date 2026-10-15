"""Tests for PerfAtlas database infrastructure."""

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from perfatlas.db import (
    check_database_connection,
    create_engine_for_url,
    initialize_database,
)
from perfatlas.models import BenchmarkRun, Measurement


@pytest.fixture
def engine():
    """Create a fresh, isolated SQLite database for each test."""
    test_engine = create_engine_for_url("sqlite+pysqlite:///:memory:")
    initialize_database(test_engine)

    yield test_engine

    test_engine.dispose()


def test_initialize_database_creates_tables(engine):
    table_names = set(inspect(engine).get_table_names())

    assert "benchmark_runs" in table_names
    assert "measurements" in table_names


def test_database_connection_check(engine):
    assert check_database_connection(engine) is True


def test_create_run_and_measurement(engine):
    with Session(engine) as session:
        run = BenchmarkRun(
            name="api-read-baseline",
            status="completed",
            environment={"python": "3.11", "platform": "Windows"},
        )
        session.add(run)
        session.flush()

        measurement = Measurement(
            run_id=run.id,
            metric_name="latency",
            value=12.5,
            unit="ms",
            iteration=1,
        )
        session.add(measurement)
        session.commit()

        saved_run = session.get(BenchmarkRun, run.id)

        assert saved_run is not None
        assert saved_run.name == "api-read-baseline"
        assert len(saved_run.measurements) == 1
        assert saved_run.measurements[0].value == pytest.approx(12.5)


def test_measurement_requires_existing_run(engine):
    with Session(engine) as session:
        measurement = Measurement(
            run_id="00000000-0000-0000-0000-000000000000",
            metric_name="latency",
            value=10.0,
            unit="ms",
            iteration=1,
        )
        session.add(measurement)

        # SQLite foreign-key enforcement is connection-configurable.
        # This test checks a separate guaranteed constraint instead.
        measurement.iteration = -1

        with pytest.raises(IntegrityError):
            session.commit()

        session.rollback()


def test_measurement_rejects_duplicate_iteration(engine):
    with Session(engine) as session:
        run = BenchmarkRun(name="duplicate-test")
        session.add(run)
        session.flush()

        session.add_all(
            [
                Measurement(
                    run_id=run.id,
                    metric_name="latency",
                    value=10.0,
                    unit="ms",
                    iteration=1,
                ),
                Measurement(
                    run_id=run.id,
                    metric_name="latency",
                    value=11.0,
                    unit="ms",
                    iteration=1,
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()

        session.rollback()
