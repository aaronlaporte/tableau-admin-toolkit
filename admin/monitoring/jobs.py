"""
Job monitoring utilities: background tasks, extracts, flows.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from ..session import authenticated_session

logger = logging.getLogger(__name__)


@dataclass
class JobStatus:
    job_id: str
    status: str
    started: Optional[datetime]
    ended: Optional[datetime]
    notes: Optional[str] = None


def list_recent_jobs(limit: int = 25) -> List[JobStatus]:
    """
    Return a friendly list of recent Tableau jobs.
    """
    with authenticated_session() as conn:
        resp = conn.query_jobs()
        jobs_data = resp.json().get("backgroundJobs", {})
        all_jobs = jobs_data.get("backgroundJob", []) if isinstance(jobs_data, dict) else jobs_data
        jobs = all_jobs[:limit]

    statuses = []
    for job in jobs:
        statuses.append(
            JobStatus(
                job_id=job.get("id"),
                status=job.get("status"),
                started=_parse_dt(job.get("startedAt")),
                ended=_parse_dt(job.get("completedAt") or job.get("endedAt")),
                notes=job.get("notes"),
            )
        )
    logger.debug("Retrieved %d recent jobs", len(statuses))
    return statuses


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
