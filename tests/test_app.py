"""End-to-end tests. Run with:  python -m unittest discover -s tests -v   (or: pytest)"""
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from library import create_app
from library.db import execute, query


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "TESTING_OUTBOX": True,
            "DATABASE_PATH": str(Path(self.tmp.name) / "test.db"),
            "SECRET_KEY": "test-secret",
            "STAFF_ACCESS_CODE": "letmein",
            "OTP_RESEND_SECONDS": 0,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    # ---------- helpers ----------
    def token(self, path="/login"):
        html = self.client.get(path, follow_redirects=True).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, path, data=None, follow=True, token_from="/login"):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token(token_from))
        return self.client.post(path, data=data, follow_redirects=follow)

    def last_code(self):
        outbox = self.app.extensions["outbox"]
        return re.search(r"\b(\d{6})\b", outbox[-1]["text"]).group(1)

    def signup(self, username="shivam.p", email="shivam@example.org", role="student", staff_code=""):
        r = self.post("/signup", {"full_name": "Shivam Pandya", "username": username, "email": email,
                                  "role": role, "staff_code": staff_code, "department": "B.Tech AI"},
                      token_from="/signup")
        return r

    def verify(self, code):
        return self.post("/verify", {"code": code}, token_from="/verify")

    def demo(self, role):
        return self.post(f"/demo/{role}")

    def user_id(self, username):
        with self.app.app_context():
            return query("SELECT id FROM users WHERE username = ?", (username,), one=True)["id"]


