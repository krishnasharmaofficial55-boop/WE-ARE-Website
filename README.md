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
- **Legal pages**: Community Guidelines, Privacy Policy, Terms of Service,
  and a working Contact form, all linked from the footer and the
  registration page. The privacy policy is deliberately honest about the
  one place the app doesn't yet match the brief: it says plainly that
  private messages aren't end-to-end encrypted yet, rather than claiming
  otherwise. These are a solid starting draft, not a substitute for review
  by an actual lawyer before launch (said outright on the terms page too).
- **File uploads**: avatars and post images, both genuinely validated —
  every upload is opened and decoded with Pillow (not trusted off its
  filename or declared Content-Type), resized (512px avatars, 1600px post
  images), and re-encoded on save, which strips EXIF/GPS metadata and any
  non-image bytes. Filenames are always server-generated (uuid4), never
  the client's. A `/settings` page ties this together with the profile
  bio/identity fields, which previously had no edit UI at all.
- **Notifications**: a real inbox at `/notifications` covering connection
  requests, accepted connections, likes, comments, reposts, and messages —
  each one links to the right place (the post, the connections page, the
  message thread). An unread-count badge shows in the nav and clears once
  you've actually viewed the inbox (not on a timer or a dismiss click).
- **Moderation & admin dashboard**: overview stats, a reports queue
  (filterable by status), a report detail page with one-click actions
  (dismiss / warn / remove content / suspend / ban) that's genuinely wired
  up — removing content actually deletes the post, suspending/banning
  actually deactivates the account and kills its sessions immediately. A
  searchable user list with suspend/reinstate, and a full moderation log.
  Every action writes to `moderation_actions` and `audit_logs`. Access is
  gated by `admin_required` (403 for anyone not in `admin_users`) — see
  `promote_admin.py` for how to grant it (no default admin, no hard-coded
  credentials anywhere).
- **Discover**: interest-filter chips (multi-select, auto-applies), default
  recommendations based on the viewer's own interests when no filter is
  set, shared-interest count shown per person, and Follow/Connect actions
  right from the card. Age-aware: minors and adults are never surfaced to
  each other, checked server-side off the private `is_minor` flag — never
  off an exposed birth date.
- **Posts & feed**: create text/link posts, like, comment, repost, save,
  report, and author-only delete — all real DB-backed toggles, not UI
  stubs. Three working feed tabs: **Global** (all public posts), **Following**
  (your follows + connections only), and **For You** (network posts plus
  posts from people who share an interest with you, falling back to recent
  global if you have neither yet). Image/video/poll post types aren't built
  — see item 6 below.
- **Follow / Connect**: one-way follow, and a full two-way connection flow —
  send request → recipient accepts or declines → connection created →
  private messaging unlocks. Sending a request to someone who already sent
  you one auto-accepts instead of creating a duplicate. Connections page
  shows incoming/outgoing requests and current connections. Profile page
  shows the right action (Connect / Request sent / Accept / Message /
  Remove connection) based on relationship state, plus "Common ground" —
  shared interests instead of a compatibility score, per the brief.
- **Messaging (gated, not yet encrypted)**: a message thread only renders
  once `are_connected()` is true — otherwise you get a locked screen, no
  content leak. The message storage itself is plaintext for now; see
  the warning at the top of `app/messaging.py` and item 4 below.
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

1. ~~**Posts & the real feed**~~ — done: create/like/comment/repost/save/
   report/delete, and three real feed tabs (see `app/posts.py`,
   `main.feed()`). Still missing: image/video uploads and poll voting
   (folded into item 6, file uploads).
2. ~~**Follow & Connect**~~ — done: request → accept → connection flow,
   gating private messaging (see `app/social.py`, `app/messaging.py`).
3. ~~**Discover**~~ — done: filter/browse by interest, age-aware, with
   Follow/Connect actions inline (see `main.discover()`). Not yet covered:
   filtering by character/goals/thinking-style survey answers (currently
   interest-only) and location-based discovery (brief marks this as a
   later phase anyway).
4. **Messaging with real E2EE** — the gate exists and works
   (`are_connected()` in `app/social.py`); the message content itself is
   still plaintext. This needs a proper audited protocol (e.g. the Signal
   protocol via `libsignal`), not something to hand-roll. Worth scoping as
   its own project.
5. ~~**Moderation & admin dashboard**~~ — done: report queue, actions,
   suspensions, user search, moderation log (see `app/admin.py`). Run
   `python3 promote_admin.py <username>` to grant access to an account
   you've already registered. Not yet built: appeals workflow (reports
   table supports it structurally, but there's no appeal-submission UI)
   and announcements management.
6. ~~**File uploads**~~ — done: avatars and post images, validated with
   Pillow (not trusted off filename/Content-Type), resized, re-encoded to
   strip metadata, server-generated filenames (see `app/uploads.py`,
   `app/settings.py`). Stored on local disk under `app/static/uploads/` —
   swap for S3-compatible object storage before production (multiple app
   servers can't share a local disk, and local disk isn't durable). Poll
   voting still isn't built (`posts.is_poll` exists in the schema but
   nothing reads or writes it yet).
7. ~~**Notifications**~~ — done: real inbox, unread badge, links resolve
   per notification kind (see `app/notifications.py`). Not yet built: push
   notifications and grouping ("3 people liked your post" instead of 3
   separate rows) — everything currently lists one row per event.
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
