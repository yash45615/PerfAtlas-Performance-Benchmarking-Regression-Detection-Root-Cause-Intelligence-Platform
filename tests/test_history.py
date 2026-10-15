"""Tests for historical benchmark retrieval."""

import pytest

from perfatlas.benchmark import execute_benchmark
from perfatlas.history import get_run_details, list_runs


def test_list_runs_returns_completed_benchmarks(engine):
    first = execute_benchmark(
        engine,
        workload_name="json",
        iterations=3,
        warmup=0,
        name="history-first",
    )
    second = execute_benchmark(
        engine,
        workload_name="cpu",
        iterations=2,
        warmup=0,
        name="history-second",
    )

    runs = list_runs(engine, limit=10)
    run_ids = {run["run_id"] for run in runs}

    assert first["run_id"] in run_ids
    assert second["run_id"] in run_ids
    assert all("status" in run for run in runs)


def test_list_runs_respects_limit(engine):
    for index in range(3):
        execute_benchmark(
            engine,
            workload_name="json",
            iterations=1,
            warmup=0,
            name=f"history-{index}",
        )

    assert len(list_runs(engine, limit=2)) == 2


def test_list_runs_rejects_invalid_limit(engine):
    with pytest.raises(ValueError, match="limit"):
        list_runs(engine, limit=0)


def test_get_run_details_returns_measurements(engine):
    result = execute_benchmark(
        engine,
        workload_name="json",
        iterations=3,
        warmup=0,
        name="history-details",
    )

    details = get_run_details(engine, result["run_id"])

    assert details["run_id"] == result["run_id"]
    assert details["name"] == "history-details"
    assert details["status"] == "completed"
    assert len(details["measurements"]) == 3
    assert [m["iteration"] for m in details["measurements"]] == [0, 1, 2]


def test_get_run_details_rejects_unknown_id(engine):
    with pytest.raises(ValueError, match="not found"):
        get_run_details(engine, "missing-run-id")


def test_history_includes_environment_metadata(engine):
    result = execute_benchmark(
        engine,
        workload_name="json",
        iterations=2,
        warmup=0,
        name="history-metadata",
    )

    details = get_run_details(engine, result["run_id"])

    assert details["environment"]["workload"] == "json"
    assert details["environment"]["iterations"] == 2
