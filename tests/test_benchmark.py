"""Tests for the PerfAtlas benchmark execution engine."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from perfatlas.benchmark import execute_benchmark
from perfatlas.db import create_engine_for_url, initialize_database
from perfatlas.models import BenchmarkRun, Measurement


@pytest.fixture
def engine():
    """Create an isolated database for each test."""
    test_engine = create_engine_for_url("sqlite+pysqlite:///:memory:")
    initialize_database(test_engine)
    yield test_engine
    test_engine.dispose()


def test_benchmark_persists_run_and_measurements(engine):
    result = execute_benchmark(
        engine,
        workload_name="json",
        iterations=5,
        warmup=2,
        name="test-json-benchmark",
    )

    assert result["iterations"] == 5
    assert result["warmup"] == 2
    assert len(result["latencies_ms"]) == 5
    assert result["min_ms"] <= result["median_ms"] <= result["max_ms"]

    with Session(engine) as session:
        run = session.get(BenchmarkRun, result["run_id"])
        measurements = session.scalars(
            select(Measurement).where(Measurement.run_id == result["run_id"])
        ).all()

        assert run is not None
        assert run.status == "completed"
        assert run.name == "test-json-benchmark"
        assert len(measurements) == 5
        assert all(m.metric_name == "latency_ms" for m in measurements)
        assert all(m.unit == "ms" for m in measurements)


def test_cpu_workload_can_be_benchmarked(engine):
    result = execute_benchmark(
        engine,
        workload_name="cpu",
        iterations=3,
        warmup=1,
    )

    assert result["workload"] == "cpu"
    assert len(result["latencies_ms"]) == 3


def test_benchmark_rejects_zero_iterations(engine):
    with pytest.raises(ValueError, match="at least 1"):
        execute_benchmark(engine, iterations=0)


def test_benchmark_rejects_negative_warmup(engine):
    with pytest.raises(ValueError, match="zero or greater"):
        execute_benchmark(engine, warmup=-1)


def test_benchmark_rejects_unknown_workload(engine):
    with pytest.raises(ValueError, match="Unknown workload"):
        execute_benchmark(engine, workload_name="not-a-real-workload")


def test_benchmark_writes_reproducibility_manifest(engine, tmp_path, monkeypatch):
    """Each benchmark run should have a matching JSON manifest."""
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "default.yaml").write_text(
        "iterations: 3\nwarmup: 1\n",
        encoding="utf-8",
    )

    result = execute_benchmark(
        engine,
        workload_name="json",
        iterations=3,
        warmup=1,
        name="manifest-test",
    )

    manifest_path = tmp_path / "reports" / "manifests" / f"{result['run_id']}.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["run_id"] == result["run_id"]
    assert manifest["workload"] == "json"
    assert manifest["iterations"] == 3
    assert manifest["warmup"] == 1
    assert manifest.get("config_sha256")

    with Session(engine) as session:
        saved_run = session.get(BenchmarkRun, result["run_id"])
        assert saved_run is not None
        assert saved_run.config_sha256 == manifest["config_sha256"]
        assert saved_run.environment["workload"] == "json"
