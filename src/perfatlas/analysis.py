"""Statistical analysis and regression detection for PerfAtlas."""

import math
from collections.abc import Sequence


def percentile(values: Sequence[float], percentile_value: float) -> float:
    """Calculate a percentile using linear interpolation."""
    if not values:
        raise ValueError("values must not be empty.")

    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile_value must be between 0 and 100.")

    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100
    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return ordered[lower_index]

    fraction = position - lower_index

    return ordered[lower_index] * (1 - fraction) + ordered[upper_index] * fraction


def analyze_latencies(values: Sequence[float]) -> dict:
    """Calculate descriptive statistics for latency measurements."""
    if not values:
        raise ValueError("At least one latency measurement is required.")

    latencies = list(values)

    if any(not math.isfinite(value) or value < 0 for value in latencies):
        raise ValueError("Latencies must be finite, non-negative numbers.")

    count = len(latencies)
    average = sum(latencies) / count
    median_value = percentile(latencies, 50)

    # Sample standard deviation, using n - 1 as the denominator.
    if count > 1:
        variance = sum((value - average) ** 2 for value in latencies) / (count - 1)
        standard_deviation = math.sqrt(variance)
    else:
        standard_deviation = 0.0

    return {
        "count": count,
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "mean_ms": average,
        "median_ms": median_value,
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99),
        "stddev_ms": standard_deviation,
        "coefficient_of_variation_pct": (standard_deviation / average * 100 if average else 0.0),
    }


def compare_runs(
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    threshold_pct: float = 10.0,
) -> dict:
    """Compare two runs and classify the median-latency change."""
    if not baseline_values or not candidate_values:
        raise ValueError("Both runs must contain measurements.")

    if not math.isfinite(threshold_pct) or not 0 <= threshold_pct < 100:
        raise ValueError("threshold_pct must be between 0 and 100.")

    baseline = analyze_latencies(baseline_values)
    candidate = analyze_latencies(candidate_values)

    baseline_median = baseline["median_ms"]
    candidate_median = candidate["median_ms"]

    if baseline_median == 0:
        change_pct = 0.0 if candidate_median == 0 else None
        status = "no_regression" if candidate_median == 0 else "inconclusive"
    else:
        change_pct = (candidate_median - baseline_median) / baseline_median * 100

        if change_pct >= threshold_pct:
            status = "regression"
        elif change_pct <= -threshold_pct:
            status = "improvement"
        else:
            status = "no_regression"

    return {
        "status": status,
        "threshold_pct": threshold_pct,
        "baseline_median_ms": baseline_median,
        "candidate_median_ms": candidate_median,
        "change_pct": change_pct,
        "baseline": baseline,
        "candidate": candidate,
    }
