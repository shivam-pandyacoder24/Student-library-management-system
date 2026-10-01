# Deployment guide

Three ways to put the app online, from easiest to most permanent. Back to the [README](../README.md).

- [Option 1: Render (one click)](#option-1-render-one-click)
- [Option 2: PythonAnywhere (keeps your data)](#option-2-pythonanywhere-keeps-your-data)
- [Option 3: Share from your laptop (no account)](#option-3-share-from-your-laptop-no-account)
- [Forgot password](#forgot-password)
- [Settings](#settings)

## Option 1: Render (one click)

You sign in with your GitHub account, and no card is needed.

1. Click the button:

   [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/shivam-pandyacoder24/Student-library-management-system)

2. Choose **Sign in with GitHub**.
3. Type a **Blueprint Name** such as `student-library` and click **Deploy Blueprint**.
4. Wait 3–5 minutes. Your link (ending in `.onrender.com`) appears on the service page.
5. Find the staff code for faculty and librarian sign-ups under the service's **Environment** tab, as `STAFF_ACCESS_CODE`.

Render reads [`render.yaml`](../render.yaml) and generates `SECRET_KEY` and `STAFF_ACCESS_CODE` for you. Every push to GitHub redeploys the site automatically.

**Free plan limits:**
- **Sleeping:** the site sleeps after 15 minutes with no visitors, so the next visit takes about a minute.
- **Resets:** it doesn't keep files, so new accounts and loans are wiped when it restarts or redeploys. The demo data reloads automatically.

## Option 2: PythonAnywhere (keeps your data)

1. Create a free **Beginner** account at [pythonanywhere.com](https://www.pythonanywhere.com/). Your site will be `https://YOUR-USERNAME.pythonanywhere.com`.
2. Open **Consoles → Bash** and run, one line at a time:
   ```bash
   git clone https://github.com/shivam-pandyacoder24/Student-library-management-system.git
   cd Student-library-management-system
   python3.11 -m venv ~/venv-library
   source ~/venv-library/bin/activate
   pip install -r requirements.txt
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
3. Copy the long text the last command printed. Then create your settings file (replace the two values first):
   ```bash
   cat > .env <<'EOF'
   SECRET_KEY=paste-the-long-text-here
   STAFF_ACCESS_CODE=choose-a-code-for-faculty-and-librarians
   COOKIE_SECURE=1
   EOF
   ```
4. Go to **Web → Add a new web app → Next → Manual configuration → Python 3.11 → Next**. Choose Manual configuration, not "Flask".
5. Under **Virtualenv**, enter `/home/YOUR-USERNAME/venv-library`.
6. Click the **WSGI configuration file** link. Delete everything in it, paste this (with your username), and click **Save**:
   ```python
   import os, sys
   path = "/home/YOUR-USERNAME/Student-library-management-system"
   if path not in sys.path:
       sys.path.insert(0, path)
   os.chdir(path)
   from wsgi import app as application
   ```
7. On the **Web** tab, turn on **Force HTTPS** and click **Reload**.

**Keep it running:**
- **Extend it monthly:** free sites switch off after a month unless you click **"Run until 1 month from today"** on the Web tab.
- **Update after changes:** run `cd ~/Student-library-management-system && git pull`, then click **Reload**.
- **Errors:** if you see "Something went wrong", open the **Error log** link on the Web tab. The usual causes are a wrong username in the WSGI file, a missing virtualenv path, or forgetting to click Reload.

## Option 3: Share from your laptop (no account)

Good for a live demo. The link works only while your laptop is on and both windows stay open, and it changes every time.

1. Start the site (see [Run it on your computer](../README.md#run-it-on-your-computer)) and leave that window open.
2. In a second terminal, install Cloudflare's tunnel tool once. On Windows: `winget install --id Cloudflare.cloudflared`, then reopen the terminal.
3. Run `cloudflared tunnel --url http://localhost:5000`.
4. Share the `https://…trycloudflare.com` link it prints.

## Forgot password

Whoever runs the server can set a new password from a terminal in the project folder:

```bash
flask --app wsgi set-password USERNAME-OR-EMAIL
```

It asks for the new password twice. On PythonAnywhere, run `source ~/venv-library/bin/activate` first.

## Settings

All settings are environment variables, or lines in a `.env` file in the project folder. See [`.env.example`](../.env.example).

| Variable | What it does | Default |
|---|---|---|
| `SECRET_KEY` | Signs session cookies. **Set a long random value.** | dev value |
| `STAFF_ACCESS_CODE` | Code needed to sign up as faculty or librarian | `staff123` |
| `LIBRARY_NAME` | Name shown in the header | Campus Library |
| `SEED_DEMO_DATA` | Load 50 books, 10 demo accounts and history into an empty database | `1` |
| `ENABLE_DEMO_LOGIN` | Show the one-click demo buttons. **Set to `0` for real use**, since anyone could open the librarian demo. | `1` |
| `LOAN_DAYS`, `MAX_ACTIVE_LOANS`, `FINE_PER_DAY` | Library rules | `14`, `3`, `5` |
| `DATABASE_PATH` | Where the SQLite file lives | `instance/library.db` |
| `COOKIE_SECURE` | Send cookies only over HTTPS | `0` |
| `FLASK_DEBUG` | Debug mode for `python wsgi.py` (never on a public site) | off |

Reload the demo data at any time with `flask --app wsgi reset-demo`. This wipes the database.
