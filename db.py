import sqlite3
from pathlib import Path

from flask import current_app, g


def get_db():
    """Return a request-scoped SQLite connection with foreign keys enforced
    and rows addressable by column name."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    """Create tables from schema.sql if they don't exist yet. Safe to call
    on every startup — CREATE TABLE IF NOT EXISTS is idempotent. For a real
    production deploy, replace this with proper migrations (Alembic)."""
    schema_path = Path(__file__).parent / "schema.sql"
    with app.app_context():
        db = get_db()
        with open(schema_path, "r") as f:
            db.executescript(f.read())
        db.commit()
    app.teardown_appcontext(close_db)
