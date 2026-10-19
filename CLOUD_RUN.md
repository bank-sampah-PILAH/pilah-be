# Google Cloud Run Production

Production backend deployment runs on pushes to `main` (or the existing manual
workflow dispatch). Backend PRs still target `staging`; promotion to `main` is a
separate operational step. The manual provisioning script below is also supported.

Target services:

- Cloud Run for the Django API
- Cloud SQL for PostgreSQL
- Google Cloud Storage for uploaded media
- Artifact Registry for the Docker image

## Dashboard origin and first-deploy ordering

The production dashboard is the separate `pilah-web` Cloud Run service owned by
`pilah-mobile`. Both services use provider-generated `*.run.app` URLs; do not
guess a URL hash or configure a custom domain.

1. Deploy the backend-independent dashboard service to obtain its actual URL
   (an initial build may use a placeholder API base and is not ready for login).
   Read it with `gcloud run services describe pilah-web --region <region>
   --project <project> --format='value(status.url)'`.
2. Set the backend repository variable `PILAH_WEB_ORIGIN` to that exact HTTPS
   origin, without a path or trailing slash. Configure the production
   repository variables `PILAH_SUPERADMIN_EMAILS` with global admins,
   `PILAH_REVIEW_SUPERADMIN_EMAILS` with review-only Superadmins, and
   `PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS` with the four production review
   account addresses listed below. The review Superadmin must be in the review
   list and out of the global list; the exemption list only skips email
   verification for the review login identities.
   Missing/invalid origin or allowlists stop deployment before cloud mutations.
3. Deploy the backend with its existing GCP/DB/storage/OAuth secrets and vars.
   CORS and CSRF explicitly allow `PILAH_WEB_ORIGIN`, never all origins.
4. Read the actual backend Cloud Run URL and rebuild/redeploy the frontend with
   the backend origin (no path) as its `BASE_URL_PROD` and the matching Google
   Web client ID. Mobile request paths already include `/api/v1`.
5. Add the exact dashboard origin to the Web OAuth client's **Authorized
   JavaScript origins** in Google Console. Frontend `GOOGLE_SERVER_CLIENT_ID`
   must equal backend `GOOGLE_CLIENT_ID`. If using the backend callback flow,
   register `<backend-url>/api/v1/auth/google/callback` as the redirect URI.

`PILAH_PUBLIC_APP_URL` remains the invite-link base and is distinct from
`PILAH_WEB_ORIGIN` (trusted browser origin) and the frontend `BASE_URL_PROD`
(backend origin only; mobile request paths include `/api/v1`). Keep the invite
base on the backend host for Android App Links. New `/invite/<token>` links
redirect to `PILAH_WEB_ORIGIN/#/invite/<token>`; older `/invite?token=...` links
remain supported by the native app, but their query token is not forwarded by the
browser fallback. The production workflow passes these repository variables
to Cloud Run and validates their email values before deployment. Keep fake
tokens and Django debug **false**.

## Production account bootstrap and review seed

After service deployment succeeds, the workflow runs the Superadmin bootstrap
then the review seed dry-run and apply steps in Cloud Run Jobs, waiting for
each. The manual script uses the same helper. Each Job copies the deployed
service image, runtime service account, environment (including the Secret
Manager password reference), Cloud SQL/VPC configuration, and mounted volumes.
The temporary manifest is owner-only and removed after use; credential values
are not logged. The deploying identity needs permissions to describe the
service, create/update/execute Jobs (for example `roles/run.admin`) and act as
the runtime service account (`roles/iam.serviceAccountUser`). The runtime
service account needs database access and `roles/secretmanager.secretAccessor`
on the review password secret. The manual deploy script grants that
secret-level binding; configure the same binding for the GitHub deployment.
Python 3 is required for the helper; it adds no runtime dependency.

