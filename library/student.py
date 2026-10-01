"""Student screens: dashboard, catalogue, issue/return, picks and insights, history."""
from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from .catalog import CATEGORIES
from .insights import student_insights, student_suggestions
from .recommender import recommend
from .services import LoanError, fine_for, issue_book, loan_history, open_loans, return_book, search_books
from .utils import role_required

bp = Blueprint("student", __name__, url_prefix="/student")


def _back(default="student.dashboard"):
    target = request.form.get("next", "")
    return redirect(target if target.startswith("/") and not target.startswith("//") else url_for(default))


@bp.route("/")
@role_required("student")
def dashboard():
    loans = open_loans(g.user["id"])
    recs = recommend(g.user["id"], limit=6)
    stats = student_insights(g.user["id"])
    tips = student_suggestions(stats, loans, recs)
    return render_template("student/dashboard.html", loans=loans, recs=recs, tips=tips, stats=stats)


@bp.route("/catalog")
@role_required("student")
def catalog():
    text = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    category = category if category in CATEGORIES else ""
    available = request.args.get("available") == "1"
    books = search_books(text, category, available)
    holding = {loan["book_id"] for loan in open_loans(g.user["id"])}
    return render_template("student/catalog.html", books=books, q=text, category=category,
                           available=available, holding=holding, categories=CATEGORIES,
                           slots_left=current_app.config["MAX_ACTIVE_LOANS"] - len(holding))


@bp.route("/issue/<int:book_id>", methods=["POST"])
@role_required("student")
def issue(book_id):
    try:
        book, due = issue_book(g.user, book_id)
        flash(f"You borrowed “{book['title']}”. Return it by {due.strftime('%a, %d %b')}.", "success")
    except LoanError as exc:
        flash(str(exc), "error")
    return _back("student.catalog")


@bp.route("/return/<int:loan_id>", methods=["POST"])
@role_required("student")
def return_(loan_id):
    try:
        loan = return_book(g.user, loan_id)
        fine = fine_for(loan)
        if fine:
            flash(f"Returned “{loan['title']}”. It was late, so please pay ₹{fine} at the desk.", "warn")
        else:
            flash(f"Returned “{loan['title']}” on time. Thanks!", "success")
    except LoanError as exc:
        flash(str(exc), "error")
    return _back()


@bp.route("/for-you")
@role_required("student")
def for_you():
    loans = open_loans(g.user["id"])
    recs = recommend(g.user["id"], limit=6)
    stats = student_insights(g.user["id"])
    tips = student_suggestions(stats, loans, recs)
    holding = {loan["book_id"] for loan in loans}
    return render_template("student/for_you.html", recs=recs, stats=stats, tips=tips, holding=holding)


@bp.route("/history")
@role_required("student")
def history():
    return render_template("student/history.html", loans=loan_history(g.user["id"]))
