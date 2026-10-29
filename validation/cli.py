"""
CLI for running Tableau vs reference validation checks.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer

from admin.logging_setup import setup_logging
from .config import load_validation_config
from .dashboards import fetch_view_data
from .reference_sources import load_reference_source
from .comparator import compare_metrics
from .alerts import notify_email, notify_slack

logger = logging.getLogger(__name__)

app = typer.Typer(help="Run validation jobs against Tableau dashboards.")


@app.callback()
def _init():
    """Initialize logging before any command runs."""
    setup_logging()


@app.command()
def compare(
    view_id: str,
    reference_sql_file: Path,
    metric: Optional[str] = typer.Option(None, help="Metric column to compare"),
    alert: bool = typer.Option(True, help="Send alert when discrepancy exceeds threshold"),
):
    """Compare a Tableau view vs SQL reference file."""
    cfg = load_validation_config()
    tableau_df = fetch_view_data(view_id)
    sql = reference_sql_file.read_text(encoding="utf-8")
    reference_df = load_reference_source().query(sql)
    result = compare_metrics(tableau_df, reference_df, metric or cfg.compare_metric)
    typer.echo(json.dumps(result.__dict__, indent=2))
    if alert and not result.within_threshold:
        message = (
            f"Discrepancy detected for {result.metric}: Tableau={result.tableau_value}, "
            f"Reference={result.reference_value}, \u0394%={result.difference_pct:.2f}"
        )
        try:
            notify_slack(message)
        except Exception as exc:
            logger.warning("Slack notification failed: %s", exc)
        notify_email(subject="Tableau validation discrepancy", body=message)


@app.command()
def snapshot_view(view_id: str, out_csv: Path):
    """Save Tableau view data to CSV for ad-hoc validation."""
    df = fetch_view_data(view_id)
    df.to_csv(out_csv, index=False)
    logger.info("Saved %d rows to %s", len(df), out_csv)


if __name__ == "__main__":
    app()
