"""App configuration, read from environment variables (see .env.example)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name, default=""):
    """Read an env var, treating empty strings as unset."""
    value = os.environ.get(name, "")
    return value.strip() if value and value.strip() else default


def _flag(name, default=False):
    return _env(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = _env("SECRET_KEY", "dev-only-change-me")
    LIBRARY_NAME = _env("LIBRARY_NAME", "Campus Library")

    # Database: a single SQLite file. On PythonAnywhere this persists between restarts.
    DATABASE_PATH = _env("DATABASE_PATH", str(BASE_DIR / "instance" / "library.db"))

    # Faculty and librarian sign-ups must enter this code, so students can't make
    # themselves librarians.
    STAFF_ACCESS_CODE = _env("STAFF_ACCESS_CODE", "staff123")

    # Demo data and one-click demo logins (handy for reviewers). Turn off in real use.
    SEED_DEMO_DATA = _flag("SEED_DEMO_DATA", True)
    ENABLE_DEMO_LOGIN = _flag("ENABLE_DEMO_LOGIN", True)

    # Library rules
    LOAN_DAYS = int(_env("LOAN_DAYS", "14"))
    MAX_ACTIVE_LOANS = int(_env("MAX_ACTIVE_LOANS", "3"))
    FINE_PER_DAY = int(_env("FINE_PER_DAY", "5"))  # rupees
    DISPLAY_TIMEZONE = _env("DISPLAY_TIMEZONE", "Asia/Kolkata")

    # OTP
    OTP_TTL_MINUTES = 10
    OTP_MAX_ATTEMPTS = 5
    OTP_RESEND_SECONDS = 45
    OTP_MAX_PER_HOUR = 6

    # Email. Provider is picked automatically:
    #   BREVO_API_KEY set           -> Brevo HTTPS API (works on Render's free tier)
    #   SMTP_HOST + SMTP_USERNAME   -> SMTP, e.g. Gmail with an App Password (works on PythonAnywhere)
    #   neither                     -> demo mode: the code is shown on screen and printed to the log
    MAIL_FROM_EMAIL = _env("MAIL_FROM_EMAIL", _env("SMTP_USERNAME", ""))
    MAIL_FROM_NAME = _env("MAIL_FROM_NAME", LIBRARY_NAME)
    BREVO_API_KEY = _env("BREVO_API_KEY")
    SMTP_HOST = _env("SMTP_HOST")
    SMTP_PORT = int(_env("SMTP_PORT", "587"))
    SMTP_USERNAME = _env("SMTP_USERNAME")
    SMTP_PASSWORD = _env("SMTP_PASSWORD").replace(" ", "")  # Gmail shows app passwords with spaces
    SMTP_USE_SSL = _flag("SMTP_USE_SSL", False)

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7
