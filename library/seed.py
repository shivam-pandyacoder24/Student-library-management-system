"""Demo catalogue, demo accounts and a realistic borrowing history so every screen has data."""
import random
from datetime import timedelta

from .db import to_ts, utcnow

BOOKS = [
    # (title, author, category, year)
    ("Clean Code", "Robert C. Martin", "Programming", 2008),
    ("The Pragmatic Programmer", "Andrew Hunt & David Thomas", "Programming", 1999),
    ("Introduction to Algorithms", "Thomas H. Cormen et al.", "Programming", 2009),
    ("Python Crash Course", "Eric Matthes", "Programming", 2019),
    ("Fluent Python", "Luciano Ramalho", "Programming", 2022),
    ("The C Programming Language", "Brian W. Kernighan & Dennis M. Ritchie", "Programming", 1988),
    ("Automate the Boring Stuff with Python", "Al Sweigart", "Programming", 2019),
    ("Artificial Intelligence: A Modern Approach", "Stuart Russell & Peter Norvig", "Artificial Intelligence", 2020),
    ("Deep Learning", "Ian Goodfellow, Yoshua Bengio & Aaron Courville", "Artificial Intelligence", 2016),
    ("Hands-On Machine Learning with Scikit-Learn, Keras & TensorFlow", "Aurélien Géron", "Artificial Intelligence", 2022),
    ("Human Compatible", "Stuart Russell", "Artificial Intelligence", 2019),
    ("Life 3.0", "Max Tegmark", "Artificial Intelligence", 2017),
    ("The Master Algorithm", "Pedro Domingos", "Artificial Intelligence", 2015),
    ("Python for Data Analysis", "Wes McKinney", "Data Science", 2022),
    ("Naked Statistics", "Charles Wheelan", "Data Science", 2013),
    ("Storytelling with Data", "Cole Nussbaumer Knaflic", "Data Science", 2015),
    ("The Signal and the Noise", "Nate Silver", "Data Science", 2012),
    ("Data Science from Scratch", "Joel Grus", "Data Science", 2019),
    ("Linear Algebra Done Right", "Sheldon Axler", "Mathematics", 2015),
    ("How Not to Be Wrong", "Jordan Ellenberg", "Mathematics", 2014),
    ("Fermat's Last Theorem", "Simon Singh", "Mathematics", 1997),
    ("Concrete Mathematics", "Ronald L. Graham, Donald E. Knuth & Oren Patashnik", "Mathematics", 1994),
    ("A Brief History of Time", "Stephen Hawking", "Science", 1988),
    ("The Selfish Gene", "Richard Dawkins", "Science", 1976),
    ("Cosmos", "Carl Sagan", "Science", 1980),
    ("The Gene: An Intimate History", "Siddhartha Mukherjee", "Science", 2016),
    ("The Intelligent Investor", "Benjamin Graham", "Finance & Economics", 1949),
    ("Thinking, Fast and Slow", "Daniel Kahneman", "Finance & Economics", 2011),
    ("The Psychology of Money", "Morgan Housel", "Finance & Economics", 2020),
    ("Rich Dad Poor Dad", "Robert T. Kiyosaki", "Finance & Economics", 1997),
    ("A Random Walk Down Wall Street", "Burton G. Malkiel", "Finance & Economics", 1973),
    ("Freakonomics", "Steven D. Levitt & Stephen J. Dubner", "Finance & Economics", 2005),
    ("To Kill a Mockingbird", "Harper Lee", "Fiction", 1960),
    ("Nineteen Eighty-Four", "George Orwell", "Fiction", 1949),
    ("The Alchemist", "Paulo Coelho", "Fiction", 1988),
    ("The God of Small Things", "Arundhati Roy", "Fiction", 1997),
    ("Malgudi Days", "R. K. Narayan", "Fiction", 1943),
    ("Project Hail Mary", "Andy Weir", "Fiction", 2021),
    ("Sapiens", "Yuval Noah Harari", "History", 2011),
    ("The Discovery of India", "Jawaharlal Nehru", "History", 1946),
    ("Guns, Germs, and Steel", "Jared Diamond", "History", 1997),
    ("India After Gandhi", "Ramachandra Guha", "History", 2007),
    ("Wings of Fire", "A. P. J. Abdul Kalam", "Biography", 1999),
    ("Steve Jobs", "Walter Isaacson", "Biography", 2011),
    ("The Story of My Experiments with Truth", "M. K. Gandhi", "Biography", 1927),
    ("The Man Who Knew Infinity", "Robert Kanigel", "Biography", 1991),
    ("Atomic Habits", "James Clear", "Self-Help", 2018),
    ("Deep Work", "Cal Newport", "Self-Help", 2016),
    ("Mindset", "Carol S. Dweck", "Self-Help", 2006),
    ("Ikigai", "Héctor García & Francesc Miralles", "Self-Help", 2016),
]

