"""
Project scaffolding utilities.
"""
from __future__ import annotations

import logging
from typing import Optional

from tableau_api_lib import TableauServerConnection

from ..config import load_config
from ..session import authenticated_session

logger = logging.getLogger(__name__)


def ensure_project(
    name: str,
    description: str = "",
    parent_project_id: Optional[str] = None,
    conn: Optional[TableauServerConnection] = None,
) -> dict:
    """
    Create a project if it does not already exist.

    Parameters
    ----------
    conn
        Pre-authenticated connection.  When *None* a new session is created.
    """
    def _ensure(connection: TableauServerConnection) -> dict:
        existing = connection.query_projects()
        projects_data = existing.json().get("projects", {})
        project_list = projects_data.get("project", []) if isinstance(projects_data, dict) else projects_data
        for project in project_list:
            if project.get("name") == name:
                logger.debug("Project '%s' already exists", name)
                return project

        resp = connection.create_project(
            project_name=name,
            project_description=description,
            parent_project_id=parent_project_id,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create project '{name}': {resp.status_code} — {resp.text}")
        logger.info("Created project '%s'", name)
        return resp.json()

    if conn is not None:
        return _ensure(conn)

    with authenticated_session() as session:
        return _ensure(session)


def bootstrap_standard_projects() -> list[dict]:
    """
    Convenience helper for setting up dev/test/prod projects using defaults.
    """
    cfg = load_config()
    standard = [
        f"{cfg.default_project} - Dev",
        f"{cfg.default_project} - Test",
        f"{cfg.default_project} - Prod",
    ]
    results = []
    for project in standard:
        results.append(ensure_project(project))
    logger.info("Bootstrapped %d standard projects", len(results))
    return results


def delete_project(project_id: str) -> dict:
    """
    Delete a project by ID.
    """
    with authenticated_session() as conn:
        resp = conn.delete_project(project_id=project_id)
        logger.info("Deleted project %s", project_id)
        return resp.json()
