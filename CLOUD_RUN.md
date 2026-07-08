# Manual Google Cloud Run Deployment

This guide deploys the backend manually using your own Google account with `gcloud auth login`.

Target services:

- Cloud Run for the Django API
- Cloud SQL for PostgreSQL
- Google Cloud Storage for uploaded media
- Artifact Registry for the Docker image

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
export GOOGLE_CLIENT_ID=''
export GOOGLE_CLIENT_IDS=''
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

## After Deploy

Open the printed Cloud Run URL, then check:

```text
/api/docs/
/api/schema/
/api-test/
```

Create a SuperAdmin account:

```bash
gcloud run jobs create pilah-create-superadmin \
  --image asia-southeast2-docker.pkg.dev/pilah-app/pilah/pilah-be:latest \
  --region asia-southeast2 \
  --set-cloudsql-instances pilah-app:asia-southeast2:pilah-postgres \
  --set-env-vars DJANGO_DEBUG=false,DB_ENGINE=django.db.backends.postgresql,DB_NAME=pilah,DB_USER=pilah,DB_PASSWORD='change-this-db-password',DB_HOST=/cloudsql/pilah-app:asia-southeast2:pilah-postgres,DB_PORT=5432,GS_BUCKET_NAME=pilah-media-prod \
  --command python \
  --args manage.py,createsuperadmin,--email,admin@example.com,--password,password123,--nama,"Admin PILAH"

gcloud run jobs execute pilah-create-superadmin \
  --region asia-southeast2 \
  --wait
```

You can also create the SuperAdmin inside a locally configured environment with direct database access, but the Cloud Run job keeps it inside Google Cloud.

## Important Production Notes

Set these before production use:

- `DJANGO_SECRET_KEY` to a long random value.
- `GOOGLE_CLIENT_IDS` to a comma-separated list of production OAuth client IDs for the mobile app, such as Android and iOS client IDs. `GOOGLE_CLIENT_ID` is still supported for one client.
- `DJANGO_ALLOWED_HOSTS` to the Cloud Run domain or custom domain.
- `CORS_ALLOW_ALL_ORIGINS=false` once the frontend domain is known.
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
