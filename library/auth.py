"""Sign up and sign in with username + email, verified by a one-time code sent by email."""
import hashlib
import hmac
import json
import re
import secrets
from datetime import timedelta

from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)

from . import emailer
from .db import execute, from_ts, now_ts, query, scalar, to_ts, utcnow
from .utils import home_for, log_in

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
ROLES = ("student", "faculty", "librarian")


class OtpError(Exception):
    pass


# ---------- OTP helpers ----------

def _hash_code(email, code):
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{email.lower()}:{code}".encode(), hashlib.sha256).hexdigest()


def _check_send_limits(email):
    cfg = current_app.config
    last = query(
        "SELECT created_at FROM otp_codes WHERE email = ? ORDER BY id DESC LIMIT 1",
        (email,), one=True,
    )
    if last:
        wait = cfg["OTP_RESEND_SECONDS"] - int((utcnow() - from_ts(last["created_at"])).total_seconds())
        if wait > 0:
            raise OtpError(f"A code was just sent. You can request another in {wait} seconds.")
    hour_ago = to_ts(utcnow() - timedelta(hours=1))
    sent = scalar("SELECT COUNT(*) FROM otp_codes WHERE email = ? AND created_at >= ?", (email, hour_ago))
    if sent >= cfg["OTP_MAX_PER_HOUR"]:
        raise OtpError("Too many codes requested for this email. Try again in an hour.")


def issue_otp(email, name, purpose, payload):
    """Create a fresh code, email it, and remember it in the session."""
    _check_send_limits(email)
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = to_ts(utcnow() + timedelta(minutes=current_app.config["OTP_TTL_MINUTES"]))
    execute("UPDATE otp_codes SET used = 1 WHERE email = ? AND used = 0", (email,))
    cur = execute(
        "INSERT INTO otp_codes (email, purpose, code_hash, payload, created_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (email, purpose, _hash_code(email, code), json.dumps(payload), now_ts(), expires),
    )
    otp_id = cur.lastrowid
    try:
        emailer.send_otp_email(email, name, code, purpose)
    except emailer.EmailError as exc:
        execute("DELETE FROM otp_codes WHERE id = ?", (otp_id,))
        raise OtpError(f"We couldn't send the code to {email}. {exc}") from exc

    session["pending_otp"] = {"id": otp_id, "email": email, "purpose": purpose, "name": name}
    if emailer.is_demo_mode():
        session["demo_code"] = code
    else:
        session.pop("demo_code", None)


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
    form = {"username": "", "email": ""}
    if request.method == "POST":
        form["username"] = request.form.get("username", "").strip()
        form["email"] = request.form.get("email", "").strip().lower()
        user = query(
            "SELECT * FROM users WHERE username = ? AND email = ?",
            (form["username"], form["email"]), one=True,
        )
        if not form["username"] or not form["email"]:
            flash("Enter your username and email.", "error")
        elif user is None:
            flash("No account matches that username and email. Check both, or create an account.", "error")
        elif user["is_demo"]:
            flash("Demo accounts don't have a real inbox. Use the demo buttons below instead.", "info")
        else:
            try:
                issue_otp(user["email"], user["full_name"], "login", {"user_id": user["id"]})
                session["next"] = _safe_next(request.args.get("next"))
                return redirect(url_for("auth.verify"))
            except OtpError as exc:
                flash(str(exc), "error")
    return render_template("auth/login.html", form=form, shelf=_shelf_books())


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(home_for(g.user))
    form = {k: request.form.get(k, "").strip() for k in ("full_name", "username", "email", "role", "department")}
    form["email"] = form["email"].lower()
    form["role"] = form["role"] or "student"
    if request.method == "POST":
        errors = []
        if not 2 <= len(form["full_name"]) <= 60:
            errors.append("Enter your full name (2–60 characters).")
        if not USERNAME_RE.match(form["username"]):
            errors.append("Usernames are 3–30 characters: letters, numbers, dots and underscores.")
        if not EMAIL_RE.match(form["email"]):
            errors.append("Enter a valid email address.")
        if form["role"] not in ROLES:
            errors.append("Choose student, faculty or librarian.")
        elif form["role"] != "student":
            code = request.form.get("staff_code", "").strip()
            if not hmac.compare_digest(code, current_app.config["STAFF_ACCESS_CODE"]):
                errors.append("The staff access code is incorrect. Ask the librarian for it.")
        if not errors:
            if query("SELECT 1 FROM users WHERE username = ?", (form["username"],), one=True):
                errors.append("That username is taken. Try another one.")
            if query("SELECT 1 FROM users WHERE email = ?", (form["email"],), one=True):
                errors.append("An account with that email already exists. Sign in instead.")
        if errors:
            for message in errors:
                flash(message, "error")
        else:
            try:
                issue_otp(form["email"], form["full_name"], "signup", form)
                return redirect(url_for("auth.verify"))
            except OtpError as exc:
                flash(str(exc), "error")
    return render_template("auth/signup.html", form=form, shelf=_shelf_books())


