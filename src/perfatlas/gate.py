"""Automated regression gates for benchmark runs."""

import json
from pathlib import Path

from sqlalchemy import Engine

from perfatlas.analysis import compare_runs
from perfatlas.diagnostics import diagnose_comparison
from perfatlas.history import get_run_details
from perfatlas.manifest import compare_environment_manifests
from perfatlas.statistics import bootstrap_median_difference


def run_regression_gate(
    engine: Engine,
    baseline_run_id: str,
    candidate_run_id: str,
    threshold_pct: float = 10.0,
    output_path: str | Path | None = None,
) -> dict:
    """Compare completed runs and report uncertainty and environment differences."""
    baseline = get_run_details(engine, baseline_run_id)
    candidate = get_run_details(engine, candidate_run_id)

    for label, run in (
        ("Baseline", baseline),
        ("Candidate", candidate),
    ):
        if run["status"] != "completed":
            raise ValueError(f"{label} run must be completed; got status {run['status']!r}.")

    baseline_manifest = baseline.get("environment") or {}
    candidate_manifest = candidate.get("environment") or {}

    baseline_workload = baseline_manifest.get("workload")
    candidate_workload = candidate_manifest.get("workload")

    if not baseline_workload or not candidate_workload:
        raise ValueError("Both runs must contain workload metadata.")

    if baseline_workload != candidate_workload:
        raise ValueError(
            f"Cannot compare different workloads: {baseline_workload!r} vs {candidate_workload!r}."
        )

    baseline_values = [
        item["value"] for item in baseline["measurements"] if item["metric_name"] == "latency_ms"
    ]
    candidate_values = [
        item["value"] for item in candidate["measurements"] if item["metric_name"] == "latency_ms"
    ]

    comparison = compare_runs(
        baseline_values,
        candidate_values,
        threshold_pct=threshold_pct,
    )

    uncertainty = bootstrap_median_difference(
        baseline_values,
        candidate_values,
        confidence_level=0.95,
        resamples=2000,
        seed=42,
    )

    environment_comparison = compare_environment_manifests(
        baseline_manifest,
        candidate_manifest,
    )
    diagnostics = diagnose_comparison(
        baseline_values,
        candidate_values,
        # Keep any other existing arguments unchanged.
    )
    # Environment differences are reported as warnings; the existing
    # threshold-based gate pass/fail behavior remains unchanged.
    passed = comparison["status"] in {
        "no_regression",
        "improvement",
    }

    report = {
        "passed": passed,
        "status": comparison["status"],
        "diagnostics": diagnostics,
        "baseline": {
            "run_id": baseline["run_id"],
            "name": baseline["name"],
            "workload": baseline_workload,
        },
        "candidate": {
            "run_id": candidate["run_id"],
            "name": candidate["name"],
            "workload": candidate_workload,
        },
        "threshold_pct": threshold_pct,
        "change_pct": comparison["change_pct"],
        "baseline_median_ms": comparison["baseline_median_ms"],
        "candidate_median_ms": comparison["candidate_median_ms"],
        "comparison": comparison,
        "uncertainty": uncertainty,
        "environment_comparison": environment_comparison,
    }

    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    return report
