"""Tests for configuration loading and validation."""

import pytest
import yaml
from pydantic import ValidationError

from perfatlas.config import AppConfig, load_config


def test_load_default_configuration():
    config = load_config("config/default.yaml")

    assert config.project.name == "PerfAtlas"
    assert config.benchmark.warmup_iterations == 5
    assert config.benchmark.measured_iterations == 30
    assert config.benchmark.concurrency == 4
    assert config.metrics.percentiles == [50, 90, 95, 99]


def test_reject_negative_iterations():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"benchmark": {"measured_iterations": -1}})


def test_reject_unknown_configuration_key():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"benchmak": {}})


def test_reject_invalid_percentile():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"metrics": {"percentiles": [50, 100]}})


def test_reject_duplicate_percentiles():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"metrics": {"percentiles": [50, 50]}})


def test_missing_config_file():
    with pytest.raises(FileNotFoundError):
        load_config("config/does-not-exist.yaml")


def test_reject_non_mapping_yaml(tmp_path):
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        yaml.safe_dump(["not", "a", "mapping"]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="YAML mapping"):
        load_config(config_path)


def test_reject_empty_yaml(tmp_path):
    config_path = tmp_path / "empty.yaml"
    config_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="YAML mapping"):
        load_config(config_path)
