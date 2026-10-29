"""
Datasource publishing operations.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from tableau_api_lib import TableauServerConnection

from ..config import load_config
from ..session import authenticated_session

logger = logging.getLogger(__name__)


def publish_datasource(
    datasource_path: str | Path,
    project_name: Optional[str] = None,
    connection_credentials: Optional[dict] = None,
    overwrite: bool = True,
    conn: Optional[TableauServerConnection] = None,
) -> dict:
    """
    Publish a datasource (.tdsx or .hyper) to Tableau Server.

    Parameters
    ----------
    conn
        Pre-authenticated connection.  When *None* a new session is created.
    """
    cfg = load_config()
    project = project_name or cfg.default_project
    file_path = Path(datasource_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Datasource path {file_path} does not exist")

    def _do_publish(connection: TableauServerConnection) -> dict:
        resp = connection.publish_data_source(
            datasource_file_path=str(file_path),
            datasource_name=file_path.stem,
            project_id=project,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to publish datasource '{file_path.stem}': {resp.status_code} — {resp.text}"
            )
        logger.info("Published datasource '%s' to project '%s'", file_path.stem, project)
        return resp.json()

    if conn is not None:
        return _do_publish(conn)

    with authenticated_session() as session:
        return _do_publish(session)


def refresh_datasource(datasource_id: str) -> dict:
    """
    Kick off a datasource refresh and return the job payload.
    """
    with authenticated_session() as conn:
        resp = conn.refresh_data_source(datasource_id=datasource_id)
        logger.info("Triggered refresh for datasource %s", datasource_id)
        return resp.json()


def download_datasource(datasource_id: str, destination: str | Path) -> Path:
    """
    Download a datasource (.tdsx or .hyper) to the destination path.
    """
    dest_path = Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with authenticated_session() as conn:
        conn.download_data_source(
            datasource_id=datasource_id,
        )
    logger.info("Downloaded datasource %s to %s", datasource_id, dest_path)
    return dest_path
