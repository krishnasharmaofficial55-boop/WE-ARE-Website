# WE ARE.

*Different places. Similar minds.*

This is the first milestone of the WE ARE. platform: a working Flask app with
real authentication, the onboarding survey, a feed, profiles, and the brand's
visual identity applied throughout. It's a foundation to keep building on,
not the finished product — see **What's not built yet** below.

## Running it locally

```bash
cd we-are
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 seed.py        # populates the interest taxonomy
python3 run.py          # http://127.0.0.1:5000
```

Set a real `SECRET_KEY` env var before doing anything beyond local dev:

```bash
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

## What's implemented

- **Auth**: registration (with age check — under 13 is blocked, under 18 is
  flagged privately as a minor), login, logout, forgot/reset password,
  email verification token flow. Passwords are hashed with `scrypt` via
  Werkzeug. Sessions are opaque server-side tokens (hashed at rest, like
  passwords) in an HttpOnly, SameSite cookie — not a JWT, so a session can
  actually be revoked. CSRF protection on every state-changing request.
- **Onboarding survey**: optional, skippable, stores interests and free-text
  answers. No personality scoring — just self-described signals, per the
  brief.
- **Feed / Discover / Profile**: real routes and templates, wired to the
  database, with honest empty states instead of a placeholder page.
- **Database schema** (`app/schema.sql`): every core model from the brief —
  users, profiles, interests, survey responses, posts, likes, comments,
  reposts, saves, follows, connection requests, connections, messages,
  message attachments, blocks, reports, moderation actions, notifications,
  sessions, admin users, audit logs.
- **Brand identity**: the color system, typography, logo mark (SVG, in
  `app/static/img/`), and the abstract connection-pattern visual language
  from the brief, all applied as real CSS tokens rather than one-off values.

## Architecture note: no ORM, no Postgres — yet

This sandbox has no network access, so packages like `Flask-SQLAlchemy`,
`Flask-Login`, `Flask-WTF`, and `psycopg2` couldn't be installed. Rather than
fake it, this build uses Python's built-in `sqlite3` directly (see `app/db.py`)
plus `werkzeug.security` for password hashing and `itsdangerous` for signed
tokens — genuinely secure, just more hand-written.

**Recommended next step once you have network access:** migrate `app/db.py`
and the raw SQL in `auth.py`/`main.py` to SQLAlchemy models, add Alembic
migrations, and swap SQLite for PostgreSQL in production (the schema was
designed to translate directly — foreign keys, constraints and indexes are
already there in `schema.sql`). `requirements.txt` lists the intended
packages for that migration.

## What's not built yet

This spec describes a full production social platform. Sensible next
milestones, roughly in the order they unlock each other:

1. **Posts & the real feed** — creating posts (text/image/video/poll),
   likes/comments/reposts/saves, and the For You / Following / Global
   ranking logic.
2. **Follow & Connect** — the request → accept → connection flow, and using
   it to gate private messaging.
3. **Discover** — interest/goal/character-based matching, "common ground"
   surfacing instead of a compatibility score.
4. **Messaging with real E2EE** — this needs a proper audited protocol
   (e.g. the Signal protocol via `libsignal`), not something to hand-roll.
   Worth scoping as its own project once the rest of the graph exists.
5. **Moderation & admin dashboard** — report queue, content actions,
   suspensions/appeals, audit log viewer, platform stats.
6. **File uploads** — avatar/media storage (S3-compatible), image
   processing, size/type validation (config ceilings are already set in
   `app/config.py`).
7. **Notifications** — in-app + eventually push, deduplicated/grouped.
8. **Production deploy**: PostgreSQL, a real mail provider for
   verification/reset emails (currently just logged), Gunicorn/WSGI,
   HTTPS, rate limiting (e.g. Flask-Limiter), and a CSP header.

## Security notes for whoever picks this up

- Every protected route checks authorization server-side — never trust a
  client-sent role or ownership flag.
- `is_minor` is derived from birth date server-side at write time; it's
  never accepted as client input.
- No admin credentials are hard-coded anywhere; `admin_users` is a table,
  and there's no seed data granting anyone admin by default.
- When E2EE messaging is built, the server must never have automatic
  access to plaintext — the `reports` table already has a voluntary
  `evidence_url` field for a participant to submit context when reporting
  abuse in an encrypted conversation, per the brief.
