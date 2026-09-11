from flask import Blueprint, render_template, request, redirect, url_for, abort, flash

from .db import get_db
from .security import current_user, login_required, csrf_protect, get_csrf_token

bp = Blueprint("social", __name__)


@bp.before_request
def _csrf():
    csrf_protect()


def _get_user_by_username(db, username):
    return db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def _connection_pair(user_a_id: int, user_b_id: int):
    """Connections are stored with the smaller id first so each pair has
    exactly one row regardless of who initiated it."""
    return (user_a_id, user_b_id) if user_a_id < user_b_id else (user_b_id, user_a_id)


def are_connected(db, user_a_id: int, user_b_id: int) -> bool:
    a, b = _connection_pair(user_a_id, user_b_id)
    row = db.execute(
        "SELECT 1 FROM connections WHERE user_a_id = ? AND user_b_id = ?", (a, b)
    ).fetchone()
    return row is not None


def is_blocked(db, user_a_id: int, user_b_id: int) -> bool:
    row = db.execute(
        """SELECT 1 FROM blocks WHERE (blocker_id = ? AND blocked_id = ?)
                                     OR (blocker_id = ? AND blocked_id = ?)""",
        (user_a_id, user_b_id, user_b_id, user_a_id),
    ).fetchone()
    return row is not None


