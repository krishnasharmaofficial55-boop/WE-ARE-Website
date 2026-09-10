import re
from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, make_response, current_app

from .db import get_db
from .security import (
    hash_password,
    verify_password,
    create_session,
    destroy_session,
    current_user,
    csrf_protect,
    get_csrf_token,
    make_email_token,
    read_email_token,
    compute_age,
    is_minor,
)

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.before_request
def _csrf():
    csrf_protect()


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("main.feed"))

    errors = {}
    form = {"email": "", "username": "", "display_name": "", "birth_date": ""}

    if request.method == "POST":
        form["email"] = request.form.get("email", "").strip().lower()
        form["username"] = request.form.get("username", "").strip().lower()
        form["display_name"] = request.form.get("display_name", "").strip()
        form["birth_date"] = request.form.get("birth_date", "").strip()
        password = request.form.get("password", "")

        if not EMAIL_RE.match(form["email"]):
            errors["email"] = "Enter a valid email address."
        if not USERNAME_RE.match(form["username"]):
            errors["username"] = "3–20 characters: letters, numbers, underscores."
        if not form["display_name"]:
            errors["display_name"] = "Tell us what to call you."
        if len(password) < 10:
            errors["password"] = "Use at least 10 characters."

        birth_date_obj = None
        if not form["birth_date"]:
            errors["birth_date"] = "We need this to keep the community age-appropriate."
        else:
            try:
                birth_date_obj = datetime.strptime(form["birth_date"], "%Y-%m-%d").date()
                if compute_age(birth_date_obj) < current_app.config["MIN_AGE"]:
                    errors["birth_date"] = f"You must be at least {current_app.config['MIN_AGE']} to join."
                if birth_date_obj > date.today():
                    errors["birth_date"] = "That date doesn't look right."
            except ValueError:
                errors["birth_date"] = "Use the date picker to enter your birth date."

        db = get_db()
        if not errors:
            if db.execute("SELECT 1 FROM users WHERE email = ?", (form["email"],)).fetchone():
                errors["email"] = "An account already uses this email."
            if db.execute("SELECT 1 FROM users WHERE username = ?", (form["username"],)).fetchone():
                errors["username"] = "That username is taken."

        if not errors:
            cur = db.execute(
                """INSERT INTO users (email, username, password_hash, display_name, birth_date, is_minor)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    form["email"],
                    form["username"],
                    hash_password(password),
                    form["display_name"],
                    birth_date_obj.isoformat(),
                    1 if is_minor(birth_date_obj) else 0,
                ),
            )
            user_id = cur.lastrowid
            db.execute("INSERT INTO profiles (user_id) VALUES (?)", (user_id,))
            db.commit()

            # In production this dispatches a real email via a transactional
            # mail provider. Logged here only because there's no mail
            # backend configured in this environment.
            token = make_email_token(user_id, "verify_email")
            current_app.logger.info("Verification link for %s: /verify-email/%s", form["email"], token)

            session_token = create_session(user_id)
            resp = make_response(redirect(url_for("main.onboarding")))
            resp.set_cookie(
                current_app.config["AUTH_COOKIE_NAME"],
                session_token,
                httponly=True,
                samesite=current_app.config["SESSION_COOKIE_SAMESITE"],
                secure=current_app.config["SESSION_COOKIE_SECURE"],
                max_age=current_app.config["SESSION_LIFETIME_DAYS"] * 86400,
            )
            return resp

    return render_template("auth/register.html", form=form, errors=errors, csrf_token=get_csrf_token())


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.feed"))

    error = None
    email = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        # Same generic error whether the email is unknown or the password is
        # wrong — don't leak which accounts exist.
        if row is None or not verify_password(row["password_hash"], password):
            error = "That email and password don't match."
        elif not row["is_active"]:
            error = "This account is suspended. Contact support if you think that's wrong."
        else:
            token = create_session(row["id"])
            next_url = request.args.get("next") or url_for("main.feed")
            resp = make_response(redirect(next_url))
            resp.set_cookie(
                current_app.config["AUTH_COOKIE_NAME"],
                token,
                httponly=True,
                samesite=current_app.config["SESSION_COOKIE_SAMESITE"],
                secure=current_app.config["SESSION_COOKIE_SECURE"],
                max_age=current_app.config["SESSION_LIFETIME_DAYS"] * 86400,
            )
            return resp

    return render_template("auth/login.html", error=error, email=email, csrf_token=get_csrf_token())


@bp.route("/logout", methods=["POST"])
def logout():
    token = request.cookies.get(current_app.config["AUTH_COOKIE_NAME"])
    if token:
        destroy_session(token)
    resp = make_response(redirect(url_for("main.index")))
    resp.delete_cookie(current_app.config["AUTH_COOKIE_NAME"])
    return resp


@bp.route("/verify-email/<token>")
def verify_email(token):
    user_id = read_email_token(token, "verify_email", max_age_seconds=86400)
    if user_id is None:
        flash("That verification link has expired. Request a new one from settings.", "error")
        return redirect(url_for("auth.login"))
    db = get_db()
    db.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))
    db.commit()
    flash("Email verified.", "success")
    return redirect(url_for("main.feed"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    sent = False
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            token = make_email_token(row["id"], "reset_password")
            current_app.logger.info("Password reset link for %s: /reset-password/%s", email, token)
        # Always show the same confirmation — don't reveal whether the email exists.
        sent = True
    return render_template("auth/forgot_password.html", sent=sent, csrf_token=get_csrf_token())


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user_id = read_email_token(token, "reset_password", max_age_seconds=1800)
    if user_id is None:
        flash("That reset link has expired. Request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))

    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 10:
            error = "Use at least 10 characters."
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))  # log out everywhere
            db.commit()
            flash("Password updated. Sign in with your new password.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", error=error, token=token, csrf_token=get_csrf_token())
