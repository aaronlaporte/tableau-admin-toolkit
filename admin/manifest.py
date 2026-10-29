"""
Site manifest helpers: convenience access to sites from the unified config
and validation against the live Tableau REST API.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .catalog import list_sites
from .config import TableauConfig, SiteDefinition, load_config

logger = logging.getLogger(__name__)


def load_manifest(config_path: str | Path | None = None) -> TableauConfig:
    """
    Load the unified config and return it.

    This is a convenience alias — callers that only need site definitions
    can use ``cfg.sites`` / ``cfg.enabled_sites()`` directly.
    """
    return load_config(config_path)


def validate_manifest_against_api(
    config: Optional[TableauConfig] = None,
) -> dict[str, list[str]]:
    """
    Compare the sites in config against what the Tableau REST API returns.

    Returns a dict with three keys:

    * ``matched`` — content URLs present in both config and API
    * ``manifest_only`` — content URLs in the config but not found via API
    * ``api_only`` — content URLs returned by the API but missing from config
    """
    cfg = config or load_config()
    api_sites = list_sites()

    manifest_urls = {s.content_url for s in cfg.enabled_sites()}
    api_urls = {site.get("contentUrl", "") for site in api_sites}

    result = {
        "matched": sorted(manifest_urls & api_urls),
        "manifest_only": sorted(manifest_urls - api_urls),
        "api_only": sorted(api_urls - manifest_urls),
    }

    if result["manifest_only"]:
        logger.warning(
            "Sites in config but not found on server: %s",
            ", ".join(result["manifest_only"]),
        )
    if result["api_only"]:
        logger.info(
            "Sites on server but not in config: %s",
            ", ".join(result["api_only"]),
        )

    return result
