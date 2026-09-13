from flask import Blueprint, render_template, request, redirect, url_for, abort, flash, current_app
from pathlib import Path

from .db import get_db
from .security import current_user, login_required, csrf_protect, get_csrf_token
from .social import is_blocked, _notify
from .uploads import save_post_image, UploadError

bp = Blueprint("posts", __name__)


@bp.before_request
def _csrf():
    csrf_protect()


MAX_POST_LENGTH = 2000
MAX_COMMENT_LENGTH = 1000


def _get_post_or_404(db, post_id):
    row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        abort(404)
    return row


def annotate_posts(db, posts, viewer_id):
    """Attach counts and this-viewer's interaction state to a list of post
    rows, without an N+1 query per post-per-interaction-type."""
    if not posts:
        return []

    post_ids = [p["id"] for p in posts]
    placeholders = ",".join("?" * len(post_ids))

    def counts_by_post(table):
        rows = db.execute(
            f"SELECT post_id, COUNT(*) AS n FROM {table} WHERE post_id IN ({placeholders}) GROUP BY post_id",
            post_ids,
        ).fetchall()
        return {r["post_id"]: r["n"] for r in rows}

    like_counts = counts_by_post("likes")
    comment_counts = counts_by_post("comments")
    repost_counts = counts_by_post("reposts")

    media_rows = db.execute(
        f"SELECT post_id, url, media_type FROM post_media WHERE post_id IN ({placeholders}) ORDER BY position",
        post_ids,
    ).fetchall()
    media_by_post = {}
    for m in media_rows:
        media_by_post.setdefault(m["post_id"], []).append({"url": m["url"], "type": m["media_type"]})

    def viewer_ids(table):
        rows = db.execute(
            f"SELECT post_id FROM {table} WHERE post_id IN ({placeholders}) AND user_id = ?",
            post_ids + [viewer_id],
        ).fetchall()
        return {r["post_id"] for r in rows}

    liked = viewer_ids("likes")
    reposted = viewer_ids("reposts")
    saved = viewer_ids("saves")

    annotated = []
    for p in posts:
        d = dict(p)
        d["like_count"] = like_counts.get(p["id"], 0)
        d["comment_count"] = comment_counts.get(p["id"], 0)
        d["repost_count"] = repost_counts.get(p["id"], 0)
        d["media"] = media_by_post.get(p["id"], [])
        d["viewer_liked"] = p["id"] in liked
        d["viewer_reposted"] = p["id"] in reposted
        d["viewer_saved"] = p["id"] in saved
        d["is_author"] = p["user_id"] == viewer_id
        annotated.append(d)
    return annotated


# ---------------------------------------------------------------------------
# Create / delete
# ---------------------------------------------------------------------------

@bp.route("/posts", methods=["POST"])
@login_required
def create():
    user = current_user()
    db = get_db()
    body = request.form.get("body", "").strip()
    link_url = request.form.get("link_url", "").strip() or None
    image_file = request.files.get("image")
    has_image = bool(image_file and image_file.filename)

    if not body and not link_url and not has_image:
        flash("Write something, add a link, or attach an image before posting.", "error")
        return redirect(url_for("main.feed"))
    if len(body) > MAX_POST_LENGTH:
        flash(f"Posts are limited to {MAX_POST_LENGTH} characters.", "error")
        return redirect(url_for("main.feed"))

    if has_image:
        try:
            image_url = save_post_image(image_file)
        except UploadError as e:
            flash(str(e), "error")
            return redirect(url_for("main.feed"))

    cur = db.execute(
        "INSERT INTO posts (user_id, body, link_url) VALUES (?, ?, ?)",
        (user["id"], body, link_url),
    )
    if has_image:
        db.execute(
            "INSERT INTO post_media (post_id, media_type, url, position) VALUES (?, 'image', ?, 0)",
            (cur.lastrowid, image_url),
        )
    db.commit()
    return redirect(url_for("main.feed"))


@bp.route("/posts/<int:post_id>/delete", methods=["POST"])
@login_required
def delete(post_id):
    user = current_user()
    db = get_db()
    post = _get_post_or_404(db, post_id)
    if post["user_id"] != user["id"]:
        abort(403)

    media = db.execute("SELECT url FROM post_media WHERE post_id = ?", (post_id,)).fetchall()
    db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    db.commit()

    for m in media:
        try:
            (Path(current_app.root_path) / "static" / m["url"]).unlink(missing_ok=True)
        except OSError:
            pass  # best-effort cleanup; an orphaned file is a disk-hygiene issue, not a data-integrity one

    return redirect(request.referrer or url_for("main.feed"))


