"""Simple insights for students, faculty and librarians."""
from collections import Counter
from datetime import timedelta

from flask import current_app

from .catalog import CATEGORIES, category_color
from .db import from_ts, query, scalar, to_ts, utcnow
from .services import BOOK_SELECT, days_left, days_overdue, fine_for, loan_history


def _months(n=6):
    """The last n calendar months as (key 'YYYY-MM', short label) oldest first."""
    today = utcnow().date().replace(day=1)
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append((f"{y:04d}-{m:02d}", today.replace(year=y, month=m).strftime("%b")))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _bars(counter, order=None):
    """Turn a Counter into rows for a bar chart, with share of total and category colour."""
    total = sum(counter.values()) or 1
    top = max(counter.values(), default=1) or 1
    keys = order or [k for k, _ in counter.most_common()]
    return [
        {"label": k, "n": counter.get(k, 0), "pct": round(100 * counter.get(k, 0) / total),
         "width": round(100 * counter.get(k, 0) / top), "color": category_color(k)}
        for k in keys if counter.get(k, 0)
    ]


def _monthly(rows, field="issued_at", months=6):
    keys = _months(months)
    counts = Counter(r[field][:7] for r in rows)
    top = max((counts.get(k, 0) for k, _ in keys), default=0) or 1
    return [{"label": label, "n": counts.get(k, 0), "height": round(100 * counts.get(k, 0) / top)}
            for k, label in keys]


# ---------------- students ----------------

def student_insights(user_id):
    rows = loan_history(user_id)
    returned = [r for r in rows if r["returned_at"]]
    on_time = sum(1 for r in returned if days_overdue(r) == 0)
    kept = [(from_ts(r["returned_at"]) - from_ts(r["issued_at"])).days for r in returned]
    cats = Counter(r["category"] for r in rows)
    favorite, fav_n = (cats.most_common(1)[0] if cats else (None, 0))
    last = rows[0] if rows else None
    return {
        "total": len(rows),
        "current": sum(1 for r in rows if not r["returned_at"]),
        "returned": len(returned),
        "on_time": on_time,
        "on_time_rate": round(100 * on_time / len(returned)) if returned else None,
        "avg_days": round(sum(kept) / len(kept), 1) if kept else None,
        "authors": len({r["author"] for r in rows}),
        "favorite": favorite,
        "favorite_share": round(100 * fav_n / len(rows)) if rows else 0,
        "explored": len(cats),
        "category_total": len(CATEGORIES),
        "categories": _bars(cats),
        "monthly": _monthly(rows),
        "days_since_last": (utcnow() - from_ts(last["issued_at"])).days if last else None,
        "fines_paid": sum(fine_for(r) for r in returned),
    }


def student_suggestions(insights, loans, recs):
    cfg = current_app.config
    tips = []
    for loan in loans:
        late = days_overdue(loan)
        left = days_left(loan)
        if late:
            tips.append(("alert", f"“{loan['title']}” is {late} day{'s' if late != 1 else ''} overdue. "
                                  f"Return it soon: the fine is ₹{fine_for(loan)} and rises ₹{cfg['FINE_PER_DAY']} a day."))
        elif left <= 3:
            when = "today" if left == 0 else ("tomorrow" if left == 1 else f"in {left} days")
            tips.append(("warn", f"“{loan['title']}” is due {when}."))
    if len(loans) >= cfg["MAX_ACTIVE_LOANS"]:
        tips.append(("info", f"You're holding the maximum of {cfg['MAX_ACTIVE_LOANS']} books. Return one to borrow more."))

    if insights["total"] == 0:
        tips.append(("info", "Borrow your first book. Recommendations get sharper with every book you read."))
        return tips

    explore = next((r for r in recs if r["kind"] == "explore"), None)
    if insights["total"] >= 3 and insights["favorite_share"] >= 60:
        msg = f"{insights['favorite_share']}% of your reading is {insights['favorite']}."
        if explore:
            msg += f" To broaden it, try “{explore['book']['title']}” ({explore['book']['category']})."
        tips.append(("idea", msg))
    elif insights["explored"] >= 4:
        tips.append(("good", f"You've read across {insights['explored']} categories. That's a well-rounded shelf."))

    rate = insights["on_time_rate"]
    if rate is not None and insights["returned"] >= 2:
        if rate < 80:
            late = insights["returned"] - insights["on_time"]
            tips.append(("warn", f"{late} of your {insights['returned']} returns were late. "
                                 f"Set a reminder a couple of days before the due date."))
        elif rate == 100 and insights["returned"] >= 3:
            tips.append(("good", f"All {insights['returned']} of your returns were on time."))

    gap = insights["days_since_last"]
    if not loans and gap is not None and gap > 30:
        tips.append(("idea", f"It's been {gap} days since you last borrowed. Your picks below are a good place to restart."))
    return tips


