#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-pilah-app}"
REGION="${REGION:-asia-southeast2}"
SERVICE_NAME="${SERVICE_NAME:-pilah-be}"
ARTIFACT_REPO="${ARTIFACT_REPO:-pilah}"
IMAGE_NAME="${IMAGE_NAME:-pilah-be}"
SQL_INSTANCE="${SQL_INSTANCE:-pilah-postgres}"
SQL_TIER="${SQL_TIER:-db-f1-micro}"
SQL_EDITION="${SQL_EDITION:-ENTERPRISE}"
DB_NAME="${DB_NAME:-pilah}"
DB_USER="${DB_USER:-pilah}"
DB_PASSWORD="${DB_PASSWORD:?Set DB_PASSWORD before running this script}"
GCS_BUCKET="${GCS_BUCKET:?Set GCS_BUCKET before running this script}"
DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:?Set DJANGO_SECRET_KEY before running this script}"
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"
GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-}"
GOOGLE_REDIRECT_URI="${GOOGLE_REDIRECT_URI:-}"
PILAH_PUBLIC_APP_URL="${PILAH_PUBLIC_APP_URL:-}"
WHATSAPP_GATEWAY_URL="${WHATSAPP_GATEWAY_URL:-}"
WHATSAPP_GATEWAY_TOKEN="${WHATSAPP_GATEWAY_TOKEN:-}"

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${IMAGE_NAME}:latest"
SQL_CONNECTION_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"
RUNTIME_SA="${SERVICE_NAME}-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}"

gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com

gcloud artifacts repositories describe "${ARTIFACT_REPO}" \
  --location="${REGION}" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "${ARTIFACT_REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="PILAH backend images"

gcloud sql instances describe "${SQL_INSTANCE}" >/dev/null 2>&1 \
  || gcloud sql instances create "${SQL_INSTANCE}" \
    --database-version=POSTGRES_16 \
    --region="${REGION}" \
    --edition="${SQL_EDITION}" \
    --tier="${SQL_TIER}" \
    --storage-size=10GB

gcloud sql databases describe "${DB_NAME}" --instance="${SQL_INSTANCE}" >/dev/null 2>&1 \
  || gcloud sql databases create "${DB_NAME}" --instance="${SQL_INSTANCE}"

if gcloud sql users describe "${DB_USER}" --instance="${SQL_INSTANCE}" >/dev/null 2>&1; then
  gcloud sql users set-password "${DB_USER}" --instance="${SQL_INSTANCE}" --password="${DB_PASSWORD}"
else
  gcloud sql users create "${DB_USER}" --instance="${SQL_INSTANCE}" --password="${DB_PASSWORD}"
fi

gcloud storage buckets describe "gs://${GCS_BUCKET}" >/dev/null 2>&1 \
  || gcloud storage buckets create "gs://${GCS_BUCKET}" \
    --location="${REGION}" \
    --uniform-bucket-level-access

gcloud iam service-accounts describe "${RUNTIME_SA}" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "${SERVICE_NAME}-runtime" \
    --display-name="PILAH Cloud Run runtime"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUN_AGENT="service-${PROJECT_NUMBER}@serverless-robot-prod.iam.gserviceaccount.com"
COMPUTE_DEFAULT_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
CLOUD_BUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/cloudsql.client" \
  --quiet >/dev/null

gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/storage.objectAdmin" \
  --quiet >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUN_AGENT}" \
  --role="roles/cloudsql.client" \
  --quiet >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${COMPUTE_DEFAULT_SA}" \
  --role="roles/storage.objectViewer" \
  --quiet >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${COMPUTE_DEFAULT_SA}" \
  --role="roles/artifactregistry.writer" \
  --quiet >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CLOUD_BUILD_SA}" \
  --role="roles/storage.objectViewer" \
  --quiet >/dev/null || true

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CLOUD_BUILD_SA}" \
  --role="roles/artifactregistry.writer" \
  --quiet >/dev/null || true

gcloud builds submit --tag "${IMAGE_URI}" .

gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_URI}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --service-account="${RUNTIME_SA}" \
  --add-cloudsql-instances="${SQL_CONNECTION_NAME}" \
  --set-env-vars="^|^DJANGO_DEBUG=false|DJANGO_ALLOWED_HOSTS=*|CORS_ALLOW_ALL_ORIGINS=true|DB_ENGINE=django.db.backends.postgresql|DB_NAME=${DB_NAME}|DB_USER=${DB_USER}|DB_PASSWORD=${DB_PASSWORD}|DB_HOST=/cloudsql/${SQL_CONNECTION_NAME}|DB_PORT=5432|GS_BUCKET_NAME=${GCS_BUCKET}|PILAH_ALLOW_FAKE_GOOGLE_TOKEN=false|PILAH_PUBLIC_APP_URL=${PILAH_PUBLIC_APP_URL}|GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}|GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}|GOOGLE_REDIRECT_URI=${GOOGLE_REDIRECT_URI}|WHATSAPP_GATEWAY_URL=${WHATSAPP_GATEWAY_URL}|WHATSAPP_GATEWAY_TOKEN=${WHATSAPP_GATEWAY_TOKEN}|DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}"

gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format="value(status.url)"
