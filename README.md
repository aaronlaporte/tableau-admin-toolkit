# Tableau Admin Toolkit

A Python-first toolkit for Tableau **Server and Cloud** administration, deployment automation, content migration, and dashboard validation. Designed for multi-tenant environments where each client gets their own Tableau site with a standardized folder structure, groups, and permissions.

## How It Works

One YAML config file drives everything. Define your connection, your standardized folder template, and your list of client sites. The toolkit loops through every enabled site and applies the same operations to each one.

```yaml
# config/tableau.yaml — this is the only file you need to configure
server: https://YOUR_POD.online.tableau.com
deployment_target: cloud

site_defaults:
  auth_method: "jwt"
  jwt_username: "admin@example.com"
  target_workbook_project: "Client Reports/Standard Reports"
  target_datasource_project: "Data Sources/Billing Ledger"
  sub_projects:
    - name: "Data Sources"
      children:
        - name: "Billing Ledger"
    - name: "Client Reports"
      children:
        - name: "Executive Reports"
        - name: "Standard Reports"
        - name: "Ad Hoc"
  groups:
    - name: "{site_name} Admins"
      minimum_site_role: "SiteAdministratorCreator"
    - name: "{site_name} Creators"
      minimum_site_role: "Creator"
    - name: "{site_name} Viewers"
      minimum_site_role: "Viewer"

sites:
  - name: "Client Alpha"
    content_url: "clientalpha"
    jwt_client_id: "abc123"
    jwt_secret_id: "def456"
    jwt_secret_value: os.environ.get("TCS_CLIENTALPHA_SECRET")

  - name: "Retired Client"
    content_url: "retiredclient"
    enabled: false
```

`site_defaults` is defined once and applied to every site. Each site entry needs `name`, `content_url`, and its Connected App credentials. Group names use `{site_name}` as a template variable ("Client Alpha" becomes "Client Alpha Admins"). Set `enabled: false` to skip a site without removing it.

## Authentication

The toolkit supports two authentication methods per site:

### JWT (Connected Apps) — recommended for Cloud

Each site gets a Connected App (Direct Trust) created in the Tableau Cloud UI. The toolkit mints a short-lived JWT on each sign-in — no tokens to rotate or expire.

Per-site config fields: `jwt_client_id`, `jwt_secret_id`, `jwt_secret_value`, `jwt_username`

Set `auth_method: "jwt"` in `site_defaults` to apply to all sites.

### PAT (Personal Access Tokens)

One PAT per site, created in the Tableau Cloud UI. PATs expire after 1 year and must be rotated manually. On Cloud, each PAT is scoped to a single site — there is no cross-site PAT.

Per-site config fields: `pat_name`, `pat_secret` (falls back to top-level if not set per-site)

### Credential storage

Secrets should be stored as environment variables, referenced in YAML:

```yaml
jwt_secret_value: os.environ.get("TCS_SITENAME_SECRET")
```

The `os.environ.get("...")` syntax is resolved at config load time. Environment variables with the `TABLEAU_*` prefix also override top-level YAML values when set.

## Adding a New Site

When a new client is onboarded, follow these steps:

### 1. Create the site on Tableau Cloud

Create the site manually in the Tableau Cloud admin UI. Note the **content URL** (the URL slug, e.g. `newclient`).

### 2. Create a Connected App on the site

Go to the new site's **Settings > Connected Apps > New Connected App > Direct Trust**:

1. Name it (e.g. "Admin Toolkit")
2. Set it to **Enabled**
3. Click **Generate New Secret**
4. Save the three values:
   - **Client ID** (on the Connected App page)
   - **Secret ID** (shown after generating)
   - **Secret Value** (shown once — copy it immediately)

### 3. Set the environment variable

```bash
# macOS / Linux
export TCS_NEWCLIENT_SECRET="the_secret_value_here"
# Add to ~/.bashrc or ~/.zshrc for persistence

# Windows (persistent — open a new terminal afterwards)
setx TCS_NEWCLIENT_SECRET "the_secret_value_here"
```

### 4. Add the site to your config YAML

Add under `sites:` in your config file:

```yaml
  - name: "New Client"
    content_url: "newclient"
    jwt_client_id: "from-connected-app-page"
    jwt_secret_id: "from-generated-secret"
    jwt_secret_value: os.environ.get("TCS_NEWCLIENT_SECRET")
```

### 5. Run bootstrap

```bash
# Dry run first to verify
python tests/nomad_test_scenario.py --config config/tableau.yaml --phase bootstrap --dry-run

# Live run — safe to re-run; existing sites are skipped (idempotent)
python tests/nomad_test_scenario.py --config config/tableau.yaml --phase bootstrap
```

Bootstrap is idempotent: existing projects and groups are detected and skipped, new ones are created. You can safely run it against all sites whenever a new site is added.

## Architecture: Orchestrators vs Building Blocks

The modules fall into two categories:

### Orchestrators (main workflows — these are what you run)

| Module | What it does | Uses |
|---|---|---|
| **`bootstrap.py`** | Sets up a new site end-to-end: creates the folder tree, groups, provisions users, applies permissions. Run once per client onboard, or `bootstrap-all` for every site. | `create/projects.py`, `create/groups.py`, `create/users.py`, `governance/permissions.py` |
| **`publish/batch.py`** | Publishes all workbooks or datasources in a directory to every enabled site. The main deployment command. | `publish/workbooks.py`, `publish/datasources.py`, `session.py` |
| **`migrate.py`** | Downloads content from a Server instance and uploads it to Cloud. Resumable via JSON state file. | `publish/workbooks.py`, `publish/datasources.py`, `catalog.py`, `session.py` |
| **`maintenance/alerts.py`** | Polls for failed extract refreshes and sends Slack/email notifications. Run on a schedule (cron). | `monitoring/jobs.py`, `config.py` |
| **`cli.py`** | Typer-based CLI that wires every operation into a command. The entry point for all human interaction. | Everything |
| **`tests/nomad_test_scenario.py`** | 5-phase end-to-end test harness with `--dry-run` support. | `bootstrap.py`, `publish/batch.py`, `stats.py` |

### Building Blocks (contextual modules — used by orchestrators, or standalone for one-off tasks)

All building blocks accept an optional `conn` parameter. Orchestrators open one authenticated session per site and inject it so all operations target the correct site without redundant sign-ins.

| Module | What it does | Standalone use |
|---|---|---|
| **`config.py`** | Loads `tableau.yaml`, merges `site_defaults` into sites, resolves env var references. The foundation everything reads from. | `show-config` |
| **`session.py`** | Creates authenticated connections via PAT or JWT. `authenticated_session()` for default site, `authenticated_session_for_site()` for multi-site loops with automatic auth method selection. | N/A (used by everything) |
| **`manifest.py`** | Thin wrapper for site validation — compares config sites against what the API returns. | `validate-manifest`, `list-manifest-sites` |
| **`catalog.py`** | Lists and deletes sites, projects, workbooks, datasources, views. Read/delete only. | `sites`, `projects`, `workbooks`, `datasources`, `views`, `delete-wb`, `delete-ds` |
| **`create/users.py`** | User CRUD + bulk provisioning from CSV. | `create-user-cmd`, `bulk-users`, `list-users-cmd`, `delete-user-cmd` |
| **`create/groups.py`** | Group CRUD + membership management. | `create-group-cmd`, `list-groups-cmd`, `group-add`, `remove-group-user`, `delete-group-cmd` |
| **`create/projects.py`** | Project CRUD with idempotent `ensure_project`. | `delete-project-cmd` |
| **`publish/workbooks.py`** | Publishes a single workbook with optional embedded SA credentials. Also handles downloads and promotions. | `publish-wb`, `download-wb` |
| **`publish/datasources.py`** | Publishes a single datasource. Also handles downloads and extract refreshes. | `publish-ds`, `download-ds`, `refresh-ds` |
| **`maintenance/extracts.py`** | Triggers extract refreshes with polling and auto-alerting on failure. | `refresh-ds` |
| **`maintenance/schedules.py`** | Extract schedule management. Server only — raises on Cloud. | N/A (Server only) |
| **`governance/permissions.py`** | Compares current vs desired permissions and applies diffs. | Called by `bootstrap.py` |
| **`governance/audit.py`** | Finds stale content and failed jobs. | Standalone reporting |
| **`flows/flows.py`** | Prep flow lifecycle: list, publish, trigger, poll for completion. | `list-flows-cmd`, `publish-flow-cmd`, `run-flow`, `flow-status` |
| **`monitoring/jobs.py`** | Job history snapshots. | Called by `alerts.py` |
| **`stats.py`** | JSON-backed run statistics at `~/.tableau-admin/run_stats.json`. Tracks job-level pass/fail and success rate. | `stats` |
| **`logging_setup.py`** | Centralized logging config. All output to stderr, JSON data to stdout (pipeable). | N/A (auto-initialized) |

