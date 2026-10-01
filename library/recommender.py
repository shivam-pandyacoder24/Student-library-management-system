"""Book recommendations from borrowing history.

Each unread book gets a score from four simple signals:
  * category match   - how much of the student's reading is in that category (recent reads count more)
  * same author      - the student has read this author before
  * co-borrowing     - other students who borrowed the same books also borrowed this one
  * popularity       - how often it was borrowed in the last 180 days
An author match or a strong co-borrowing link becomes the reason shown on the card, otherwise
the category match. At most two picks share a category, and one pick always comes from a
category the student hasn't read yet, so the list doesn't become an echo chamber.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from math import sqrt

from .db import from_ts, query, to_ts, utcnow
from .services import BOOK_SELECT

WEIGHTS = {"category": 0.6, "author": 0.25, "co": 0.35, "popular": 0.1}
MAX_PER_CATEGORY = 2
MIN_SHARED_READERS = 2  # ignore "also borrowed" links backed by a single student
HALF_LIFE_DAYS = 90


def _popularity(days=180):
    since = to_ts(utcnow() - timedelta(days=days))
    rows = query("SELECT book_id, COUNT(*) AS n FROM loans WHERE issued_at >= ? GROUP BY book_id", (since,))
    counts = {r["book_id"]: r["n"] for r in rows}
    top = max(counts.values(), default=1)
    return {k: v / top for k, v in counts.items()}, counts


def user_profile(user_id):
    """Category weights (with recency decay), authors and book ids from a user's history."""
    rows = query(
        "SELECT l.book_id, l.issued_at, b.category, b.author, b.title FROM loans l"
        " JOIN books b ON b.id = l.book_id WHERE l.user_id = ?",
        (user_id,),
    )
    now = utcnow()
    cat = Counter()
    for r in rows:
        age = (now - from_ts(r["issued_at"])).days
        cat[r["category"]] += 0.5 ** (age / HALF_LIFE_DAYS)
    total = sum(cat.values()) or 1
    return {
        "rows": rows,
        "read_ids": {r["book_id"] for r in rows},
        "categories": {k: v / total for k, v in cat.items()},
        "authors": {r["author"] for r in rows},
        "titles": {r["book_id"]: r["title"] for r in rows},
    }


def _co_borrowed(user_id, read_ids):
    """How strongly each book co-occurs with the user's books in other students' histories.

    Uses cosine similarity (shared readers / sqrt(readers_a * readers_b)) so that books
    everyone borrows don't drown out more specific connections.
    """
    if not read_ids:
        return {}, {}
    readers = {r["book_id"]: r["n"] for r in query(
        "SELECT book_id, COUNT(DISTINCT user_id) AS n FROM loans GROUP BY book_id")}
    marks = ",".join("?" * len(read_ids))
    rows = query(
        f"""SELECT mine.book_id AS anchor, theirs.book_id AS other, COUNT(DISTINCT theirs.user_id) AS n
            FROM loans mine
            JOIN loans theirs ON theirs.user_id = mine.user_id AND theirs.book_id != mine.book_id
            WHERE mine.book_id IN ({marks}) AND mine.user_id != ?
            GROUP BY mine.book_id, theirs.book_id
            HAVING COUNT(DISTINCT theirs.user_id) >= ?""",
        (*read_ids, user_id, MIN_SHARED_READERS),
    )
    score = defaultdict(float)
    best_anchor, best_sim = {}, defaultdict(float)
    for r in rows:
        sim = r["n"] / sqrt(readers.get(r["anchor"], 1) * readers.get(r["other"], 1))
        score[r["other"]] += sim
        if sim > best_sim[r["other"]]:
            best_sim[r["other"]], best_anchor[r["other"]] = sim, r["anchor"]
    top = max(score.values(), default=1) or 1
    return {k: v / top for k, v in score.items()}, best_anchor


def recommend(user_id, limit=6):
    profile = user_profile(user_id)
    popular, pop_counts = _popularity()
    books = query(BOOK_SELECT + " WHERE b.is_active = 1")
    candidates = [b for b in books if b["id"] not in profile["read_ids"]]

    # Cold start: nothing borrowed yet, so suggest what's popular (and on the shelf).
    if not profile["read_ids"]:
        ranked = sorted(candidates, key=lambda b: (b["available"] > 0, pop_counts.get(b["id"], 0)), reverse=True)
        return [_card(b, "Popular with students this semester", "popular") for b in ranked[:limit]]

    co, anchors = _co_borrowed(user_id, profile["read_ids"])
    top_cat = max(profile["categories"].values(), default=1) or 1
    scored = []
    for b in candidates:
        parts = {
            "category": WEIGHTS["category"] * profile["categories"].get(b["category"], 0) / top_cat,
            "author": WEIGHTS["author"] if b["author"] in profile["authors"] else 0,
            "co": WEIGHTS["co"] * co.get(b["id"], 0),
            "popular": WEIGHTS["popular"] * popular.get(b["id"], 0),
        }
        total = sum(parts.values())
        if b["available"] <= 0:
            total *= 0.8  # still worth showing, but prefer books on the shelf
        scored.append((total, parts, b))
    scored.sort(key=lambda t: t[0], reverse=True)

    picks, per_category = [], Counter()
    for total, parts, b in scored:
        if total <= 0 or len(picks) >= limit - 1:
            break
        if per_category[b["category"]] >= MAX_PER_CATEGORY:
            continue  # keep the list varied
        per_category[b["category"]] += 1
        if parts["author"]:
            kind, reason = "author", f"You've read {b['author']} before"
        elif parts["co"] >= 0.5 * WEIGHTS["co"] and b["id"] in anchors:
            kind, reason = "co", f"Readers of “{profile['titles'][anchors[b['id']]]}” also borrowed this"
        elif parts["category"] > 0:
            kind, reason = "category", f"Matches your interest in {b['category']}"
        else:
            kind, reason = "popular", "Popular with students this semester"
        picks.append(_card(b, reason, kind))

    # One deliberate 'something different' pick from a category the student hasn't explored.
    explore = explore_pick(profile, candidates, pop_counts, exclude={p["book"]["id"] for p in picks})
    if explore:
        picks.append(explore)

    # Top up with popular titles if the signals above didn't fill the list.
    if len(picks) < limit:
        taken = {p["book"]["id"] for p in picks}
        rest = sorted((b for b in candidates if b["id"] not in taken),
                      key=lambda b: (b["available"] > 0, pop_counts.get(b["id"], 0)), reverse=True)
        picks += [_card(b, "Popular with students this semester", "popular") for b in rest[: limit - len(picks)]]
    return picks[:limit]


def explore_pick(profile, candidates, pop_counts, exclude=()):
    unexplored = [b for b in candidates if b["category"] not in profile["categories"] and b["id"] not in exclude]
    if not unexplored:
        return None
    best = max(unexplored, key=lambda b: (b["available"] > 0, pop_counts.get(b["id"], 0), -b["id"]))
    return _card(best, f"Something different: you haven't tried {best['category']} yet", "explore")


def _card(book, reason, kind):
    return {"book": book, "reason": reason, "kind": kind}
