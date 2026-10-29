"""
Helpers for querying Tableau views/dashboards.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from admin.session import authenticated_session

logger = logging.getLogger(__name__)


def fetch_view_data(view_id: str, parameter_map: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """
    Download view data as a pandas DataFrame, optionally applying parameter filters.
    """
    with authenticated_session() as conn:
        resp = conn.views.get_view_data(view_id=view_id, parameter_dict=parameter_map or {})
        df = pd.DataFrame(resp.json().get("data", []))
        logger.debug("Fetched %d rows from view %s", len(df), view_id)
        return df


def summarize_view_metrics(view_id: str, metric_column: str) -> float:
    """
    Fetch a simple aggregate from a view (sum of a target column).
    """
    df = fetch_view_data(view_id)
    if metric_column not in df.columns:
        raise KeyError(f"Column {metric_column} not found in view data.")
    return float(df[metric_column].sum())
