import os


class Config:
    """Base config. Every secret comes from the environment — nothing here
    is a real credential, and the app refuses to boot with an unsafe
    default SECRET_KEY in production (see create_app)."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    DATABASE_PATH = os.environ.get("DATABASE_PATH", "we_are.sqlite3")

    # In production, point this at a managed PostgreSQL instance instead —
    # see README.md for the migration note.
    ENV = os.environ.get("FLASK_ENV", "development")

    # Flask's own SESSION_COOKIE_* config governs the built-in `session`
    # object, which we use only to hold the CSRF token. Our authenticated
    # login token is a *separate* cookie (AUTH_COOKIE_NAME below) — giving
    # them the same name would let one silently overwrite the other.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = ENV == "production"

    AUTH_COOKIE_NAME = "we_are_auth"

    SESSION_LIFETIME_DAYS = 14

    MAX_CONTENT_LENGTH = 15 * 1024 * 1024  # 15MB upload ceiling
    ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm"}

    MIN_AGE = 13  # platform-wide minimum; users under 18 are flagged is_minor
