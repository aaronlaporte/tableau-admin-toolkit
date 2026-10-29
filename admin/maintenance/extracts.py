"""
Extract orchestration utilities.
"""
from __future__ import annotations

import logging
import time

from ..session import authenticated_session

logger = logging.getLogger(__name__)


def trigger_extract_refresh(datasource_id: str) -> dict:
    """
    Start an extract refresh task.
    """
    with authenticated_session() as conn:
        resp = conn.refresh_data_source(datasource_id=datasource_id)
        logger.info("Triggered extract refresh for datasource %s", datasource_id)
        return resp.json()


def wait_for_job(job_id: str, poll_seconds: int = 10, timeout_seconds: int = 900) -> dict:
    """
    Poll the Tableau backgrounders for a job until it completes.
    """
    start_time = time.time()
    with authenticated_session() as conn:
        while True:
            job = conn.query_job(job_id=job_id).json().get("job")
            finish_code = job.get("finishCode")
            if finish_code is not None and int(finish_code) != -1:
                logger.info("Job %s finished (finishCode=%s)", job_id, finish_code)
                return job
            elapsed = int(time.time() - start_time)
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Job {job_id} did not finish within {timeout_seconds} seconds.")
            logger.debug("Job %s still running (%ds elapsed), polling in %ds", job_id, elapsed, poll_seconds)
            time.sleep(poll_seconds)


def refresh_and_wait(datasource_id: str, alert_on_failure: bool = True) -> dict:
    """
    Convenience helper that triggers a refresh and blocks until the job finishes.

    When *alert_on_failure* is True and the job fails (finishCode != 0),
    sends Slack/email alerts if configured.
    """
    job_payload = trigger_extract_refresh(datasource_id)
    job_id = job_payload.get("job", {}).get("id")
    if not job_id:
        raise RuntimeError(f"Unexpected job payload: {job_payload}")
    job = wait_for_job(job_id)

    finish_code = int(job.get("finishCode", 0))
    if finish_code != 0 and alert_on_failure:
        _alert_on_failure(job, datasource_id)

    return job


def _alert_on_failure(job: dict, datasource_id: str) -> None:
    """Send alerts for a failed extract refresh job."""
    try:
        from validation.alerts.notifier import notify_slack, notify_email

        message = (
            f"Extract refresh FAILED for datasource {datasource_id}\n"
            f"Job ID: {job.get('id')}\n"
            f"Notes: {job.get('notes', 'N/A')}"
        )
        try:
            notify_slack(message)
        except Exception:
            pass
        try:
            notify_email(subject="Tableau: extract refresh failure", body=message)
        except Exception:
            pass
    except ImportError:
        logger.warning("Validation alerts module not available; skipping failure notification")
