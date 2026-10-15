"""Explain observed latency patterns and identify diagnostic clues."""

import math
from collections.abc import Sequence

from perfatlas.analysis import analyze_latencies, percentile


def analyze_latency_diagnostics(values: Sequence[float]) -> dict:
    """Summarize latency behavior and flag potential outliers."""
    stats = analyze_latencies(values)
    latencies = list(values)

    q1 = percentile(latencies, 25)
    q3 = percentile(latencies, 75)
    iqr = q3 - q1

    lower_fence = max(0.0, q1 - 1.5 * iqr)
    upper_fence = q3 + 1.5 * iqr

    outliers = [
        {
            "iteration": index,
            "latency_ms": value,
            "type": "high" if value > upper_fence else "low",
        }
        for index, value in enumerate(latencies)
        if value < lower_fence or value > upper_fence
    ]

    findings = []

    if len(latencies) < 20:
        findings.append(
            {
                "type": "small_sample",
                "severity": "info",
                "message": (
                    "This run has fewer than 20 measured iterations. "
                    "Tail-percentile estimates may be unstable."
                ),
            }
        )

    if outliers:
        high_count = sum(item["type"] == "high" for item in outliers)
        low_count = len(outliers) - high_count

        findings.append(
            {
                "type": "outliers_detected",
                "severity": "warning",
                "message": (
                    f"Detected {len(outliers)} potential outlier(s): "
                    f"{high_count} high and {low_count} low."
                ),
            }
        )

    if stats["coefficient_of_variation_pct"] >= 20:
        findings.append(
            {
                "type": "high_variability",
                "severity": "warning",
                "message": (
                    "Latency variability is high relative to the mean. "
                    "Investigate background activity, scheduling, and "
                    "workload consistency."
                ),
            }
        )

    return {
        "statistics": stats,
        "quartiles": {
            "q1_ms": q1,
            "q3_ms": q3,
            "iqr_ms": iqr,
        },
        "outlier_rule": "Tukey 1.5xIQR fences",
        "outlier_count": len(outliers),
        "outliers": outliers,
        "findings": findings,
    }


def diagnose_comparison(
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    threshold_pct: float = 10.0,
) -> dict:
    """Compare latency patterns and suggest areas to investigate."""
    if not math.isfinite(threshold_pct) or not 0 <= threshold_pct < 100:
        raise ValueError("threshold_pct must be between 0 and 100.")

    baseline = analyze_latency_diagnostics(baseline_values)
    candidate = analyze_latency_diagnostics(candidate_values)

    baseline_stats = baseline["statistics"]
    candidate_stats = candidate["statistics"]

    def percentage_change(before: float, after: float) -> float | None:
        if before == 0:
            return 0.0 if after == 0 else None
        return (after - before) / before * 100

    median_change = percentage_change(
        baseline_stats["median_ms"],
        candidate_stats["median_ms"],
    )
    p95_change = percentage_change(
        baseline_stats["p95_ms"],
        candidate_stats["p95_ms"],
    )

    cv_change_points = (
        candidate_stats["coefficient_of_variation_pct"]
        - baseline_stats["coefficient_of_variation_pct"]
    )

    findings = []
    suggestions = []

    if median_change is None:
        findings.append(
            {
                "type": "zero_baseline_median",
                "severity": "info",
                "message": (
                    "The baseline median is zero, so percentage change "
                    "in median latency cannot be calculated."
                ),
            }
        )
        suggestions.append(
            "Inspect the raw measurements and confirm the timing resolution "
            "is appropriate for this workload."
        )
    elif median_change >= threshold_pct:
        findings.append(
            {
                "type": "typical_latency_increased",
                "severity": "warning",
                "change_pct": median_change,
                "message": (
                    "Candidate median latency increased beyond the configured diagnostic threshold."
                ),
            }
        )
        suggestions.append(
            "Compare recent code changes, workload inputs, dependency versions, and resource usage."
        )

    if p95_change is None:
        findings.append(
            {
                "type": "zero_baseline_p95",
                "severity": "info",
                "message": (
                    "The baseline p95 is zero, so percentage change "
                    "in p95 latency cannot be calculated."
                ),
            }
        )
    elif p95_change >= threshold_pct:
        findings.append(
            {
                "type": "tail_latency_increased",
                "severity": "warning",
                "change_pct": p95_change,
                "message": (
                    "Candidate p95 latency increased beyond the configured diagnostic threshold."
                ),
            }
        )
        suggestions.append(
            "Investigate intermittent delays, I/O waits, garbage "
            "collection, scheduling, and occasional expensive operations."
        )

    if cv_change_points >= 5:
        findings.append(
            {
                "type": "variability_increased",
                "severity": "warning",
                "change_percentage_points": cv_change_points,
                "message": (
                    "The candidate coefficient of variation increased "
                    "by at least five percentage points."
                ),
            }
        )
        suggestions.append(
            "Repeat the benchmark under controlled conditions and check "
            "background processes, power settings, and thermal throttling."
        )

    if candidate["outlier_count"] > baseline["outlier_count"]:
        findings.append(
            {
                "type": "more_candidate_outliers",
                "severity": "warning",
                "message": ("The candidate contains more Tukey-rule outliers than the baseline."),
            }
        )
        suggestions.append(
            "Inspect the reported outlier iterations and correlate them "
            "with available CPU, memory, disk, or application traces."
        )

    if not findings:
        findings.append(
            {
                "type": "no_major_pattern_detected",
                "severity": "info",
                "message": (
                    "No configured latency-pattern warning was triggered. "
                    "This does not prove that the runs are equivalent."
                ),
            }
        )

    if not suggestions:
        suggestions.append(
            "If performance is still a concern, collect more independent "
            "runs and inspect application-level traces."
        )

    return {
        "threshold_pct": threshold_pct,
        "changes": {
            "median_pct": median_change,
            "p95_pct": p95_change,
            "coefficient_of_variation_percentage_points": cv_change_points,
        },
        "baseline": baseline,
        "candidate": candidate,
        "findings": findings,
        "investigation_suggestions": list(dict.fromkeys(suggestions)),
        "limitations": [
            "These are statistical clues, not proof of a root cause.",
            "Outliers are identified using the Tukey 1.5xIQR rule.",
            "Tail-percentile estimates can be unstable with small samples.",
            "Measurements from one run may be correlated.",
        ],
    }
