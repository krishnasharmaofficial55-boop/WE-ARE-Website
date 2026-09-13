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


@bp.route("/guidelines")
def guidelines():
    return render_template("guidelines.html")


@bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@bp.route("/terms")
def terms():
    return render_template("terms.html")


@bp.route("/contact", methods=["GET", "POST"])
def contact():
    sent = False
    if request.method == "POST":
        # In production this creates a support ticket or sends an email to
        # the safety/support team. Logged here only because there's no
        # ticketing backend configured in this environment.
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
        if name and email and message:
            current_app.logger.info("Contact form submission from %s <%s>: %s", name, email, message)
            sent = True
    return render_template("contact.html", sent=sent, csrf_token=get_csrf_token())


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
    from .posts import annotate_posts

    tab = request.args.get("tab", "for_you")
    if tab not in ("for_you", "following", "global"):
        tab = "for_you"

    followed_or_connected = db.execute(
        """SELECT DISTINCT followee_id AS uid FROM follows WHERE follower_id = ?
           UNION
           SELECT DISTINCT CASE WHEN user_a_id = ? THEN user_b_id ELSE user_a_id END AS uid
           FROM connections WHERE user_a_id = ? OR user_b_id = ?""",
        (user["id"], user["id"], user["id"], user["id"]),
    ).fetchall()
    network_ids = [r["uid"] for r in followed_or_connected]

    if tab == "global":
        posts = db.execute(
            """SELECT posts.*, users.username, users.display_name, users.show_real_name
               FROM posts JOIN users ON users.id = posts.user_id
               WHERE posts.visibility = 'public'
               ORDER BY posts.created_at DESC LIMIT 30"""
        ).fetchall()
    elif tab == "following":
        ids = network_ids or [-1]
        placeholders = ",".join("?" * len(ids))
        posts = db.execute(
            f"""SELECT posts.*, users.username, users.display_name, users.show_real_name
                FROM posts JOIN users ON users.id = posts.user_id
                WHERE posts.user_id IN ({placeholders})
                ORDER BY posts.created_at DESC LIMIT 30""",
            ids,
        ).fetchall()
    else:  # for_you — network posts plus posts from people who share an interest
        interest_ids = [
            r["interest_id"]
            for r in db.execute("SELECT interest_id FROM user_interests WHERE user_id = ?", (user["id"],)).fetchall()
        ]
        candidate_ids = set(network_ids)
        if interest_ids:
            placeholders = ",".join("?" * len(interest_ids))
            similar = db.execute(
                f"""SELECT DISTINCT user_id FROM user_interests
                    WHERE interest_id IN ({placeholders}) AND user_id != ?""",
                interest_ids + [user["id"]],
            ).fetchall()
            candidate_ids.update(r["user_id"] for r in similar)

        if candidate_ids:
            ids = list(candidate_ids)
            placeholders = ",".join("?" * len(ids))
            posts = db.execute(
                f"""SELECT posts.*, users.username, users.display_name, users.show_real_name
                    FROM posts JOIN users ON users.id = posts.user_id
                    WHERE posts.user_id IN ({placeholders}) AND posts.visibility = 'public'
                    ORDER BY posts.created_at DESC LIMIT 30""",
                ids,
            ).fetchall()
        else:
            posts = []

        if not posts:
            # Nothing tailored yet (new account, no interests, no network) —
            # fall back to recent global rather than showing an empty feed.
            posts = db.execute(
                """SELECT posts.*, users.username, users.display_name, users.show_real_name
                   FROM posts JOIN users ON users.id = posts.user_id
                   WHERE posts.visibility = 'public'
                   ORDER BY posts.created_at DESC LIMIT 30"""
            ).fetchall()

    posts = annotate_posts(db, posts, user["id"])
    return render_template("feed.html", user=user, posts=posts, tab=tab, csrf_token=get_csrf_token())


