# Fly.io Staging

Pushes to `staging` deploy the verified backend commit to `pilah-be-staging`.
CI then requires `/healthz` to succeed and automatically seeds the idempotent
E2E fixture. Seed failure fails deployment; no separate dispatch is needed.
Staging runs are serialized so deploy and seed are not interrupted by a newer
push. No reset or deletion runs in the deployment pipeline.

The API runs in Singapore, connects to Neon over TLS, and stores uploaded
media on the single `media_data` Fly volume. Only logo files are public local
media; activity proofs use short-lived signed URLs for Superadmins.

## Domains and Google OAuth

- Dashboard (separate mobile-repository Fly app): `https://pilah-web-staging.fly.dev`
- Backend API base: `https://pilah-be-staging.fly.dev/api/v1/`
- Backend health check: `https://pilah-be-staging.fly.dev/healthz`

`fly.toml` explicitly allows only the staging dashboard browser origin with
`CORS_ALLOW_ALL_ORIGINS=false` and adds it to `CSRF_TRUSTED_ORIGINS`.
Remove any older Fly secret overriding `CORS_ALLOWED_ORIGINS` with another
value, or set it to exactly `https://pilah-web-staging.fly.dev`.
No custom domain or wildcard browser allowlist is required.

Set backend `GOOGLE_CLIENT_ID` to the same Web OAuth client ID used as
`GOOGLE_SERVER_CLIENT_ID` by the frontend. Add
`https://pilah-web-staging.fly.dev` to that client's **Authorized JavaScript
origins**, and add staging test accounts to the consent screen's test-user
list. If using the backend callback flow, register this redirect URI:

```text
https://pilah-be-staging.fly.dev/api/v1/auth/google/callback
```

`PILAH_PUBLIC_APP_URL` is the invite-link base, not the CORS origin or frontend
API base; it currently remains the backend URL in `fly.toml`. Changing invite
routing is outside this delivery. Keep `PILAH_ALLOW_FAKE_GOOGLE_TOKEN=false`
and `DJANGO_DEBUG=false`; web hosting does not enable demo login.

## Required Secrets and Seed Variables

Set Django and Neon values directly on Fly using the individual connection
fields; never commit a connection string:

```bash
flyctl secrets set --app pilah-be-staging \
  DJANGO_SECRET_KEY='change-me' \
  DB_NAME='neondb' \
  DB_USER='neondb_owner' \
  DB_PASSWORD='change-me' \
  DB_HOST='ep-example.ap-southeast-1.aws.neon.tech' \
  GOOGLE_CLIENT_ID='your-web-oauth-client-id' \
  PILAH_SUPERADMIN_EMAILS='superadmin@example.com'
```

Set Google callback and WhatsApp/Twilio secrets as needed. The Fly runtime
allowlist is authoritative for Superadmin login/API access and must include
the configured fixture Superadmin. Non-debug fixture seeding fails unless
`PILAH_ENVIRONMENT=staging` (set in `fly.toml`), the confirmation is provided,
and that Superadmin is allowlisted.

GitHub's `staging` environment needs an app-scoped `FLY_API_TOKEN` and these
non-secret variables before the next staging push:

```text
PILAH_SEED_PENGURUS_EMAIL
PILAH_SEED_CUSTOMER_EMAIL
PILAH_SEED_CUSTOMER_TWO_EMAIL
PILAH_SEED_SUPERADMIN_EMAIL
PILAH_SEED_PENDING_PENGURUS_EMAIL
PILAH_SEED_INDUK_EMAIL
```

`PILAH_SEED_INDUK_EMAIL` defaults to `induk.demo@example.com`. The old
`PILAH_SEED_OPERATOR_EMAIL` and `PILAH_SEED_PENDING_OPERATOR_EMAIL` remain
fallbacks, with Pengurus values taking precedence. Use real Google test
accounts and include Induk's chosen address on the consent screen too.
Missing/invalid required addresses fail the deploy job. Seed arguments are
validated and passed as data rather than interpolated into a shell script.

The command updates deterministic active Pengelola/Induk banks and pending
approval fixtures, customers, balances, waste types and transaction history;
it never flushes or removes unrelated data. As before, fixture profiles can
be restored by reseeding, so do not use fixture identities for permanent data.
For local SQLite or Docker Postgres, run migrations followed by
`python manage.py seed_testing_data`; local execution requires `DJANGO_DEBUG=true`.
Production runtime markers always forbid fixture seeding.

## Operations

```bash
flyctl status --app pilah-be-staging
flyctl checks list --app pilah-be-staging
flyctl logs --app pilah-be-staging
```

Migrations and static collection run from `docker/entrypoint.sh` before
Gunicorn starts. The volume limits this staging app to one machine; move
media to object storage before scaling beyond one machine or region.
After deploying, verify genuine Google sign-in from the dashboard as Pengurus,
Pengurus Induk and Superadmin. This change does not itself deploy or configure
cloud resources or Google Console settings.
