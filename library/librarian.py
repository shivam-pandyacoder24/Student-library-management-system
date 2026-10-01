"""Librarian screens: overview, stock insights, overdue loans, add and delete books."""
import re
from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .catalog import CATEGORIES
from .db import execute, now_ts, query
from .insights import library_overview, overdue_loans, stock_insights
from .services import LOAN_SELECT, get_book, open_loans, search_books
from .utils import role_required

bp = Blueprint("librarian", __name__, url_prefix="/librarian")

ISBN_RE = re.compile(r"^[0-9Xx-]{10,17}$")


def _back():
    target = request.form.get("next", "")
    if target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(url_for("librarian.books"))


@bp.route("/")
@role_required("librarian")
def dashboard():
    recent = query(LOAN_SELECT + " ORDER BY COALESCE(l.returned_at, l.issued_at) DESC LIMIT 8")
    return render_template(
        "librarian/dashboard.html",
        o=library_overview(),
        stock=stock_insights(),
        overdue=overdue_loans(),
        out=open_loans(),
        recent=recent,
    )


@bp.route("/books")
@role_required("librarian")
def books():
    text = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    category = category if category in CATEGORIES else ""
    return render_template(
        "librarian/books.html",
        books=search_books(text, category),
        q=text,
        category=category,
        categories=CATEGORIES,
        form={},
        this_year=date.today().year,
    )


@bp.route("/books/add", methods=["POST"])
@role_required("librarian")
def add_book():
    f = {k: request.form.get(k, "").strip() for k in ("title", "author", "category", "isbn", "year", "copies")}
    errors = []
    if not 1 <= len(f["title"]) <= 200:
        errors.append("Enter the book's title.")
    if not 1 <= len(f["author"]) <= 120:
        errors.append("Enter the author's name.")
    if f["category"] not in CATEGORIES:
        errors.append("Choose a category.")
    if f["isbn"] and not ISBN_RE.match(f["isbn"]):
        errors.append("ISBNs are 10 or 13 digits (hyphens are fine).")
    year = None
    if f["year"]:
        try:
            year = int(f["year"])
            if not 1000 <= year <= date.today().year:
                raise ValueError
        except ValueError:
            errors.append(f"Enter a publication year between 1000 and {date.today().year}.")
    try:
        copies = int(f["copies"] or 1)
        if not 1 <= copies <= 100:
            raise ValueError
    except ValueError:
        copies = 1
        errors.append("Copies must be a number from 1 to 100.")

    if not errors:
        dup = query("SELECT id FROM books WHERE is_active = 1 AND LOWER(title) = LOWER(?) AND LOWER(author) = LOWER(?)",
                    (f["title"], f["author"]), one=True)
        if dup:
            errors.append(f"“{f['title']}” is already in the catalogue. Change its copies in the list instead.")

    if errors:
        for e in errors:
            flash(e, "error")
        return render_template("librarian/books.html", books=search_books(), q="", category="",
                               categories=CATEGORIES, form=f, this_year=date.today().year), 400

    execute(
        "INSERT INTO books (title, author, category, isbn, published_year, total_copies, added_by, added_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (f["title"], f["author"], f["category"], f["isbn"] or None, year, copies, g.user["id"], now_ts()),
    )
    flash(f"Added “{f['title']}” with {copies} cop{'ies' if copies != 1 else 'y'}.", "success")
    return redirect(url_for("librarian.books"))


@bp.route("/books/<int:book_id>/copies", methods=["POST"])
@role_required("librarian")
def change_copies(book_id):
    book = get_book(book_id)
    if book is None:
        flash("That book isn't in the catalogue.", "error")
        return redirect(url_for("librarian.books"))
    step = 1 if request.form.get("action") == "add" else -1
    new_total = book["total_copies"] + step
    if new_total < max(book["on_loan"], 1):
        flash(f"Can't go below {max(book['on_loan'], 1)}: "
              f"{'that many copies are on loan' if book['on_loan'] else 'a book needs at least one copy'}. "
              f"To remove the title, delete it.", "error")
    else:
        execute("UPDATE books SET total_copies = ? WHERE id = ?", (new_total, book_id))
        flash(f"“{book['title']}” now has {new_total} cop{'ies' if new_total != 1 else 'y'}.", "success")
    return _back()


@bp.route("/books/<int:book_id>/delete", methods=["POST"])
@role_required("librarian")
def delete_book(book_id):
    book = get_book(book_id)
    if book is None:
        flash("That book was already removed.", "info")
    elif book["on_loan"]:
        flash(f"“{book['title']}” has {book['on_loan']} cop{'ies' if book['on_loan'] != 1 else 'y'} on loan. "
              f"It can be deleted once they're returned.", "error")
    else:
        # Kept in the database (hidden) so past loans and insights stay accurate.
        execute("UPDATE books SET is_active = 0 WHERE id = ?", (book_id,))
        flash(f"Deleted “{book['title']}” from the catalogue.", "success")
    return _back()
