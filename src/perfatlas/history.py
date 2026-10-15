"""Query historical benchmark runs and their measurements."""

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from perfatlas.models import BenchmarkRun, Measurement


def list_runs(engine: Engine, limit: int = 10) -> list[dict]:
    """Return the most recent benchmark runs."""
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    with Session(engine) as session:
        statement = (
            select(BenchmarkRun)
            .order_by(BenchmarkRun.started_at.desc(), BenchmarkRun.id.desc())
            .limit(limit)
        )
        runs = session.scalars(statement).all()

        return [
            {
                "run_id": run.id,
                "name": run.name,
                "status": run.status,
                "started_at": (run.started_at.isoformat() if run.started_at else None),
                "finished_at": (run.finished_at.isoformat() if run.finished_at else None),
                "git_commit": run.git_commit,
                "config_sha256": run.config_sha256,
                "workload": (run.environment.get("workload") if run.environment else None),
                "iterations": (run.environment.get("iterations") if run.environment else None),
            }
            for run in runs
        ]


def get_run_details(engine: Engine, run_id: str) -> dict:
    """Return a benchmark run and its recorded latency measurements."""
    with Session(engine) as session:
        run = session.get(BenchmarkRun, run_id)

        if run is None:
            raise ValueError(f"Benchmark run not found: {run_id}")

        statement = (
            select(Measurement)
            .where(Measurement.run_id == run_id)
            .order_by(Measurement.iteration.asc())
        )
        measurements = session.scalars(statement).all()

        return {
            "run_id": run.id,
            "name": run.name,
            "status": run.status,
            "started_at": (run.started_at.isoformat() if run.started_at else None),
            "finished_at": (run.finished_at.isoformat() if run.finished_at else None),
            "git_commit": run.git_commit,
            "config_sha256": run.config_sha256,
            "environment": run.environment or {},
            "measurements": [
                {
                    "metric_name": measurement.metric_name,
                    "value": measurement.value,
                    "unit": measurement.unit,
                    "iteration": measurement.iteration,
                }
                for measurement in measurements
            ],
        }
