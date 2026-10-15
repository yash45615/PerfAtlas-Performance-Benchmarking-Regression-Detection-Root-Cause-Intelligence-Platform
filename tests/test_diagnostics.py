"""Tests for latency diagnostics and regression explanations."""

import pytest

from perfatlas.diagnostics import (
    analyze_latency_diagnostics,
    diagnose_comparison,
)


def test_diagnostics_return_statistics_and_quartiles():
    result = analyze_latency_diagnostics([10, 20, 30, 40, 50])

    assert result["statistics"]["median_ms"] == 30
    assert result["quartiles"]["q1_ms"] == 20
    assert result["quartiles"]["q3_ms"] == 40
    assert result["quartiles"]["iqr_ms"] == 20
    assert result["outlier_count"] == 0


def test_diagnostics_detect_high_outlier():
    result = analyze_latency_diagnostics([10, 11, 10, 12, 11, 100])

    assert result["outlier_count"] == 1
    assert result["outliers"][0]["iteration"] == 5
    assert result["outliers"][0]["type"] == "high"
    assert any(finding["type"] == "outliers_detected" for finding in result["findings"])


def test_diagnostics_report_small_sample():
    result = analyze_latency_diagnostics([10, 11, 12])

    assert any(finding["type"] == "small_sample" for finding in result["findings"])


def test_comparison_detects_typical_latency_increase():
    result = diagnose_comparison(
        baseline_values=[10, 10, 10, 10, 10],
        candidate_values=[12, 12, 12, 12, 12],
        threshold_pct=10,
    )

    assert result["changes"]["median_pct"] == pytest.approx(20)
    assert any(finding["type"] == "typical_latency_increased" for finding in result["findings"])
    assert result["investigation_suggestions"]


def test_comparison_detects_tail_latency_increase():
    result = diagnose_comparison(
        baseline_values=[10, 10, 10, 10, 10, 10, 10, 10],
        candidate_values=[10, 10, 10, 10, 10, 10, 10, 30],
        threshold_pct=10,
    )

    assert result["changes"]["p95_pct"] > 10
    assert any(finding["type"] == "tail_latency_increased" for finding in result["findings"])


def test_comparison_handles_zero_baseline():
    result = diagnose_comparison(
        baseline_values=[0, 0, 0],
        candidate_values=[1, 1, 1],
    )

    assert result["changes"]["median_pct"] is None
    assert any(finding["type"] == "zero_baseline_median" for finding in result["findings"])


@pytest.mark.parametrize(
    "values",
    [
        [],
        [-1],
        [float("nan")],
        [float("inf")],
    ],
)
def test_diagnostics_reject_invalid_measurements(values):
    with pytest.raises(ValueError):
        analyze_latency_diagnostics(values)


def test_comparison_rejects_invalid_threshold():
    with pytest.raises(ValueError, match="threshold_pct"):
        diagnose_comparison([10], [12], threshold_pct=100)
