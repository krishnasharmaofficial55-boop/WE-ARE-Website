import secrets
import hashlib
from datetime import datetime, timedelta, date

from flask import current_app, g, request, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from .db import get_db

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(raw_password: str) -> str:
    # scrypt via Werkzeug — no custom crypto, no plaintext ever stored.
    return generate_password_hash(raw_password, method="scrypt")


def verify_password(password_hash: str, raw_password: str) -> bool:
    return check_password_hash(password_hash, raw_password)


# ---------------------------------------------------------------------------
# Sessions (server-side, opaque token in an HttpOnly cookie)
# ---------------------------------------------------------------------------

def _hash_token(token: str) -> str:
    # Only the hash is stored server-side, same principle as password storage:
    # a leaked DB row doesn't hand over a live session.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db = get_db()
    expires_at = datetime.utcnow() + timedelta(days=current_app.config["SESSION_LIFETIME_DAYS"])
    db.execute(
        "INSERT INTO sessions (id, user_id, user_agent, expires_at) VALUES (?, ?, ?, ?)",
        (_hash_token(token), user_id, request.headers.get("User-Agent", "")[:255], expires_at.isoformat()),
    )
    db.commit()
    return token


def destroy_session(token: str) -> None:
    db = get_db()
    db.execute("DELETE FROM sessions WHERE id = ?", (_hash_token(token),))
    db.commit()


def current_user():
    """Resolve the logged-in user from the session cookie, or None."""
    if "user" in g:
        return g.user

    token = request.cookies.get(current_app.config["AUTH_COOKIE_NAME"])
    g.user = None
    if not token:
        return None

    db = get_db()
    row = db.execute(
        """SELECT users.* FROM sessions
           JOIN users ON users.id = sessions.user_id
           WHERE sessions.id = ? AND sessions.expires_at > datetime('now')
                 AND users.is_active = 1""",
        (_hash_token(token),),
    ).fetchone()
    g.user = row
    return row


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            abort(401)
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            abort(401)
        db = get_db()
        is_admin = db.execute(
            "SELECT 1 FROM admin_users WHERE user_id = ?", (user["id"],)
        ).fetchone()
        if not is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# CSRF — double-submit token stored in the session cookie's signed partner
# ---------------------------------------------------------------------------

def get_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def validate_csrf(submitted_token: str) -> bool:
    real_token = session.get("csrf_token")
    return bool(real_token) and secrets.compare_digest(real_token, submitted_token or "")


def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not validate_csrf(token):
            abort(400, description="Invalid or missing CSRF token.")


# ---------------------------------------------------------------------------
# Signed, expiring tokens for email verification / password reset
# ---------------------------------------------------------------------------

def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def make_email_token(user_id: int, purpose: str) -> str:
    return _serializer().dumps({"uid": user_id, "purpose": purpose})


def read_email_token(token: str, purpose: str, max_age_seconds: int = 3600):
    try:
        data = _serializer().loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    if data.get("purpose") != purpose:
        return None
    return data.get("uid")


# ---------------------------------------------------------------------------
# Age / minor status — derived server-side, never trust a client-sent flag
# ---------------------------------------------------------------------------

def compute_age(birth_date: date) -> int:
    today = date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def is_minor(birth_date: date) -> bool:
    return compute_age(birth_date) < 18
