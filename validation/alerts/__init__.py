"""
Alerting helpers for validation discrepancies.
"""

from .notifier import notify_email, notify_slack

__all__ = ["notify_slack", "notify_email"]
