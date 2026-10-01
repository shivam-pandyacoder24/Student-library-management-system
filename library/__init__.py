"""Student Library Management System - Flask application factory."""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, g, render_template

from . import db as dbmod
from .catalog import category_color
from .config import Config
from .utils import csrf_token, load_current_user, verify_csrf


def create_app(overrides=None):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    logging.basicConfig(level=logging.INFO)

    if app.config["SECRET_KEY"] == "dev-only-change-me" and not app.debug and not app.testing:
        app.logger.warning("SECRET_KEY is not set. Set it in the environment before going live.")

    # Database: create tables, and add demo data the first time.
    conn = dbmod.connect(app.config["DATABASE_PATH"])
    try:
        dbmod.init_schema(conn)
        if app.config["SEED_DEMO_DATA"]:
            from .seed import seed_demo
            if seed_demo(conn, loan_days=app.config["LOAN_DAYS"]):
                app.logger.info("Loaded demo catalogue and accounts.")
    finally:
        conn.close()
    app.teardown_appcontext(dbmod.close_db)

    from . import auth, faculty, librarian, student
    app.register_blueprint(auth.bp)
    app.register_blueprint(student.bp)
    app.register_blueprint(faculty.bp)
    app.register_blueprint(librarian.bp)

    @app.before_request
    def _before():
        load_current_user()
        verify_csrf()

    _register_template_helpers(app)
    _register_errors(app)
    _register_cli(app)
    return app


def _register_template_helpers(app):
    try:
        tz = ZoneInfo(app.config["DISPLAY_TIMEZONE"])
    except ZoneInfoNotFoundError:  # e.g. Windows without the tzdata package
        app.logger.warning("Time zone %s not found; showing times in UTC.", app.config["DISPLAY_TIMEZONE"])
        tz = timezone.utc

    def local(value):
        dt = dbmod.from_ts(value)
        return dt.replace(tzinfo=timezone.utc).astimezone(tz) if dt else None

    @app.template_filter("day")
    def _day(value):
        dt = local(value)
        return f"{dt:%a}, {dt.day} {dt:%b}" if dt else ""

    @app.template_filter("date")
    def _date(value):
        dt = local(value)
        return f"{dt.day} {dt:%b %Y}" if dt else ""

    @app.template_filter("when")
    def _when(value):
        dt = local(value)
        return f"{dt.day} {dt:%b}, {dt.hour % 12 or 12}:{dt:%M %p}" if dt else ""

    @app.template_filter("color")
    def _color(category):
        return category_color(category)

    @app.template_filter("initials")
    def _initials(name):
        parts = [p for p in (name or "").replace("Dr.", "").split() if p]
        return "".join(p[0] for p in parts[:2]).upper()

    from .services import days_left, days_overdue, fine_for

    @app.context_processor
    def _globals():
        hour = datetime.now(tz).hour
        greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
        return {
            "csrf_token": csrf_token,
            "library_name": app.config["LIBRARY_NAME"],
            "cfg": app.config,
            "greeting": greeting,
            "days_left": days_left,
            "days_overdue": days_overdue,
            "fine_for": fine_for,
            "current_user": g.get("user"),
        }


def _register_errors(app):
    @app.errorhandler(400)
    def _400(e):
        return render_template("error.html", code=400, title="Something was off with that request",
                               message=getattr(e, "description", "")), 400

    @app.errorhandler(403)
    def _403(_e):
        return render_template("error.html", code=403, title="This page isn't for your role",
                               message="Your account doesn't have access here. Head back to your dashboard."), 403

    @app.errorhandler(404)
    def _404(_e):
        return render_template("error.html", code=404, title="Page not found",
                               message="The link may be old, or the item was removed."), 404


def _register_cli(app):
    @app.cli.command("reset-demo")
    def reset_demo():
        """Wipe the database and reload the demo catalogue and accounts."""
        from .seed import seed_demo
        conn = dbmod.connect(app.config["DATABASE_PATH"])
        dbmod.init_schema(conn)
        seed_demo(conn, loan_days=app.config["LOAN_DAYS"], force=True)
        conn.close()
        print("Demo data reloaded.")

    @app.cli.command("init-db")
    def init_db():
        """Create the tables without demo data."""
        conn = dbmod.connect(app.config["DATABASE_PATH"])
        dbmod.init_schema(conn)
        conn.close()
        print(f"Database ready at {app.config['DATABASE_PATH']}")