The `bootstrap_superadmins` Job drops privileges to the image's `appuser`
before running `python manage.py bootstrap_superadmins`. It creates only
missing accounts in the runtime `PILAH_SUPERADMIN_EMAILS` allowlist, with role
Superadmin and an unusable password for Google login. It creates no banks,
customers, balances, waste types, or transactions. Existing account profiles,
passwords, active flags, Google identities, and Django admin flags are never
changed. A non-Superadmin role conflict fails atomically; resolve account
ownership manually rather than silently promoting it. Job failure fails the
deploy workflow, although the service revision has already deployed.

The `seed_play_demo_accounts` Jobs provision these password login identities:

- Pengelola: `pilah.pengelola@pilah.com`
- Pengurus: `pilah.pengurus@pilah.com`
- Nasabah: `pilah.nasabah@pilah.com`
- Review Superadmin: `pilah.superadmin@pilah.com`

Set `PILAH_REVIEW_SUPERADMIN_EMAILS` to include the review Superadmin and keep
it out of `PILAH_SUPERADMIN_EMAILS`. Set
`PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS` to all four addresses. This setting
only skips the verified-email requirement for the review login accounts; it
does not grant Superadmin access.

Create the Secret Manager secret `PILAH_REVIEW_ACCOUNT_PASSWORD` and add the
shared password as a secret version before deployment. Cloud Run refers to its
`latest` version through the `PILAH_REVIEW_ACCOUNT_PASSWORD` environment name;
the value is not passed as a GitHub variable or command argument. The seed
stores password hashes only. Use a secure credential-sharing process when
providing reviewers with login access. The seed does not create mailboxes or
provide signup, email delivery, or password-reset flows.

The image entrypoint applies database migrations before the post-deploy seed
Jobs run. The dry-run validates the production target and secret before the
apply Job runs. Re-running is safe for its seeded rows: recognized identities
from the previous seed are migrated in place, preserving user IDs, roles,
synthetic bank/membership/history relationships, while changing their emails,
setting the shared password hash, and clearing old Google subject bindings.
Unrecognized legacy users or target-email/identity conflicts stop the command
before writes. It preserves unrelated tenant data and approval decisions on the
synthetic review bank. Runtime `PILAH_ENVIRONMENT=production` forbids
`seed_testing_data`, even with its staging confirmation or debug enabled;
staging fixture variables are not used in production.

## Prerequisites

