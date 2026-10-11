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
   origin, without a path or trailing slash. Also configure the production
   repository variable `PILAH_SUPERADMIN_EMAILS` with real authorized accounts.
   Missing/invalid origin or allowlist stops deployment before cloud mutations.
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
`PILAH_WEB_ORIGIN` (browser origin) and the frontend `BASE_URL_PROD` (backend
origin only; mobile request paths include `/api/v1`). Configure it for the
existing invite route; this delivery does not change invite routing. Keep fake
tokens and Django debug **false**.

## Automatic production Superadmin bootstrap

After service deployment succeeds, the workflow creates/replaces and executes
`<backend-service>-bootstrap-superadmins` as a real Cloud Run Job and waits for
success. The manual script uses the same helper. The Job copies the deployed
service image, runtime service account, environment (including Secret Manager
references), Cloud SQL/VPC configuration and mounted volumes. The temporary
manifest is owner-only and removed after use; credential values are not logged.
The deploying identity therefore needs permissions to describe the service,
create/update/execute Jobs (for example `roles/run.admin`) and act as the
runtime service account (`roles/iam.serviceAccountUser`). Runtime DB/Cloud SQL
permissions are the same as the backend service. Python 3 is required for the
helper; it adds no runtime dependency.

The Job runs `python manage.py bootstrap_superadmins`. Only missing accounts
in the runtime `PILAH_SUPERADMIN_EMAILS` allowlist are created, with role
Superadmin and an unusable password for genuine Google login. It creates no
banks, customers, balances, waste types or transactions. Existing account
profiles, passwords, active flags, Google identities and Django admin flags
are never changed. A non-Superadmin role conflict fails atomically; resolve
account ownership manually rather than silently promoting it. Job failure
fails the deploy workflow, although the service revision has already deployed.
Re-running the bootstrap is safe. Runtime `PILAH_ENVIRONMENT=production`
forbids `seed_testing_data`, even with its staging confirmation or debug enabled.
Staging fixture variables are not used in production.

## Prerequisites

Install and initialize the Google Cloud SDK, then log in:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project pilah-app
```

Your Google account needs enough permissions to create and manage:

- Cloud Run services
- Cloud SQL instances
- Artifact Registry repositories
- Cloud Storage buckets
- IAM service accounts and IAM bindings
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
7. Grant Cloud SQL and GCS access.
8. Build and push the Docker image with Cloud Build.
9. Deploy to Cloud Run.
10. Print the Cloud Run service URL.
11. Execute and wait for the production-only Superadmin bootstrap Job.

The origin and allowlist are required and validated before provisioning starts.

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
sign-in as an allowlisted Superadmin. Confirm the production database contains
no demo fixture records. No live cloud/Google Console changes are made merely
by merging this code; required variables and promotion must be completed.

## Important Production Notes

Set these before production use:

- `DJANGO_SECRET_KEY` to a long random value.
- `GOOGLE_CLIENT_ID` to the production OAuth client ID.
- `DJANGO_ALLOWED_HOSTS` to the Cloud Run domain or custom domain.
- `PILAH_WEB_ORIGIN` to the actual dashboard HTTPS origin (required).
- `PILAH_SUPERADMIN_EMAILS` to the authoritative production Google accounts.
- `CORS_ALLOW_ALL_ORIGINS=false`; both deploy paths enforce explicit origins.
- `PILAH_PUBLIC_APP_URL` to the public app or API URL used for invite links.
- `WHATSAPP_GATEWAY_URL` and `WHATSAPP_GATEWAY_TOKEN` if WhatsApp sending is enabled.

The script currently passes environment variables directly to Cloud Run for speed and simplicity. For stronger production hygiene, move secrets such as `DJANGO_SECRET_KEY`, `DB_PASSWORD`, and `WHATSAPP_GATEWAY_TOKEN` into Secret Manager and deploy with `--set-secrets`.

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