@bp.route("/discover")
@login_required
def discover():
    user = current_user()
    db = get_db()

    all_interests = db.execute("SELECT name, category FROM interests ORDER BY category, name").fetchall()
    selected = request.args.getlist("interest")

    # Exclude yourself and anyone who's blocked you or you've blocked.
    blocked_ids = {
        r["blocked_id"] if r["blocker_id"] == user["id"] else r["blocker_id"]
        for r in db.execute(
            "SELECT blocker_id, blocked_id FROM blocks WHERE blocker_id = ? OR blocked_id = ?",
            (user["id"], user["id"]),
        ).fetchall()
    }
    exclude_ids = blocked_ids | {user["id"]}

    if selected:
        placeholders = ",".join("?" * len(selected))
        candidates = db.execute(
            f"""SELECT users.id, users.username, users.display_name, users.show_real_name,
                       COUNT(DISTINCT user_interests.interest_id) AS shared_count
                FROM users
                JOIN user_interests ON user_interests.user_id = users.id
                JOIN interests ON interests.id = user_interests.interest_id
                WHERE interests.name IN ({placeholders}) AND users.is_active = 1
                GROUP BY users.id
                ORDER BY shared_count DESC, users.created_at DESC
                LIMIT 30""",
            selected,
        ).fetchall()
    else:
        # No filter chosen yet — default to people who share the viewer's own interests.
        my_interest_ids = [
            r["interest_id"]
            for r in db.execute("SELECT interest_id FROM user_interests WHERE user_id = ?", (user["id"],)).fetchall()
        ]
        if my_interest_ids:
            placeholders = ",".join("?" * len(my_interest_ids))
            candidates = db.execute(
                f"""SELECT users.id, users.username, users.display_name, users.show_real_name,
                           COUNT(DISTINCT user_interests.interest_id) AS shared_count
                    FROM users
                    JOIN user_interests ON user_interests.user_id = users.id
                    WHERE user_interests.interest_id IN ({placeholders}) AND users.is_active = 1
                    GROUP BY users.id
                    ORDER BY shared_count DESC, users.created_at DESC
                    LIMIT 30""",
                my_interest_ids,
            ).fetchall()
        else:
            candidates = db.execute(
                """SELECT id, username, display_name, show_real_name, 0 AS shared_count
                   FROM users WHERE is_active = 1
                   ORDER BY created_at DESC LIMIT 30"""
            ).fetchall()

    candidates = [c for c in candidates if c["id"] not in exclude_ids]

    # Age-aware filtering: don't surface minors to adults or adults to minors.
    # Exact birth date/age is never exposed — this only reads the private
    # is_minor flag server-side to decide who appears in whose results.
    candidate_ids = [c["id"] for c in candidates]
    if candidate_ids:
        placeholders = ",".join("?" * len(candidate_ids))
        minor_flags = {
            r["id"]: r["is_minor"]
            for r in db.execute(f"SELECT id, is_minor FROM users WHERE id IN ({placeholders})", candidate_ids).fetchall()
        }
        candidates = [c for c in candidates if minor_flags.get(c["id"]) == user["is_minor"]]

    # Attach each candidate's own interest tags and this viewer's relationship to them.
    results = []
    for c in candidates:
        tags = db.execute(
            """SELECT interests.name FROM user_interests
               JOIN interests ON interests.id = user_interests.interest_id
               WHERE user_interests.user_id = ? LIMIT 6""",
            (c["id"],),
        ).fetchall()
        following = db.execute(
            "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?", (user["id"], c["id"])
        ).fetchone() is not None
        from .social import are_connected

        results.append({
            "username": c["username"],
            "display_name": c["display_name"] if c["show_real_name"] else c["username"],
            "shared_count": c["shared_count"],
            "tags": [t["name"] for t in tags],
            "following": following,
            "connected": are_connected(db, user["id"], c["id"]),
        })

    return render_template(
        "discover.html",
        all_interests=all_interests,
        selected=selected,
        results=results,
        csrf_token=get_csrf_token(),
    )


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

    relationship = None
    viewer = current_user()
    if viewer and viewer["id"] != row["id"]:
        from .social import are_connected, _connection_pair

        following = db.execute(
            "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?",
            (viewer["id"], row["id"]),
        ).fetchone() is not None

        connected = are_connected(db, viewer["id"], row["id"])

        pending_outgoing = db.execute(
            """SELECT 1 FROM connection_requests WHERE sender_id = ? AND recipient_id = ?
               AND status = 'pending'""",
            (viewer["id"], row["id"]),
        ).fetchone() is not None

        pending_incoming = db.execute(
            """SELECT id FROM connection_requests WHERE sender_id = ? AND recipient_id = ?
               AND status = 'pending'""",
            (row["id"], viewer["id"]),
        ).fetchone()

        # Common ground, per the brief — shared interests instead of a score.
        shared_interests = db.execute(
            """SELECT interests.name FROM user_interests ui1
               JOIN user_interests ui2 ON ui1.interest_id = ui2.interest_id
               JOIN interests ON interests.id = ui1.interest_id
               WHERE ui1.user_id = ? AND ui2.user_id = ?""",
            (viewer["id"], row["id"]),
        ).fetchall()

        relationship = {
            "following": following,
            "connected": connected,
            "pending_outgoing": pending_outgoing,
            "pending_incoming_id": pending_incoming["id"] if pending_incoming else None,
            "shared_interests": [r["name"] for r in shared_interests],
        }

    return render_template(
        "profile.html", profile=row, interests=interests, relationship=relationship,
        csrf_token=get_csrf_token(),
    )
