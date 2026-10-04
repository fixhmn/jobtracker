import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str
    database_path: Path = Path("data/jobtracker.db")
    api_base_url: str = "http://127.0.0.1:8000"
    timezone: str = "America/Chicago"
    telegram_bot_token: str = ""
    owner_telegram_id: int = 0
    worker_poll_seconds: int = 15

    @classmethod
    def from_env(cls, *, telegram: bool = False):
        load_dotenv()
        key = os.getenv("API_KEY", "").strip()
        if len(key) < 24:
            raise ValueError("Set API_KEY to a random string of at least 24 characters in .env")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        owner = int(os.getenv("OWNER_TELEGRAM_ID", "") or 0)
        if telegram and (not token or owner <= 0):
            raise ValueError("Set TELEGRAM_BOT_TOKEN and a positive OWNER_TELEGRAM_ID in .env")
        timezone = os.getenv("TIMEZONE", "America/Chicago")
        ZoneInfo(timezone)
        poll = int(os.getenv("WORKER_POLL_SECONDS", "15"))
        if not 1 <= poll <= 3600:
            raise ValueError("WORKER_POLL_SECONDS must be between 1 and 3600")
        return cls(
            api_key=key,
            database_path=Path(os.getenv("DATABASE_PATH", "data/jobtracker.db")),
            api_base_url=os.getenv("API_BASE_URL", "http://127.0.0.1:8000"),
            timezone=timezone,
            telegram_bot_token=token,
            owner_telegram_id=owner,
            worker_poll_seconds=poll,
        )
