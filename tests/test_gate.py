"""Tests for automated regression gates."""

import json

import pytest

from perfatlas import gate


def make_run(
    run_id: str,
    name: str,
    values: list[float],
    workload: str = "json",
    status: str = "completed",
) -> dict:
    """Build a test benchmark-run record."""
    return {
        "run_id": run_id,
        "name": name,
        "status": status,
        "environment": {"workload": workload},
        "measurements": [
            {
                "metric_name": "latency_ms",
                "value": value,
                "unit": "ms",
                "iteration": index,
            }
            for index, value in enumerate(values)
        ],
    }


@pytest.fixture
def fake_runs(monkeypatch):
    """Provide deterministic baseline and candidate records."""
    runs = {
        "baseline": make_run("baseline", "baseline-run", [10.0, 10.0, 10.0]),
        "candidate": make_run("candidate", "candidate-run", [12.0, 12.0, 12.0]),
    }

    def fake_get_run_details(engine, run_id):
        if run_id not in runs:
            raise ValueError(f"Benchmark run not found: {run_id}")
        return runs[run_id]

    monkeypatch.setattr(gate, "get_run_details", fake_get_run_details)
    return runs


def test_regression_gate_fails_for_regression(fake_runs):
    report = gate.run_regression_gate(
        engine=None,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
        threshold_pct=10.0,
    )

    assert report["passed"] is False
    assert report["status"] == "regression"
    assert report["change_pct"] == pytest.approx(20.0)
    assert report["uncertainty"]["confidence_level"] == 0.95
    assert report["uncertainty"]["resamples"] == 2000
    assert report["uncertainty"]["ci_lower_ms"] > 0
    assert report["uncertainty"]["interpretation"] == "likely_regression"


def test_regression_gate_writes_json_report(fake_runs, tmp_path):
    destination = tmp_path / "reports" / "gate.json"

    report = gate.run_regression_gate(
        engine=None,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
        output_path=destination,
    )

    saved = json.loads(destination.read_text(encoding="utf-8"))

    assert saved["passed"] is False
    assert saved["status"] == "regression"
    assert saved["candidate"]["run_id"] == "candidate"
    assert report == saved


def test_regression_gate_rejects_different_workloads(
    fake_runs,
):
    fake_runs["candidate"]["environment"]["workload"] = "cpu"

    with pytest.raises(ValueError, match="different workloads"):
        gate.run_regression_gate(
            engine=None,
            baseline_run_id="baseline",
            candidate_run_id="candidate",
        )


def test_regression_gate_rejects_incomplete_run(fake_runs):
    fake_runs["candidate"]["status"] = "running"

    with pytest.raises(ValueError, match="must be completed"):
        gate.run_regression_gate(
            engine=None,
            baseline_run_id="baseline",
            candidate_run_id="candidate",
        )


def test_regression_gate_passes_when_change_is_below_threshold(
    fake_runs,
):
    fake_runs["candidate"]["measurements"] = [
        {
            "metric_name": "latency_ms",
            "value": 10.5,
            "unit": "ms",
            "iteration": index,
        }
        for index in range(3)
    ]

    report = gate.run_regression_gate(
        engine=None,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
        threshold_pct=10.0,
    )

    assert report["passed"] is True
    assert report["status"] == "no_regression"
    assert report["change_pct"] == pytest.approx(5.0)
    assert "uncertainty" in report
    assert report["uncertainty"]["interpretation"] == "likely_regression"


def test_regression_gate_reports_environment_mismatch(fake_runs):
    full_environment = {
        "python_version": "3.11.2",
        "implementation": "CPython",
        "platform": "Windows-11",
        "machine": "AMD64",
        "processor": "Example CPU",
        "cpu_count": 8,
    }

    fake_runs["baseline"]["environment"].update(
        {
            "environment": full_environment,
        }
    )
    fake_runs["candidate"]["environment"].update(
        {
            "environment": {**full_environment, "cpu_count": 16},
        }
    )

    report = gate.run_regression_gate(
        engine=None,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
    )

    assert report["environment_comparison"]["status"] == "mismatch"
    assert report["environment_comparison"]["compatible"] is False
    assert report["environment_comparison"]["warnings"]
    # Environment differences do not override the existing latency gate.
    assert report["passed"] is False


def test_regression_gate_keeps_pass_behavior_with_unknown_environment(fake_runs):
    fake_runs["candidate"]["measurements"] = [
        {
            "metric_name": "latency_ms",
            "value": 10.5,
            "unit": "ms",
            "iteration": index,
        }
        for index in range(3)
    ]

    report = gate.run_regression_gate(
        engine=None,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
        threshold_pct=10.0,
    )

    assert report["passed"] is True
    assert report["environment_comparison"]["status"] == "unknown"
    assert report["environment_comparison"]["warnings"]


def test_regression_gate_includes_diagnostics(fake_runs):
    report = gate.run_regression_gate(
        engine=None,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
        threshold_pct=10.0,
    )

    diagnostics = report["diagnostics"]

    assert diagnostics["changes"]["median_pct"] == pytest.approx(20.0)
    assert diagnostics["baseline"]["statistics"]["median_ms"] == pytest.approx(10.0)
    assert diagnostics["candidate"]["statistics"]["median_ms"] == pytest.approx(12.0)
    assert diagnostics["findings"]
    assert diagnostics["investigation_suggestions"]
    assert diagnostics["limitations"]


def test_regression_gate_passes_when_candidate_improves(fake_runs):
    """A faster candidate should pass the gate."""
    fake_runs["candidate"]["measurements"] = [
        {
            "metric_name": "latency_ms",
            "value": 8.0,
            "unit": "ms",
            "iteration": index,
        }
        for index in range(3)
    ]

    report = gate.run_regression_gate(
        engine=None,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
        threshold_pct=10.0,
    )

    assert report["passed"] is True
    assert report["status"] == "improvement"
    assert report["change_pct"] == pytest.approx(-20.0)


def test_regression_gate_rejects_missing_workload_metadata(fake_runs):
    """Runs without workload metadata cannot be compared safely."""
    fake_runs["candidate"]["environment"] = {}

    with pytest.raises(ValueError, match="workload metadata"):
        gate.run_regression_gate(
            engine=None,
            baseline_run_id="baseline",
            candidate_run_id="candidate",
        )


def test_regression_gate_rejects_empty_latency_measurements(fake_runs):
    """An empty candidate measurement set should fail safely."""
    fake_runs["candidate"]["measurements"] = []

    with pytest.raises(ValueError):
        gate.run_regression_gate(
            engine=None,
            baseline_run_id="baseline",
            candidate_run_id="candidate",
        )