# ---------------- library-wide (faculty and librarian) ----------------

def library_overview(days=180):
    since = to_ts(utcnow() - timedelta(days=days))
    today = to_ts(utcnow().replace(hour=0, minute=0, second=0))
    month_ago = to_ts(utcnow() - timedelta(days=30))
    student_loans = query(
        "SELECT l.*, b.category, b.title, b.author, u.full_name FROM loans l"
        " JOIN books b ON b.id = l.book_id JOIN users u ON u.id = l.user_id"
        " WHERE u.role = 'student' AND l.issued_at >= ?", (since,)
    )
    top_books = Counter((r["book_id"], r["title"], r["author"], r["category"]) for r in student_loans)
    top_readers = Counter((r["user_id"], r["full_name"]) for r in student_loans)
    cats = Counter(r["category"] for r in student_loans)
    return {
        "titles": scalar("SELECT COUNT(*) FROM books WHERE is_active = 1"),
        "copies": scalar("SELECT COALESCE(SUM(total_copies), 0) FROM books WHERE is_active = 1"),
        "out": scalar("SELECT COUNT(*) FROM loans WHERE returned_at IS NULL"),
        "overdue": scalar("SELECT COUNT(*) FROM loans WHERE returned_at IS NULL AND due_at < ?", (today,)),
        "students": scalar("SELECT COUNT(*) FROM users WHERE role = 'student'"),
        "active_readers": scalar(
            "SELECT COUNT(DISTINCT l.user_id) FROM loans l JOIN users u ON u.id = l.user_id"
            " WHERE u.role = 'student' AND l.issued_at >= ?", (month_ago,)),
        "loans_period": len(student_loans),
        "categories": _bars(cats),
        "top_category": cats.most_common(1)[0][0] if cats else None,
        "top_books": [{"id": k[0], "title": k[1], "author": k[2], "category": k[3], "n": n,
                       "color": category_color(k[3])} for k, n in top_books.most_common(5)],
        "top_readers": [{"id": k[0], "name": k[1], "n": n} for k, n in top_readers.most_common(5)],
        "monthly": _monthly(student_loans),
        "days": days,
    }


def student_category_matrix():
    """Rows of students with how many books they borrowed in each category, plus current reads."""
    students = query("SELECT * FROM users WHERE role = 'student' ORDER BY full_name COLLATE NOCASE")
    counts = query(
        "SELECT l.user_id, b.category, COUNT(*) AS n FROM loans l JOIN books b ON b.id = l.book_id"
        " GROUP BY l.user_id, b.category"
    )
    current = query(
        "SELECT l.user_id, l.due_at, b.title, b.category FROM loans l JOIN books b ON b.id = l.book_id"
        " WHERE l.returned_at IS NULL ORDER BY l.issued_at DESC"
    )
    by_user = {}
    for r in counts:
        by_user.setdefault(r["user_id"], Counter())[r["category"]] = r["n"]
    reading = {}
    for r in current:
        reading.setdefault(r["user_id"], []).append(r)
    peak = max((n for c in by_user.values() for n in c.values()), default=1)
    present = {cat for c in by_user.values() for cat in c}
    used = [c for c in CATEGORIES if c in present] + sorted(present - set(CATEGORIES))
    rows = []
    for s in students:
        c = by_user.get(s["id"], Counter())
        rows.append({
            "user": s,
            "counts": c,
            "total": sum(c.values()),
            "top": c.most_common(1)[0][0] if c else None,
            "current": reading.get(s["id"], []),
        })
    return {"rows": rows, "categories": used, "peak": peak}


