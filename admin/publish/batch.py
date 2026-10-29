"""
Batch publishing: publish workbooks and datasources across multiple sites.

Reads target sites from the unified config (``config/tableau.yaml``) and iterates
over each enabled site, opening a dedicated session per site.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from ..config import TableauConfig, load_config
from ..session import authenticated_session_for_site
from ..stats import StatsTracker
from .workbooks import publish_workbook
from .datasources import publish_datasource

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """Outcome of publishing a single content item to a single site."""

    site_name: str
    content_url: str
    content_name: str
    content_type: str  # "workbook" or "datasource"
    success: bool
    detail: str = ""


def batch_publish_workbooks(
    workbook_dir: str | Path,
    config: Optional[TableauConfig] = None,
    embed_credentials: bool = False,
    connection_username: Optional[str] = None,
    connection_password: Optional[str] = None,
    connection_server_address: Optional[str] = None,
    show_tabs: bool = True,
    overwrite: bool = True,
    on_error: Literal["continue", "stop"] = "continue",
) -> list[PublishResult]:
    """
    Publish all ``.twbx`` workbooks in *workbook_dir* to every enabled site
    in the config.

    Parameters
    ----------
    on_error
        ``"continue"`` (default) logs failures and keeps going.
        ``"stop"`` raises on the first failure.
    """
    cfg = config or load_config()
    wb_dir = Path(workbook_dir)
    workbook_paths = sorted(wb_dir.glob("*.twbx"))
    if not workbook_paths:
        logger.warning("No .twbx files found in %s", wb_dir)
        return []

    logger.info(
        "Batch publishing %d workbooks to %d sites",
        len(workbook_paths),
        len(cfg.enabled_sites()),
    )

    results: list[PublishResult] = []

    for site in cfg.enabled_sites():
        try:
            with authenticated_session_for_site(site.content_url) as conn:
                for wb_path in workbook_paths:
                    try:
                        publish_workbook(
                            workbook_path=wb_path,
                            project_name=site.target_workbook_project,
                            show_tabs=show_tabs,
                            overwrite=overwrite,
                            embed_credentials=embed_credentials,
                            connection_username=connection_username,
                            connection_password=connection_password,
                            connection_server_address=connection_server_address,
                            conn=conn,
                        )
                        results.append(
                            PublishResult(
                                site_name=site.name,
                                content_url=site.content_url,
                                content_name=wb_path.stem,
                                content_type="workbook",
                                success=True,
                            )
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to publish '%s' to site '%s': %s",
                            wb_path.stem,
                            site.name,
                            exc,
                        )
                        results.append(
                            PublishResult(
                                site_name=site.name,
                                content_url=site.content_url,
                                content_name=wb_path.stem,
                                content_type="workbook",
                                success=False,
                                detail=str(exc),
                            )
                        )
                        if on_error == "stop":
                            raise
        except Exception as exc:
            if on_error == "stop":
                raise
            logger.error("Failed to connect to site '%s': %s", site.name, exc)

    failures = sum(1 for r in results if not r.success)
    logger.info("Batch publish complete: %d succeeded, %d failed", len(results) - failures, failures)
    StatsTracker().record_run(
        "batch_publish_workbooks",
        success=failures == 0,
        details={
            "sites": [s.content_url for s in cfg.enabled_sites()],
            "workbooks": [p.stem for p in workbook_paths],
        },
    )
    return results


def batch_publish_datasources(
    datasource_dir: str | Path,
    config: Optional[TableauConfig] = None,
    connection_credentials: Optional[dict] = None,
    overwrite: bool = True,
    on_error: Literal["continue", "stop"] = "continue",
) -> list[PublishResult]:
    """
    Publish all ``.tdsx`` and ``.hyper`` datasources in *datasource_dir* to
    every enabled site in the config.
    """
    cfg = config or load_config()
    ds_dir = Path(datasource_dir)
    ds_paths = sorted(
        p for p in ds_dir.iterdir() if p.suffix.lower() in {".tdsx", ".hyper"}
    )
    if not ds_paths:
        logger.warning("No .tdsx/.hyper files found in %s", ds_dir)
        return []

    logger.info(
        "Batch publishing %d datasources to %d sites",
        len(ds_paths),
        len(cfg.enabled_sites()),
    )

    results: list[PublishResult] = []

    for site in cfg.enabled_sites():
        try:
            with authenticated_session_for_site(site.content_url) as conn:
                for ds_path in ds_paths:
                    try:
                        publish_datasource(
                            datasource_path=ds_path,
                            project_name=site.target_datasource_project,
                            connection_credentials=connection_credentials,
                            overwrite=overwrite,
                            conn=conn,
                        )
                        results.append(
                            PublishResult(
                                site_name=site.name,
                                content_url=site.content_url,
                                content_name=ds_path.stem,
                                content_type="datasource",
                                success=True,
                            )
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to publish '%s' to site '%s': %s",
                            ds_path.stem,
                            site.name,
                            exc,
                        )
                        results.append(
                            PublishResult(
                                site_name=site.name,
                                content_url=site.content_url,
                                content_name=ds_path.stem,
                                content_type="datasource",
                                success=False,
                                detail=str(exc),
                            )
                        )
                        if on_error == "stop":
                            raise
        except Exception as exc:
            if on_error == "stop":
                raise
            logger.error("Failed to connect to site '%s': %s", site.name, exc)

    failures = sum(1 for r in results if not r.success)
    logger.info("Batch datasource publish complete: %d succeeded, %d failed", len(results) - failures, failures)
    StatsTracker().record_run(
        "batch_publish_datasources",
        success=failures == 0,
        details={
            "sites": [s.content_url for s in cfg.enabled_sites()],
            "datasources": [p.stem for p in ds_paths],
        },
    )
    return results
