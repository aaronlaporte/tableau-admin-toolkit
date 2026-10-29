"""
Shared configuration utilities for Tableau admin tooling.

Everything lives in a single YAML file (``config/tableau.yaml`` by default):
connection details, PAT credentials, site definitions, alert settings, and
operational defaults.  Environment variables can still override individual
fields when set globally, but the YAML is fully self-contained.

Site definitions are minimal (name + content_url + enabled).  The standardized
folder structure, publish targets, and group templates are defined once in
``site_defaults`` and applied to every site at load time.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .config_loader import apply_defaults, env_override, load_yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parents[1] / "config" / "tableau.yaml"

# Cached config — once loaded, subsequent load_config() calls with no path
# reuse the same instance.  This avoids every building-block module needing
# the config path threaded through its function signature.
_cached_config: Optional["TableauConfig"] = None


# ── Site definition models ──────────────────────────────────────────────


class SiteGroupDef(BaseModel):
    """A group to create/maintain on a site."""

    name: str
    minimum_site_role: str = "Viewer"


class SubProjectDef(BaseModel):
    """
    A project folder that can contain nested children.

    Supports arbitrary depth so the manifest can describe full directory
    trees like::

        Data Sources/
        └── Billing Ledger/
        Client Reports/
        ├── Executive Reports/
        ├── Standard Reports/
        └── Ad Hoc/
    """

    name: str
    children: list["SubProjectDef"] = Field(default_factory=list)



class SiteDefinition(BaseModel):
    """One managed Tableau site."""

    name: str
    content_url: str
    target_workbook_project: str = ""
    target_datasource_project: str = ""
    sub_projects: list[SubProjectDef] = Field(default_factory=list)
    groups: list[SiteGroupDef] = Field(default_factory=list)
    enabled: bool = True

    # Per-site auth — overrides top-level credentials when set.
    auth_method: str = Field(
        default="pat",
        description="'pat' for Personal Access Token, 'jwt' for Connected App (JWT).",
    )
    # PAT fields (per-site override)
    pat_name: str = ""
    pat_secret: str = ""
    # JWT / Connected App fields
    jwt_client_id: str = ""
    jwt_secret_id: str = ""
    jwt_secret_value: str = ""
    jwt_username: str = Field(
        default="",
        description="Email of the user the JWT impersonates on this site.",
    )


# ── Main config model ───────────────────────────────────────────────────


class TableauConfig(BaseModel):
    """Pydantic model for the unified Tableau configuration file."""

    # Connection
    server: str
    pat_name: str = ""
    pat_secret: str = ""
    site: str = Field(default="default", alias="default_site")
    api_version: str = "3.23"
    deployment_target: str = Field(
        default="server",
        description="Where this toolkit points: 'server' or 'cloud'.",
        pattern="^(server|cloud)$",
    )

    # Sites
    sites: List[SiteDefinition] = Field(default_factory=list)

    # Operational defaults
    default_project: str = "Default"
    default_owner: Optional[str] = None
    content_paths: Dict[str, str] = Field(default_factory=dict)
    extract_defaults: Dict[str, Any] = Field(default_factory=dict)
    validation: Dict[str, Any] = Field(default_factory=dict)
    alerts: Dict[str, Any] = Field(default_factory=dict)

    @property
    def is_cloud(self) -> bool:
        """True when the toolkit targets Tableau Cloud."""
        return self.deployment_target == "cloud"

    def enabled_sites(self) -> list[SiteDefinition]:
        """Return only sites marked as enabled."""
        return [s for s in self.sites if s.enabled]

    model_config = {"populate_by_name": True}


def load_config(config_path: str | Path | None = None) -> TableauConfig:
    """
    Load the unified YAML config into a :class:`TableauConfig` model.

    ``site_defaults`` are merged into every site entry at load time.  Group
    names support ``{site_name}`` as a template variable (e.g.
    ``"{site_name} Admins"`` becomes ``"Nomad-01 Admins"``).

    Environment variables override YAML values when set:

    * ``TABLEAU_SERVER``
    * ``TABLEAU_PAT_NAME``
    * ``TABLEAU_PAT_SECRET``
    * ``TABLEAU_SITE``
    * ``TABLEAU_API_VERSION``
    * ``TABLEAU_DEPLOYMENT_TARGET``
    """
    global _cached_config

    # If no path given and we already have a cached config, return it
    if config_path is None and _cached_config is not None:
        return _cached_config

    config_file = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    data = load_yaml(config_file)

    # Environment variables override YAML values when set
    env_override(data, "TABLEAU_SERVER", "server")
    env_override(data, "TABLEAU_PAT_NAME", "pat_name")
    env_override(data, "TABLEAU_PAT_SECRET", "pat_secret")
    env_override(data, "TABLEAU_SITE", "default_site")
    env_override(data, "TABLEAU_API_VERSION", "api_version")
    env_override(data, "TABLEAU_DEPLOYMENT_TARGET", "deployment_target", lower=True)

    # Apply site_defaults to each site
    defaults = data.pop("site_defaults", {})
    if defaults and "sites" in data:
        data["sites"] = [apply_defaults(site, defaults) for site in data["sites"]]

    cfg = TableauConfig.model_validate(data)
    logger.info(
        "Loaded config from %s — server=%s, deployment=%s, %d sites (%d enabled)",
        config_file,
        cfg.server,
        cfg.deployment_target,
        len(cfg.sites),
        len(cfg.enabled_sites()),
    )

    # Cache so downstream modules that call load_config() with no args get
    # the same config that was loaded with the explicit path
    _cached_config = cfg
    return cfg


