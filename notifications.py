from flask import Blueprint, render_template, redirect, url_for, abort

from .db import get_db
from .security import current_user, login_required, csrf_protect, get_csrf_token

bp = Blueprint("notifications", __name__)


@bp.before_request
def _csrf():
    csrf_protect()


def unread_count(db, user_id: int) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,)
    ).fetchone()
    return row["n"]


def _resolve_link(n):
    """Where a notification should take you when clicked."""
    if n["kind"] in ("connection_request",):
        return url_for("social.connections")
    if n["kind"] in ("connection_accepted",) and n["actor_username"]:
        return url_for("main.profile", username=n["actor_username"])
    if n["kind"] in ("like", "comment", "repost") and n["subject_id"]:
        return url_for("posts.view", post_id=n["subject_id"])
    if n["kind"] == "message" and n["actor_username"]:
        return url_for("messaging.thread", username=n["actor_username"])
    return url_for("main.feed")


_LABELS = {
    "connection_request": "sent you a connection request",
    "connection_accepted": "accepted your connection request",
    "like": "liked your post",
    "comment": "commented on your post",
    "repost": "reposted your post",
    "message": "sent you a message",
    "safety": "safety update",
}


@bp.route("/notifications")
@login_required
def inbox():
    user = current_user()
    db = get_db()

    rows = db.execute(
        """SELECT notifications.*, users.username AS actor_username,
                  users.display_name AS actor_display_name, users.show_real_name AS actor_show_real_name
           FROM notifications
           LEFT JOIN users ON users.id = notifications.actor_id
           WHERE notifications.user_id = ?
           ORDER BY notifications.created_at DESC LIMIT 50""",
        (user["id"],),
    ).fetchall()

    items = []
    for n in rows:
        actor_name = None
        if n["actor_username"]:
            actor_name = n["actor_display_name"] if n["actor_show_real_name"] else n["actor_username"]
        items.append({
            "id": n["id"],
            "label": _LABELS.get(n["kind"], n["kind"]),
            "actor_name": actor_name,
            "actor_username": n["actor_username"],
            "is_read": bool(n["is_read"]),
            "created_at": n["created_at"],
            "link": _resolve_link(n),
        })

    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (user["id"],))
    db.commit()

    return render_template("notifications.html", items=items, csrf_token=get_csrf_token())


@bp.route("/notifications/<int:notification_id>/open", methods=["POST"])
@login_required
def open_notification(notification_id):
    """Mark-as-read-and-redirect for a single item, used when JS is off and
    the inbox itself hasn't already blanket-marked things read."""
    user = current_user()
    db = get_db()
    row = db.execute(
        """SELECT notifications.*, users.username AS actor_username
           FROM notifications LEFT JOIN users ON users.id = notifications.actor_id
           WHERE notifications.id = ?""",
        (notification_id,),
    ).fetchone()
    if row is None or row["user_id"] != user["id"]:
        abort(404)
    db.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
    db.commit()
    return redirect(_resolve_link(row))