Install and initialize the Google Cloud SDK, then log in:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project pilah-app
```

Create the Secret Manager secret `PILAH_REVIEW_ACCOUNT_PASSWORD` and add the
shared review password as a secret version before deploying. Keep the value in
Secret Manager; the service uses its `latest` version reference and does not
read a GitHub secret or variable. The runtime service account needs
`roles/secretmanager.secretAccessor` on that secret.

Your Google account needs enough permissions to create and manage:

- Cloud Run services
- Cloud SQL instances
- Artifact Registry repositories
- Cloud Storage buckets
- IAM service accounts and IAM bindings
- Secret Manager secrets and IAM bindings
- Cloud Build builds

## One Command Deploy

Set required variables:

```bash
export PROJECT_ID=pilah-app
export REGION=asia-southeast2
export SERVICE_NAME=pilah-be
export ARTIFACT_REPO=pilah
export SQL_INSTANCE=pilah-postgres
export DB_NAME=pilah
export DB_USER=pilah
export DB_PASSWORD='change-this-db-password'
export GCS_BUCKET='pilah-media-prod'
export DJANGO_SECRET_KEY='change-this-django-secret'
export PILAH_PUBLIC_APP_URL=''
export PILAH_WEB_ORIGIN='https://<actual-dashboard-provider-url>'
export PILAH_SUPERADMIN_EMAILS='admin@example.com'
export PILAH_REVIEW_SUPERADMIN_EMAILS='pilah.superadmin@pilah.com'
export PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS='pilah.pengelola@pilah.com,pilah.pengurus@pilah.com,pilah.nasabah@pilah.com,pilah.superadmin@pilah.com'
export GOOGLE_CLIENT_ID=''
export WHATSAPP_GATEWAY_URL=''
export WHATSAPP_GATEWAY_TOKEN=''
```

Run:

```bash
./scripts/deploy-cloud-run.sh
```

The script will:

1. Enable required Google Cloud APIs.
2. Create Artifact Registry if missing.
3. Create Cloud SQL PostgreSQL if missing.
4. Create the database and database user if missing.
5. Create the GCS bucket if missing.
6. Create a Cloud Run runtime service account if missing.
7. Grant Cloud SQL, GCS, and review-password Secret Manager access.
8. Build and push the Docker image with Cloud Build.
9. Deploy to Cloud Run.
10. Print the Cloud Run service URL.
11. Execute and wait for the production Superadmin bootstrap and review seed
    dry-run/apply Jobs.

The origin, allowlists, and email verification exemptions are required and
validated before provisioning starts. The manual deploy grants the runtime
service account access to the review password secret. The review seed hashes
the shared secret for all four accounts; reruns preserve seeded user IDs and
synthetic relationships, clear old Google subject bindings, and abort before
writes when legacy or target identities conflict. Service migrations run before
the post-deploy seed Jobs.

## After Deploy

Open the printed Cloud Run URL, then check:

```text
/healthz
```

`/api/docs/`, `/api/schema/` and `/api-test/` are developer tools served only
when `DJANGO_DEBUG=true`, so on Cloud Run (`DJANGO_DEBUG=false`) they answer 404.
Use a local run, or `python manage.py spectacular --file openapi.yaml`, to read
the API docs.

Superadmins are bootstrapped automatically as described above; do not run the
staging fixture or `createsuperadmin` in the deployment pipeline. The latter
is an explicit local/operator tool that overwrites role, profile and password,
not an idempotent production bootstrap.

After configuring OAuth and rebuilding the frontend, verify real Google
sign-in as an allowlisted Superadmin. Verify that review identities retain
synthetic-only scope and that the review Superadmin has no Django staff or
superuser access. No live cloud/Google Console changes are made merely by
merging this code; required variables and promotion must be completed.

## Important Production Notes

Set these before production use:

- `DJANGO_SECRET_KEY` to a long random value.
- `GOOGLE_CLIENT_ID` to the production OAuth client ID.
- `DJANGO_ALLOWED_HOSTS` to the Cloud Run domain or custom domain.
- `PILAH_WEB_ORIGIN` to the actual dashboard HTTPS origin (required).
- `PILAH_SUPERADMIN_EMAILS` to the authoritative production Google accounts.
- `PILAH_REVIEW_SUPERADMIN_EMAILS` to include `pilah.superadmin@pilah.com`
  and exclude it from the global Superadmin list.
- `PILAH_EMAIL_VERIFICATION_EXEMPT_EMAILS` to all four password review account
  addresses (Pengelola, Pengurus, Nasabah, and review Superadmin).
- `PILAH_REVIEW_ACCOUNT_PASSWORD` as a Secret Manager secret version, with
  runtime service account access. Never add its value to GitHub variables or
  source control.
- `CORS_ALLOW_ALL_ORIGINS=false`; both deploy paths enforce explicit origins.
- `PILAH_PUBLIC_APP_URL` to the public app or API URL used for invite links.
- `WHATSAPP_GATEWAY_URL` and `WHATSAPP_GATEWAY_TOKEN` if WhatsApp sending is enabled.

The deploy workflow and script provide the review password through Secret
Manager, never as a plain environment variable. The existing database,
Twilio/WhatsApp, and Django secrets follow the current deployment configuration.

## Manual Reset

Delete the Cloud Run service:

```bash
gcloud run services delete pilah-be --region asia-southeast2
```

Delete the Cloud SQL instance:

```bash
gcloud sql instances delete pilah-postgres
```

Delete the GCS bucket and all objects:

```bash
gcloud storage rm --recursive gs://pilah-media-prod
```

Delete the Artifact Registry repository:

```bash
gcloud artifacts repositories delete pilah --location asia-southeast2
```