# ---------------------------------------------------------------------------
# Interactions — like, repost, save all follow the same toggle shape
# ---------------------------------------------------------------------------

def _toggle(table, post_id, user_id, db):
    existing = db.execute(
        f"SELECT 1 FROM {table} WHERE user_id = ? AND post_id = ?", (user_id, post_id)
    ).fetchone()
    if existing:
        db.execute(f"DELETE FROM {table} WHERE user_id = ? AND post_id = ?", (user_id, post_id))
        db.commit()
        return False
    db.execute(f"INSERT INTO {table} (user_id, post_id) VALUES (?, ?)", (user_id, post_id))
    db.commit()
    return True


@bp.route("/posts/<int:post_id>/like", methods=["POST"])
@login_required
def toggle_like(post_id):
    user = current_user()
    db = get_db()
    post = _get_post_or_404(db, post_id)
    now_liked = _toggle("likes", post_id, user["id"], db)
    if now_liked and post["user_id"] != user["id"]:
        _notify(db, post["user_id"], "like", user["id"], "post", post_id)
        db.commit()
    return redirect(request.referrer or url_for("main.feed"))


@bp.route("/posts/<int:post_id>/repost", methods=["POST"])
@login_required
def toggle_repost(post_id):
    user = current_user()
    db = get_db()
    post = _get_post_or_404(db, post_id)
    now_reposted = _toggle("reposts", post_id, user["id"], db)
    if now_reposted and post["user_id"] != user["id"]:
        _notify(db, post["user_id"], "repost", user["id"], "post", post_id)
        db.commit()
    return redirect(request.referrer or url_for("main.feed"))


@bp.route("/posts/<int:post_id>/save", methods=["POST"])
@login_required
def toggle_save(post_id):
    user = current_user()
    db = get_db()
    _get_post_or_404(db, post_id)
    _toggle("saves", post_id, user["id"], db)
    return redirect(request.referrer or url_for("main.feed"))


@bp.route("/posts/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    user = current_user()
    db = get_db()
    post = _get_post_or_404(db, post_id)
    body = request.form.get("body", "").strip()
    if not body:
        return redirect(url_for("posts.view", post_id=post_id))
    if len(body) > MAX_COMMENT_LENGTH:
        flash(f"Comments are limited to {MAX_COMMENT_LENGTH} characters.", "error")
        return redirect(url_for("posts.view", post_id=post_id))

    db.execute(
        "INSERT INTO comments (post_id, user_id, body) VALUES (?, ?, ?)",
        (post_id, user["id"], body),
    )
    if post["user_id"] != user["id"]:
        _notify(db, post["user_id"], "comment", user["id"], "post", post_id)
    db.commit()
    return redirect(url_for("posts.view", post_id=post_id))


@bp.route("/posts/<int:post_id>/report", methods=["POST"])
@login_required
def report(post_id):
    user = current_user()
    db = get_db()
    _get_post_or_404(db, post_id)
    reason = request.form.get("reason", "").strip() or "unspecified"
    db.execute(
        "INSERT INTO reports (reporter_id, subject_type, subject_id, reason) VALUES (?, 'post', ?, ?)",
        (user["id"], post_id, reason),
    )
    db.commit()
    flash("Thanks — this post has been reported to our team.", "success")
    return redirect(request.referrer or url_for("main.feed"))


@bp.route("/posts/<int:post_id>")
def view(post_id):
    db = get_db()
    row = db.execute(
        """SELECT posts.*, users.username, users.display_name, users.show_real_name
           FROM posts JOIN users ON users.id = posts.user_id WHERE posts.id = ?""",
        (post_id,),
    ).fetchone()
    if row is None:
        return render_template("404.html"), 404

    viewer = current_user()
    viewer_id = viewer["id"] if viewer else 0
    post = annotate_posts(db, [row], viewer_id)[0]

    comments = db.execute(
        """SELECT comments.*, users.username, users.display_name, users.show_real_name
           FROM comments JOIN users ON users.id = comments.user_id
           WHERE comments.post_id = ? ORDER BY comments.created_at ASC""",
        (post_id,),
    ).fetchall()

    return render_template(
        "post_detail.html", post=post, comments=comments, csrf_token=get_csrf_token(),
    )
