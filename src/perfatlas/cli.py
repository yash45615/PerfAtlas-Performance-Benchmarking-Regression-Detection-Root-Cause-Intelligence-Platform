"""Command-line interface for PerfAtlas."""

import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.orm import Session

from perfatlas import __version__
from perfatlas.analysis import analyze_latencies, compare_runs
from perfatlas.benchmark import execute_benchmark
from perfatlas.config import load_config
from perfatlas.db import (
    check_database_connection,
    create_engine_for_url,
    get_database_url,
    initialize_database,
)
from perfatlas.gate import run_regression_gate
from perfatlas.history import get_run_details, list_runs
from perfatlas.logging_config import configure_logging
from perfatlas.manifest import build_manifest, write_manifest
from perfatlas.models import BenchmarkRun, Measurement

app = typer.Typer(
    name="perfatlas",
    help="Reproducible performance benchmarking and regression intelligence.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger("perfatlas")


@app.command("analyze")
def analyze_command(
    run_id: str = typer.Argument(..., help="Benchmark run ID to analyze."),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="DATABASE_URL",
        show_default=False,
    ),
) -> None:
    """Analyze latency measurements for a benchmark run."""
    engine = None

    try:
        url = database_url or get_database_url()
        engine = create_engine_for_url(url)

        with Session(engine) as session:
            run = session.get(BenchmarkRun, run_id)

            if run is None:
                raise ValueError(f"Benchmark run not found: {run_id}")
            if run.status != "completed":
                raise ValueError(f"Run must be completed; current status is '{run.status}'.")

            values = list(
                session.scalars(
                    select(Measurement.value)
                    .where(
                        Measurement.run_id == run_id,
                        Measurement.metric_name == "latency_ms",
                    )
                    .order_by(Measurement.iteration)
                )
            )

            result = analyze_latencies(values)

        table = Table(title=f"Analysis: {run.name}")
        table.add_column("Statistic")
        table.add_column("Value", justify="right")

        rows = [
            ("Measurements", str(result["count"])),
            ("Minimum", f"{result['min_ms']:.4f} ms"),
            ("Mean", f"{result['mean_ms']:.4f} ms"),
            ("Median / p50", f"{result['p50_ms']:.4f} ms"),
            ("p95", f"{result['p95_ms']:.4f} ms"),
            ("p99", f"{result['p99_ms']:.4f} ms"),
            ("Maximum", f"{result['max_ms']:.4f} ms"),
            ("Std. deviation", f"{result['stddev_ms']:.4f} ms"),
            (
                "Coefficient of variation",
                f"{result['coefficient_of_variation_pct']:.2f}%",
            ),
        ]

        for label, value in rows:
            table.add_row(label, value)

        console.print(table)

    except Exception as exc:
        logger.error("Benchmark analysis failed: %s", exc)
        raise typer.Exit(code=1) from exc
    finally:
        if engine is not None:
            engine.dispose()


