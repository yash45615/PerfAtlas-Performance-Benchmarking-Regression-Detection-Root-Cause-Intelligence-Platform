"""Capture metadata needed to reproduce a performance experiment."""

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from perfatlas import __version__

ENVIRONMENT_KEYS = (
    "python_version",
    "implementation",
    "platform",
    "machine",
    "processor",
    "cpu_count",
)


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()

    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(65_536), b""):
            digest.update(chunk)

    return digest.hexdigest()


def get_git_commit(cwd: str | Path | None = None) -> str | None:
    """Return the current Git commit, or None outside a Git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def fingerprint_environment(environment: dict) -> str | None:
    """Return a deterministic SHA-256 fingerprint for environment metadata."""
    relevant = {
        key: environment.get(key)
        for key in ENVIRONMENT_KEYS
        if environment.get(key) is not None and environment.get(key) != ""
    }

    if not relevant:
        return None

    canonical = json.dumps(
        relevant,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compare_environment_manifests(
    baseline_manifest: dict,
    candidate_manifest: dict,
) -> dict:
    """Compare environment metadata from two benchmark manifests."""
    baseline_env = baseline_manifest.get("environment") or {}
    candidate_env = candidate_manifest.get("environment") or {}

    if not isinstance(baseline_env, dict):
        baseline_env = {}
    if not isinstance(candidate_env, dict):
        candidate_env = {}

    baseline_fingerprint = baseline_manifest.get(
        "environment_fingerprint"
    ) or fingerprint_environment(baseline_env)
    candidate_fingerprint = candidate_manifest.get(
        "environment_fingerprint"
    ) or fingerprint_environment(candidate_env)

    differences = []
    missing_fields = []

    for key in ENVIRONMENT_KEYS:
        baseline_value = baseline_env.get(key)
        candidate_value = candidate_env.get(key)

        if baseline_value is None or candidate_value is None:
            missing_fields.append(key)
        elif baseline_value != candidate_value:
            differences.append(
                {
                    "field": key,
                    "baseline": baseline_value,
                    "candidate": candidate_value,
                }
            )

    if differences:
        status = "mismatch"
    elif baseline_fingerprint is None or candidate_fingerprint is None or missing_fields:
        status = "unknown"
    else:
        status = "match"

    warnings = []

    if differences:
        warnings.append(
            "Benchmark environments differ; interpret performance comparisons with caution."
        )

    if status == "unknown":
        warnings.append(
            "Environment metadata is incomplete; compatibility could not be fully verified."
        )

    return {
        "status": status,
        "compatible": status == "match",
        "baseline_fingerprint": baseline_fingerprint,
        "candidate_fingerprint": candidate_fingerprint,
        "differences": differences,
        "missing_fields": missing_fields,
        "warnings": warnings,
    }


def build_manifest(
    config_path: str | Path,
    cwd: str | Path | None = None,
) -> dict:
    """Build a JSON-serializable record describing a benchmark environment."""
    config_file = Path(config_path).resolve()

    if not config_file.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_file}")

    environment = {
        "python_version": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
    }

    return {
        "run_id": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "tool": {
            "name": "PerfAtlas",
            "version": __version__,
        },
        "source": {
            "git_commit": get_git_commit(cwd),
        },
        "environment": environment,
        "environment_fingerprint": fingerprint_environment(environment),
        "configuration": {
            "path": str(config_file),
            "sha256": sha256_file(config_file),
        },
    }


def write_manifest(
    manifest: dict,
    output_path: str | Path,
) -> Path:
    """Write a manifest atomically so partial JSON is not left behind."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary = destination.with_suffix(destination.suffix + ".tmp")

    try:
        temporary.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    return destination
