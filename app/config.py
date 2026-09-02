import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

# Optional alert channels -- unset by default. Alerts always show on the
# in-app Alerts tab regardless of these; email/Telegram only fire once you
# add credentials here.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DB_PATH = ROOT_DIR / "data" / "scanner.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_ZONE_PCT = 0.05
DEFAULT_APPROACH_THRESHOLD_PCT = 0.10
DEFAULT_VERY_CLOSE_THRESHOLD_PCT = 0.01
DEFAULT_TOUCH_THRESHOLD_PCT = 0.001


def require_credentials() -> None:
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        raise RuntimeError(
            "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not set. "
            "Copy .env.example to .env and fill in your DhanHQ credentials."
        )
