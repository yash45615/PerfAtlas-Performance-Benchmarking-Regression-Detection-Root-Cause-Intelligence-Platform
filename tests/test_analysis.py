"""Tests for statistical analysis and regression detection."""

import pytest

from perfatlas.analysis import (
    analyze_latencies,
    compare_runs,
    percentile,
)


def test_percentile_interpolates_between_values():
    assert percentile([10, 20, 30, 40, 50], 95) == pytest.approx(48)


def test_analysis_returns_expected_statistics():
    result = analyze_latencies([10, 20, 30, 40, 50])

    assert result["count"] == 5
    assert result["min_ms"] == 10
    assert result["max_ms"] == 50
    assert result["mean_ms"] == 30
    assert result["median_ms"] == 30
    assert result["p50_ms"] == 30
    assert result["p95_ms"] == pytest.approx(48)
    assert result["p99_ms"] == pytest.approx(49.6)


def test_single_measurement_has_zero_standard_deviation():
    result = analyze_latencies([12.5])

    assert result["stddev_ms"] == 0
    assert result["coefficient_of_variation_pct"] == 0


def test_analysis_rejects_empty_measurements():
    with pytest.raises(ValueError, match="At least one"):
        analyze_latencies([])


@pytest.mark.parametrize("values", [[-1], [float("nan")], [float("inf")]])
def test_analysis_rejects_invalid_measurements(values):
    with pytest.raises(ValueError, match="finite, non-negative"):
        analyze_latencies(values)


def test_detects_regression():
    result = compare_runs(
        baseline_values=[20, 20, 20, 20, 20],
        candidate_values=[24, 24, 24, 24, 24],
        threshold_pct=10,
    )

    assert result["status"] == "regression"
    assert result["change_pct"] == pytest.approx(20)


def test_detects_improvement():
    result = compare_runs(
        baseline_values=[20, 20, 20],
        candidate_values=[16, 16, 16],
        threshold_pct=10,
    )

    assert result["status"] == "improvement"
    assert result["change_pct"] == pytest.approx(-20)


def test_small_change_is_not_flagged():
    result = compare_runs(
        baseline_values=[20, 20, 20],
        candidate_values=[21, 21, 21],
        threshold_pct=10,
    )

    assert result["status"] == "no_regression"
    assert result["change_pct"] == pytest.approx(5)


def test_zero_baseline_is_handled():
    result = compare_runs([0, 0], [1, 1])

    assert result["status"] == "inconclusive"
    assert result["change_pct"] is None


def test_comparison_rejects_invalid_threshold():
    with pytest.raises(ValueError, match="threshold_pct"):
        compare_runs([10], [12], threshold_pct=100)
