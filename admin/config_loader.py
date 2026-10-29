"""
Generic YAML config utilities used by :mod:`admin.config`.

Handles:
- Loading a YAML file into a plain dict
- Resolving os.environ.get("VAR") string references in YAML values
- Applying environment variable overrides
- Merging defaults into per-item configs with {name} template substitution
- Masking secrets for safe logging
"""
from __future__ import annotations

import copy
import logging
import re
from os import getenv
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ENV_REF_PATTERN = re.compile(r"""^os\.environ\.get\(\s*["']([^"']+)["']\s*\)$""")

_DEFAULT_SECRET_KEYS = frozenset({
    "pat_secret", "password", "secret", "token", "api_key",
    "jwt_secret_value", "jwt_secret_id", "webhook",
})


def load_yaml(path: str | Path) -> dict:
    """Load a YAML file, resolving any os.environ.get(...) references."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    resolve_env_refs(data)
    return data


def resolve_env_refs(data: Any) -> None:
    """
    Recursively replace os.environ.get("VAR") strings with their env values.
    Mutates the input in-place. Logs a warning for unset variables.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                m = _ENV_REF_PATTERN.match(value.strip())
                if m:
                    env_name = m.group(1)
                    resolved = getenv(env_name, "")
                    data[key] = resolved
                    if not resolved:
                        logger.warning("YAML references env var '%s' but it is not set", env_name)
                else:
                    resolve_env_refs(value)
            else:
                resolve_env_refs(value)
    elif isinstance(data, list):
        for item in data:
            resolve_env_refs(item)


def env_override(data: dict, env_key: str, yaml_key: str, lower: bool = False) -> None:
    """Apply a single environment variable override to a config dict."""
    value = getenv(env_key)
    if value:
        data[yaml_key] = value.lower() if lower else value


def apply_defaults(item: dict, defaults: dict) -> dict:
    """
    Merge a defaults dict into an item dict. The item's own keys win.
    Supports {name} and {site_name} template substitution in default values.
    Resolves any remaining env var references after merging.
    """
    merged = copy.deepcopy(defaults)
    merged.update(item)
    name = merged.get("name", "")
    _substitute_templates(merged, name)
    resolve_env_refs(merged)
    return merged


def mask_secrets(data: dict, secret_keys: frozenset | None = None) -> dict:
    """Return a deep copy of data with sensitive fields replaced by '***'."""
    keys = secret_keys if secret_keys is not None else _DEFAULT_SECRET_KEYS
    result = copy.deepcopy(data)
    _mask_recursive(result, keys)
    return result


def _substitute_templates(data: Any, name: str) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                data[key] = value.replace("{site_name}", name).replace("{name}", name)
            else:
                _substitute_templates(value, name)
    elif isinstance(data, list):
        for item in data:
            _substitute_templates(item, name)


def _mask_recursive(data: Any, secret_keys: frozenset) -> None:
    if isinstance(data, dict):
        for key in data:
            if any(sk in key.lower() for sk in secret_keys) and data[key]:
                data[key] = "***"
            else:
                _mask_recursive(data[key], secret_keys)
    elif isinstance(data, list):
        for item in data:
            _mask_recursive(item, secret_keys)
