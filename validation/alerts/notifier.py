"""
Slack / email alert notifications.

``Notifier`` delivers messages over a Slack incoming webhook or SMTP.
``notify_slack`` / ``notify_email`` build one from the validation config so
callers don't have to pass connection details around.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import smtplib
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Optional

from ..config import load_validation_config

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        *,
        slack_webhook: str | None = None,
        smtp_host: str | None = None,
        smtp_port: int = 587,
        smtp_sender: str | None = None,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        smtp_use_tls: bool = True,
        default_recipients: list[str] | None = None,
    ):
        self.slack_webhook = slack_webhook
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_sender = smtp_sender or smtp_username
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.smtp_use_tls = smtp_use_tls
        self.default_recipients: list[str] = default_recipients or []

    # ── Slack ─────────────────────────────────────────────────────────────────

    def slack(self, message: str, *, extra: dict | None = None) -> None:
        if not self.slack_webhook:
            logger.warning("Slack webhook not configured; skipping")
            return
        payload: dict = {"text": message}
        if extra:
            payload.update(extra)
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.slack_webhook,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        logger.info("Slack notification sent")

    # ── Email ─────────────────────────────────────────────────────────────────

    def email(
        self,
        subject: str,
        body: str,
        recipients: Iterable[str] | None = None,
        attachments: list[str | Path] | None = None,
    ) -> None:
        rcpts = list(recipients or self.default_recipients)
        if not rcpts:
            logger.warning("No email recipients configured; skipping")
            return
        if not self.smtp_host:
            logger.warning("SMTP not configured; email skipped: %s", subject)
            return

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp_sender
        msg["To"] = ", ".join(rcpts)
        msg.set_content(body)

        for attachment in attachments or []:
            p = Path(attachment)
            if not p.exists():
                logger.warning("Attachment not found, skipping: %s", p)
                continue
            mime, _ = mimetypes.guess_type(p.name)
            maintype, subtype = mime.split("/", 1) if mime else ("application", "octet-stream")
            with p.open("rb") as fh:
                msg.add_attachment(fh.read(), maintype=maintype, subtype=subtype, filename=p.name)

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as client:
            if self.smtp_use_tls:
                client.starttls()
            if self.smtp_username and self.smtp_password:
                client.login(self.smtp_username, self.smtp_password)
            client.send_message(msg)
        logger.info("Email sent to %s", ", ".join(rcpts))


def _notifier() -> Notifier:
    cfg = load_validation_config()
    s = cfg.smtp
    return Notifier(
        slack_webhook=cfg.slack_webhook,
        smtp_host=s.host,
        smtp_port=s.port,
        smtp_sender=s.sender,
        smtp_username=s.username,
        smtp_password=s.password,
        smtp_use_tls=s.use_tls,
        default_recipients=cfg.email_recipients,
    )


def notify_slack(message: str, webhook_url: Optional[str] = None) -> None:
    n = _notifier()
    if webhook_url:
        n.slack_webhook = webhook_url
    if not n.slack_webhook:
        raise RuntimeError("Slack webhook is not configured.")
    n.slack(message)


def notify_email(subject: str, body: str, recipients: Optional[Iterable[str]] = None) -> None:
    n = _notifier()
    rcpts = list(recipients or []) or None
    if not rcpts and not n.default_recipients:
        raise RuntimeError("Email recipients are not configured.")
    n.email(subject, body, recipients=rcpts)
