"""
Content migration: download from Tableau Server, upload to Tableau Cloud.

Supports resumable migrations via a JSON state file.  Each content item
tracks its own status so a failed run can be re-executed without
re-downloading or re-uploading items that already succeeded.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

from .catalog import list_workbooks, list_datasources
from .config import TableauConfig, load_config
from .config import TableauConfig
from .publish.workbooks import download_workbook, publish_workbook
from .publish.datasources import download_datasource, publish_datasource
from .session import authenticated_session, authenticated_session_for_site
from .stats import StatsTracker

logger = logging.getLogger(__name__)


@dataclass
class MigrationItem:
    """Tracks one piece of content through the migration pipeline."""

    content_type: str  # "workbook" or "datasource"
    content_id: str
    content_name: str
    source_site: str
    target_site: str
    target_project: str
    status: str = "pending"  # pending | downloaded | uploaded | failed
    error: str | None = None


class MigrationTracker:
    """
    Persist migration state to a JSON file so runs are resumable.
    """

    def __init__(self, state_file: Path) -> None:
        self.path = state_file

    def load(self) -> list[MigrationItem]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [MigrationItem(**item) for item in data]

    def save(self, items: list[MigrationItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump([asdict(item) for item in items], f, indent=2)

    def pending_items(self) -> list[MigrationItem]:
        return [item for item in self.load() if item.status in ("pending", "downloaded")]


def plan_migration(
    source_config: TableauConfig,
    target_config: TableauConfig,
    content_types: list[str] | None = None,
    source_site: str | None = None,
) -> list[MigrationItem]:
    """
    Query the source server for all content and map each item to a target
    site/project from the target config.

    If *source_site* is provided, only content from that site is included.
    Otherwise content from the default site in *source_config* is used.

    The mapping is by site content_url: source site -> target config entry with
    the same content_url.  Content on sites not in the manifest is skipped.
    """
    types = content_types or ["workbook", "datasource"]
    items: list[MigrationItem] = []

    # Build lookup from content_url -> target_project
    target_map = {s.content_url: s for s in target_config.enabled_sites()}

    with authenticated_session(source_config) as conn:
        if "workbook" in types:
            workbooks = list_workbooks()
            for wb in workbooks:
                site_url = source_site or source_config.site
                target = target_map.get(site_url)
                if not target:
                    continue
                items.append(
                    MigrationItem(
                        content_type="workbook",
                        content_id=wb.get("id", ""),
                        content_name=wb.get("name", ""),
                        source_site=site_url,
                        target_site=target.content_url,
                        target_project=target.target_workbook_project,
                    )
                )

        if "datasource" in types:
            datasources = list_datasources()
            for ds in datasources:
                site_url = source_site or source_config.site
                target = target_map.get(site_url)
                if not target:
                    continue
                items.append(
                    MigrationItem(
                        content_type="datasource",
                        content_id=ds.get("id", ""),
                        content_name=ds.get("name", ""),
                        source_site=site_url,
                        target_site=target.content_url,
                        target_project=target.target_datasource_project,
                    )
                )

    logger.info("Migration plan: %d items (%d workbooks, %d datasources)",
                len(items),
                sum(1 for i in items if i.content_type == "workbook"),
                sum(1 for i in items if i.content_type == "datasource"))
    return items


def execute_migration(
    state_file: Path,
    source_config: TableauConfig,
    target_config: TableauConfig,
    download_dir: Path,
    embed_credentials: bool = False,
    connection_username: Optional[str] = None,
    connection_password: Optional[str] = None,
    on_error: Literal["continue", "stop"] = "continue",
) -> list[MigrationItem]:
    """
    Execute a migration plan.  Resumable — skips items already uploaded.

    1. Download each pending item from the source server.
    2. Upload to the target Cloud site/project.
    3. Update status in the state file after each step.
    """
    tracker = MigrationTracker(state_file)
    items = tracker.load()
    download_dir.mkdir(parents=True, exist_ok=True)

    for item in items:
        if item.status == "uploaded":
            continue

        # --- Download phase ---
        if item.status == "pending":
            try:
                if item.content_type == "workbook":
                    dest = download_dir / f"{item.content_name}.twbx"
                    download_workbook(item.content_id, dest)
                else:
                    dest = download_dir / f"{item.content_name}.tdsx"
                    download_datasource(item.content_id, dest)
                item.status = "downloaded"
                tracker.save(items)
                logger.info("Downloaded %s '%s'", item.content_type, item.content_name)
            except Exception as exc:
                item.status = "failed"
                item.error = str(exc)
                tracker.save(items)
                logger.error("Failed to download %s '%s': %s", item.content_type, item.content_name, exc)
                if on_error == "stop":
                    raise
                continue

        # --- Upload phase ---
        if item.status == "downloaded":
            try:
                with authenticated_session_for_site(item.target_site, target_config) as conn:
                    if item.content_type == "workbook":
                        file_path = download_dir / f"{item.content_name}.twbx"
                        publish_workbook(
                            workbook_path=file_path,
                            project_name=item.target_project,
                            embed_credentials=embed_credentials,
                            connection_username=connection_username,
                            connection_password=connection_password,
                            conn=conn,
                        )
                    else:
                        file_path = download_dir / f"{item.content_name}.tdsx"
                        creds = None
                        if connection_username and connection_password:
                            creds = {"username": connection_username, "password": connection_password}
                        publish_datasource(
                            datasource_path=file_path,
                            project_name=item.target_project,
                            connection_credentials=creds,
                        )
                item.status = "uploaded"
                tracker.save(items)
                logger.info("Uploaded %s '%s' to site '%s'", item.content_type, item.content_name, item.target_site)
            except Exception as exc:
                item.status = "failed"
                item.error = str(exc)
                tracker.save(items)
                logger.error("Failed to upload %s '%s': %s", item.content_type, item.content_name, exc)
                if on_error == "stop":
                    raise

    # Record stats
    uploaded = sum(1 for i in items if i.status == "uploaded")
    failed = sum(1 for i in items if i.status == "failed")
    StatsTracker().record_run(
        "content_migration",
        success=failed == 0,
        details={"state_file": str(state_file)},
    )
    logger.info("Migration complete: %d uploaded, %d failed", uploaded, failed)
    return items
