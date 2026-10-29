"""
Typer-based CLI entry point for Tableau admin operations.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer

from .config import load_config
from .logging_setup import setup_logging
from .catalog import list_datasources, list_projects, list_sites, list_views, list_workbooks, delete_workbook, delete_datasource
from .create.users import UserDefinition, bulk_provision, create_user, list_users, delete_user
from .create.groups import add_users_to_group, create_group, list_groups, list_group_members, remove_user_from_group, delete_group
from .create.projects import delete_project
from .publish.datasources import publish_datasource, refresh_datasource
from .publish.datasources import download_datasource
from .publish.workbooks import download_workbook, publish_workbook
from .maintenance.extracts import refresh_and_wait
from .manifest import validate_manifest_against_api
from .publish.batch import batch_publish_workbooks, batch_publish_datasources
from .stats import StatsTracker
from .bootstrap import bootstrap_site, bootstrap_all_sites
from .migrate import plan_migration, execute_migration, MigrationTracker
from .flows.flows import list_flows, publish_flow, trigger_flow_run, get_flow_run_status, run_flow_and_wait
from .maintenance.alerts import check_and_alert_failed_extracts

logger = logging.getLogger(__name__)

app = typer.Typer(help="Tableau admin automation CLI")


@app.callback()
def _init():
    """Initialize logging before any command runs."""
    setup_logging()


@app.command()
def create_user_cmd(username: str, site_role: str = typer.Option("Viewer"), full_name: Optional[str] = None):
    """Create a Tableau user."""
    user = UserDefinition(username=username, site_role=site_role, full_name=full_name)
    result = create_user(user)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def bulk_users(csv_path: Path):
    """Provision users from a CSV file with columns username,site_role."""
    import csv

    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        users = [UserDefinition(**row) for row in reader]
    results = bulk_provision(users)
    logger.info("Provisioned %d users from %s", len(results), csv_path)


@app.command()
def create_group_cmd(name: str, min_role: str = typer.Option("Viewer")):
    """Create a Tableau group."""
    result = create_group(name=name, minimum_site_role=min_role)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def group_add(group_id: str, user_ids: list[str] = typer.Argument(...)):
    """Add users to a group."""
    result = add_users_to_group(group_id, user_ids)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def publish_wb(path: Path, project: Optional[str] = None):
    """Publish a workbook."""
    result = publish_workbook(workbook_path=path, project_name=project)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def publish_ds(path: Path, project: Optional[str] = None):
    """Publish a datasource."""
    result = publish_datasource(datasource_path=path, project_name=project)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def refresh_ds(datasource_id: str, wait: bool = True):
    """Refresh datasource extracts."""
    if wait:
        result = refresh_and_wait(datasource_id)
    else:
        result = refresh_datasource(datasource_id)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def download_wb(workbook_id: str, out: Path):
    """Download a workbook (.twbx) to the given path."""
    dest = download_workbook(workbook_id=workbook_id, destination=out)
    typer.echo(f"Downloaded workbook to {dest}")


@app.command()
def download_ds(datasource_id: str, out: Path):
    """Download a datasource (.tdsx/.hyper) to the given path."""
    dest = download_datasource(datasource_id=datasource_id, destination=out)
    typer.echo(f"Downloaded datasource to {dest}")


@app.command()
def sites():
    """List sites visible to the PAT."""
    typer.echo(json.dumps(list_sites(), indent=2))


@app.command()
def projects():
    """List projects."""
    typer.echo(json.dumps(list_projects(), indent=2))


@app.command()
def workbooks(project_id: Optional[str] = None):
    """List workbooks, optionally filtered by project."""
    typer.echo(json.dumps(list_workbooks(project_id=project_id), indent=2))


@app.command()
def datasources(project_id: Optional[str] = None):
    """List datasources, optionally filtered by project."""
    typer.echo(json.dumps(list_datasources(project_id=project_id), indent=2))


@app.command()
def views(workbook_id: Optional[str] = None):
    """List views, optionally filtered by workbook."""
    typer.echo(json.dumps(list_views(workbook_id=workbook_id), indent=2))


@app.command()
def show_config(config: Optional[Path] = typer.Option(None, help="Path to tableau.yaml")):
    """Print current Tableau config (safe subset — PAT secret is masked)."""
    cfg = load_config(config)
    safe = cfg.dict()
    if safe.get("pat_secret"):
        safe["pat_secret"] = "***"
    typer.echo(json.dumps(safe, indent=2, default=str))


# ---------------------------------------------------------------------------
# User CRUD commands
# ---------------------------------------------------------------------------


@app.command()
def list_users_cmd():
    """List all users on the active site."""
    typer.echo(json.dumps(list_users(), indent=2))


@app.command()
def delete_user_cmd(user_id: str):
    """Remove a user from the site."""
    result = delete_user(user_id)
    typer.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Group CRUD commands
# ---------------------------------------------------------------------------


@app.command()
def list_groups_cmd():
    """List all groups on the active site."""
    typer.echo(json.dumps(list_groups(), indent=2))


@app.command()
def list_group_members_cmd(group_id: str):
    """List all members of a group."""
    typer.echo(json.dumps(list_group_members(group_id), indent=2))


@app.command()
def remove_group_user(group_id: str, user_id: str):
    """Remove a user from a group."""
    result = remove_user_from_group(group_id, user_id)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def delete_group_cmd(group_id: str):
    """Delete a group."""
    result = delete_group(group_id)
    typer.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Project / Content delete commands
# ---------------------------------------------------------------------------


@app.command()
def delete_project_cmd(project_id: str):
    """Delete a project."""
    result = delete_project(project_id)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def delete_wb(workbook_id: str):
    """Delete a workbook."""
    result = delete_workbook(workbook_id)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def delete_ds(datasource_id: str):
    """Delete a datasource."""
    result = delete_datasource(datasource_id)
    typer.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Manifest / validation commands
# ---------------------------------------------------------------------------


@app.command()
def validate_manifest(config: Optional[Path] = typer.Option(None, help="Path to tableau.yaml")):
    """Compare site definitions in config against what the Tableau REST API returns."""
    cfg = load_config(config)
    result = validate_manifest_against_api(cfg)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def list_manifest_sites(config: Optional[Path] = typer.Option(None, help="Path to tableau.yaml")):
    """List enabled sites from the config."""
    cfg = load_config(config)
    sites_info = [
        {
            "name": s.name,
            "content_url": s.content_url,
            "target_workbook_project": s.target_workbook_project,
            "target_datasource_project": s.target_datasource_project,
        }
        for s in cfg.enabled_sites()
    ]
    typer.echo(json.dumps(sites_info, indent=2))


# ---------------------------------------------------------------------------
# Batch publish commands
# ---------------------------------------------------------------------------


@app.command()
def batch_publish_wb(
    workbook_dir: Path = typer.Argument(..., help="Directory containing .twbx files"),
    embed_creds: bool = typer.Option(False, help="Embed SA credentials in published workbooks"),
    cred_username: Optional[str] = typer.Option(None, help="DB username to embed"),
    cred_password: Optional[str] = typer.Option(None, help="DB password to embed"),
    cred_server: Optional[str] = typer.Option(None, help="DB server address to embed"),
    show_tabs: bool = typer.Option(True, help="Show tabs in published workbook"),
    on_error: str = typer.Option("continue", help="'continue' or 'stop' on failure"),
    config: Optional[Path] = typer.Option(None, help="Path to tableau.yaml"),
):
    """Publish all .twbx workbooks to every enabled site in the config."""
    cfg = load_config(config)
    results = batch_publish_workbooks(
        workbook_dir=workbook_dir,
        config=cfg,
        embed_credentials=embed_creds,
        connection_username=cred_username,
        connection_password=cred_password,
        connection_server_address=cred_server,
        show_tabs=show_tabs,
        on_error=on_error,  # type: ignore[arg-type]
    )
    summary = {
        "total": len(results),
        "succeeded": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success),
        "details": [
            {"site": r.site_name, "content": r.content_name, "success": r.success, "detail": r.detail}
            for r in results
        ],
    }
    typer.echo(json.dumps(summary, indent=2))


@app.command()
def batch_publish_ds(
    datasource_dir: Path = typer.Argument(..., help="Directory containing .tdsx/.hyper files"),
    on_error: str = typer.Option("continue", help="'continue' or 'stop' on failure"),
    config: Optional[Path] = typer.Option(None, help="Path to tableau.yaml"),
):
    """Publish all .tdsx/.hyper datasources to every enabled site in the config."""
    cfg = load_config(config)
    results = batch_publish_datasources(
        datasource_dir=datasource_dir,
        config=cfg,
        on_error=on_error,  # type: ignore[arg-type]
    )
    summary = {
        "total": len(results),
        "succeeded": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success),
        "details": [
            {"site": r.site_name, "content": r.content_name, "success": r.success, "detail": r.detail}
            for r in results
        ],
    }
    typer.echo(json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# Bootstrap commands
# ---------------------------------------------------------------------------


@app.command()
def bootstrap_site_cmd(
    site_content_url: str = typer.Argument(..., help="content_url of the site to bootstrap"),
    users_csv: Optional[Path] = typer.Option(None, help="CSV file with user definitions"),
    dry_run: bool = typer.Option(False, help="Log what would happen without making API calls"),
    config: Optional[Path] = typer.Option(None, help="Path to tableau.yaml"),
):
    """Bootstrap a single site: create projects, groups, users, permissions, sub-projects."""
    cfg = load_config(config)
    site_def = next((s for s in cfg.sites if s.content_url == site_content_url), None)
    if not site_def:
        typer.echo(f"Site '{site_content_url}' not found in config")
        raise typer.Exit(1)
    steps = bootstrap_site(site_def, users_csv=users_csv, dry_run=dry_run)
    output = [{"step": s.step, "success": s.success, "detail": s.detail} for s in steps]
    typer.echo(json.dumps(output, indent=2))


@app.command()
def bootstrap_all(
    users_csv: Optional[Path] = typer.Option(None, help="CSV file with user definitions"),
    dry_run: bool = typer.Option(False, help="Log what would happen without making API calls"),
    on_error: str = typer.Option("continue", help="'continue' or 'stop' on failure"),
    config: Optional[Path] = typer.Option(None, help="Path to tableau.yaml"),
):
    """Bootstrap all enabled sites from the config."""
    cfg = load_config(config)
    results = bootstrap_all_sites(
        config=cfg,
        users_csv=users_csv,
        dry_run=dry_run,
        on_error=on_error,  # type: ignore[arg-type]
    )
    output = {
        site: [{"step": s.step, "success": s.success, "detail": s.detail} for s in steps]
        for site, steps in results.items()
    }
    typer.echo(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Migration commands
# ---------------------------------------------------------------------------


@app.command()
def migrate_plan(
    source_config: Path = typer.Option(..., help="Path to source tableau.yaml (Server)"),
    target_config: Optional[Path] = typer.Option(None, help="Path to target tableau.yaml (Cloud)"),
    out: Path = typer.Option("migration_plan.json", help="Output state file"),
    content_types: Optional[str] = typer.Option(None, help="Comma-separated: workbook,datasource"),
    source_site: Optional[str] = typer.Option(None, help="Content URL of source site to migrate"),
):
    """Plan a migration: query source server and map content to target sites."""
    source_cfg = load_config(source_config)
    target_cfg = load_config(target_config)
    types = content_types.split(",") if content_types else None
    items = plan_migration(source_cfg, target_cfg, content_types=types, source_site=source_site)
    tracker = MigrationTracker(out)
    tracker.save(items)
    typer.echo(f"Migration plan saved to {out} ({len(items)} items)")


@app.command()
def migrate_execute(
    plan_file: Path = typer.Argument(..., help="Migration state JSON file"),
    source_config: Path = typer.Option(..., help="Path to source tableau.yaml (Server)"),
    target_config: Path = typer.Option(..., help="Path to target tableau.yaml (Cloud)"),
    download_dir: Path = typer.Option("./migration_staging", help="Directory for downloaded content"),
    embed_creds: bool = typer.Option(False, help="Embed SA credentials on upload"),
    cred_username: Optional[str] = typer.Option(None, help="DB username to embed"),
    cred_password: Optional[str] = typer.Option(None, help="DB password to embed"),
    on_error: str = typer.Option("continue", help="'continue' or 'stop' on failure"),
):
    """Execute a migration plan (resumable)."""
    source_cfg = load_config(source_config)
    target_cfg = load_config(target_config)
    items = execute_migration(
        state_file=plan_file,
        source_config=source_cfg,
        target_config=target_cfg,
        download_dir=download_dir,
        embed_credentials=embed_creds,
        connection_username=cred_username,
        connection_password=cred_password,
        on_error=on_error,  # type: ignore[arg-type]
    )
    uploaded = sum(1 for i in items if i.status == "uploaded")
    failed = sum(1 for i in items if i.status == "failed")
    typer.echo(f"Migration complete: {uploaded} uploaded, {failed} failed")


# ---------------------------------------------------------------------------
# Flow commands
# ---------------------------------------------------------------------------


@app.command()
def list_flows_cmd():
    """List all Prep flows on the active site."""
    typer.echo(json.dumps(list_flows(), indent=2))


@app.command()
def publish_flow_cmd(
    path: Path,
    project: Optional[str] = None,
):
    """Publish a .tflx flow file."""
    result = publish_flow(flow_path=path, project_name=project)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def run_flow(
    flow_id: str,
    wait: bool = typer.Option(True, help="Block until the flow run completes"),
):
    """Trigger a flow run."""
    if wait:
        result = run_flow_and_wait(flow_id)
    else:
        result = trigger_flow_run(flow_id)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def flow_status(job_id: str):
    """Check the status of a flow run job."""
    result = get_flow_run_status(job_id)
    typer.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Stats commands
# ---------------------------------------------------------------------------


@app.command()
def stats(
    operation: Optional[str] = typer.Option(None, help="Filter to a specific operation"),
    last: int = typer.Option(0, help="Show last N run records (0 = summary only)"),
):
    """Show run statistics (total runs, successes, failures)."""
    tracker = StatsTracker()
    if last > 0:
        history = tracker.get_history(operation=operation, last_n=last)
        typer.echo(json.dumps(history, indent=2))
    else:
        typer.echo(json.dumps(tracker.get_summary(operation=operation), indent=2))


# ---------------------------------------------------------------------------
# Extract alerting commands
# ---------------------------------------------------------------------------


@app.command()
def check_extract_alerts(
    lookback: int = typer.Option(60, help="Lookback window in minutes"),
    slack: bool = typer.Option(True, help="Send Slack alerts"),
    email: bool = typer.Option(True, help="Send email alerts"),
):
    """Check for failed extract refreshes and send alerts."""
    failed = check_and_alert_failed_extracts(
        lookback_minutes=lookback,
        notify_slack=slack,
        notify_email=email,
    )
    typer.echo(f"Found {len(failed)} failed extract(s)")
    if failed:
        typer.echo(json.dumps(failed, indent=2))


if __name__ == "__main__":
    app()
