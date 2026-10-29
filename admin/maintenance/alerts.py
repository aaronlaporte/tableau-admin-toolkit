"""
Extract refresh alerting: detect failed extract jobs and notify via Slack/email.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..governance.audit import collect_failed_jobs

logger = logging.getLogger(__name__)


def check_and_alert_failed_extracts(
    lookback_minutes: int = 60,
    notify_slack: bool = True,
    notify_email: bool = True,
) -> list[dict]:
    """
    Poll recent jobs, filter for failed extract refreshes within the
    lookback window, and send alerts via configured channels.

    Returns the list of failed jobs that were alerted on.
    """
    from validation.alerts.notifier import notify_slack as _slack, notify_email as _email

    failed_jobs = collect_failed_jobs(limit=100)

    # Filter to extract-type jobs within the lookback window
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    extract_failures = []
    for job in failed_jobs:
        job_type = job.get("type", "").lower()
        if "extract" not in job_type and "refresh" not in job_type:
            continue
        # Check timestamp
        ended = job.get("completedAt") or job.get("endedAt")
        if ended:
            try:
                ended_dt = datetime.fromisoformat(ended.replace("Z", "+00:00"))
                if ended_dt < cutoff:
                    continue
            except ValueError:
                pass
        extract_failures.append(job)

    if not extract_failures:
        logger.info("No failed extract jobs in the last %d minutes", lookback_minutes)
        return []

    logger.warning("Found %d failed extract jobs", len(extract_failures))

    # Build alert message
    lines = [f"** {len(extract_failures)} extract refresh(es) failed in the last {lookback_minutes} min **\n"]
    for job in extract_failures:
        name = job.get("extractRefreshJob", {}).get("datasource", {}).get("name", "unknown")
        job_id = job.get("id", "?")
        notes = job.get("notes", "")
        lines.append(f"- {name} (job {job_id}): {notes}")
    message = "\n".join(lines)

    if notify_slack:
        try:
            _slack(message)
        except Exception as exc:
            logger.warning("Slack alert failed: %s", exc)

    if notify_email:
        try:
            _email(
                subject=f"Tableau: {len(extract_failures)} extract refresh failure(s)",
                body=message,
            )
        except Exception as exc:
            logger.warning("Email alert failed: %s", exc)

    return extract_failures
