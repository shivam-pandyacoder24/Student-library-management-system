"""Sign up and sign in with a password. One account per email address."""
import hmac
import re
from datetime import timedelta

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import execute, from_ts, now_ts, query, scalar, to_ts, utcnow
from .utils import home_for, log_in

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
ROLES = ("student", "faculty", "librarian")
HASH_METHOD = "pbkdf2:sha256"  # available on every Python build
# Compared against when the account doesn't exist, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = generate_password_hash("not-a-real-password", method=HASH_METHOD)


def hash_password(password):
    return generate_password_hash(password, method=HASH_METHOD)


def password_problems(password, confirm=None):
    """Return a list of reasons the password isn't acceptable (empty if it's fine)."""
    min_len = current_app.config["MIN_PASSWORD_LENGTH"]
    problems = []
    if len(password) < min_len:
        problems.append(f"Use a password of at least {min_len} characters.")
    elif password.isdigit() or password.isalpha():
        problems.append("Mix letters with numbers or symbols in your password.")
    if len(password) > 128:
        problems.append("Passwords can be at most 128 characters.")
    if confirm is not None and password != confirm:
        problems.append("The two passwords don't match.")
    return problems


# ---------- failed sign-in tracking ----------

def _lock_key(user, identifier):
    return f"user:{user['id']}" if user else f"name:{identifier.lower()}"


def _minutes_locked(key):
    cfg = current_app.config
    since = to_ts(utcnow() - timedelta(minutes=cfg["LOGIN_LOCK_MINUTES"]))
    failures = scalar("SELECT COUNT(*) FROM login_failures WHERE lock_key = ? AND created_at >= ?", (key, since))
    if failures < cfg["LOGIN_MAX_FAILURES"]:
        return 0
    oldest = scalar(
        "SELECT created_at FROM login_failures WHERE lock_key = ? AND created_at >= ? ORDER BY created_at"
        " LIMIT 1 OFFSET ?", (key, since, failures - cfg["LOGIN_MAX_FAILURES"]))
    unlock = from_ts(oldest) + timedelta(minutes=cfg["LOGIN_LOCK_MINUTES"])
    return max(1, round((unlock - utcnow()).total_seconds() / 60))


def _safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


def _shelf_books(limit=30):
    """Books for the decorative shelf on the sign-in page, mixing categories round-robin."""
    by_cat = {}
    for b in query("SELECT id, title, author, category FROM books WHERE is_active = 1 ORDER BY id"):
        by_cat.setdefault(b["category"], []).append(b)
    shelf, piles = [], list(by_cat.values())
    while piles and len(shelf) < limit:
        for pile in piles:
            if pile and len(shelf) < limit:
                shelf.append(pile.pop(0))
        piles = [p for p in piles if p]
    return shelf


# ---------- routes ----------

@bp.route("/")
def index():
    if g.user:
        return redirect(home_for(g.user))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_for(g.user))
    identifier = ""
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        user = query("SELECT * FROM users WHERE username = ? OR email = ?", (identifier, identifier), one=True)
        key = _lock_key(user, identifier)
        locked = _minutes_locked(key) if identifier else 0

        if not identifier or not password:
            flash("Enter your username or email, and your password.", "error")
        elif locked:
            flash(f"Too many wrong attempts. Try again in {locked} minute{'s' if locked != 1 else ''}.", "error")
        elif user and user["is_demo"] and not user["password_hash"]:
            flash("That's a demo account. Use the demo buttons below to open it.", "info")
        elif user and user["password_hash"] and check_password_hash(user["password_hash"], password):
            execute("DELETE FROM login_failures WHERE lock_key = ?", (key,))
            execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_ts(), user["id"]))
            log_in(user["id"])
            flash(f"Welcome back, {user['full_name'].split()[0]}.", "success")
            return redirect(_safe_next(request.args.get("next")) or home_for(user))
        else:
            if not user:
                check_password_hash(_DUMMY_HASH, password)
            execute("INSERT INTO login_failures (lock_key, created_at) VALUES (?, ?)", (key, now_ts()))
            flash("Wrong username, email or password. Check them and try again.", "error")
    return render_template("auth/login.html", identifier=identifier, shelf=_shelf_books())


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(home_for(g.user))
    form = {k: request.form.get(k, "").strip() for k in ("full_name", "username", "email", "role", "department")}
    form["email"] = form["email"].lower()
    form["role"] = form["role"] or "student"
    if request.method == "POST":
        password = request.form.get("password", "")
        errors = []
        if not 2 <= len(form["full_name"]) <= 60:
            errors.append("Enter your full name (2–60 characters).")
        if not USERNAME_RE.match(form["username"]):
            errors.append("Usernames are 3–30 characters: letters, numbers, dots and underscores.")
        if not EMAIL_RE.match(form["email"]):
            errors.append("Enter a valid email address.")
        errors += password_problems(password, request.form.get("confirm_password", ""))
        if form["role"] not in ROLES:
            errors.append("Choose student, faculty or librarian.")
        elif form["role"] != "student":
            code = request.form.get("staff_code", "").strip()
            if not hmac.compare_digest(code, current_app.config["STAFF_ACCESS_CODE"]):
                errors.append("The staff access code is incorrect. Ask the librarian for it.")
        if not errors:
            if query("SELECT 1 FROM users WHERE email = ?", (form["email"],), one=True):
                errors.append("An account with that email already exists. Sign in instead.")
            if query("SELECT 1 FROM users WHERE username = ?", (form["username"],), one=True):
                errors.append("That username is taken. Try another one.")
        if errors:
            for message in errors:
                flash(message, "error")
        else:
            cur = execute(
                "INSERT INTO users (username, email, full_name, role, department, password_hash, created_at, last_login_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (form["username"], form["email"], form["full_name"], form["role"], form["department"] or None,
                 hash_password(password), now_ts(), now_ts()),
            )
            log_in(cur.lastrowid)
            flash(f"Welcome, {form['full_name'].split()[0]}. Your account is ready.", "success")
            return redirect(url_for({"student": "student.dashboard", "faculty": "faculty.dashboard",
                                     "librarian": "librarian.dashboard"}[form["role"]]))
    return render_template("auth/signup.html", form=form, shelf=_shelf_books())


@bp.route("/demo/<role>", methods=["POST"])
def demo_login(role):
    if not current_app.config["ENABLE_DEMO_LOGIN"] or role not in ROLES:
        flash("Demo sign-in is turned off on this server.", "error")
        return redirect(url_for("auth.login"))
    user = query("SELECT * FROM users WHERE is_demo = 1 AND role = ? ORDER BY id LIMIT 1", (role,), one=True)
    if user is None:
        flash("There's no demo account for that role yet.", "error")
        return redirect(url_for("auth.login"))
    log_in(user["id"])
    flash(f"You're exploring as {user['full_name']}, a demo {role}.", "success")
    return redirect(home_for(user))


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You've signed out.", "info")
    return redirect(url_for("auth.login"))