POPULAR = {"Atomic Habits", "The Psychology of Money", "Hands-On Machine Learning with Scikit-Learn, Keras & TensorFlow",
           "Python Crash Course", "Sapiens", "Wings of Fire", "Clean Code"}

STAFF = [
    # username, email, name, role, department
    ("librarian", "librarian@example.com", "Lakshmi Iyer", "librarian", "Central Library"),
    ("prof.raghav", "raghav.menon@example.com", "Dr. Raghav Menon", "faculty", "Computer Science"),
]

STUDENTS = [
    # username, name, department, favourite categories, open loans as (days until due)
    ("aarav.k", "Aarav Krishnan", "B.Tech AI", ["Artificial Intelligence", "Programming", "Data Science"], [2, 9]),
    ("diya.s", "Diya Sharma", "B.Tech CSE", ["Fiction", "Self-Help"], [1]),
    ("kabir.r", "Kabir Reddy", "B.Tech AI", ["Finance & Economics", "Data Science"], [-4]),
    ("meera.n", "Meera Nair", "B.Sc Physics", ["Science", "Mathematics"], [6]),
    ("rohan.p", "Rohan Patel", "B.Tech IT", ["Programming", "Self-Help"], []),
    ("sneha.v", "Sneha Varma", "BBA", ["Finance & Economics", "Biography"], [11]),
    ("arjun.m", "Arjun Mehta", "B.Tech CSE", ["History", "Fiction", "Biography"], [-2]),
    ("priya.d", "Priya Das", "B.Tech AI", ["Artificial Intelligence", "Mathematics"], []),
]


def seed_demo(conn, loan_days=14, force=False, rng_seed=7):
    """Fill an empty database with demo data. With force=True, wipe everything first."""
    if force:
        conn.executescript("DELETE FROM loans; DELETE FROM otp_codes; DELETE FROM books; DELETE FROM users;"
                           "DELETE FROM sqlite_sequence;")
    elif conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]:
        return False

    rng = random.Random(rng_seed)
    now = utcnow()

    def at(days_ago):
        return now - timedelta(days=days_ago, hours=rng.randint(0, 8), minutes=rng.randint(0, 59))

    created = to_ts(now - timedelta(days=200))
    staff_ids = {}
    for username, email, name, role, dept in STAFF:
        cur = conn.execute(
            "INSERT INTO users (username, email, full_name, role, department, is_demo, created_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?)", (username, email, name, role, dept, created))
        staff_ids[role] = cur.lastrowid

    books = []
    for title, author, category, year in BOOKS:
        copies = rng.randint(2, 4) + (1 if title in POPULAR else 0)
        cur = conn.execute(
            "INSERT INTO books (title, author, category, published_year, total_copies, added_by, added_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, author, category, year, copies, staff_ids["librarian"], created))
        books.append({"id": cur.lastrowid, "title": title, "category": category, "copies": copies})

    out_now = {b["id"]: 0 for b in books}
    for username, name, dept, likes, open_due in STUDENTS:
        cur = conn.execute(
            "INSERT INTO users (username, email, full_name, role, department, is_demo, created_at)"
            " VALUES (?, ?, ?, 'student', ?, 1, ?)",
            (username, f"{username.replace('.', '')}@example.com", name, dept, created))
        uid = cur.lastrowid

        weights = [(6 if b["category"] in likes else 1) * (2 if b["title"] in POPULAR else 1) for b in books]
        picks = []
        target = rng.randint(6, 11) + len(open_due)
        while len(picks) < target:
            b = rng.choices(books, weights)[0]
            if b not in picks:
                picks.append(b)

        past, current = picks[len(open_due):], picks[:len(open_due)]
        for b, days_ago in zip(past, sorted(rng.sample(range(22, 175), len(past)), reverse=True)):
            issued = at(days_ago)
            kept = loan_days + rng.randint(1, 5) if rng.random() < 0.15 else rng.randint(4, loan_days)
            conn.execute(
                "INSERT INTO loans (user_id, book_id, issued_at, due_at, returned_at) VALUES (?, ?, ?, ?, ?)",
                (uid, b["id"], to_ts(issued), to_ts(issued + timedelta(days=loan_days)),
                 to_ts(issued + timedelta(days=kept))))

        for b, due_in in zip(current, open_due):
            if out_now[b["id"]] >= b["copies"]:
                continue
            out_now[b["id"]] += 1
            issued = now - timedelta(days=loan_days - due_in)
            conn.execute(
                "INSERT INTO loans (user_id, book_id, issued_at, due_at) VALUES (?, ?, ?, ?)",
                (uid, b["id"], to_ts(issued), to_ts(issued + timedelta(days=loan_days))))
    conn.commit()
    return True
