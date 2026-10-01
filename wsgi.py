"""Entry point for gunicorn (Render), PythonAnywhere's WSGI file, or `python wsgi.py` locally."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name(".env"))  # settings from a local .env file, if present

from library import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    # Debug mode stays off unless FLASK_DEBUG=1, so the site is safe to share through a tunnel.
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
