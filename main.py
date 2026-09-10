from flask import Blueprint, render_template, request, redirect, url_for, current_app

from .db import get_db
from .security import current_user, login_required, csrf_protect, get_csrf_token

bp = Blueprint("main", __name__)


@bp.before_request
def _csrf():
    csrf_protect()


@bp.route("/")
def index():
    if current_user():
        return redirect(url_for("main.feed"))
    return render_template("index.html")


@bp.route("/about")
def about():
    return render_template("about.html")


# ---------------------------------------------------------------------------
# Onboarding survey — optional, skippable, editable later (see settings)
# ---------------------------------------------------------------------------

SURVEY_QUESTIONS = [
    ("conversations_enjoyed", "What kind of conversations do you enjoy?"),
    ("currently_curious", "What are you curious about right now?"),
    ("currently_learning", "What are you currently trying to learn?"),
    ("looking_for", "What would you like to find on WE ARE.?"),
]

INTEREST_CATEGORIES = {
    "topic": [
        "Technology", "Science", "Music", "Movies", "Books", "Gaming", "Art",
        "Photography", "Travel", "Sports", "Entrepreneurship", "Languages",
        "Study", "Fashion", "Mythology", "Culture",
    ],
    "character": [
        "Curious", "Creative", "Analytical", "Ambitious", "Calm",
        "Open-minded", "Adventurous", "Thoughtful",
    ],
}


@bp.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        if request.form.get("action") != "skip":
            selected_interests = request.form.getlist("interests")
            for name in selected_interests:
                row = db.execute("SELECT id FROM interests WHERE name = ?", (name,)).fetchone()
                if row:
                    db.execute(
                        "INSERT OR IGNORE INTO user_interests (user_id, interest_id) VALUES (?, ?)",
                        (user["id"], row["id"]),
                    )

            for key, _ in SURVEY_QUESTIONS:
                answer = request.form.get(key, "").strip()
                if answer:
                    db.execute(
                        """INSERT INTO survey_responses (user_id, question_key, response_text)
                           VALUES (?, ?, ?)
                           ON CONFLICT(user_id, question_key)
                           DO UPDATE SET response_text = excluded.response_text, updated_at = datetime('now')""",
                        (user["id"], key, answer),
                    )
            db.commit()
        return redirect(url_for("main.feed"))

    return render_template(
        "onboarding.html",
        interest_categories=INTEREST_CATEGORIES,
        survey_questions=SURVEY_QUESTIONS,
        csrf_token=get_csrf_token(),
    )


@bp.route("/feed")
@login_required
def feed():
    user = current_user()
    db = get_db()
    posts = db.execute(
        """SELECT posts.*, users.username, users.display_name
           FROM posts JOIN users ON users.id = posts.user_id
           ORDER BY posts.created_at DESC LIMIT 30"""
    ).fetchall()
    return render_template("feed.html", user=user, posts=posts)


@bp.route("/discover")
@login_required
def discover():
    return render_template("discover.html")


@bp.route("/profile/<username>")
def profile(username):
    db = get_db()
    row = db.execute(
        """SELECT users.id, users.username, users.display_name, users.show_real_name,
                  profiles.* FROM users JOIN profiles ON profiles.user_id = users.id
           WHERE users.username = ?""",
        (username,),
    ).fetchone()
    if row is None:
        return render_template("404.html"), 404
    interests = db.execute(
        """SELECT interests.name, interests.category FROM user_interests
           JOIN interests ON interests.id = user_interests.interest_id
           WHERE user_interests.user_id = ?""",
        (row["id"],),
    ).fetchall()
    return render_template("profile.html", profile=row, interests=interests)
