from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from pathlib import Path
from datetime import datetime
import re

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "lost_found.db"
app = Flask(__name__)
app.secret_key = "change-this-demo-secret-key"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL CHECK(report_type IN ('lost', 'found')),
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                location TEXT NOT NULL,
                item_date TEXT NOT NULL,
                contact_name TEXT NOT NULL,
                contact_email TEXT NOT NULL,
                contact_phone TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        # Migrate databases created by earlier versions of this project.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
        if "contact_phone" not in columns:
            conn.execute("ALTER TABLE items ADD COLUMN contact_phone TEXT NOT NULL DEFAULT ''")


def clean_text(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def get_items():
    with get_db() as conn:
        return conn.execute("SELECT * FROM items ORDER BY id DESC").fetchall()


def similarity_score(lost, found):
    """Return an approximate text + category + location similarity score."""
    text_a = f"{lost['title']} {lost['category']} {lost['description']} {lost['location']}"
    text_b = f"{found['title']} {found['category']} {found['description']} {found['location']}"
    if SKLEARN_AVAILABLE:
        try:
            matrix = TfidfVectorizer(stop_words="english").fit_transform([text_a, text_b])
            text_score = float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])
        except ValueError:
            text_score = 0.0
    else:
        words_a = set(re.findall(r"\w+", text_a.lower()))
        words_b = set(re.findall(r"\w+", text_b.lower()))
        text_score = len(words_a & words_b) / max(1, len(words_a | words_b))

    category_bonus = 0.20 if lost["category"].lower() == found["category"].lower() else 0.0
    location_bonus = 0.10 if lost["location"].lower() == found["location"].lower() else 0.0
    title_words_a = set(re.findall(r"\w+", lost["title"].lower()))
    title_words_b = set(re.findall(r"\w+", found["title"].lower()))
    title_bonus = 0.10 if title_words_a & title_words_b else 0.0
    return round(min(1.0, text_score * 0.60 + category_bonus + location_bonus + title_bonus), 3)


def get_matches(item, all_items):
    opposite = "found" if item["report_type"] == "lost" else "lost"
    candidates = [x for x in all_items if x["report_type"] == opposite and x["id"] != item["id"]]
    matches = []
    for candidate in candidates:
        score = similarity_score(item, candidate) if item["report_type"] == "lost" else similarity_score(candidate, item)
        if score >= 0.08:
            matches.append({"item": candidate, "score": score})
    return sorted(matches, key=lambda x: x["score"], reverse=True)[:5]


@app.route("/")
def index():
    items = get_items()
    lost_count = sum(1 for x in items if x["report_type"] == "lost")
    found_count = sum(1 for x in items if x["report_type"] == "found")
    recent = items[:6]
    return render_template("index.html", lost_count=lost_count, found_count=found_count, recent=recent)


@app.route("/report/<report_type>", methods=["GET", "POST"])
def report(report_type):
    if report_type not in ("lost", "found"):
        return redirect(url_for("index"))
    if request.method == "POST":
        fields = {
            "title": clean_text(request.form.get("title")),
            "category": clean_text(request.form.get("category")),
            "description": clean_text(request.form.get("description")),
            "location": clean_text(request.form.get("location")),
            "item_date": clean_text(request.form.get("item_date")),
            "contact_name": clean_text(request.form.get("contact_name")),
            "contact_email": clean_text(request.form.get("contact_email")),
            "contact_phone": clean_text(request.form.get("contact_phone")),
        }
        if any(not value for value in fields.values()):
            flash("Please complete every field before submitting.", "error")
            return render_template("report.html", report_type=report_type, form=request.form)
        if "@" not in fields["contact_email"] or "." not in fields["contact_email"].split("@")[-1]:
            flash("Please enter a valid email address.", "error")
            return render_template("report.html", report_type=report_type, form=request.form)
        phone_digits = re.sub(r"\D", "", fields["contact_phone"])
        if len(phone_digits) < 7 or len(phone_digits) > 15:
            flash("Please enter a valid phone number, including country code if possible.", "error")
            return render_template("report.html", report_type=report_type, form=request.form)
        with get_db() as conn:
            cur = conn.execute("""
                INSERT INTO items
                (report_type, title, category, description, location, item_date,
                 contact_name, contact_email, contact_phone, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (report_type, fields["title"], fields["category"], fields["description"],
                  fields["location"], fields["item_date"], fields["contact_name"],
                  fields["contact_email"], fields["contact_phone"],
                  datetime.now().isoformat(timespec="seconds")))
            item_id = cur.lastrowid
        flash("Your report was submitted. We found possible matches to review.", "success")
        return redirect(url_for("item_detail", item_id=item_id))
    return render_template("report.html", report_type=report_type, form={})


@app.route("/search")
def search():
    query = clean_text(request.args.get("q", "")).lower()
    category = clean_text(request.args.get("category", ""))
    report_type = clean_text(request.args.get("type", ""))
    items = get_items()
    if query:
        items = [x for x in items if query in " ".join(str(x[k]) for k in ("title", "description", "location", "category")).lower()]
    if category:
        items = [x for x in items if x["category"] == category]
    if report_type in ("lost", "found"):
        items = [x for x in items if x["report_type"] == report_type]
    categories = sorted({x["category"] for x in get_items()})
    return render_template("search.html", items=items, q=query, category=category,
                           report_type=report_type, categories=categories)


@app.route("/item/<int:item_id>")
def item_detail(item_id):
    with get_db() as conn:
        item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        flash("That report could not be found.", "error")
        return redirect(url_for("search"))
    matches = get_matches(item, get_items())
    return render_template("detail.html", item=item, matches=matches)


@app.route("/admin")
def admin():
    # Demo-only admin page. Add authentication before any real deployment.
    items = get_items()
    return render_template("admin.html", items=items)


@app.route("/admin/delete/<int:item_id>", methods=["POST"])
def delete_item(item_id):
    # Demo-only action. Add authentication and authorization before deployment.
    with get_db() as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    flash("Report deleted.", "success")
    return redirect(url_for("admin"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
