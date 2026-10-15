"""Integration tests for the PerfAtlas regression-gate CLI command."""

from typer.testing import CliRunner

from perfatlas import cli

runner = CliRunner()


class FakeEngine:
    """Minimal engine substitute for CLI tests."""

    def dispose(self) -> None:
        """Simulate closing the database engine."""


def make_report(passed: bool) -> dict:
    """Return a deterministic regression-gate report."""
    return {
        "passed": passed,
        "status": "no_regression" if passed else "regression",
        "baseline": {
            "run_id": "baseline-id",
            "name": "baseline-run",
            "workload": "json",
        },
        "candidate": {
            "run_id": "candidate-id",
            "name": "candidate-run",
            "workload": "json",
        },
        "threshold_pct": 10.0,
        "change_pct": 5.0 if passed else 20.0,
        "baseline_median_ms": 10.0,
        "candidate_median_ms": 10.5 if passed else 12.0,
        "comparison": {},
    }


def configure_cli(monkeypatch, passed: bool) -> None:
    """Replace database and gate dependencies with deterministic fakes."""
    monkeypatch.setattr(
        cli,
        "get_database_url",
        lambda: "sqlite://",
    )
    monkeypatch.setattr(
        cli,
        "create_engine_for_url",
        lambda url: FakeEngine(),
    )
    monkeypatch.setattr(
        cli,
        "run_regression_gate",
        lambda **kwargs: make_report(passed),
    )


def test_gate_cli_returns_zero_when_gate_passes(monkeypatch):
    configure_cli(monkeypatch, passed=True)

    result = runner.invoke(
        cli.app,
        [
            "gate",
            "--baseline",
            "baseline-id",
            "--candidate",
            "candidate-id",
            "--threshold",
            "10",
        ],
    )

    assert result.exit_code == 0
    assert "PASS" in result.output
    assert "NO_REGRESSION" in result.output


def test_gate_cli_returns_one_when_gate_fails(monkeypatch):
    configure_cli(monkeypatch, passed=False)

    result = runner.invoke(
        cli.app,
        [
            "gate",
            "--baseline",
            "baseline-id",
            "--candidate",
            "candidate-id",
            "--threshold",
            "10",
        ],
    )

    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "REGRESSION" in result.output
