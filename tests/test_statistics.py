"""Tests for bootstrap confidence intervals."""

import pytest

from perfatlas.statistics import bootstrap_median_difference


def test_detects_separated_candidate_distribution():
    result = bootstrap_median_difference(
        [10.0] * 20,
        [15.0] * 20,
        resamples=500,
    )

    assert result["observed_median_difference_ms"] == pytest.approx(5.0)
    assert result["ci_lower_ms"] > 0
    assert result["interpretation"] == "likely_regression"


def test_detects_separated_improvement_distribution():
    result = bootstrap_median_difference(
        [15.0] * 20,
        [10.0] * 20,
        resamples=500,
    )

    assert result["ci_upper_ms"] < 0
    assert result["interpretation"] == "likely_improvement"


def test_overlapping_distributions_can_be_inconclusive():
    result = bootstrap_median_difference(
        [10.0, 11.0, 12.0, 13.0, 14.0],
        [10.0, 11.0, 12.0, 13.0, 14.0],
        resamples=1000,
    )

    assert result["interpretation"] == "inconclusive"


def test_rejects_empty_measurements():
    with pytest.raises(ValueError, match="measurements"):
        bootstrap_median_difference([], [1.0, 2.0])


def test_rejects_invalid_confidence_level():
    with pytest.raises(ValueError, match="confidence_level"):
        bootstrap_median_difference(
            [1.0],
            [2.0],
            confidence_level=1.0,
        )


def test_rejects_too_few_resamples():
    with pytest.raises(ValueError, match="at least 100"):
        bootstrap_median_difference(
            [1.0],
            [2.0],
            resamples=50,
        )