### How They Connect

```
tableau.yaml
    │
    ▼
config.py ──→ session.py ──→ Tableau REST API (JWT or PAT per site)
    │
    ▼
┌─────────────────────────────────────────────────┐
│              ORCHESTRATORS                       │
│                                                  │
│  bootstrap.py ──→ create/projects.py             │
│                   create/groups.py                │
│                   create/users.py                 │
│                   governance/permissions.py       │
│                                                  │
│  publish/batch.py ──→ publish/workbooks.py       │
│                       publish/datasources.py     │
│                                                  │
│  migrate.py ──→ publish/workbooks.py             │
│                 publish/datasources.py            │
│                 catalog.py                        │
│                                                  │
│  maintenance/alerts.py ──→ monitoring/jobs.py    │
└─────────────────────────────────────────────────┘
    │
    ▼
stats.py (records pass/fail per run)
```

## Typical Workflows

### New Client Onboarding
```bash
# 1. Create site on Tableau Cloud + Connected App (see "Adding a New Site")
# 2. Add site to config YAML + set env var
# 3. Bootstrap (creates folders, groups, users)
python tests/nomad_test_scenario.py --config config/tableau.yaml --phase bootstrap

# 4. Publish standard workbooks and datasources
python -m admin.cli batch-publish-wb ./workbooks/ --embed-creds --cred-username sa_user --cred-password sa_pass
python -m admin.cli batch-publish-ds ./datasources/
```

### Daily Operations
```bash
# Publish updated workbooks to all sites
python -m admin.cli batch-publish-wb ./workbooks/

# Check for failed extracts and alert
python -m admin.cli check-extract-alerts --lookback 120

# Review run history
python -m admin.cli stats --last 10
```

### Server-to-Cloud Migration
```bash
# You need two config files, one per environment, both in the same format as
# config/tableau.example.yaml: config/tableau_server.yaml (source, with
# deployment_target: server) and config/tableau_cloud.yaml (target)

# Plan: query source, map content to target sites
python -m admin.cli migrate-plan \
  --source-config ./config/tableau_server.yaml \
  --target-config ./config/tableau_cloud.yaml

# Execute (resumable — safe to re-run on failure)
python -m admin.cli migrate-execute migration_plan.json \
  --source-config ./config/tableau_server.yaml \
  --target-config ./config/tableau_cloud.yaml \
  --embed-creds --cred-username sa_user --cred-password sa_pass
```

### Validate Everything Matches
```bash
# Check that config sites exist on the server
python -m admin.cli validate-manifest

# View what the config resolves to
python -m admin.cli list-manifest-sites

# Dashboard data validation against source DB
python -m validation.cli compare <view-id> ./sql/reference.sql --metric revenue
```

## Getting Started

Requires Python 3.10 or newer.

