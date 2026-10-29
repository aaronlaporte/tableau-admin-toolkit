"""
Compare Tableau metrics vs reference data.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import ValidationConfig, load_validation_config


@dataclass
class ComparisonResult:
    metric: str
    tableau_value: float
    reference_value: float
    difference: float
    difference_pct: float
    within_threshold: bool


def compare_metrics(tableau_df: pd.DataFrame, reference_df: pd.DataFrame, metric: str | None = None) -> ComparisonResult:
    """
    Compare a single metric aggregated from Tableau vs reference dataset.
    """
    cfg = load_validation_config()
    metric_name = metric or cfg.compare_metric
    tableau_value = float(tableau_df[metric_name].sum())
    reference_value = float(reference_df[metric_name].sum())
    diff = tableau_value - reference_value
    diff_pct = (diff / reference_value * 100) if reference_value else 0
    return ComparisonResult(
        metric=metric_name,
        tableau_value=tableau_value,
        reference_value=reference_value,
        difference=diff,
        difference_pct=diff_pct,
        within_threshold=abs(diff_pct) <= cfg.discrepancy_threshold_pct,
    )
