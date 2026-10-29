"""
Test Scenario — end-to-end harness for test sites.

This script exercises the full toolkit lifecycle against a live Tableau
Cloud (or Server) instance.  Before running, ensure:

  1. Your config YAML exists with your credentials (see config/tableau.example.yaml).

  2. The test sites listed in your config exist on your Cloud pod.
     Sites must be created manually — the toolkit sets up everything
     inside them (projects, groups, users).

  3. (Optional) Place .twbx files in tests/sample_workbooks/ to test
     batch publishing.

Usage:
    # Dry run — validates everything without touching the server
    python tests/nomad_test_scenario.py --dry-run

    # Live run — actually creates projects, groups, users, publishes
    python tests/nomad_test_scenario.py

    # Run specific phases only
    python tests/nomad_test_scenario.py --phase manifest
    python tests/nomad_test_scenario.py --phase bootstrap
    python tests/nomad_test_scenario.py --phase publish
    python tests/nomad_test_scenario.py --phase stats

    # Use a specific config file
    python tests/nomad_test_scenario.py --config path/to/your_config.yaml
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure the repo root is importable
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from admin.logging_setup import setup_logging
from admin.config import load_config
from admin.manifest import validate_manifest_against_api
from admin.bootstrap import bootstrap_all_sites, bootstrap_site
from admin.publish.batch import batch_publish_workbooks, batch_publish_datasources
from admin.stats import StatsTracker

logger = logging.getLogger("nomad_test")

CONFIG_PATH = REPO_ROOT / "config" / "tableau.yaml"
USERS_CSV = REPO_ROOT / "tests" / "nomad_test_users.csv"
SAMPLE_WB_DIR = REPO_ROOT / "tests" / "sample_workbooks"
SAMPLE_DS_DIR = REPO_ROOT / "tests" / "sample_datasources"


# ---------------------------------------------------------------------------
# Phase 1: Manifest validation
# ---------------------------------------------------------------------------

def phase_manifest(config_path: Path, dry_run: bool = False):
    """Load the config and validate it against the live API."""
    print("\n" + "=" * 70)
    print("PHASE 1: MANIFEST VALIDATION")
    print("=" * 70)

    cfg = load_config(config_path)
    print(f"\nLoaded {len(cfg.sites)} sites ({len(cfg.enabled_sites())} enabled)")

    for site in cfg.enabled_sites():
        print(f"  {site.name:12s}  url={site.content_url:10s}  "
              f"wb_project={site.target_workbook_project}  "
              f"ds_project={site.target_datasource_project}  "
              f"sub_projects={len(site.sub_projects)}  "
              f"groups={len(site.groups)}")

    if dry_run:
        print("\n[DRY RUN] Skipping live API validation")
        return None

    print("\nValidating against Tableau API...")
    try:
        result = validate_manifest_against_api(cfg)
        print(f"  Matched:       {len(result['matched'])} sites")
        print(f"  Manifest-only: {len(result['manifest_only'])} sites")
        print(f"  API-only:      {len(result['api_only'])} sites")

        if result["manifest_only"]:
            print(f"\n  WARNING: These sites are in the config but NOT on the server:")
            for url in result["manifest_only"]:
                print(f"    - {url}")
            print("  Create these sites on your Tableau Cloud pod before running bootstrap.")

        if result["matched"]:
            print(f"\n  Ready to operate on: {', '.join(result['matched'])}")

        return result
    except Exception as exc:
        print(f"\n  Could not validate (API unreachable?): {exc}")
        print("  Continuing with config-only mode...")
        return None


# ---------------------------------------------------------------------------
# Phase 2: Bootstrap all sites
# ---------------------------------------------------------------------------

def phase_bootstrap(config_path: Path, dry_run: bool = False):
    """Bootstrap every enabled site: projects, groups, users, sub-projects."""
    print("\n" + "=" * 70)
    print(f"PHASE 2: SITE BOOTSTRAPPING {'(DRY RUN)' if dry_run else '(LIVE)'}")
    print("=" * 70)

    cfg = load_config(config_path)
    results = bootstrap_all_sites(
        config=cfg,
        users_csv=USERS_CSV,
        dry_run=dry_run,
        on_error="continue",
    )

    total_steps = 0
    total_ok = 0
    total_fail = 0

    for site_name, steps in results.items():
        ok = sum(1 for s in steps if s.success)
        fail = sum(1 for s in steps if not s.success)
        total_steps += len(steps)
        total_ok += ok
        total_fail += fail

        status = "OK" if fail == 0 else "PARTIAL" if ok > 0 else "FAILED"
        print(f"  {site_name:12s}  [{status}]  {ok}/{len(steps)} steps succeeded")

        if fail > 0:
            for s in steps:
                if not s.success:
                    print(f"    FAIL: {s.step} — {s.detail}")

    print(f"\nTotal: {total_ok}/{total_steps} steps succeeded, {total_fail} failed")
    return results


# ---------------------------------------------------------------------------
# Phase 3: Batch publish
# ---------------------------------------------------------------------------

def phase_publish(config_path: Path, dry_run: bool = False):
    """Batch publish sample workbooks and datasources to every enabled site."""
    print("\n" + "=" * 70)
    print(f"PHASE 3: BATCH PUBLISHING {'(DRY RUN)' if dry_run else '(LIVE)'}")
    print("=" * 70)

    cfg = load_config(config_path)

    # --- Workbooks ---
    if SAMPLE_WB_DIR.exists() and list(SAMPLE_WB_DIR.glob("*.twbx")):
        wb_files = list(SAMPLE_WB_DIR.glob("*.twbx"))
        print(f"\nFound {len(wb_files)} workbook(s) in {SAMPLE_WB_DIR}:")
        for f in wb_files:
            print(f"  - {f.name}")

        if dry_run:
            print(f"  [DRY RUN] Would publish {len(wb_files)} workbooks to "
                  f"{len(cfg.enabled_sites())} sites "
                  f"= {len(wb_files) * len(cfg.enabled_sites())} total publishes")
        else:
            results = batch_publish_workbooks(
                workbook_dir=SAMPLE_WB_DIR,
                config=cfg,
                embed_credentials=False,
                on_error="continue",
            )
            ok = sum(1 for r in results if r.success)
            fail = sum(1 for r in results if not r.success)
            print(f"  Workbooks: {ok} succeeded, {fail} failed")
            if fail > 0:
                for r in results:
                    if not r.success:
                        print(f"    FAIL: {r.site_name}/{r.content_name} — {r.detail}")
    else:
        print(f"\nNo sample workbooks found at {SAMPLE_WB_DIR}")
        print(f"  To test batch publishing, create the directory and add .twbx files:")
        print(f"    mkdir -p {SAMPLE_WB_DIR}")
        print(f"    cp /path/to/your/workbook.twbx {SAMPLE_WB_DIR}/")

    # --- Datasources ---
    if SAMPLE_DS_DIR.exists() and list(SAMPLE_DS_DIR.iterdir()):
        ds_files = [f for f in SAMPLE_DS_DIR.iterdir() if f.suffix.lower() in {".tdsx", ".hyper"}]
        if ds_files:
            print(f"\nFound {len(ds_files)} datasource(s) in {SAMPLE_DS_DIR}:")
            for f in ds_files:
                print(f"  - {f.name}")

            if dry_run:
                print(f"  [DRY RUN] Would publish {len(ds_files)} datasources to "
                      f"{len(cfg.enabled_sites())} sites")
            else:
                results = batch_publish_datasources(
                    datasource_dir=SAMPLE_DS_DIR,
                    config=cfg,
                    on_error="continue",
                )
                ok = sum(1 for r in results if r.success)
                fail = sum(1 for r in results if not r.success)
                print(f"  Datasources: {ok} succeeded, {fail} failed")
    else:
        print(f"\nNo sample datasources found at {SAMPLE_DS_DIR}")
        print(f"  To test, add .tdsx or .hyper files to: {SAMPLE_DS_DIR}")


# ---------------------------------------------------------------------------
# Phase 4: Stats summary
# ---------------------------------------------------------------------------

def phase_stats():
    """Print accumulated run statistics."""
    print("\n" + "=" * 70)
    print("PHASE 4: RUN STATISTICS")
    print("=" * 70)

    tracker = StatsTracker()

    for op in ["bootstrap_sites", "batch_publish_workbooks", "batch_publish_datasources"]:
        summary = tracker.get_summary(operation=op)
        if summary["total_runs"] > 0:
            print(f"\n  {op}:")
            print(f"    Runs:         {summary['total_runs']}")
            print(f"    Succeeded:    {summary['succeeded']}")
            print(f"    Failed:       {summary['failed']}")
            print(f"    Success rate: {summary['success_rate']:.1%}")
            print(f"    Last run:     {summary['last_run']}")

    overall = tracker.get_summary()
    print(f"\n  Overall: {overall['total_runs']} runs — "
          f"{overall['succeeded']} succeeded, {overall['failed']} failed "
          f"({overall['success_rate']:.1%})")


# ---------------------------------------------------------------------------
# Phase 5: Config verification
# ---------------------------------------------------------------------------

def phase_config(config_path: Path):
    """Print current config to verify connection details are correct."""
    print("\n" + "=" * 70)
    print("PHASE 0: CONFIGURATION CHECK")
    print("=" * 70)

    try:
        cfg = load_config(config_path)
        print(f"  Server:            {cfg.server}")
        print(f"  Site:              {cfg.site}")
        print(f"  API version:       {cfg.api_version}")
        print(f"  Deployment target: {cfg.deployment_target} (is_cloud={cfg.is_cloud})")
        print(f"  PAT name:          {cfg.pat_name or 'NOT SET'}")
        print(f"  PAT secret:        {'***' if cfg.pat_secret else 'NOT SET'}")
        print(f"  Sites defined:     {len(cfg.sites)} ({len(cfg.enabled_sites())} enabled)")

        if not cfg.pat_name or not cfg.pat_secret:
            print("\n  WARNING: PAT credentials not set. Add pat_name/pat_secret to your config.")
    except Exception as exc:
        print(f"  Config load failed: {exc}")
        print(f"  Ensure {config_path} exists. Copy from config/tableau.example.yaml")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="End-to-end test scenario for the Tableau admin toolkit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and log without making API changes",
    )
    parser.add_argument(
        "--phase",
        choices=["config", "manifest", "bootstrap", "publish", "stats", "all"],
        default="all",
        help="Run a specific phase only (default: all)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to tableau.yaml config file",
    )
    args = parser.parse_args()

    setup_logging("INFO")

    print("=" * 70)
    print("  TEST SCENARIO — Tableau Admin Toolkit")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"  Config: {args.config}")
    print("=" * 70)

    if args.phase in ("all", "config"):
        phase_config(args.config)

    if args.phase in ("all", "manifest"):
        phase_manifest(args.config, dry_run=args.dry_run)

    if args.phase in ("all", "bootstrap"):
        phase_bootstrap(args.config, dry_run=args.dry_run)

    if args.phase in ("all", "publish"):
        phase_publish(args.config, dry_run=args.dry_run)

    if args.phase in ("all", "stats"):
        phase_stats()

    print("\n" + "=" * 70)
    print("  SCENARIO COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
