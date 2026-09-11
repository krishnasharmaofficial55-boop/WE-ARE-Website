"""
Messaging, gated on Follow/Connect.

IMPORTANT: this stores plaintext. It exists to demonstrate and test the
connection gate (no private messaging until a connection is accepted), not
as the final messaging feature. The brief requires real end-to-end
encryption via an established, audited protocol (e.g. libsignal) before
this is user-facing — see README.md, "What's not built yet" item 4. Do not
present this module as encrypted anywhere in the UI.
"""

from flask import Blueprint, render_template, request, redirect, url_for, abort

from .db import get_db
from .security import current_user, login_required, csrf_protect, get_csrf_token
from .social import are_connected, is_blocked, _get_user_by_username, _notify

bp = Blueprint("messaging", __name__)


@bp.before_request
def _csrf():
    csrf_protect()


def _conversation_id(user_a_id: int, user_b_id: int) -> str:
    a, b = sorted((user_a_id, user_b_id))
    return f"{a}-{b}"


@bp.route("/messages")
@login_required
def inbox():
    user = current_user()
    db = get_db()
    connected = db.execute(
        """SELECT users.id, users.username, users.display_name, users.show_real_name
           FROM connections
           JOIN users ON users.id = CASE WHEN connections.user_a_id = ? THEN connections.user_b_id
                                          ELSE connections.user_a_id END
           WHERE connections.user_a_id = ? OR connections.user_b_id = ?""",
        (user["id"], user["id"], user["id"]),
    ).fetchall()

    conversations = []
    for other in connected:
        conv_id = _conversation_id(user["id"], other["id"])
        last = db.execute(
            "SELECT created_at FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
            (conv_id,),
        ).fetchone()
        conversations.append({
            "username": other["username"],
            "display_name": other["display_name"] if other["show_real_name"] else other["username"],
            "last_at": last["created_at"] if last else None,
        })
    conversations.sort(key=lambda c: c["last_at"] or "", reverse=True)

    return render_template("messages/inbox.html", conversations=conversations)


@bp.route("/messages/<username>", methods=["GET", "POST"])
@login_required
def thread(username):
    user = current_user()
    db = get_db()
    other = _get_user_by_username(db, username)
    if other is None:
        abort(404)
    if other["id"] == user["id"]:
        abort(400)

    if not are_connected(db, user["id"], other["id"]):
        return render_template("messages/locked.html", other=other), 403

    if is_blocked(db, user["id"], other["id"]):
        abort(403)

    conv_id = _conversation_id(user["id"], other["id"])

    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if body:
            db.execute(
                "INSERT INTO messages (conversation_id, sender_id, ciphertext) VALUES (?, ?, ?)",
                (conv_id, user["id"], body.encode("utf-8")),
            )
            _notify(db, other["id"], "message", user["id"], "message", None)
            db.commit()
        return redirect(url_for("messaging.thread", username=username))

    rows = db.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conv_id,),
    ).fetchall()
    thread_messages = [
        {"sender_id": r["sender_id"], "body": r["ciphertext"].decode("utf-8"), "created_at": r["created_at"]}
        for r in rows
    ]

    return render_template(
        "messages/thread.html", other=other, messages=thread_messages, user=user,
        csrf_token=get_csrf_token(),
    )
