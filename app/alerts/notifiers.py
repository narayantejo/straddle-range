"""
Alert channel dispatch (spec Section 40).

Dashboard alerts require no setup -- app.db.database.get_recent_alerts() is
the source of truth for the Alerts tab regardless of what's below.

Email and Telegram are OFF by default and only activate once you add the
matching credentials to .env; dispatch() silently skips (not errors) any
channel that isn't configured, so enabling a rule's "email" channel before
SMTP_* is set just means that channel is a no-op until you configure it.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

import requests

from app import config
from app.alerts.rules import CHANNEL_EMAIL, CHANNEL_TELEGRAM

logger = logging.getLogger(__name__)


def email_configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_USERNAME and config.SMTP_PASSWORD and config.ALERT_EMAIL_TO)


def telegram_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def send_email(subject: str, body: str) -> bool:
    if not email_configured():
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = config.SMTP_USERNAME
        msg["To"] = config.ALERT_EMAIL_TO
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("Email alert send failed: %s", e)
        return False


def send_telegram(message: str) -> bool:
    if not telegram_configured():
        return False
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url, json={"chat_id": config.TELEGRAM_CHAT_ID, "text": message}, timeout=15
        )
        return resp.status_code == 200
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram alert send failed: %s", e)
        return False


def dispatch(channels: list[str], message: str) -> list[str]:
    """Sends to every requested channel that's actually configured.
    Returns the list of channels that were successfully sent (dashboard is
    implicit -- it's the alert_log row itself, so it's never included here)."""
    sent: list[str] = []
    if CHANNEL_EMAIL in channels and send_email("F&O Scanner Alert", message):
        sent.append(CHANNEL_EMAIL)
    if CHANNEL_TELEGRAM in channels and send_telegram(message):
        sent.append(CHANNEL_TELEGRAM)
    return sent