1. Clone the repo and install dependencies into a virtual environment:
   ```bash
   git clone https://github.com/aaronlaporte/tableau-admin-toolkit.git
   cd tableau-admin-toolkit
   python3 -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Copy the config template:
   ```bash
   cp config/tableau.example.yaml config/tableau.yaml
   ```

3. Edit `config/tableau.yaml` — server URL, site list, and auth credentials. The standardized folder structure and groups are already defined in `site_defaults`. Secrets should be stored as environment variables:
   ```yaml
   jwt_secret_value: os.environ.get("TCS_SITENAME_SECRET")
   ```

4. Validate your setup:
   ```bash
   python tests/nomad_test_scenario.py --config config/tableau.yaml --dry-run   # offline check
   python -m admin.cli show-config
   python -m admin.cli validate-manifest
   ```

Run `python -m admin.cli --help` for the full command list.

## Server and Cloud Support

Set `deployment_target: cloud` or `deployment_target: server` in your config. Cloud differences are handled automatically:

- **Authentication**: Cloud sites use JWT (Connected Apps) or per-site PATs. Server can use a single PAT or username/password.
- Schedule management (`/schedules` endpoint) is Server-only; the toolkit warns and skips on Cloud.
- The site manifest replaces internal Postgres queries that are only available on Server.

For migration, create two config files (one Server, one Cloud) and pass them to `migrate-plan` / `migrate-execute`.

## Folder Structure (per site)

Defined once in `site_defaults`, created on every site by `bootstrap`. Visible under Tableau's Explore sidebar:

```
Data Sources/
└── Billing Ledger/               <- datasources publish here
Client Reports/
├── Executive Reports/
├── Standard Reports/             <- workbooks publish here
└── Ad Hoc/
```

The toolkit manages this standardized structure. Any client-specific custom folders or content are created manually in Tableau.

## Alerting & Notifications

- **Slack**: set `alerts.slack_webhook` in `tableau.yaml`.
- **Email/SMTP**: set `alerts.smtp` values plus `alerts.email_recipients` in the same file.
- When SMTP isn't configured, email alerts are skipped and a warning is logged.
- `check-extract-alerts` polls for failed extract jobs and sends notifications.

## Suggested Maintenance Schedule

| Frequency | Task | Command / Action |
|---|---|---|
| **Per new client** | Create site, Connected App, add to config, bootstrap | See "Adding a New Site" above |
| **As needed** | Publish updated workbooks/datasources to all sites | `batch-publish-wb` / `batch-publish-ds` |
| **Daily** | Check for failed extract refreshes | `check-extract-alerts --lookback 1440` |
| **Weekly** | Review run statistics for failures | `stats --last 20` |
| **Weekly** | Audit stale content and failed jobs | `governance/audit.py` |
| **Monthly** | Re-run bootstrap to verify all sites match the template | `--phase bootstrap` (idempotent — safe to re-run) |
| **Monthly** | Review Tableau Cloud Connected App status | Tableau Cloud UI — confirm all apps are Enabled |
| **Quarterly** | Review user provisioning — deactivate departed users | `list-users-cmd` per site, cross-reference with HR |
| **Quarterly** | Review group membership alignment | `list-groups-cmd` + `group-members` per site |
| **Never** | Rotate Connected App secrets | JWT secrets don't expire. Only rotate if compromised. |

## Directory Layout

```
tableau-admin-toolkit/
├── README.md
├── LICENSE
├── requirements.txt
├── config/
│   ├── tableau.example.yaml          # Config template — copy to tableau.yaml
│   └── tableau.yaml                  # Your config (gitignored — keep local)
├── admin/
│   ├── __init__.py
│   ├── cli.py                        # CLI entry point (all commands)
│   ├── config.py                     # Config loader + site models + env var resolution
│   ├── config_loader.py              # Generic YAML helpers (env refs, overrides, defaults)
│   ├── session.py                    # Auth sessions (JWT + PAT, per-site)
│   ├── manifest.py                   # Site validation against API
│   ├── bootstrap.py                  # ORCHESTRATOR: site setup (idempotent)
│   ├── migrate.py                    # ORCHESTRATOR: Server-to-Cloud migration
│   ├── stats.py                      # Run statistics tracker (pass/fail per job)
│   ├── logging_setup.py              # Centralized logging
│   ├── catalog.py                    # Asset listing + deletion
│   ├── create/
│   │   ├── users.py                  # User CRUD + bulk provisioning
│   │   ├── groups.py                 # Group CRUD + membership
│   │   └── projects.py              # Project CRUD + scaffolding (idempotent)
│   ├── publish/
│   │   ├── workbooks.py              # Single workbook publish + embed creds
│   │   ├── datasources.py            # Single datasource publish
│   │   └── batch.py                  # ORCHESTRATOR: multi-site batch publish
│   ├── maintenance/
│   │   ├── extracts.py               # Extract refresh + auto-alerting
│   │   ├── schedules.py              # Schedule management (Server only)
│   │   └── alerts.py                 # ORCHESTRATOR: extract failure alerting
│   ├── governance/
│   │   ├── audit.py                  # Stale content, failed jobs
│   │   └── permissions.py            # Permission diff + apply
│   ├── flows/
│   │   └── flows.py                  # Prep flow management
│   └── monitoring/
│       └── jobs.py                   # Job status tracking
├── validation/
│   ├── cli.py
│   ├── config.py
│   ├── dashboards.py
│   ├── reference_sources.py
│   ├── comparator.py
│   └── alerts/
│       └── notifier.py
└── tests/
    ├── nomad_test_scenario.py         # 5-phase end-to-end test harness
    ├── nomad_test_users.csv           # 8 sample users
    ├── debug_login.ipynb              # Interactive auth debugging notebook
    ├── sample_workbooks/              # Place .twbx files here for testing (gitignored)
    └── sample_datasources/            # Place .tdsx/.hyper files here for testing (gitignored)
