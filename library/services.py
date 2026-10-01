"""Core library rules: availability, issuing and returning books, fines."""
from datetime import timedelta

from flask import current_app

from .db import from_ts, get_db, now_ts, query, to_ts, utcnow

# Every book row comes with a live 'available' count = copies minus open loans.
BOOK_SELECT = """
SELECT b.*,
       b.total_copies - COALESCE(o.out_count, 0) AS available,
       COALESCE(o.out_count, 0)                  AS on_loan
FROM books b
LEFT JOIN (SELECT book_id, COUNT(*) AS out_count
           FROM loans WHERE returned_at IS NULL GROUP BY book_id) o ON o.book_id = b.id
"""

LOAN_SELECT = """
SELECT l.*, b.title, b.author, b.category, u.full_name, u.username
FROM loans l
JOIN books b ON b.id = l.book_id
JOIN users u ON u.id = l.user_id
"""


class LoanError(Exception):
    pass


def get_book(book_id, include_removed=False):
    sql = BOOK_SELECT + " WHERE b.id = ?" + ("" if include_removed else " AND b.is_active = 1")
    return query(sql, (book_id,), one=True)


def search_books(text="", category="", available_only=False):
    sql = BOOK_SELECT + " WHERE b.is_active = 1"
    args = []
    if text:
        sql += " AND (LOWER(b.title) LIKE ? OR LOWER(b.author) LIKE ? OR b.isbn LIKE ?)"
        like = f"%{text.lower()}%"
        args += [like, like, like]
    if category:
        sql += " AND b.category = ?"
        args.append(category)
    if available_only:
        sql += " AND b.total_copies - COALESCE(o.out_count, 0) > 0"
    sql += " ORDER BY b.title COLLATE NOCASE"
    return query(sql, args)


def open_loans(user_id=None):
    sql = LOAN_SELECT + " WHERE l.returned_at IS NULL"
    args = []
    if user_id is not None:
        sql += " AND l.user_id = ?"
        args.append(user_id)
    return query(sql + " ORDER BY l.due_at", args)


def loan_history(user_id, limit=None):
    sql = LOAN_SELECT + " WHERE l.user_id = ? ORDER BY l.issued_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return query(sql, (user_id,))


def days_overdue(loan):
    """Whole days past the due date (0 if on time). Uses the return date for closed loans."""
    due = from_ts(loan["due_at"])
    end = from_ts(loan["returned_at"]) if loan["returned_at"] else utcnow()
    return max(0, (end.date() - due.date()).days)


def days_left(loan):
    return (from_ts(loan["due_at"]).date() - utcnow().date()).days


def fine_for(loan):
    return days_overdue(loan) * current_app.config["FINE_PER_DAY"]


def issue_book(user, book_id):
    """Lend one copy of a book to a student. Raises LoanError with a readable reason."""
    cfg = current_app.config
    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")  # lock so two students can't take the last copy at once
    try:
        book = conn.execute(BOOK_SELECT + " WHERE b.id = ? AND b.is_active = 1", (book_id,)).fetchone()
        if book is None:
            raise LoanError("That book isn't in the catalogue any more.")
        mine = conn.execute(
            "SELECT book_id, due_at FROM loans WHERE user_id = ? AND returned_at IS NULL", (user["id"],)
        ).fetchall()
        if any(row["book_id"] == book["id"] for row in mine):
            raise LoanError(f"You already have “{book['title']}”.")
        if any(from_ts(row["due_at"]).date() < utcnow().date() for row in mine):
            raise LoanError("Return your overdue book before borrowing another.")
        if len(mine) >= cfg["MAX_ACTIVE_LOANS"]:
            raise LoanError(f"You can hold {cfg['MAX_ACTIVE_LOANS']} books at a time. Return one to borrow this.")
        if book["available"] <= 0:
            raise LoanError(f"All copies of “{book['title']}” are out right now.")
        due = utcnow() + timedelta(days=cfg["LOAN_DAYS"])
        conn.execute(
            "INSERT INTO loans (user_id, book_id, issued_at, due_at) VALUES (?, ?, ?, ?)",
            (user["id"], book["id"], now_ts(), to_ts(due)),
        )
        conn.commit()
        return book, due
    except Exception:
        conn.rollback()
        raise


def return_book(user, loan_id):
    conn = get_db()
    loan = conn.execute(
        LOAN_SELECT + " WHERE l.id = ? AND l.user_id = ?", (loan_id, user["id"])
    ).fetchone()
    if loan is None:
        raise LoanError("We couldn't find that loan on your account.")
    if loan["returned_at"]:
        raise LoanError(f"“{loan['title']}” was already returned.")
    conn.execute("UPDATE loans SET returned_at = ? WHERE id = ?", (now_ts(), loan_id))
    conn.commit()
    return query(LOAN_SELECT + " WHERE l.id = ?", (loan_id,), one=True)