@app.command("compare")
def compare_command(
    baseline_run_id: str = typer.Argument(
        ...,
        help="ID of the baseline benchmark run.",
    ),
    candidate_run_id: str = typer.Argument(
        ...,
        help="ID of the newer benchmark run.",
    ),
    threshold_pct: float = typer.Option(
        10.0,
        "--threshold",
        min=0.0,
        max=99.99,
        help="Percentage change required to flag a regression.",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="DATABASE_URL",
        show_default=False,
    ),
) -> None:
    """Compare two completed benchmark runs."""
    engine = None

    try:
        url = database_url or get_database_url()
        engine = create_engine_for_url(url)

        with Session(engine) as session:
            baseline_run = session.get(BenchmarkRun, baseline_run_id)
            candidate_run = session.get(BenchmarkRun, candidate_run_id)

            if baseline_run is None or candidate_run is None:
                raise ValueError("Baseline or candidate run was not found.")

            for run in (baseline_run, candidate_run):
                if run.status != "completed":
                    raise ValueError(f"Run '{run.name}' must be completed before comparison.")

            baseline_workload = baseline_run.environment.get("workload")
            candidate_workload = candidate_run.environment.get("workload")

            if baseline_workload != candidate_workload:
                raise ValueError("Runs use different workloads and cannot be compared.")

            def read_latencies(run_id: str) -> list[float]:
                return list(
                    session.scalars(
                        select(Measurement.value)
                        .where(
                            Measurement.run_id == run_id,
                            Measurement.metric_name == "latency_ms",
                        )
                        .order_by(Measurement.iteration)
                    )
                )

            result = compare_runs(
                read_latencies(baseline_run_id),
                read_latencies(candidate_run_id),
                threshold_pct=threshold_pct,
            )

        change = result["change_pct"]
        change_text = "undefined (zero baseline)" if change is None else f"{change:+.2f}%"

        table = Table(title="PerfAtlas Regression Comparison")
        table.add_column("Metric")
        table.add_column("Result", justify="right")
        table.add_row("Baseline", baseline_run.name)
        table.add_row("Candidate", candidate_run.name)
        table.add_row(
            "Baseline median",
            f"{result['baseline_median_ms']:.4f} ms",
        )
        table.add_row(
            "Candidate median",
            f"{result['candidate_median_ms']:.4f} ms",
        )
        table.add_row("Median change", change_text)
        table.add_row("Threshold", f"{threshold_pct:.2f}%")
        table.add_row("Classification", result["status"].upper())

        console.print(table)

        if result["status"] in {"regression", "inconclusive"}:
            console.print("[yellow]Investigate this result before drawing conclusions.[/yellow]")

    except Exception as exc:
        logger.error("Benchmark comparison failed: %s", exc)
        raise typer.Exit(code=1) from exc
    finally:
        if engine is not None:
            engine.dispose()


@app.command("benchmark")
def benchmark_command(
    workload: str = typer.Option(
        "json",
        "--workload",
        help="Workload to run: json or cpu.",
    ),
    iterations: int = typer.Option(
        10,
        "--iterations",
        help="Number of measured iterations.",
    ),
    warmup: int = typer.Option(
        2,
        "--warmup",
        help="Number of warmup iterations.",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Optional name for this benchmark run.",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="DATABASE_URL",
        show_default=False,
        help="Database URL; defaults to DATABASE_URL.",
    ),
) -> None:
    """Execute a benchmark and save its measurements."""
    engine = None

    try:
        url = database_url or get_database_url()
        engine = create_engine_for_url(url)

        check_database_connection(engine)
        result = execute_benchmark(
            engine=engine,
            workload_name=workload,
            iterations=iterations,
            warmup=warmup,
            name=name,
        )

        table = Table(title="PerfAtlas Benchmark Results")
        table.add_column("Metric")
        table.add_column("Value", justify="right")

        table.add_row("Workload", result["workload"])
        table.add_row("Iterations", str(result["iterations"]))
        table.add_row("Warmups", str(result["warmup"]))
        table.add_row("Minimum latency", f"{result['min_ms']:.4f} ms")
        table.add_row("Median latency", f"{result['median_ms']:.4f} ms")
        table.add_row("Maximum latency", f"{result['max_ms']:.4f} ms")

        console.print(table)
        console.print(f"[green]Run ID:[/green] {result['run_id']}")

    except Exception as exc:
        logger.error("Benchmark failed: %s", exc)
        raise typer.Exit(code=1) from exc

    finally:
        if engine is not None:
            engine.dispose()


@app.callback()
def main(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable debug logging.",
    ),
) -> None:
    """Initialize common CLI behavior."""
    # Load the default configuration's logging settings in a later phase.
    configure_logging("DEBUG" if verbose else "INFO")


@app.command()
def version() -> None:
    """Display the installed PerfAtlas version."""
    console.print(f"PerfAtlas {__version__}")


@app.command("validate-config")
def validate_config_command(
    config_path: Path = typer.Option(
        Path("config/default.yaml"),
        "--config",
        "-c",
        help="Path to the YAML configuration file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Validate a configuration file."""
    try:
        config = load_config(config_path)
    except Exception as exc:
        logger.error("Configuration validation failed: %s", exc)
        raise typer.Exit(code=1) from exc

    table = Table(title="PerfAtlas Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Project", config.project.name)
    table.add_row("Version", config.project.version)
    table.add_row("Warm-up iterations", str(config.benchmark.warmup_iterations))
    table.add_row("Measured iterations", str(config.benchmark.measured_iterations))
    table.add_row("Concurrency", str(config.benchmark.concurrency))
    table.add_row("Timeout (seconds)", str(config.benchmark.timeout_seconds))
    table.add_row("Percentiles", str(config.metrics.percentiles))
    table.add_row(
        "Regression threshold (%)",
        str(config.metrics.regression_threshold_percent),
    )

    console.print(table)
    console.print("[green]Configuration is valid.[/green]")


@app.command()
def manifest(
    config_path: Path = typer.Option(
        Path("config/default.yaml"),
        "--config",
        "-c",
        help="Configuration file to record.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    output_path: Path = typer.Option(
        Path("runs/latest/manifest.json"),
        "--output",
        "-o",
        help="Destination JSON file.",
    ),
) -> None:
    """Create a reproducibility manifest."""
    try:
        # Validate the configuration before recording the experiment.
        load_config(config_path)
        result = build_manifest(config_path, cwd=Path.cwd())
        destination = write_manifest(result, output_path)
    except Exception as exc:
        logger.error("Could not create manifest: %s", exc)
        raise typer.Exit(code=1) from exc

    console.print(f"[green]Manifest written:[/green] {destination}")
    console.print_json(json.dumps(result, indent=2))


@app.command("init-db")
def init_database_command(
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Database URL. Defaults to the DATABASE_URL environment variable.",
        envvar="DATABASE_URL",
        show_default=False,
    ),
) -> None:
    """Initialize the database schema and verify connectivity."""
    engine = None

    try:
        url = database_url or get_database_url()
        engine = create_engine_for_url(url)
        check_database_connection(engine)
        initialize_database(engine)
        check_database_connection(engine)
    except Exception as exc:
        logger.error("Database initialization failed: %s", exc)
        raise typer.Exit(code=1) from exc
    else:
        console.print("[green]Database initialized successfully.[/green]")
        console.print("[green]Connection check passed.[/green]")
    finally:
        if engine is not None:
            engine.dispose()


@app.command("history")
def history_command(
    limit: int = typer.Option(
        10,
        "--limit",
        min=1,
        help="Maximum number of recent benchmark runs to display.",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="DATABASE_URL",
        show_default=False,
    ),
) -> None:
    """List recent benchmark runs."""
    engine = None

    try:
        url = database_url or get_database_url()
        engine = create_engine_for_url(url)
        runs = list_runs(engine, limit=limit)

        if not runs:
            console.print("[yellow]No benchmark runs found.[/yellow]")
            return

        table = Table(title="PerfAtlas Benchmark History")
        table.add_column("Run ID", overflow="fold")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Started At")
        table.add_column("Workload")

        for run in runs:
            table.add_row(
                str(run.get("run_id", "")),
                str(run.get("name", "")),
                str(run.get("status", "")),
                str(run.get("started_at") or "-"),
                str(run.get("workload") or "-"),
            )

        console.print(table)

    except Exception as exc:
        logger.error("Could not retrieve benchmark history: %s", exc)
        raise typer.Exit(code=1) from exc
    finally:
        if engine is not None:
            engine.dispose()


@app.command("show")
def show_command(
    run_id: str = typer.Argument(
        ...,
        help="ID of the benchmark run to inspect.",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="DATABASE_URL",
        show_default=False,
    ),
) -> None:
    """Show details and measurements for a benchmark run."""
    engine = None

    try:
        url = database_url or get_database_url()
        engine = create_engine_for_url(url)
        details = get_run_details(engine, run_id)

        console.print(f"[bold]Run:[/bold] {details['name']}")
        console.print(f"[bold]Run ID:[/bold] {details['run_id']}")
        console.print(f"[bold]Status:[/bold] {details['status']}")
        console.print(f"[bold]Started:[/bold] {details.get('started_at') or '-'}")
        console.print(f"[bold]Finished:[/bold] {details.get('finished_at') or '-'}")
        console.print(f"[bold]Git commit:[/bold] {details.get('git_commit') or '-'}")
        console.print(f"[bold]Config SHA-256:[/bold] {details.get('config_sha256') or '-'}")

        environment = details.get("environment") or {}
        console.print("\n[bold]Environment metadata[/bold]")
        console.print_json(json.dumps(environment, indent=2, default=str))

        measurements = details.get("measurements") or []
        if measurements:
            table = Table(title="Measurements")
            table.add_column("Iteration", justify="right")
            table.add_column("Metric")
            table.add_column("Value", justify="right")
            table.add_column("Unit")

            for measurement in measurements:
                table.add_row(
                    str(measurement.get("iteration", "")),
                    str(measurement.get("metric_name", "")),
                    str(measurement.get("value", "")),
                    str(measurement.get("unit", "")),
                )

            console.print(table)
        else:
            console.print("[yellow]No measurements recorded for this run.[/yellow]")

    except Exception as exc:
        logger.error("Could not retrieve benchmark details: %s", exc)
        raise typer.Exit(code=1) from exc
    finally:
        if engine is not None:
            engine.dispose()


@app.command("gate")
def gate_command(
    baseline_run_id: str = typer.Option(
        ...,
        "--baseline",
        help="ID of the baseline benchmark run.",
    ),
    candidate_run_id: str = typer.Option(
        ...,
        "--candidate",
        help="ID of the candidate benchmark run.",
    ),
    threshold_pct: float = typer.Option(
        10.0,
        "--threshold",
        min=0.0,
        max=99.99,
        help="Maximum tolerated median-latency regression percentage.",
    ),
    output_path: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Optional path for the JSON regression-gate report.",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="DATABASE_URL",
        show_default=False,
        help="Database URL; defaults to DATABASE_URL.",
    ),
) -> None:
    """Compare benchmark runs and return a CI-friendly pass/fail result."""
    engine = None

    try:
        url = database_url or get_database_url()
        engine = create_engine_for_url(url)

        report = run_regression_gate(
            engine=engine,
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            threshold_pct=threshold_pct,
            output_path=output_path,
        )

        change = report["change_pct"]
        change_text = "undefined (zero baseline)" if change is None else f"{change:+.2f}%"

        table = Table(title="PerfAtlas Regression Gate")
        table.add_column("Metric")
        table.add_column("Result", justify="right")

        table.add_row("Baseline", report["baseline"]["name"])
        table.add_row("Candidate", report["candidate"]["name"])
        table.add_row("Workload", report["candidate"]["workload"])
        table.add_row(
            "Baseline median",
            f"{report['baseline_median_ms']:.4f} ms",
        )
        table.add_row(
            "Candidate median",
            f"{report['candidate_median_ms']:.4f} ms",
        )
        table.add_row("Median change", change_text)
        table.add_row("Threshold", f"{threshold_pct:.2f}%")
        table.add_row("Classification", report["status"].upper())
        table.add_row("Gate result", "PASS" if report["passed"] else "FAIL")

        console.print(table)

        if output_path is not None:
            console.print(f"JSON report: {output_path}")

        if not report["passed"]:
            raise typer.Exit(code=1)

    except typer.Exit:
        raise
    except Exception as exc:
        logger.error("Regression gate failed: %s", exc)
        raise typer.Exit(code=1) from exc
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    app()
