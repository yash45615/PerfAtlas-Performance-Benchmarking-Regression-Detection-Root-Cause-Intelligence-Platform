"""Interactive historical performance dashboard for PerfAtlas."""

from functools import lru_cache

import pandas as pd
import streamlit as st

from perfatlas.analysis import analyze_latencies, compare_runs
from perfatlas.db import create_engine_for_url, get_database_url
from perfatlas.diagnostics import diagnose_comparison
from perfatlas.history import get_run_details, list_runs


@lru_cache(maxsize=1)
def get_engine():
    """Create a reusable database engine from DATABASE_URL."""
    return create_engine_for_url(get_database_url())


def summarize_run(run: dict) -> dict | None:
    """Summarize a completed run's recorded latency measurements."""
    latencies = [
        item["value"] for item in run["measurements"] if item["metric_name"] == "latency_ms"
    ]

    if not latencies:
        return None

    stats = analyze_latencies(latencies)
    environment = run.get("environment") or {}

    return {
        "run_id": run["run_id"],
        "name": run["name"],
        "started_at": run.get("started_at"),
        "workload": environment.get("workload", "unknown"),
        "git_commit": run.get("git_commit"),
        "count": stats["count"],
        "median_ms": stats["median_ms"],
        "p95_ms": stats["p95_ms"],
        "p99_ms": stats["p99_ms"],
        "mean_ms": stats["mean_ms"],
    }


def get_latency_values(run: dict) -> list[float]:
    """Extract latency measurements from a run's detail record."""
    return [
        item["value"] for item in run.get("measurements", []) if item["metric_name"] == "latency_ms"
    ]


def annotate_regressions(
    summaries: list[dict],
    details_by_id: dict,
    threshold_pct: float = 10.0,
) -> list[dict]:
    """Compare each run with the preceding run of the same workload."""
    ordered = sorted(
        summaries,
        key=lambda item: item.get("started_at") or "",
    )

    previous_by_workload = {}

    for summary in ordered:
        workload = summary["workload"]
        previous = previous_by_workload.get(workload)

        summary["change_vs_previous_pct"] = None
        summary["status_vs_previous"] = "first_run"

        if previous is not None:
            baseline = details_by_id.get(previous["run_id"], {})
            candidate = details_by_id.get(summary["run_id"], {})

            baseline_values = get_latency_values(baseline)
            candidate_values = get_latency_values(candidate)

            if baseline_values and candidate_values:
                try:
                    comparison = compare_runs(
                        baseline_values,
                        candidate_values,
                        threshold_pct=threshold_pct,
                    )
                    summary["change_vs_previous_pct"] = comparison["change_pct"]
                    summary["status_vs_previous"] = comparison["status"]
                except ValueError:
                    summary["status_vs_previous"] = "inconclusive"

        previous_by_workload[workload] = summary

    return ordered


