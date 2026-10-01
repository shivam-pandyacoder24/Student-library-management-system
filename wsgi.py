"""Entry point for gunicorn (Render), PythonAnywhere's WSGI file, or `python wsgi.py` locally."""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name(".env"))  # settings from a local .env file, if present

from library import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
