"""End-to-end tests. Run with:  python -m unittest discover -s tests -v   (or: pytest)"""
import re
import tempfile
import unittest
from pathlib import Path

from library import create_app
from library.db import execute, query


PASSWORD = "Shelf2026!"


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "DATABASE_PATH": str(Path(self.tmp.name) / "test.db"),
            "SECRET_KEY": "test-secret",
            "STAFF_ACCESS_CODE": "letmein",
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

    def signup(self, username="shivam.p", email="shivam@example.org", role="student", staff_code="",
               password=PASSWORD, confirm=None):
        return self.post("/signup", {"full_name": "Shivam Pandya", "username": username, "email": email,
                                     "password": password, "confirm_password": password if confirm is None else confirm,
                                     "role": role, "staff_code": staff_code, "department": "B.Tech AI"},
                         token_from="/signup")

    def login(self, identifier, password=PASSWORD):
        return self.post("/login", {"identifier": identifier, "password": password})

    def logout(self):
        return self.post("/logout")

    def demo(self, role):
        return self.post(f"/demo/{role}")

    def user_id(self, username):
        with self.app.app_context():
            return query("SELECT id FROM users WHERE username = ?", (username,), one=True)["id"]


class AuthTests(LibraryTestCase):
    def test_signup_creates_account_and_signs_in(self):
        r = self.signup()
        self.assertEqual(r.request.path, "/student/")
        self.assertIn("Your account is ready", r.get_data(as_text=True))

    def test_password_is_stored_hashed(self):
        self.signup()
        with self.app.app_context():
            stored = query("SELECT password_hash FROM users WHERE username = 'shivam.p'", one=True)[0]
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(stored.startswith("pbkdf2:sha256"))

    def test_one_account_per_email(self):
        self.signup(); self.logout()
        r = self.signup(username="someone.else", email="SHIVAM@example.org")
        self.assertIn("An account with that email already exists", r.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(query("SELECT COUNT(*) FROM users WHERE email = 'shivam@example.org'", one=True)[0], 1)

    def test_duplicate_username_rejected(self):
        self.signup(); self.logout()
        r = self.signup(email="new@example.org")
        self.assertIn("That username is taken", r.get_data(as_text=True))

    def test_password_rules(self):
        self.assertIn("at least 8 characters", self.signup(password="ab1").get_data(as_text=True))
        self.assertIn("Mix letters with numbers", self.signup(password="onlyletters").get_data(as_text=True))
        r = self.signup(confirm="Different2026!")
        self.assertIn("The two passwords don&#39;t match", r.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(query("SELECT 1 FROM users WHERE username = 'shivam.p'", one=True))

    def test_sign_in_with_username_or_email(self):
        self.signup(); self.logout()
        r = self.login("shivam.p")
        self.assertEqual(r.request.path, "/student/")
        self.logout()
        r = self.login("SHIVAM@example.org")
        self.assertEqual(r.request.path, "/student/")

    def test_wrong_password_is_rejected(self):
        self.signup(); self.logout()
        r = self.login("shivam.p", "WrongPass123")
        self.assertIn("Wrong username, email or password", r.get_data(as_text=True))
        self.assertEqual(r.request.path, "/login")

    def test_unknown_user_gets_the_same_message(self):
        r = self.login("nobody", "Whatever123")
        self.assertIn("Wrong username, email or password", r.get_data(as_text=True))

    def test_too_many_wrong_passwords_pause_the_account(self):
        self.signup(); self.logout()
        for _ in range(5):
            self.login("shivam.p", "WrongPass123")
        r = self.login("shivam.p")  # right password, but paused
        self.assertIn("Too many wrong attempts", r.get_data(as_text=True))
        r = self.login("shivam@example.org")  # same account by email is paused too
        self.assertIn("Too many wrong attempts", r.get_data(as_text=True))

    def test_successful_login_clears_failures(self):
        self.signup(); self.logout()
        for _ in range(4):
            self.login("shivam.p", "WrongPass123")
        self.assertEqual(self.login("shivam.p").request.path, "/student/")
        self.logout()
        for _ in range(4):
            self.login("shivam.p", "WrongPass123")
        self.assertEqual(self.login("shivam.p").request.path, "/student/")

    def test_staff_roles_need_access_code(self):
        r = self.signup(role="librarian", staff_code="wrong")
        self.assertIn("staff access code is incorrect", r.get_data(as_text=True))
        r = self.signup(role="librarian", staff_code="letmein")
        self.assertEqual(r.request.path, "/librarian/")

    def test_demo_accounts_cannot_use_the_password_form(self):
        r = self.login("librarian", "anything123")
        self.assertIn("demo account", r.get_data(as_text=True))

    def test_post_without_csrf_token_is_refused(self):
        r = self.client.post("/login", data={"identifier": "x", "password": "y"})
        self.assertEqual(r.status_code, 400)

    def test_roles_cannot_open_each_others_pages(self):
        self.demo("student")
        self.assertEqual(self.client.get("/librarian/").status_code, 403)
        self.assertEqual(self.client.get("/faculty/").status_code, 403)

    def test_pages_require_sign_in(self):
        r = self.client.get("/student/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_set_password_command(self):
        self.signup(); self.logout()
        result = self.app.test_cli_runner().invoke(args=["set-password", "shivam.p"], input="NewShelf99\nNewShelf99\n")
        self.assertIn("Password updated", result.output)
        self.assertEqual(self.login("shivam.p", "NewShelf99").request.path, "/student/")


class StudentTests(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.signup()
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


if __name__ == "__main__":
    unittest.main()
