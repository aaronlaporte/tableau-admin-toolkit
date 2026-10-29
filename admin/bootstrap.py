"""
Site bootstrapping orchestrator.

Chains project creation, group creation, user provisioning, permission
assignment, and sub-project creation into a single repeatable operation.
Reads site definitions from the manifest and uses existing primitives.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from .create.groups import create_group, add_users_to_group
from .create.projects import ensure_project
from .create.users import UserDefinition, bulk_provision
from .governance.permissions import set_project_permissions
from .config import SiteDefinition, SubProjectDef, TableauConfig, load_config
from .session import authenticated_session_for_site
from .stats import StatsTracker

logger = logging.getLogger(__name__)


@dataclass
class BootstrapStep:
    """Result of a single bootstrap step."""

    step: str
    success: bool
    detail: str = ""


def bootstrap_site(
    site_def: SiteDefinition,
    users_csv: Optional[Path] = None,
    permission_template: Optional[dict] = None,
    dry_run: bool = False,
) -> list[BootstrapStep]:
    """
    Orchestrate full site setup:

    1. Create the target project
    2. Create each group from the site definition
    3. If *users_csv* is provided, provision users and add to first group
    4. Apply *permission_template* to the target project
    5. Create sub-projects under the target project
    """
    steps: list[BootstrapStep] = []

    if dry_run:
        logger.info("[DRY RUN] Would bootstrap site '%s'", site_def.name)
        for g in site_def.groups:
            steps.append(BootstrapStep("create_group", True, f"Would create group '{g.name}'"))
        if users_csv:
            steps.append(BootstrapStep("provision_users", True, f"Would provision from {users_csv}"))
        if permission_template:
            steps.append(BootstrapStep("set_permissions", True, "Would apply permission template"))
        # Sub-projects are top-level projects on the site (visible under Explore)
        _create_sub_projects(site_def.sub_projects, None, site_def.name, steps, dry_run=True)
        return steps

    with authenticated_session_for_site(site_def.content_url) as conn:
        # 1. Create groups
        group_ids: dict[str, str] = {}
        for group_def in site_def.groups:
            try:
                result = create_group(group_def.name, group_def.minimum_site_role, conn=conn)
                gid = result.get("id") or result.get("group", {}).get("id")
                group_ids[group_def.name] = gid
                steps.append(BootstrapStep("create_group", True, f"Group '{group_def.name}' ready"))
            except Exception as exc:
                steps.append(BootstrapStep("create_group", False, f"{group_def.name}: {exc}"))
                logger.error("Site '%s': failed to create group '%s': %s", site_def.name, group_def.name, exc)

        # 2. Provision users (optional)
        if users_csv and users_csv.exists():
            try:
                with users_csv.open("r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    users = [UserDefinition(**row) for row in reader]
                results = bulk_provision(users, conn=conn)
                steps.append(BootstrapStep("provision_users", True, f"Provisioned {len(results)} users"))

                # Add provisioned users to the first group if available
                if group_ids:
                    first_group_id = next(iter(group_ids.values()))
                    user_ids = [
                        r.get("id") or r.get("user", {}).get("id")
                        for r in results
                        if r.get("id") or r.get("user", {}).get("id")
                    ]
                    if user_ids:
                        add_users_to_group(first_group_id, user_ids, conn=conn)
                        steps.append(
                            BootstrapStep("add_users_to_group", True, f"Added {len(user_ids)} users to group")
                        )
            except Exception as exc:
                steps.append(BootstrapStep("provision_users", False, str(exc)))
                logger.error("Site '%s': user provisioning failed: %s", site_def.name, exc)

        # 3. Create top-level project tree (visible under Explore)
        # Sub-projects have no wrapper — "Data Sources" and "Client Reports"
        # appear directly in Explore alongside any custom client projects.
        _create_sub_projects(site_def.sub_projects, None, site_def.name, steps, dry_run, conn=conn)

        # 4. Apply permission template to each top-level project (optional)
        if permission_template:
            for sp in site_def.sub_projects:
                try:
                    project = ensure_project(sp.name, conn=conn)
                    sp_id = project.get("id") or project.get("project", {}).get("id")
                    if sp_id:
                        set_project_permissions(sp_id, permission_template, conn=conn)
                        steps.append(BootstrapStep("set_permissions", True, f"Permissions applied to '{sp.name}'"))
                except Exception as exc:
                    steps.append(BootstrapStep("set_permissions", False, f"{sp.name}: {exc}"))
                    logger.error("Site '%s': permission assignment failed for '%s': %s", site_def.name, sp.name, exc)

    return steps


def _create_sub_projects(
    sub_projects: list[SubProjectDef],
    parent_id: str | None,
    site_name: str,
    steps: list[BootstrapStep],
    dry_run: bool = False,
    depth: int = 0,
    conn=None,
) -> None:
    """Recursively create a nested sub-project tree."""
    indent = "  " * depth
    for sp in sub_projects:
        if dry_run:
            steps.append(BootstrapStep("create_sub_project", True, f"Would create '{indent}{sp.name}'"))
            _create_sub_projects(sp.children, None, site_name, steps, dry_run=True, depth=depth + 1)
            continue

        try:
            result = ensure_project(sp.name, parent_project_id=parent_id, conn=conn)
            sp_id = result.get("id") or result.get("project", {}).get("id")
            steps.append(BootstrapStep("create_sub_project", True, f"Sub-project '{sp.name}' ready"))
            logger.info("Site '%s': sub-project '%s' ready", site_name, sp.name)

            # Recurse into children
            if sp.children:
                _create_sub_projects(sp.children, sp_id, site_name, steps, depth=depth + 1, conn=conn)

        except Exception as exc:
            steps.append(BootstrapStep("create_sub_project", False, f"{sp.name}: {exc}"))
            logger.error("Site '%s': failed to create sub-project '%s': %s", site_name, sp.name, exc)


def bootstrap_all_sites(
    config: Optional[TableauConfig] = None,
    users_csv: Optional[Path] = None,
    permission_template: Optional[dict] = None,
    dry_run: bool = False,
    on_error: Literal["continue", "stop"] = "continue",
) -> dict[str, list[BootstrapStep]]:
    """
    Run :func:`bootstrap_site` for every enabled site in the config.
    """
    cfg = config or load_config()
    all_results: dict[str, list[BootstrapStep]] = {}

    for site_def in cfg.enabled_sites():
        try:
            steps = bootstrap_site(
                site_def,
                users_csv=users_csv,
                permission_template=permission_template,
                dry_run=dry_run,
            )
            all_results[site_def.name] = steps
        except Exception as exc:
            logger.error("Bootstrap failed for site '%s': %s", site_def.name, exc)
            all_results[site_def.name] = [BootstrapStep("bootstrap", False, str(exc))]
            if on_error == "stop":
                raise

    # Record stats — job-level pass/fail
    any_failure = any(
        not s.success for steps in all_results.values() for s in steps
    )
    if not dry_run:
        StatsTracker().record_run(
            "bootstrap_sites",
            success=not any_failure,
            details={"sites": list(all_results.keys())},
        )

    return all_results