def main():
    """Render the PerfAtlas performance intelligence dashboard."""
    st.set_page_config(
        page_title="PerfAtlas | Performance Intelligence",
        page_icon="📈",
        layout="wide",
    )

    st.title("PerfAtlas")
    st.caption("Measure reliably. Detect regressions. Find the root cause.")

    with st.sidebar:
        st.header("Dashboard settings")
        regression_threshold = st.number_input(
            "Regression threshold (%)",
            min_value=0.1,
            max_value=99.9,
            value=10.0,
            step=1.0,
            help=(
                "A same-workload median-latency increase at or above "
                "this threshold is classified as a regression."
            ),
        )
        history_limit = st.slider(
            "Maximum runs to load",
            min_value=10,
            max_value=500,
            value=200,
            step=10,
        )

        if st.button("Refresh dashboard", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    try:
        engine = get_engine()
        runs = list_runs(engine, limit=history_limit)
    except Exception as exc:
        st.error(f"Could not connect to the PerfAtlas database: {exc}")
        st.info(
            "Set DATABASE_URL in this terminal to the same database used by "
            "your PerfAtlas CLI, then restart the dashboard."
        )
        st.stop()

    completed_runs = [run for run in runs if run["status"] == "completed"]

    if not completed_runs:
        st.warning("No completed benchmark runs were found in this database.")
        st.write("Run a benchmark with your PerfAtlas CLI, then refresh this page.")
        st.stop()

    details_by_id = {}

    progress = st.progress(0, text="Loading benchmark measurements...")

    for index, run in enumerate(completed_runs):
        try:
            details_by_id[run["run_id"]] = get_run_details(
                engine,
                run["run_id"],
            )
        except (ValueError, KeyError):
            pass

        progress.progress(
            (index + 1) / len(completed_runs),
            text=f"Loading run {index + 1} of {len(completed_runs)}...",
        )

    progress.empty()

    summaries = []

    for details in details_by_id.values():
        try:
            summary = summarize_run(details)
        except (TypeError, ValueError, KeyError):
            continue

        if summary is not None:
            summaries.append(summary)

    if not summaries:
        st.warning("No completed runs contain valid latency measurements.")
        st.stop()

    summaries = annotate_regressions(
        summaries,
        details_by_id,
        threshold_pct=float(regression_threshold),
    )

    summary_by_id = {item["run_id"]: item for item in summaries}
    latest = summaries[-1]

    regression_count = sum(item["status_vs_previous"] == "regression" for item in summaries)
    improvement_count = sum(item["status_vs_previous"] == "improvement" for item in summaries)
    inconclusive_count = sum(item["status_vs_previous"] == "inconclusive" for item in summaries)

    st.subheader("Performance overview")

    col1, col2, col3 = st.columns(3)
    col1.metric("Completed runs", len(summaries))
    col2.metric("Detected regressions", regression_count)
    col3.metric("Detected improvements", improvement_count)

    col4, col5, col6 = st.columns(3)
    col4.metric("Latest workload", latest["workload"])
    col5.metric("Latest median", f"{latest['median_ms']:.3f} ms")
    col6.metric("Latest p95", f"{latest['p95_ms']:.3f} ms")

    st.caption(
        f"Regression screening threshold: {regression_threshold:.1f}%. "
        f"Inconclusive comparisons: {inconclusive_count}. "
        "These classifications compare consecutive runs of the same workload; "
        "they are screening signals, not proof of a root cause."
    )

    if latest["status_vs_previous"] == "regression":
        st.warning(
            "The latest run is classified as a regression relative to "
            "the previous run of the same workload."
        )
    elif latest["status_vs_previous"] == "improvement":
        st.success(
            "The latest run is classified as an improvement relative to "
            "the previous run of the same workload."
        )
    elif latest["status_vs_previous"] == "inconclusive":
        st.info("The latest same-workload comparison is inconclusive.")

    st.divider()
    st.subheader("Historical performance")

    workload_options = sorted({item["workload"] for item in summaries})

    selected_workload = st.selectbox(
        "Filter by workload",
        ["All workloads", *workload_options],
    )

    filtered = [
        item
        for item in summaries
        if selected_workload == "All workloads" or item["workload"] == selected_workload
    ]

    trend_data = pd.DataFrame(filtered)

    if not trend_data.empty:
        trend_data["started_at"] = pd.to_datetime(
            trend_data["started_at"],
            errors="coerce",
            utc=True,
        )
        trend_data = trend_data.dropna(subset=["started_at"])
        trend_data = trend_data.sort_values("started_at")

        if not trend_data.empty:
            st.line_chart(
                trend_data,
                x="started_at",
                y=["median_ms", "p95_ms", "p99_ms"],
                x_label="Benchmark start time",
                y_label="Latency (ms)",
            )
        else:
            st.info("Historical timestamps are unavailable for charting.")

    st.caption(
        "Each point represents one benchmark run. p95 and p99 estimates "
        "can be unstable when a run has few iterations. Compare runs under "
        "similar system conditions for more reliable conclusions."
    )

    st.divider()
    st.subheader("Recent benchmark runs")

    display_columns = [
        "started_at",
        "name",
        "workload",
        "count",
        "median_ms",
        "p95_ms",
        "p99_ms",
        "change_vs_previous_pct",
        "status_vs_previous",
        "git_commit",
    ]

    table_data = pd.DataFrame(filtered)

    if not table_data.empty:
        table_data["change_vs_previous_pct"] = table_data["change_vs_previous_pct"].map(
            lambda value: "-" if pd.isna(value) else f"{value:+.2f}%"
        )

        table_data["git_commit"] = table_data["git_commit"].fillna("-")

        st.dataframe(
            table_data[display_columns],
            hide_index=True,
            width="stretch",
        )

    else:
        st.info("No runs match the selected workload.")

    st.divider()
    st.subheader("Compare two runs")

    run_ids = list(summary_by_id)

    if len(run_ids) < 2:
        st.info(
            "At least two completed runs with latency measurements are "
            "needed to compare performance."
        )
        st.stop()

    labels = {
        run_id: (
            f"{summary_by_id[run_id]['name']} [{summary_by_id[run_id]['workload']}] ({run_id[:8]})"
        )
        for run_id in run_ids
    }

    baseline_id = st.selectbox(
        "Baseline run",
        run_ids,
        format_func=lambda run_id: labels[run_id],
        key="baseline_run",
    )

    candidate_options = [run_id for run_id in run_ids if run_id != baseline_id]

    candidate_id = st.selectbox(
        "Candidate run",
        candidate_options,
        format_func=lambda run_id: labels[run_id],
        key="candidate_run",
    )

    if st.button("Analyze comparison", type="primary"):
        baseline = details_by_id[baseline_id]
        candidate = details_by_id[candidate_id]

        baseline_workload = (baseline.get("environment") or {}).get("workload")
        candidate_workload = (candidate.get("environment") or {}).get("workload")

        if baseline_workload != candidate_workload:
            st.error("Choose runs with the same workload for a meaningful performance comparison.")
        else:
            baseline_values = get_latency_values(baseline)
            candidate_values = get_latency_values(candidate)

            if not baseline_values or not candidate_values:
                st.error("Both selected runs must contain latency measurements.")
            else:
                try:
                    diagnosis = diagnose_comparison(
                        baseline_values,
                        candidate_values,
                        threshold_pct=float(regression_threshold),
                    )

                    change = diagnosis["changes"]["median_pct"]

                    if change is None:
                        st.metric("Median latency change", "Inconclusive")
                    else:
                        st.metric(
                            "Median latency change",
                            f"{change:+.2f}%",
                            help=(
                                "Positive means the candidate is slower; "
                                "negative means it is faster."
                            ),
                        )

                    left, right = st.columns(2)

                    left.metric(
                        "Baseline median",
                        (f"{diagnosis['baseline']['statistics']['median_ms']:.3f} ms"),
                    )
                    right.metric(
                        "Candidate median",
                        (f"{diagnosis['candidate']['statistics']['median_ms']:.3f} ms"),
                    )

                    st.markdown("**Findings**")

                    for finding in diagnosis["findings"]:
                        st.write(
                            f"**{finding['severity'].upper()} — "
                            f"{finding['type']}:** {finding['message']}"
                        )

                    st.markdown("**Investigation suggestions**")

                    for suggestion in diagnosis["investigation_suggestions"]:
                        st.write(f"- {suggestion}")

                    with st.expander("Detailed diagnostic data"):
                        st.json(diagnosis)

                    st.caption(
                        "Diagnostics identify patterns worth investigating; "
                        "they do not prove a root cause or replace the "
                        "automated regression gate."
                    )

                except (ValueError, KeyError, TypeError) as exc:
                    st.error(f"Could not compare these runs: {exc}")


if __name__ == "__main__":
    main()