```

## CLI Quick Reference

| Command | Description |
|---|---|
| `show-config` | Print resolved config (secrets masked) |
| `validate-manifest` | Compare config sites vs Tableau API |
| `list-manifest-sites` | Show all enabled sites with publish targets |
| `bootstrap-site-cmd <url>` | Bootstrap one site |
| `bootstrap-all` | Bootstrap all enabled sites |
| `batch-publish-wb <dir>` | Publish all .twbx to all sites |
| `batch-publish-ds <dir>` | Publish all .tdsx/.hyper to all sites |
| `migrate-plan` | Plan a Server-to-Cloud migration |
| `migrate-execute <plan>` | Execute migration (resumable) |
| `publish-wb <path>` | Publish one workbook |
| `publish-ds <path>` | Publish one datasource |
| `download-wb <id> <path>` | Download a workbook |
| `download-ds <id> <path>` | Download a datasource |
| `refresh-ds <id>` | Trigger extract refresh |
| `check-extract-alerts` | Check for failed extracts, send alerts |
| `create-user-cmd <email>` | Create a user |
| `bulk-users <csv>` | Bulk provision from CSV |
| `create-group-cmd <name>` | Create a group |
| `list-flows-cmd` | List Prep flows |
| `run-flow <id>` | Trigger a flow run |
| `stats` | View run statistics |
| `sites` / `projects` / `workbooks` / `datasources` / `views` | List assets |
| `delete-wb` / `delete-ds` / `delete-project-cmd` / `delete-user-cmd` / `delete-group-cmd` | Delete assets |

All multi-site commands accept `--config <path>` to use a specific config file. Most batch commands accept `--on-error continue|stop`.

## Test Scenario

A pre-built test harness for validating the toolkit against live sites. Point it at your own config file targeting sites that already exist on your Tableau Cloud pod.

```bash
# Dry run — validates config, no API calls
python tests/nomad_test_scenario.py --config config/tableau.yaml --dry-run

# Run specific phases
python tests/nomad_test_scenario.py --config config/tableau.yaml --phase config
python tests/nomad_test_scenario.py --config config/tableau.yaml --phase bootstrap
python tests/nomad_test_scenario.py --config config/tableau.yaml --phase publish

# Full live run
python tests/nomad_test_scenario.py --config config/tableau.yaml
```

Set your Connected App secret values as environment variables (matching the `os.environ.get(...)` references in your YAML) and run. The `site_defaults` template handles the rest.

## Python Tooling

- Primary SDK: [`tableau-api-lib`](https://github.com/tableau/tableau-api-lib)
- Supplementary SDK: [`tableauserverclient`](https://github.com/tableau/server-client-python) (flows, metadata, async jobs)
- JWT: [`PyJWT`](https://pyjwt.readthedocs.io/) (Connected App authentication)
- CLI: [`typer`](https://typer.tiangolo.com)
- Config: `pydantic` + YAML. One file, secrets via environment variables.
- Validation: `pandas` + `SQLAlchemy` for reference-query comparisons.

## License

MIT — see [LICENSE](LICENSE).
