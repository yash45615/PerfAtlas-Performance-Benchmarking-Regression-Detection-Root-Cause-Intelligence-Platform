"""Tests for reproducibility manifest generation."""

import json

import pytest

from perfatlas.manifest import (
    build_manifest,
    compare_environment_manifests,
    fingerprint_environment,
    sha256_file,
    write_manifest,
)


def test_sha256_file(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello", encoding="utf-8")

    assert sha256_file(file_path) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_build_manifest_contains_environment(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project:\n  name: PerfAtlas\n", encoding="utf-8")

    result = build_manifest(config_path, cwd=tmp_path)

    assert result["tool"]["name"] == "PerfAtlas"
    assert result["run_id"]
    assert result["environment"]["python_version"]
    assert result["environment"]["platform"]
    assert len(result["configuration"]["sha256"]) == 64


def test_missing_config_rejected():
    with pytest.raises(FileNotFoundError):
        build_manifest("config/missing.yaml")


def test_write_manifest_creates_parent_directory(tmp_path):
    output_path = tmp_path / "nested" / "run" / "manifest.json"
    payload = {"run_id": "test-run", "status": "created"}

    returned_path = write_manifest(payload, output_path)

    assert returned_path == output_path
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_manifest_is_valid_json(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project:\n  name: PerfAtlas\n", encoding="utf-8")

    result = build_manifest(config_path, cwd=tmp_path)
    output_path = tmp_path / "manifest.json"
    write_manifest(result, output_path)

    parsed = json.loads(output_path.read_text(encoding="utf-8"))

    assert parsed["run_id"] == result["run_id"]
    assert parsed["configuration"]["sha256"] == (result["configuration"]["sha256"])


def test_environment_fingerprint_is_deterministic():
    environment = {
        "python_version": "3.11.2",
        "implementation": "CPython",
        "platform": "Windows-11",
        "machine": "AMD64",
        "processor": "Example CPU",
        "cpu_count": 8,
    }

    first = fingerprint_environment(environment)
    second = fingerprint_environment(dict(environment))

    assert first == second
    assert len(first) == 64


def test_environment_fingerprint_changes_when_environment_changes():
    baseline = {
        "python_version": "3.11.2",
        "implementation": "CPython",
        "platform": "Windows-11",
        "machine": "AMD64",
        "processor": "Example CPU",
        "cpu_count": 8,
    }
    candidate = {**baseline, "cpu_count": 16}

    assert fingerprint_environment(baseline) != fingerprint_environment(candidate)


def test_environment_fingerprint_handles_missing_metadata():
    assert fingerprint_environment({}) is None


def test_matching_environment_manifests():
    environment = {
        "python_version": "3.11.2",
        "implementation": "CPython",
        "platform": "Windows-11",
        "machine": "AMD64",
        "processor": "Example CPU",
        "cpu_count": 8,
    }
    baseline = {"environment": environment}
    candidate = {"environment": dict(environment)}

    result = compare_environment_manifests(baseline, candidate)

    assert result["status"] == "match"
    assert result["compatible"] is True
    assert result["differences"] == []
    assert result["baseline_fingerprint"] == result["candidate_fingerprint"]


def test_environment_mismatch_is_reported():
    baseline = {
        "environment": {
            "python_version": "3.11.2",
            "implementation": "CPython",
            "platform": "Windows-11",
            "machine": "AMD64",
            "processor": "Example CPU",
            "cpu_count": 8,
        }
    }
    candidate = {
        "environment": {
            **baseline["environment"],
            "cpu_count": 16,
        }
    }

    result = compare_environment_manifests(baseline, candidate)

    assert result["status"] == "mismatch"
    assert result["compatible"] is False
    assert any(difference["field"] == "cpu_count" for difference in result["differences"])
    assert result["warnings"]


def test_environment_comparison_handles_missing_fields():
    result = compare_environment_manifests(
        {"environment": {}},
        {"environment": {}},
    )

    assert result["status"] == "unknown"
    assert result["compatible"] is False
    assert result["warnings"]
