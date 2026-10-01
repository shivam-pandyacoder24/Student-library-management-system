"""SQLite access helpers and schema. Uses only Python's built-in sqlite3 module."""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('student', 'faculty', 'librarian')),
    department    TEXT,
    password_hash TEXT,
    is_demo       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS books (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    author         TEXT NOT NULL,
    category       TEXT NOT NULL,
    isbn           TEXT,
    published_year INTEGER,
    total_copies   INTEGER NOT NULL DEFAULT 1 CHECK (total_copies >= 0),
    is_active      INTEGER NOT NULL DEFAULT 1,
    added_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    added_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS loans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id     INTEGER NOT NULL REFERENCES books(id),
    issued_at   TEXT NOT NULL,
    due_at      TEXT NOT NULL,
    returned_at TEXT
);

CREATE TABLE IF NOT EXISTS login_failures (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lock_key   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_loans_user   ON loans(user_id);
CREATE INDEX IF NOT EXISTS idx_loans_book   ON loans(book_id);
CREATE INDEX IF NOT EXISTS idx_loans_open   ON loans(returned_at);
CREATE INDEX IF NOT EXISTS idx_failures    ON login_failures(lock_key, created_at);
CREATE INDEX IF NOT EXISTS idx_books_active ON books(is_active, category);
"""

TS_FORMAT = "%Y-%m-%d %H:%M:%S"


# ---------- time helpers (everything is stored in UTC) ----------

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_ts(dt):
    return dt.strftime(TS_FORMAT)


def from_ts(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.strptime(value, TS_FORMAT)


def now_ts(offset_days=0):
    return to_ts(utcnow() + timedelta(days=offset_days))


# ---------- connection handling ----------

def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def scalar(sql, args=()):
    row = get_db().execute(sql, args).fetchone()
    return row[0] if row else None


def execute(sql, args=(), commit=True):
    conn = get_db()
    cur = conn.execute(sql, args)
    if commit:
        conn.commit()
    return cur


def init_schema(conn):
    conn.executescript(SCHEMA)
    # Databases made by the earlier email-code version have no password column yet.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "password_hash" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    conn.commit()
