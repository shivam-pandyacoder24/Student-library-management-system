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

    # Passwords and sign-in
    MIN_PASSWORD_LENGTH = 8
    LOGIN_MAX_FAILURES = 5     # wrong passwords before the account is paused...
    LOGIN_LOCK_MINUTES = 15    # ...for this many minutes

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7
