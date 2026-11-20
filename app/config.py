"""Configuration. Secrets come from environment variables / a private .env file only."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env = BASE_DIR / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

DB_PATH = os.environ.get("UPSC_DB_PATH", str(BASE_DIR / "data" / "hub.sqlite3"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")  # empty => admin disabled
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")  # must be set for admin login
TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Kolkata")
USER_AGENT = "UPSC-GS-Hub/0.2 (personal study tool for exam preparation; low-volume, respects robots/terms)"
FETCH_TIMEOUT = int(os.environ.get("FETCH_TIMEOUT", "20"))

# Optional integrations. Never hard-code values here.
ANTHROPIC_API_KEY_SET = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
# The model name is NOT guessed: set ANTHROPIC_MODEL yourself in .env (see README).
AI_MAX_BULK = int(os.environ.get("AI_MAX_BULK", "10"))
# Automatic refresh every N minutes (each source also honours its own interval). 0 = off.
AI_AUTO_MAX = int(os.environ.get("AI_AUTO_MAX", "40"))  # notes written automatically after each fetch (only when AI is on)
FETCH_EVERY_MIN = int(os.environ.get("FETCH_EVERY_MIN", "30"))

# Audio news bulletin: where MP3 files are kept (keep this OUTSIDE OneDrive if you can) and how many days to keep them.
AUDIO_DIR = os.environ.get("UPSC_AUDIO_DIR", str(BASE_DIR / "data" / "audio"))
AUDIO_KEEP_DAYS = int(os.environ.get("AUDIO_KEEP_DAYS", "7"))

# Set COOKIE_SECURE=1 when the site is served over https (any public host).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "") == "1"
