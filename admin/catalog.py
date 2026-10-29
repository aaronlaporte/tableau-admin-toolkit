"""
Lightweight catalog helpers for listing Tableau assets via REST API.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .session import authenticated_session

logger = logging.getLogger(__name__)


def list_sites() -> List[dict]:
    """
    Return all sites visible to the PAT.
    """
    with authenticated_session() as conn:
        resp = conn.query_sites()
        sites_data = resp.json().get("sites", {})
        sites = sites_data.get("site", []) if isinstance(sites_data, dict) else sites_data
        logger.debug("Retrieved %d sites", len(sites))
        return sites


def list_projects() -> List[dict]:
    """
    Return all projects on the active site.
    """
    with authenticated_session() as conn:
        resp = conn.query_projects()
        projects_data = resp.json().get("projects", {})
        projects = projects_data.get("project", []) if isinstance(projects_data, dict) else projects_data
        logger.debug("Retrieved %d projects", len(projects))
        return projects


def list_workbooks(project_id: Optional[str] = None) -> List[dict]:
    """
    Return all workbooks, optionally filtered by project.
    """
    with authenticated_session() as conn:
        resp = conn.query_workbooks_on_site()
        workbooks_data = resp.json().get("workbooks", {})
        workbooks = workbooks_data.get("workbook", []) if isinstance(workbooks_data, dict) else workbooks_data
        if project_id:
            workbooks = [wb for wb in workbooks if wb.get("project", {}).get("id") == project_id]
        logger.debug("Retrieved %d workbooks", len(workbooks))
        return workbooks


def list_datasources(project_id: Optional[str] = None) -> List[dict]:
    """
    Return all datasources, optionally filtered by project.
    """
    with authenticated_session() as conn:
        resp = conn.query_data_sources()
        datasources_data = resp.json().get("datasources", {})
        datasources = datasources_data.get("datasource", []) if isinstance(datasources_data, dict) else datasources_data
        if project_id:
            datasources = [ds for ds in datasources if ds.get("project", {}).get("id") == project_id]
        logger.debug("Retrieved %d datasources", len(datasources))
        return datasources


def list_views(workbook_id: Optional[str] = None) -> List[dict]:
    """
    Return all views, optionally filtered by workbook.
    """
    with authenticated_session() as conn:
        if workbook_id:
            resp = conn.query_views_for_workbook(workbook_id=workbook_id)
        else:
            resp = conn.query_views_for_site()
        views_data = resp.json().get("views", {})
        views = views_data.get("view", []) if isinstance(views_data, dict) else views_data
        logger.debug("Retrieved %d views", len(views))
        return views


def delete_workbook(workbook_id: str) -> dict:
    """
    Delete a workbook by ID.
    """
    with authenticated_session() as conn:
        resp = conn.delete_workbook(workbook_id=workbook_id)
        logger.info("Deleted workbook %s", workbook_id)
        return resp.json()


def delete_datasource(datasource_id: str) -> dict:
    """
    Delete a datasource by ID.
    """
    with authenticated_session() as conn:
        resp = conn.delete_data_source(datasource_id=datasource_id)
        logger.info("Deleted datasource %s", datasource_id)
        return resp.json()
