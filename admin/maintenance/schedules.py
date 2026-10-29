"""
Schedule management.
"""
from __future__ import annotations

import logging
from datetime import time
from typing import Optional

from ..config import load_config
from ..session import authenticated_session

logger = logging.getLogger(__name__)


def list_schedules() -> list[dict]:
    """
    Retrieve available schedules from Tableau Server.

    Returns an empty list on Tableau Cloud where the ``/schedules``
    endpoint does not exist.
    """
    cfg = load_config()
    if cfg.is_cloud:
        logger.warning("Schedule listing is not supported on Tableau Cloud; skipping.")
        return []

    with authenticated_session() as conn:
        resp = conn.query_schedules()
        return resp.json().get("schedules", [])


def create_extract_schedule(
    name: str,
    frequency: str,
    priority: int = 50,
    start_time: Optional[time] = None,
) -> dict:
    """
    Create an extract refresh schedule (e.g., daily at 1am).

    Raises ``NotImplementedError`` on Tableau Cloud which manages
    schedules via extract tasks rather than the ``/schedules`` endpoint.
    """
    cfg = load_config()
    if cfg.is_cloud:
        raise NotImplementedError(
            "Tableau Cloud manages schedules via extract tasks, not the /schedules endpoint."
        )

    schedule_payload = {
        "name": name,
        "priority": priority,
        "type": "Extract",
        "frequency": frequency,
    }
    if start_time:
        schedule_payload["executionOrder"] = start_time.strftime("%H:%M:%S")

    with authenticated_session() as conn:
        resp = conn.create_schedule(schedule_payload)
        logger.info("Created extract schedule '%s' (frequency=%s)", name, frequency)
        return resp.json()
