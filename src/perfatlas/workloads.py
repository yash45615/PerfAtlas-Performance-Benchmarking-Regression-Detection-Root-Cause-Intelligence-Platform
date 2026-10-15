"""Lightweight, deterministic workloads for PerfAtlas benchmarks."""

import json
import os
import time


def json_roundtrip() -> int:
    """Serialize and deserialize a representative application payload."""
    payload = {
        "request_id": "req-0001",
        "user": {"id": 42, "active": True},
        "items": [{"sku": f"SKU-{i:04d}", "quantity": i % 5 + 1} for i in range(100)],
        "metadata": {"source": "perfatlas", "version": 1},
    }

    encoded = json.dumps(payload, separators=(",", ":"))
    decoded = json.loads(encoded)

    # Test-only fault injection for the regression-detection lab.
    # Normal runs have no artificial delay.
    delay_ms = float(os.getenv("PERFATLAS_INJECT_REGRESSION_MS", "0"))
    if delay_ms > 0:
        time.sleep(delay_ms / 1000)

    return len(decoded["items"])


def cpu_checksum() -> int:
    """Run a small, repeatable CPU-bound integer workload."""
    checksum = 0

    for number in range(1, 10_001):
        checksum = (checksum + number * number) % 1_000_000_007

    return checksum


WORKLOADS = {
    "json": json_roundtrip,
    "cpu": cpu_checksum,
}


def get_workload(name: str):
    """Return a registered workload or raise a helpful error."""
    try:
        return WORKLOADS[name]
    except KeyError as exc:
        available = ", ".join(sorted(WORKLOADS))
        raise ValueError(f"Unknown workload '{name}'. Available workloads: {available}") from exc