class AuthTests(LibraryTestCase):
    def test_signup_sends_otp_and_creates_verified_account(self):
        r = self.signup()
        self.assertIn("Check your email", r.get_data(as_text=True))
        self.assertEqual(self.app.extensions["outbox"][-1]["to"], "shivam@example.org")
        r = self.verify(self.last_code())
        self.assertEqual(r.request.path, "/student/")
        self.assertIn("Your email is verified", r.get_data(as_text=True))

    def test_account_is_not_created_before_verification(self):
        self.signup()
        with self.app.app_context():
            self.assertIsNone(query("SELECT 1 FROM users WHERE username = 'shivam.p'", one=True))

    def test_wrong_code_is_rejected_and_attempts_are_limited(self):
        self.signup()
        r = self.verify("000000" if self.last_code() != "000000" else "111111")
        self.assertIn("doesn&#39;t match", r.get_data(as_text=True))
        for _ in range(5):
            self.verify("999999" if self.last_code() != "999999" else "888888")
        r = self.verify(self.last_code())
        self.assertIn("Too many wrong attempts", r.get_data(as_text=True))

    def test_login_with_username_and_email(self):
        self.signup(); self.verify(self.last_code())
        self.post("/logout")
        r = self.post("/login", {"username": "shivam.p", "email": "SHIVAM@example.org"})
        self.assertIn("Check your email", r.get_data(as_text=True))
        r = self.verify(self.last_code())
        self.assertEqual(r.request.path, "/student/")

    def test_login_rejects_mismatched_email(self):
        self.signup(); self.verify(self.last_code()); self.post("/logout")
        r = self.post("/login", {"username": "shivam.p", "email": "other@example.org"})
        self.assertIn("No account matches", r.get_data(as_text=True))

    def test_duplicate_username_rejected(self):
        self.signup(); self.verify(self.last_code()); self.post("/logout")
        r = self.signup(email="new@example.org")
        self.assertIn("That username is taken", r.get_data(as_text=True))

    def test_staff_roles_need_access_code(self):
        r = self.signup(role="librarian", staff_code="wrong")
        self.assertIn("staff access code is incorrect", r.get_data(as_text=True))
        self.signup(role="librarian", staff_code="letmein")
        r = self.verify(self.last_code())
        self.assertEqual(r.request.path, "/librarian/")

    def test_expired_code_is_rejected(self):
        self.signup()
        with self.app.app_context():
            execute("UPDATE otp_codes SET expires_at = '2000-01-01 00:00:00'")
        r = self.verify(self.last_code())
        self.assertIn("expired", r.get_data(as_text=True))

    def test_post_without_csrf_token_is_refused(self):
        r = self.client.post("/login", data={"username": "x", "email": "x@example.org"})
        self.assertEqual(r.status_code, 400)

    def test_roles_cannot_open_each_others_pages(self):
        self.demo("student")
        self.assertEqual(self.client.get("/librarian/").status_code, 403)
        self.assertEqual(self.client.get("/faculty/").status_code, 403)

    def test_pages_require_sign_in(self):
        r = self.client.get("/student/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])


class StudentTests(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.signup(); self.verify(self.last_code())
        self.uid = self.user_id("shivam.p")

    def book_id(self, title):
        with self.app.app_context():
            return query("SELECT id FROM books WHERE title = ?", (title,), one=True)["id"]

    def test_issue_and_return(self):
        bid = self.book_id("Clean Code")
        r = self.post(f"/student/issue/{bid}", token_from="/student/catalog")
        self.assertIn("You borrowed “Clean Code”", r.get_data(as_text=True))
        with self.app.app_context():
            loan = query("SELECT * FROM loans WHERE user_id = ? AND returned_at IS NULL", (self.uid,), one=True)
        self.assertEqual(loan["book_id"], bid)
        r = self.post(f"/student/return/{loan['id']}", token_from="/student/")
        self.assertIn("Returned “Clean Code” on time", r.get_data(as_text=True))

    def test_cannot_borrow_same_book_twice(self):
        bid = self.book_id("Clean Code")
        self.post(f"/student/issue/{bid}", token_from="/student/catalog")
        r = self.post(f"/student/issue/{bid}", token_from="/student/catalog")
        self.assertIn("You already have", r.get_data(as_text=True))

    def test_loan_limit(self):
        for title in ["Clean Code", "Deep Learning", "Sapiens"]:
            self.post(f"/student/issue/{self.book_id(title)}", token_from="/student/catalog")
        r = self.post(f"/student/issue/{self.book_id('Cosmos')}", token_from="/student/catalog")
        self.assertIn("You can hold 3 books at a time", r.get_data(as_text=True))

    def test_cannot_take_more_copies_than_exist(self):
        bid = self.book_id("Cosmos")
        with self.app.app_context():
            execute("UPDATE books SET total_copies = 0 WHERE id = ?", (bid,))
        r = self.post(f"/student/issue/{bid}", token_from="/student/catalog")
        self.assertIn("All copies of “Cosmos” are out", r.get_data(as_text=True))

    def test_overdue_book_blocks_borrowing_and_shows_fine(self):
        self.post(f"/student/issue/{self.book_id('Clean Code')}", token_from="/student/catalog")
        with self.app.app_context():
            execute("UPDATE loans SET due_at = datetime('now', '-3 days') WHERE user_id = ?", (self.uid,))
        r = self.post(f"/student/issue/{self.book_id('Cosmos')}", token_from="/student/catalog")
        self.assertIn("Return your overdue book", r.get_data(as_text=True))
        html = self.client.get("/student/").get_data(as_text=True)
        self.assertIn("3 days overdue", html)
        self.assertIn("₹15", html)

    def test_new_student_gets_popular_picks(self):
        html = self.client.get("/student/for-you").get_data(as_text=True)
        self.assertIn("Popular with students this semester", html)

    def test_picks_follow_reading_history(self):
        for title in ["Deep Learning", "Life 3.0"]:
            self.post(f"/student/issue/{self.book_id(title)}", token_from="/student/catalog")
        html = self.client.get("/student/for-you").get_data(as_text=True)
        self.assertIn("Matches your interest in Artificial Intelligence", html)
        self.assertIn("Something different", html)

    def test_catalogue_search(self):
        html = self.client.get("/student/catalog?q=python&category=Programming").get_data(as_text=True)
        self.assertIn("Python Crash Course", html)
        self.assertNotIn("Sapiens", html)


class LibrarianTests(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.demo("librarian")

    def test_add_book(self):
        r = self.post("/librarian/books/add", {"title": "Grokking Algorithms", "author": "Aditya Bhargava",
                                               "category": "Programming", "year": "2016", "copies": "3"},
                      token_from="/librarian/books")
        self.assertIn("Added “Grokking Algorithms” with 3 copies", r.get_data(as_text=True))

    def test_add_book_validation(self):
        r = self.post("/librarian/books/add", {"title": "", "author": "", "category": "Cooking", "copies": "0"},
                      token_from="/librarian/books")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Choose a category", r.get_data(as_text=True))

    def test_delete_book(self):
        with self.app.app_context():
            book = query("SELECT b.id FROM books b WHERE NOT EXISTS (SELECT 1 FROM loans l WHERE l.book_id = b.id"
                         " AND l.returned_at IS NULL) LIMIT 1", one=True)
        r = self.post(f"/librarian/books/{book['id']}/delete", token_from="/librarian/books")
        self.assertIn("Deleted", r.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(query("SELECT is_active FROM books WHERE id = ?", (book["id"],), one=True)[0], 0)

    def test_cannot_delete_book_on_loan(self):
        with self.app.app_context():
            loan = query("SELECT book_id FROM loans WHERE returned_at IS NULL LIMIT 1", one=True)
        r = self.post(f"/librarian/books/{loan['book_id']}/delete", token_from="/librarian/books")
        self.assertIn("It can be deleted once", r.get_data(as_text=True))

    def test_change_copies(self):
        with self.app.app_context():
            book = query("SELECT id, total_copies FROM books LIMIT 1", one=True)
        self.post(f"/librarian/books/{book['id']}/copies", {"action": "add"}, token_from="/librarian/books")
        with self.app.app_context():
            self.assertEqual(query("SELECT total_copies FROM books WHERE id = ?", (book["id"],), one=True)[0],
                             book["total_copies"] + 1)

    def test_overview_shows_overdue_loans(self):
        html = self.client.get("/librarian/").get_data(as_text=True)
        self.assertIn("Overdue", html)
        self.assertIn("Demand against stock", html)


class FacultyTests(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.demo("faculty")

    def test_overview_and_matrix(self):
        self.assertIn("Reading by category", self.client.get("/faculty/").get_data(as_text=True))
        html = self.client.get("/faculty/students").get_data(as_text=True)
        self.assertIn("Every student at a glance", html)
        self.assertIn("Aarav Krishnan", html)

    def test_category_filter_lists_readers(self):
        html = self.client.get("/faculty/students?category=Fiction").get_data(as_text=True)
        self.assertIn("Fiction books read", html)

    def test_student_profile(self):
        uid = self.user_id("aarav.k")
        html = self.client.get(f"/faculty/students/{uid}").get_data(as_text=True)
        self.assertIn("Borrowing history", html)


class EmailProviderTests(unittest.TestCase):
    """The real providers, with the network mocked out."""

    def make_app(self, **cfg):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = {"TESTING": True, "DATABASE_PATH": str(Path(self.tmp.name) / "t.db"), "SEED_DEMO_DATA": False,
                "MAIL_FROM_EMAIL": "library@example.org"}
        base.update(cfg)
        return create_app(base)

    def test_brevo_api_request(self):
        app = self.make_app(BREVO_API_KEY="xkeysib-test")
        from library import emailer
        with app.test_request_context(), mock.patch("library.emailer.requests.post") as post:
            post.return_value.status_code = 201
            emailer.send_otp_email("student@example.org", "Asha Rao", "123456", "signup")
        url, kwargs = post.call_args.args[0], post.call_args.kwargs
        self.assertEqual(url, "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(kwargs["headers"]["api-key"], "xkeysib-test")
        self.assertEqual(kwargs["json"]["to"], [{"email": "student@example.org"}])
        self.assertIn("123456", kwargs["json"]["htmlContent"])

    def test_brevo_error_is_reported(self):
        app = self.make_app(BREVO_API_KEY="bad")
        from library import emailer
        with app.test_request_context(), mock.patch("library.emailer.requests.post") as post:
            post.return_value.status_code = 401
            post.return_value.text = "unauthorized"
            with self.assertRaises(emailer.EmailError):
                emailer.send_otp_email("student@example.org", "Asha", "123456", "login")

    def test_gmail_smtp(self):
        app = self.make_app(SMTP_HOST="smtp.gmail.com", SMTP_USERNAME="me@gmail.com", SMTP_PASSWORD="abcd efgh")
        from library import emailer
        with app.test_request_context(), mock.patch("library.emailer.smtplib.SMTP") as smtp:
            emailer.send_otp_email("student@example.org", "Asha", "654321", "login")
        conn = smtp.return_value.__enter__.return_value
        smtp.assert_called_with("smtp.gmail.com", 587, timeout=20)
        conn.starttls.assert_called_once()
        conn.login.assert_called_with("me@gmail.com", "abcd efgh")
        message = conn.send_message.call_args.args[0]
        self.assertEqual(message["To"], "student@example.org")
        self.assertIn("654321", message["Subject"])

    def test_demo_mode_shows_code_on_screen(self):
        app = self.make_app()
        client = app.test_client()
        html = client.get("/signup").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        r = client.post("/signup", data={"csrf_token": token, "full_name": "Asha Rao", "username": "asha",
                                         "email": "asha@example.org", "role": "student"}, follow_redirects=True)
        html = r.get_data(as_text=True)
        self.assertIn("Email sending isn't set up", html)
        code = re.search(r"<strong>(\d{6})</strong>", html).group(1)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        r = client.post("/verify", data={"csrf_token": token, "code": code}, follow_redirects=True)
        self.assertEqual(r.request.path, "/student/")


if __name__ == "__main__":
    unittest.main()