def readers_of(category):
    """Students who borrowed books in a category, with the titles they read."""
    rows = query(
        "SELECT u.id AS user_id, u.full_name, u.username, b.title, l.issued_at, l.returned_at"
        " FROM loans l JOIN books b ON b.id = l.book_id JOIN users u ON u.id = l.user_id"
        " WHERE u.role = 'student' AND b.category = ? ORDER BY l.issued_at DESC",
        (category,),
    )
    grouped = {}
    for r in rows:
        g = grouped.setdefault(r["user_id"], {"name": r["full_name"], "username": r["username"], "id": r["user_id"],
                                              "titles": [], "reading_now": [], "last": r["issued_at"]})
        if r["title"] not in g["titles"]:
            g["titles"].append(r["title"])
        if not r["returned_at"]:
            g["reading_now"].append(r["title"])
    return sorted(grouped.values(), key=lambda g: (-len(g["titles"]), g["name"]))


# ---------------- librarian ----------------

def stock_insights(days=180):
    since = to_ts(utcnow() - timedelta(days=days))
    books = query(BOOK_SELECT + " WHERE b.is_active = 1")
    loans = query(
        "SELECT l.book_id, b.category FROM loans l JOIN books b ON b.id = l.book_id WHERE l.issued_at >= ?", (since,)
    )
    demand = Counter(r["category"] for r in loans)
    per_book = Counter(r["book_id"] for r in loans)
    copies = Counter()
    for b in books:
        copies[b["category"]] += b["total_copies"]

    rows = []
    for cat in CATEGORIES:
        if copies[cat] or demand[cat]:
            rows.append({"category": cat, "color": category_color(cat), "copies": copies[cat],
                         "loans": demand[cat], "ratio": round(demand[cat] / copies[cat], 1) if copies[cat] else None})
    rows.sort(key=lambda r: (r["ratio"] is None, -(r["ratio"] or 0)))

    ever = {r["book_id"] for r in query("SELECT DISTINCT book_id FROM loans")}
    all_out = [b for b in books if b["available"] <= 0 and b["total_copies"] > 0]
    never = [b for b in books if b["id"] not in ever]
    hot = sorted((b for b in books if per_book[b["id"]] >= 3), key=lambda b: per_book[b["id"]] / max(b["total_copies"], 1),
                 reverse=True)[:3]

    tips = []
    ratios = [r["ratio"] for r in rows if r["ratio"] is not None]
    average = sum(ratios) / len(ratios) if ratios else 0
    if rows and rows[0]["ratio"] and rows[0]["ratio"] >= 1.5 * average and rows[0]["loans"] >= 3:
        tips.append(("idea", f"{rows[0]['category']} has the most loans per copy: {rows[0]['loans']} loans across "
                             f"{rows[0]['copies']} copies in {days} days, against {average:.1f} per copy library-wide. "
                             f"Consider adding copies."))
    for b in hot:
        if b["available"] <= 0:
            tips.append(("warn", f"Every copy of “{b['title']}” is out and it's been borrowed {per_book[b['id']]} times. "
                                 f"An extra copy would help."))
    if never:
        sample = ", ".join(f"“{b['title']}”" for b in never[:3])
        tips.append(("info", f"{len(never)} title{'s have' if len(never) != 1 else ' has'} never been borrowed, "
                             f"including {sample}. A display shelf might help."))
    return {"rows": rows, "all_out": all_out, "never": never, "tips": tips, "days": days}


def overdue_loans():
    today = to_ts(utcnow().replace(hour=0, minute=0, second=0))
    rows = query(
        "SELECT l.*, b.title, b.category, u.full_name, u.username, u.email FROM loans l"
        " JOIN books b ON b.id = l.book_id JOIN users u ON u.id = l.user_id"
        " WHERE l.returned_at IS NULL AND l.due_at < ? ORDER BY l.due_at", (today,)
    )
    return [dict(r, late=days_overdue(r), fine=fine_for(r)) for r in rows]
