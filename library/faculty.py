"""Faculty screens: what students are reading, by category and by student."""
from flask import Blueprint, abort, render_template, request

from .catalog import CATEGORIES
from .db import query
from .insights import library_overview, readers_of, student_category_matrix, student_insights
from .services import loan_history, open_loans
from .utils import role_required

bp = Blueprint("faculty", __name__, url_prefix="/faculty")


@bp.route("/")
@role_required("faculty")
def dashboard():
    return render_template("faculty/dashboard.html", o=library_overview())


@bp.route("/students")
@role_required("faculty")
def students():
    category = request.args.get("category", "")
    category = category if category in CATEGORIES else ""
    return render_template(
        "faculty/students.html",
        matrix=student_category_matrix(),
        category=category,
        readers=readers_of(category) if category else None,
        categories=CATEGORIES,
    )


@bp.route("/students/<int:user_id>")
@role_required("faculty")
def student_detail(user_id):
    student = query("SELECT * FROM users WHERE id = ? AND role = 'student'", (user_id,), one=True)
    if student is None:
        abort(404)
    return render_template(
        "faculty/student_detail.html",
        student=student,
        stats=student_insights(user_id),
        current=open_loans(user_id),
        history=loan_history(user_id),
    )
