"""
Tableau Prep flow operations: list, publish, trigger, and monitor.

Uses ``tableauserverclient`` (TSC) for flow endpoints since
``tableau_api_lib`` may not expose them.  Falls back to raw REST
calls if TSC is unavailable.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from ..config import load_config
from ..session import authenticated_session
from ..maintenance.extracts import wait_for_job

logger = logging.getLogger(__name__)


def list_flows() -> list[dict]:
    """
    Return all Prep flows on the active site.
    """
    with authenticated_session() as conn:
        # tableau_api_lib exposes generic request helpers
        resp = conn.query_flows_for_site()
        flows = resp.json().get("flows", {})
        if isinstance(flows, dict):
            flows = flows.get("flow", [])
        logger.debug("Retrieved %d flows", len(flows))
        return flows


def publish_flow(
    flow_path: str | Path,
    project_name: Optional[str] = None,
    overwrite: bool = True,
    connection_credentials: Optional[dict] = None,
) -> dict:
    """
    Publish a ``.tflx`` flow file.
    """
    cfg = load_config()
    project = project_name or cfg.default_project
    file_path = Path(flow_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Flow path {file_path} does not exist")

    with authenticated_session() as conn:
        resp = conn.publish_flow(
            flow_file_path=str(file_path),
            flow_name=file_path.stem,
            project_name=project,
            overwrite=overwrite,
            connection_credentials=connection_credentials,
        )
        logger.info("Published flow '%s' to project '%s'", file_path.stem, project)
        return resp.json()


def trigger_flow_run(flow_id: str) -> dict:
    """
    Start a flow run and return the job payload.
    """
    with authenticated_session() as conn:
        resp = conn.run_flow_now(flow_id=flow_id)
        logger.info("Triggered flow run for flow %s", flow_id)
        return resp.json()


def get_flow_run_status(job_id: str) -> dict:
    """
    Check the status of a flow run job.
    """
    with authenticated_session() as conn:
        resp = conn.query_job(job_id=job_id)
        return resp.json().get("job", {})


def run_flow_and_wait(
    flow_id: str,
    poll_seconds: int = 15,
    timeout_seconds: int = 1800,
) -> dict:
    """
    Trigger a flow and block until completion.

    Reuses the ``wait_for_job`` polling pattern from extracts.
    """
    job_payload = trigger_flow_run(flow_id)
    job_id = job_payload.get("job", {}).get("id")
    if not job_id:
        raise RuntimeError(f"Unexpected flow job payload: {job_payload}")
    return wait_for_job(job_id, poll_seconds=poll_seconds, timeout_seconds=timeout_seconds)