@bp.route("/verify", methods=["GET", "POST"])
def verify():
    pending = session.get("pending_otp")
    if not pending:
        flash("Start by signing in or creating an account.", "info")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        code = re.sub(r"\D", "", request.form.get("code", ""))
        otp = query("SELECT * FROM otp_codes WHERE id = ?", (pending["id"],), one=True)
        cfg = current_app.config
        if otp is None or otp["used"]:
            flash("This code is no longer valid. Request a new one.", "error")
        elif from_ts(otp["expires_at"]) < utcnow():
            flash("This code has expired. Request a new one.", "error")
        elif otp["attempts"] >= cfg["OTP_MAX_ATTEMPTS"]:
            flash("Too many wrong attempts. Request a new code.", "error")
        elif not hmac.compare_digest(otp["code_hash"], _hash_code(otp["email"], code)):
            execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?", (otp["id"],))
            left = cfg["OTP_MAX_ATTEMPTS"] - otp["attempts"] - 1
            flash(f"That code doesn't match. {left} attempt{'s' if left != 1 else ''} left.", "error")
        else:
            execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (otp["id"],))
            payload = json.loads(otp["payload"] or "{}")
            if otp["purpose"] == "signup":
                return _finish_signup(payload)
            return _finish_login(payload["user_id"])

    return render_template(
        "auth/verify.html",
        pending=pending,
        demo_code=session.get("demo_code"),
        minutes=current_app.config["OTP_TTL_MINUTES"],
        shelf=_shelf_books(),
    )


def _finish_signup(data):
    taken = query(
        "SELECT 1 FROM users WHERE username = ? OR email = ?", (data["username"], data["email"]), one=True
    )
    if taken:
        session.pop("pending_otp", None)
        flash("That username or email was registered a moment ago. Sign in or pick another.", "error")
        return redirect(url_for("auth.signup"))
    cur = execute(
        "INSERT INTO users (username, email, full_name, role, department, created_at, last_login_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (data["username"], data["email"], data["full_name"], data["role"],
         data.get("department") or None, now_ts(), now_ts()),
    )
    log_in(cur.lastrowid)
    flash(f"Welcome, {data['full_name'].split()[0]}. Your email is verified and your account is ready.", "success")
    user = query("SELECT * FROM users WHERE id = ?", (cur.lastrowid,), one=True)
    return redirect(home_for(user))


def _finish_login(user_id):
    user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if user is None:
        session.clear()
        flash("That account no longer exists.", "error")
        return redirect(url_for("auth.login"))
    next_url = session.get("next")
    log_in(user["id"])
    execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_ts(), user["id"]))
    flash(f"Signed in as {user['username']}.", "success")
    return redirect(next_url or home_for(user))


@bp.route("/verify/resend", methods=["POST"])
def resend():
    pending = session.get("pending_otp")
    if not pending:
        return redirect(url_for("auth.login"))
    otp = query("SELECT payload FROM otp_codes WHERE id = ?", (pending["id"],), one=True)
    payload = json.loads(otp["payload"]) if otp and otp["payload"] else None
    if payload is None:
        flash("Start again so we can send you a new code.", "info")
        session.pop("pending_otp", None)
        return redirect(url_for("auth.signup" if pending["purpose"] == "signup" else "auth.login"))
    try:
        issue_otp(pending["email"], pending["name"], pending["purpose"], payload)
        flash(f"A new code is on its way to {pending['email']}.", "success")
    except OtpError as exc:
        flash(str(exc), "error")
    return redirect(url_for("auth.verify"))


@bp.route("/verify/cancel", methods=["POST"])
def cancel():
    session.pop("pending_otp", None)
    session.pop("demo_code", None)
    return redirect(url_for("auth.login"))


@bp.route("/demo/<role>", methods=["POST"])
def demo_login(role):
    if not current_app.config["ENABLE_DEMO_LOGIN"] or role not in ROLES:
        flash("Demo sign-in is turned off on this server.", "error")
        return redirect(url_for("auth.login"))
    user = query(
        "SELECT * FROM users WHERE is_demo = 1 AND role = ? ORDER BY id LIMIT 1", (role,), one=True
    )
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
