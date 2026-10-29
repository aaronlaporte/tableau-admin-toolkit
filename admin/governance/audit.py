"""
Governance & audit utilities for Tableau content.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..session import authenticated_session

logger = logging.getLogger(__name__)


def list_stale_workbooks(threshold_days: int = 30) -> list[dict]:
    """
    Fetch workbooks not viewed within the threshold.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)
    with authenticated_session() as conn:
        resp = conn.query_workbooks_on_site()
        workbooks = _extract_workbooks(resp.json())

    stale = []
    for workbook in workbooks:
        last_view = workbook.get("lastViewedAt")
        parsed = _parse_timestamp(last_view)
        if parsed is None or parsed < cutoff:
            stale.append(workbook)
    logger.info("Found %d stale workbooks (threshold=%d days)", len(stale), threshold_days)
    return stale


def collect_failed_jobs(limit: int = 50) -> list[dict]:
    """
    Pull recent failed jobs for alerting/reporting.
    """
    with authenticated_session() as conn:
        resp = conn.query_jobs()
        jobs_data = resp.json().get("backgroundJobs", {})
        jobs = jobs_data.get("backgroundJob", []) if isinstance(jobs_data, dict) else jobs_data
    failed = [job for job in jobs if int(job.get("finishCode", 0)) != 0]
    logger.info("Collected %d failed jobs (limit=%d)", len(failed[:limit]), limit)
    return failed[:limit]


def summarize_permissions(project_ids: Iterable[str]) -> dict[str, list[dict]]:
    """
    Build a dictionary of permissions per project.
    """
    summary: dict[str, list[dict]] = {}
    with authenticated_session() as conn:
        for project_id in project_ids:
            resp = conn.query_project_permissions(project_id=project_id)
            summary[project_id] = resp.json().get("granteeCapabilities", [])
    logger.debug("Summarized permissions for %d projects", len(summary))
    return summary


def _extract_workbooks(payload: dict) -> list[dict]:
    workbooks = payload.get("workbooks", [])
    if isinstance(workbooks, dict):
        return workbooks.get("workbook", []) or []
    return workbooks


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """
    Tableau returns ISO 8601 timestamps; normalize variations into aware datetimes.
    """
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
