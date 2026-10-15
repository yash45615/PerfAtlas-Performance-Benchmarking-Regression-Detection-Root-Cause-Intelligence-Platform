"""Validated configuration loading for PerfAtlas."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject unknown configuration keys to catch spelling mistakes."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ProjectConfig(StrictModel):
    name: str = "PerfAtlas"
    version: str = "0.1.0"


class BenchmarkConfig(StrictModel):
    warmup_iterations: int = Field(default=5, ge=0, le=100_000)
    measured_iterations: int = Field(default=30, ge=2, le=1_000_000)
    concurrency: int = Field(default=4, ge=1, le=100_000)
    timeout_seconds: float = Field(default=10.0, gt=0, le=86_400)


class MetricsConfig(StrictModel):
    percentiles: list[int] = Field(default_factory=lambda: [50, 90, 95, 99])
    regression_threshold_percent: float = Field(default=10.0, ge=0, le=1_000)
    max_coefficient_of_variation: float = Field(default=0.10, ge=0, le=10)

    @model_validator(mode="after")
    def validate_percentiles(self):
        if not self.percentiles:
            raise ValueError("At least one percentile must be configured.")

        if any(p < 1 or p > 99 for p in self.percentiles):
            raise ValueError("Percentiles must be between 1 and 99.")

        if len(set(self.percentiles)) != len(self.percentiles):
            raise ValueError("Percentiles must not contain duplicates.")

        return self


class StorageConfig(StrictModel):
    output_directory: str = "runs"
    report_directory: str = "reports"


class LoggingConfig(StrictModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    json_output: bool = Field(default=False, alias="json")


class AppConfig(StrictModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_config(path: str | Path) -> AppConfig:
    """Load YAML configuration and validate every configured field."""
    config_path = Path(path)

    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        raw_config = yaml.safe_load(file)

    if not isinstance(raw_config, dict):
        raise ValueError("Configuration must contain a YAML mapping.")

    return AppConfig.model_validate(raw_config)
