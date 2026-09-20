# Fly.io Staging

Pushes to `staging` deploy `pilah-be-staging` after CI succeeds. The app runs in
Singapore, connects to Neon over TLS, and stores uploaded media on the single
`media_data` Fly volume.

Only logo files are served as public local media. Activity-proof files are
returned to superadmins as short-lived signed URLs.

## Required Secrets

Set Django and Neon values directly on Fly. Use the individual fields from the
Neon connection string; do not commit the connection string.

```bash
flyctl secrets set --app pilah-be-staging \
  DJANGO_SECRET_KEY='change-me' \
  DB_NAME='neondb' \
  DB_USER='neondb_owner' \
  DB_PASSWORD='change-me' \
  DB_HOST='ep-example.ap-southeast-1.aws.neon.tech'
```

Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, and any
WhatsApp/Twilio secrets the staging environment needs with the same command.
Register this Google OAuth callback URL:

```text
https://pilah-be-staging.fly.dev/api/v1/auth/google/callback
```

GitHub's `staging` environment must contain an app-scoped `FLY_API_TOKEN`.
It should also contain the four non-secret variables used by the seed workflow:

```text
PILAH_SEED_OPERATOR_EMAIL
PILAH_SEED_CUSTOMER_EMAIL
PILAH_SEED_SUPERADMIN_EMAIL
PILAH_SEED_PENDING_OPERATOR_EMAIL
```

These addresses should be Google test accounts already listed on the OAuth
consent screen. Staging uses real Google ID tokens; `PILAH_ALLOW_FAKE_GOOGLE_TOKEN`
must remain `false` and the mobile staging build does not show the local demo
login.

## Operations

```bash
flyctl status --app pilah-be-staging
flyctl checks list --app pilah-be-staging
flyctl logs --app pilah-be-staging
```

## Seed E2E data

Use the repository's **Seed Staging Testing Data** GitHub Actions workflow.
Enter `SEED-PILAH-STAGING-DATA` in its confirmation field. The workflow checks
the target app and all four configured emails, then runs:

```bash
python manage.py seed_testing_data \
  --environment staging \
  --confirm=SEED-PILAH-STAGING-DATA
```

The command is idempotent, creates the active and pending approval-flow
fixtures, and never flushes or removes unrelated staging data. For local
SQLite or Docker Postgres, run `python manage.py migrate` followed by
`python manage.py seed_testing_data` instead; local execution requires
`DJANGO_DEBUG=true`.

Migrations and static collection run from `docker/entrypoint.sh` before Gunicorn
starts. The volume limits this staging app to one machine; move media to object
storage before scaling beyond one machine or region.
