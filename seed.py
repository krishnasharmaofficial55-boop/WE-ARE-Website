"""Populate the interests table from the onboarding taxonomy. Safe to re-run."""
from app import create_app
from app.db import get_db
from app.main import INTEREST_CATEGORIES

app = create_app()

with app.app_context():
    db = get_db()
    for category, names in INTEREST_CATEGORIES.items():
        for name in names:
            db.execute(
                "INSERT OR IGNORE INTO interests (name, category) VALUES (?, ?)",
                (name, category),
            )
    db.commit()
    print("Seeded interests.")
