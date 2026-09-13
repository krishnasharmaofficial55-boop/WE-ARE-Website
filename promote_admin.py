"""Grant admin access to an existing account.

Usage:
    python3 promote_admin.py <username> [--role admin|moderator]

There is no default admin account and no hard-coded credential anywhere in
this codebase — a person must already have a registered account, and
someone with shell/DB access must explicitly run this script to grant it
admin rights.
"""
import sys
import argparse

from app import create_app
from app.db import get_db

app = create_app()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--role", choices=["admin", "moderator"], default="moderator")
    args = parser.parse_args()

    with app.app_context():
        db = get_db()
        user = db.execute("SELECT id FROM users WHERE username = ?", (args.username,)).fetchone()
        if user is None:
            print(f"No user found with username '{args.username}'.", file=sys.stderr)
            sys.exit(1)

        db.execute(
            """INSERT INTO admin_users (user_id, role) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET role = excluded.role""",
            (user["id"], args.role),
        )
        db.commit()
        print(f"Granted '{args.role}' to '{args.username}'.")


if __name__ == "__main__":
    main()
