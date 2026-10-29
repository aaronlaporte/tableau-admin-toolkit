"""
Validation configuration helpers.
"""
from __future__ import annotations

from os import getenv
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from admin.config import load_config


class SMTPSettings(BaseModel):
    """Settings for outbound email notifications."""

    host: Optional[str] = None
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    use_tls: bool = True
    sender: Optional[str] = None


class ValidationConfig(BaseModel):
    """Config shared across validation scripts."""

    compare_metric: str = "revenue"
    discrepancy_threshold_pct: float = 2.0
    reference_sql_path: Optional[str] = None
    alerts_enabled: bool = True
    slack_webhook: Optional[str] = None
    email_recipients: list[str] = Field(default_factory=list)
    smtp: SMTPSettings = Field(default_factory=SMTPSettings)


def load_validation_config(path: str | Path | None = None) -> ValidationConfig:
    """
    Merge admin config validation section with optional overrides file.
    """
    base_cfg = load_config()
    data = dict(base_cfg.validation or {})
    if path:
        overrides_path = Path(path)
        if overrides_path.exists():
            with overrides_path.open("r", encoding="utf-8") as handle:
                data.update(yaml.safe_load(handle) or {})

    alerts = base_cfg.alerts or {}
    data.setdefault("slack_webhook", alerts.get("slack_webhook"))
    data.setdefault("email_recipients", alerts.get("email_recipients", []))

    smtp_config = {
        **(alerts.get("smtp") or {}),
        **(data.get("smtp") or {}),
    }
    env_overrides = {
        "host": getenv("TABLEAU_ALERT_SMTP_HOST"),
        "port": getenv("TABLEAU_ALERT_SMTP_PORT"),
        "username": getenv("TABLEAU_ALERT_SMTP_USERNAME"),
        "password": getenv("TABLEAU_ALERT_SMTP_PASSWORD"),
        "sender": getenv("TABLEAU_ALERT_SMTP_SENDER"),
        "use_tls": getenv("TABLEAU_ALERT_SMTP_USE_TLS"),
    }
    for key, value in env_overrides.items():
        if value is None:
            continue
        if key == "port":
            smtp_config[key] = int(value)
        elif key == "use_tls":
            smtp_config[key] = value.lower() not in {"0", "false", "no"}
        else:
            smtp_config[key] = value
    data["smtp"] = smtp_config

    return ValidationConfig(**data)
