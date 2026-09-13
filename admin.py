from flask import Blueprint, render_template, request, redirect, url_for, abort, flash

from .db import get_db
from .security import current_user, admin_required, csrf_protect, get_csrf_token

bp = Blueprint("admin", __name__, url_prefix="/admin")

VALID_ACTIONS = {"warn", "remove_content", "suspend", "ban", "dismiss"}


@bp.before_request
def _csrf():
    csrf_protect()


def _log_audit(db, actor_id, action, details=None):
    db.execute(
        "INSERT INTO audit_logs (actor_id, action, details) VALUES (?, ?, ?)",
        (actor_id, action, details),
    )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@bp.route("/")
@admin_required
def overview():
    db = get_db()

    def count(sql, params=()):
        return db.execute(sql, params).fetchone()[0]

    stats = {
        "total_users": count("SELECT COUNT(*) FROM users"),
        "active_users": count("SELECT COUNT(*) FROM users WHERE is_active = 1"),
        "new_today": count("SELECT COUNT(*) FROM users WHERE date(created_at) = date('now')"),
        "total_posts": count("SELECT COUNT(*) FROM posts"),
        "total_connections": count("SELECT COUNT(*) FROM connections"),
        "open_reports": count("SELECT COUNT(*) FROM reports WHERE status = 'open'"),
        "suspended_users": count("SELECT COUNT(*) FROM users WHERE is_active = 0"),
    }
    return render_template("admin/overview.html", stats=stats)


# ---------------------------------------------------------------------------
# Reports queue
# ---------------------------------------------------------------------------

@bp.route("/reports")
@admin_required
def reports():
    db = get_db()
    status_filter = request.args.get("status", "open")
    if status_filter not in ("open", "reviewing", "resolved", "dismissed", "all"):
        status_filter = "open"

    if status_filter == "all":
        rows = db.execute(
            """SELECT reports.*, users.username AS reporter_username
               FROM reports JOIN users ON users.id = reports.reporter_id
               ORDER BY reports.created_at DESC LIMIT 100"""
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT reports.*, users.username AS reporter_username
               FROM reports JOIN users ON users.id = reports.reporter_id
               WHERE reports.status = ?
               ORDER BY reports.created_at DESC LIMIT 100""",
            (status_filter,),
        ).fetchall()

    return render_template("admin/reports.html", reports=rows, status_filter=status_filter, csrf_token=get_csrf_token())


@bp.route("/reports/<int:report_id>")
@admin_required
def report_detail(report_id):
    db = get_db()
    report_row = db.execute(
        """SELECT reports.*, users.username AS reporter_username
           FROM reports JOIN users ON users.id = reports.reporter_id WHERE reports.id = ?""",
        (report_id,),
    ).fetchone()
    if report_row is None:
        abort(404)

    subject = None
    if report_row["subject_type"] == "post":
        subject = db.execute(
            """SELECT posts.*, users.username FROM posts JOIN users ON users.id = posts.user_id
               WHERE posts.id = ?""",
            (report_row["subject_id"],),
        ).fetchone()
    elif report_row["subject_type"] == "user":
        subject = db.execute("SELECT * FROM users WHERE id = ?", (report_row["subject_id"],)).fetchone()

    history = db.execute(
        "SELECT * FROM moderation_actions WHERE report_id = ? ORDER BY created_at DESC", (report_id,)
    ).fetchall()

    return render_template(
        "admin/report_detail.html", report=report_row, subject=subject, history=history,
        csrf_token=get_csrf_token(),
    )


@bp.route("/reports/<int:report_id>/action", methods=["POST"])
@admin_required
def take_action(report_id):
    admin = current_user()
    db = get_db()
    report_row = db.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if report_row is None:
        abort(404)

    action_type = request.form.get("action_type", "")
    notes = request.form.get("notes", "").strip() or None
    if action_type not in VALID_ACTIONS:
        abort(400, description="Invalid action.")

    target_user_id = None
    if report_row["subject_type"] == "user":
        target_user_id = report_row["subject_id"]
    elif report_row["subject_type"] == "post":
        post = db.execute("SELECT user_id FROM posts WHERE id = ?", (report_row["subject_id"],)).fetchone()
        target_user_id = post["user_id"] if post else None

    if action_type == "remove_content" and report_row["subject_type"] == "post":
        db.execute("DELETE FROM posts WHERE id = ?", (report_row["subject_id"],))
    elif action_type == "suspend" and target_user_id:
        db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (target_user_id,))
    elif action_type == "ban" and target_user_id:
        db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (target_user_id,))
        db.execute("DELETE FROM sessions WHERE user_id = ?", (target_user_id,))  # log out everywhere, immediately

    new_status = "dismissed" if action_type == "dismiss" else "resolved"
    db.execute("UPDATE reports SET status = ? WHERE id = ?", (new_status, report_id))

    db.execute(
        """INSERT INTO moderation_actions (admin_id, report_id, target_user_id, action_type, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (admin["id"], report_id, target_user_id, action_type, notes),
    )
    _log_audit(db, admin["id"], f"moderation:{action_type}", f"report #{report_id}")
    db.commit()

    flash("Action recorded.", "success")
    return redirect(url_for("admin.report_detail", report_id=report_id))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@bp.route("/users")
@admin_required
def users():
    db = get_db()
    query = request.args.get("q", "").strip()
    if query:
        rows = db.execute(
            """SELECT * FROM users WHERE username LIKE ? OR email LIKE ?
               ORDER BY created_at DESC LIMIT 50""",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 50").fetchall()
    return render_template("admin/users.html", users=rows, query=query, csrf_token=get_csrf_token())


@bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@admin_required
def suspend_user(user_id):
    admin = current_user()
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        abort(404)
    db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.execute(
        """INSERT INTO moderation_actions (admin_id, target_user_id, action_type, notes)
           VALUES (?, ?, 'suspend', ?)""",
        (admin["id"], user_id, "manual suspension from user list"),
    )
    _log_audit(db, admin["id"], "user:suspend", f"user #{user_id}")
    db.commit()
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/reinstate", methods=["POST"])
@admin_required
def reinstate_user(user_id):
    admin = current_user()
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        abort(404)
    db.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user_id,))
    db.execute(
        """INSERT INTO moderation_actions (admin_id, target_user_id, action_type, notes)
           VALUES (?, ?, 'reinstate', ?)""",
        (admin["id"], user_id, "manual reinstatement from user list"),
    )
    _log_audit(db, admin["id"], "user:reinstate", f"user #{user_id}")
    db.commit()
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------------------
# Moderation log
# ---------------------------------------------------------------------------

@bp.route("/moderation-log")
@admin_required
def moderation_log():
    db = get_db()
    rows = db.execute(
        """SELECT moderation_actions.*, admins.username AS admin_username,
                  targets.username AS target_username
           FROM moderation_actions
           JOIN users AS admins ON admins.id = moderation_actions.admin_id
           LEFT JOIN users AS targets ON targets.id = moderation_actions.target_user_id
           ORDER BY moderation_actions.created_at DESC LIMIT 100"""
    ).fetchall()
    return render_template("admin/moderation_log.html", actions=rows)
