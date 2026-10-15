"""Statistical uncertainty estimates for performance comparisons."""

import math
import random
from collections.abc import Sequence


def bootstrap_median_difference(
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    confidence_level: float = 0.95,
    resamples: int = 2000,
    seed: int = 42,
) -> dict:
    """Estimate a confidence interval for candidate minus baseline median."""
    if not baseline_values or not candidate_values:
        raise ValueError("Both runs must contain measurements.")

    for values in (baseline_values, candidate_values):
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("Measurements must be finite and non-negative.")

    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between 0 and 1.")

    if resamples < 100:
        raise ValueError("resamples must be at least 100.")

    rng = random.Random(seed)
    baseline = list(baseline_values)
    candidate = list(candidate_values)

    observed_difference = _median(candidate) - _median(baseline)
    differences = []

    for _ in range(resamples):
        baseline_sample = [rng.choice(baseline) for _ in range(len(baseline))]
        candidate_sample = [rng.choice(candidate) for _ in range(len(candidate))]
        differences.append(_median(candidate_sample) - _median(baseline_sample))

    differences.sort()
    tail = (1 - confidence_level) / 2

    lower = _quantile(differences, tail)
    upper = _quantile(differences, 1 - tail)

    if lower > 0:
        interpretation = "likely_regression"
    elif upper < 0:
        interpretation = "likely_improvement"
    else:
        interpretation = "inconclusive"

    return {
        "confidence_level": confidence_level,
        "resamples": resamples,
        "observed_median_difference_ms": observed_difference,
        "ci_lower_ms": lower,
        "ci_upper_ms": upper,
        "interpretation": interpretation,
    }


def _median(values: Sequence[float]) -> float:
    """Return the median of a non-empty sequence."""
    ordered = sorted(values)
    middle = len(ordered) // 2

    if len(ordered) % 2:
        return ordered[middle]

    return (ordered[middle - 1] + ordered[middle]) / 2


def _quantile(values: Sequence[float], probability: float) -> float:
    """Calculate a linearly interpolated quantile."""
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return values[lower]

    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction
