"""Benchmark execution, measurement persistence, and reproducibility manifests."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from perfatlas.manifest import build_manifest, write_manifest
from perfatlas.models import BenchmarkRun, Measurement
from perfatlas.workloads import get_workload


def execute_benchmark(
    engine: Engine,
    workload_name: str = "json",
    iterations: int = 10,
    warmup: int = 2,
    name: str | None = None,
) -> dict:
    """Run a workload, persist measurements, and write a JSON manifest."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1.")
    if warmup < 0:
        raise ValueError("warmup must be zero or greater.")

    workload = get_workload(workload_name)
    run_name = name or f"{workload_name}-{uuid4().hex[:8]}"
    latencies_ms: list[float] = []

    with Session(engine) as session:
        run = BenchmarkRun(
            name=run_name,
            status="running",
            environment={},
        )
        session.add(run)
        session.flush()

        run_id = run.id

        try:
            # Capture the configuration and machine environment.
            config_path = Path("config/default.yaml")
            manifest = build_manifest(config_path=config_path)

            # Calculate the configuration hash explicitly.
            manifest["config_sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()

            manifest["run_id"] = run_id
            manifest["run_name"] = run_name
            manifest["workload"] = workload_name
            manifest["iterations"] = iterations
            manifest["warmup"] = warmup

            manifest_path = Path("reports") / "manifests" / f"{run_id}.json"
            write_manifest(manifest, manifest_path)

            run.git_commit = manifest.get("source", {}).get("git_commit")
            run.config_sha256 = manifest.get("config_sha256")
            run.environment = manifest

            session.commit()

            # Warmups are executed but intentionally not recorded.
            for _ in range(warmup):
                workload()

            # Record each measured invocation.
            for iteration in range(iterations):
                started_ns = perf_counter_ns()
                workload()
                finished_ns = perf_counter_ns()

                latency_ms = (finished_ns - started_ns) / 1_000_000
                latencies_ms.append(latency_ms)

                session.add(
                    Measurement(
                        run_id=run_id,
                        metric_name="latency_ms",
                        value=latency_ms,
                        unit="ms",
                        iteration=iteration,
                    )
                )

            run.status = "completed"
            run.finished_at = datetime.now(UTC)
            session.commit()

        except Exception:
            session.rollback()

            # Preserve the failed status in a separate transaction.
            failed_run = session.get(BenchmarkRun, run_id)

            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.finished_at = datetime.now(UTC)
                session.commit()

            raise

    return {
        "run_id": run_id,
        "name": run_name,
        "workload": workload_name,
        "iterations": iterations,
        "warmup": warmup,
        "min_ms": min(latencies_ms),
        "median_ms": median(latencies_ms),
        "max_ms": max(latencies_ms),
        "latencies_ms": latencies_ms,
    }
