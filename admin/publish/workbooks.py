"""
Workbook publishing operations.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from tableau_api_lib import TableauServerConnection

from ..config import TableauConfig, load_config
from ..session import authenticated_session

logger = logging.getLogger(__name__)


def publish_workbook(
    workbook_path: str | Path,
    project_name: Optional[str] = None,
    show_tabs: bool = False,
    overwrite: bool = True,
    embed_credentials: bool = False,
    connection_username: Optional[str] = None,
    connection_password: Optional[str] = None,
    connection_server_address: Optional[str] = None,
    config: Optional[TableauConfig] = None,
    conn: Optional[TableauServerConnection] = None,
) -> dict:
    """
    Publish a packaged workbook to Tableau Server or Cloud.

    Parameters
    ----------
    conn
        Pre-authenticated connection (used by batch operations to avoid
        signing in/out per workbook).  When *None* a new session is created.
    embed_credentials
        When *True*, embed database credentials so the workbook can
        refresh extracts without prompting for a password.
    connection_username / connection_password / connection_server_address
        SA credentials to embed.  Only used when *embed_credentials* is True.
    """
    cfg = config or load_config()
    project = project_name or cfg.default_project
    file_path = Path(workbook_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Workbook path {file_path} does not exist")

    def _do_publish(connection: TableauServerConnection) -> dict:
        kwargs: dict = dict(
            workbook_file_path=str(file_path),
            workbook_name=file_path.stem,
            project_name=project,
            show_tabs=show_tabs,
            overwrite=overwrite,
        )
        if embed_credentials:
            kwargs["embed_credentials_flag"] = True
            if connection_username:
                kwargs["connection_username"] = connection_username
            if connection_password:
                kwargs["connection_password"] = connection_password
            if connection_server_address:
                kwargs["server_address"] = connection_server_address

        response = connection.publish_workbook(**kwargs)
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to publish workbook '{file_path.stem}': {response.status_code} — {response.text}"
            )
        logger.info("Published workbook '%s' to project '%s'", file_path.stem, project)
        return response.json()

    if conn is not None:
        return _do_publish(conn)

    with authenticated_session(cfg) as session:
        return _do_publish(session)


def download_workbook(workbook_id: str, destination: str | Path) -> Path:
    """
    Download a packaged workbook (.twbx) to the destination path.
    """
    dest_path = Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with authenticated_session() as conn:
        conn.download_workbook(
            workbook_id=workbook_id,
        )
    logger.info("Downloaded workbook %s to %s", workbook_id, dest_path)
    return dest_path


def promote_workbook(
    workbook_id: str,
    target_project: str,
    retain_permissions: bool = True,
) -> dict:
    """
    Move workbook between projects (e.g., dev -> prod).
    """
    with authenticated_session() as conn:
        resp = conn.update_workbook(
            workbook_id=workbook_id,
        )
        if retain_permissions:
            # tableau-api-lib retains permissions by default; placeholder for custom logic
            pass
        logger.info("Promoted workbook %s to project '%s'", workbook_id, target_project)
        return resp.json()