def _notify(db, user_id: int, kind: str, actor_id: int, subject_type=None, subject_id=None):
    db.execute(
        """INSERT INTO notifications (user_id, kind, actor_id, subject_type, subject_id)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, kind, actor_id, subject_type, subject_id),
    )


# ---------------------------------------------------------------------------
# Follow — one-way, no approval needed
# ---------------------------------------------------------------------------

@bp.route("/u/<username>/follow", methods=["POST"])
@login_required
def follow(username):
    user = current_user()
    db = get_db()
    target = _get_user_by_username(db, username)
    if target is None:
        abort(404)
    if target["id"] == user["id"]:
        abort(400, description="You can't follow yourself.")
    if is_blocked(db, user["id"], target["id"]):
        abort(403)

    db.execute(
        "INSERT OR IGNORE INTO follows (follower_id, followee_id) VALUES (?, ?)",
        (user["id"], target["id"]),
    )
    db.commit()
    return redirect(url_for("main.profile", username=username))


@bp.route("/u/<username>/unfollow", methods=["POST"])
@login_required
def unfollow(username):
    user = current_user()
    db = get_db()
    target = _get_user_by_username(db, username)
    if target is None:
        abort(404)

    db.execute(
        "DELETE FROM follows WHERE follower_id = ? AND followee_id = ?",
        (user["id"], target["id"]),
    )
    db.commit()
    return redirect(url_for("main.profile", username=username))


# ---------------------------------------------------------------------------
# Connect — two-way, requires acceptance, unlocks private messaging
# ---------------------------------------------------------------------------

@bp.route("/u/<username>/connect", methods=["POST"])
@login_required
def send_connection_request(username):
    user = current_user()
    db = get_db()
    target = _get_user_by_username(db, username)
    if target is None:
        abort(404)
    if target["id"] == user["id"]:
        abort(400, description="You can't connect with yourself.")
    if is_blocked(db, user["id"], target["id"]):
        abort(403)
    if are_connected(db, user["id"], target["id"]):
        flash("You're already connected.", "success")
        return redirect(url_for("main.profile", username=username))

    existing = db.execute(
        """SELECT * FROM connection_requests
           WHERE status = 'pending' AND
                 ((sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?))""",
        (user["id"], target["id"], target["id"], user["id"]),
    ).fetchone()

    if existing is None:
        db.execute(
            "INSERT INTO connection_requests (sender_id, recipient_id) VALUES (?, ?)",
            (user["id"], target["id"]),
        )
        _notify(db, target["id"], "connection_request", user["id"], "user", user["id"])
        db.commit()
        flash("Connection request sent.", "success")
    elif existing["sender_id"] == target["id"]:
        # They already sent one — accepting it is more useful than a duplicate pending request.
        return _accept_request(db, user, existing)
    else:
        flash("You already sent a request — waiting on them.", "success")

    return redirect(url_for("main.profile", username=username))


def _accept_request(db, accepting_user, req_row):
    a, b = _connection_pair(req_row["sender_id"], req_row["recipient_id"])
    db.execute(
        "UPDATE connection_requests SET status = 'accepted', responded_at = datetime('now') WHERE id = ?",
        (req_row["id"],),
    )
    db.execute(
        "INSERT OR IGNORE INTO connections (user_a_id, user_b_id) VALUES (?, ?)", (a, b)
    )
    other_id = req_row["sender_id"] if req_row["sender_id"] != accepting_user["id"] else req_row["recipient_id"]
    _notify(db, other_id, "connection_accepted", accepting_user["id"], "user", accepting_user["id"])
    db.commit()
    flash("You're connected.", "success")
    other = db.execute("SELECT username FROM users WHERE id = ?", (other_id,)).fetchone()
    return redirect(url_for("main.profile", username=other["username"]))


@bp.route("/connections/requests/<int:request_id>/accept", methods=["POST"])
@login_required
def accept_connection_request(request_id):
    user = current_user()
    db = get_db()
    req_row = db.execute(
        "SELECT * FROM connection_requests WHERE id = ? AND status = 'pending'", (request_id,)
    ).fetchone()
    if req_row is None or req_row["recipient_id"] != user["id"]:
        abort(404)
    return _accept_request(db, user, req_row)


@bp.route("/connections/requests/<int:request_id>/decline", methods=["POST"])
@login_required
def decline_connection_request(request_id):
    user = current_user()
    db = get_db()
    req_row = db.execute(
        "SELECT * FROM connection_requests WHERE id = ? AND status = 'pending'", (request_id,)
    ).fetchone()
    if req_row is None or req_row["recipient_id"] != user["id"]:
        abort(404)
    db.execute(
        "UPDATE connection_requests SET status = 'declined', responded_at = datetime('now') WHERE id = ?",
        (request_id,),
    )
    db.commit()
    return redirect(url_for("social.connections"))


@bp.route("/u/<username>/disconnect", methods=["POST"])
@login_required
def remove_connection(username):
    user = current_user()
    db = get_db()
    target = _get_user_by_username(db, username)
    if target is None:
        abort(404)
    a, b = _connection_pair(user["id"], target["id"])
    db.execute("DELETE FROM connections WHERE user_a_id = ? AND user_b_id = ?", (a, b))
    db.commit()
    flash("Connection removed.", "success")
    return redirect(url_for("main.profile", username=username))


@bp.route("/connections")
@login_required
def connections():
    user = current_user()
    db = get_db()

    incoming = db.execute(
        """SELECT connection_requests.id, users.username, users.display_name, users.show_real_name,
                  connection_requests.created_at
           FROM connection_requests JOIN users ON users.id = connection_requests.sender_id
           WHERE connection_requests.recipient_id = ? AND connection_requests.status = 'pending'
           ORDER BY connection_requests.created_at DESC""",
        (user["id"],),
    ).fetchall()

    outgoing = db.execute(
        """SELECT connection_requests.id, users.username, users.display_name, users.show_real_name,
                  connection_requests.created_at
           FROM connection_requests JOIN users ON users.id = connection_requests.recipient_id
           WHERE connection_requests.sender_id = ? AND connection_requests.status = 'pending'
           ORDER BY connection_requests.created_at DESC""",
        (user["id"],),
    ).fetchall()

    connected = db.execute(
        """SELECT users.username, users.display_name, users.show_real_name
           FROM connections
           JOIN users ON users.id = CASE WHEN connections.user_a_id = ? THEN connections.user_b_id
                                          ELSE connections.user_a_id END
           WHERE connections.user_a_id = ? OR connections.user_b_id = ?""",
        (user["id"], user["id"], user["id"]),
    ).fetchall()

    return render_template(
        "connections.html", incoming=incoming, outgoing=outgoing, connected=connected,
        csrf_token=get_csrf_token(),
    )
