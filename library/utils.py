"""Session helpers, role-based access control and CSRF protection."""
import hmac
import secrets
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

from .db import query

ROLE_HOME = {
    "student": "student.dashboard",
    "faculty": "faculty.dashboard",
    "librarian": "librarian.dashboard",
}


def load_current_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        g.user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
        if g.user is None:
            session.pop("user_id", None)


def log_in(user_id):
    session.clear()  # start a fresh session so an old one can't be reused
    session.permanent = True
    session["user_id"] = user_id
    session["csrf_token"] = secrets.token_urlsafe(32)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Sign in to continue.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Sign in to continue.", "info")
                return redirect(url_for("auth.login", next=request.path))
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def home_for(user):
    return url_for(ROLE_HOME[user["role"]])


# ---------- CSRF ----------

def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def verify_csrf():
    if request.method != "POST":
        return
    sent = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, description="Your form expired. Go back, refresh the page and try again.")
