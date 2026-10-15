"""SQLAlchemy models for benchmark runs and measurements."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from perfatlas.db import Base


def utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


class BenchmarkRun(Base):
    """Metadata and outcome for one benchmark experiment."""

    __tablename__ = "benchmark_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'running', 'completed', 'failed', 'inconclusive')",
            name="ck_benchmark_runs_status",
        ),
        Index("ix_benchmark_runs_started_at", "started_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="created",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    environment: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    measurements: Mapped[list["Measurement"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Measurement(Base):
    """One measured metric value associated with a benchmark run."""

    __tablename__ = "measurements"
    __table_args__ = (
        CheckConstraint("iteration >= 0", name="ck_measurements_iteration"),
        CheckConstraint("value >= 0", name="ck_measurements_value"),
        UniqueConstraint(
            "run_id",
            "metric_name",
            "iteration",
            name="uq_measurements_run_metric_iteration",
        ),
        Index("ix_measurements_run_metric", "run_id", "metric_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("benchmark_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    run: Mapped[BenchmarkRun] = relationship(back_populates="measurements")
