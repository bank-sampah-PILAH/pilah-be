# PILAH Backend

PILAH is a Django REST Framework backend for a digital bank sampah management system. It implements the mobile pengelola API, SuperAdmin approval workflow, onboarding, team invitations, transaction recording, saldo updates, WhatsApp notification hooks, report export, and OpenAPI documentation.

## Stack

- Python 3.12
- Django 6
- Django REST Framework
- Simple JWT
- PostgreSQL for Docker/local production-like setup
- SQLite for direct local development by default
- drf-spectacular for OpenAPI schema
- Gunicorn and WhiteNoise for container deployment

## Main Features

- Google OAuth token verification with JWT session issuance
- Development auth token support for local testing
- Role-based access for `pengelola` and `superadmin`
- Bank sampah registration with pending, active, and rejected states
- SuperAdmin approval and rejection workflow
- Pengelola utama invitation links for additional team members
- Nasabah CRUD with manual per-bank codes
- Jenis sampah CRUD with material categories
- Atomic transaction creation with price snapshots and saldo updates
- WhatsApp notification endpoint with configurable gateway integration
- Current saldo endpoint
- Dashboard statistics and recent transactions
- Excel export for transaction reports
- Multipart upload for bank sampah activity proof image
- Browser-based API end-to-end test runner

## Quick Start With Docker

Build and run the API with Postgres:

```bash
docker compose up --build
```

Open:

- API base: `http://localhost:8000/api/v1/`
- API test runner: `http://localhost:8000/api-test/`
- OpenAPI schema: `http://localhost:8000/api/schema/`
- Swagger UI: `http://localhost:8000/api/docs/`

Create or update a SuperAdmin account:

```bash
docker compose exec web python manage.py createsuperadmin \
  --email admin@example.com \
  --password password123 \
  --nama "Admin PILAH"
```

Run tests:

```bash
docker compose exec web python manage.py test
```

Reset local Docker data:

```bash
docker compose down -v
```

For Google Cloud Run deployment, see [CLOUD_RUN.md](CLOUD_RUN.md).

## Direct Local Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a local `.env` from the example if needed:

```bash
cp .env.example .env
```

Run migrations:

```bash
python manage.py migrate
```

Start the development server:

```bash
python manage.py runserver 0.0.0.0:8000
```

Run tests:

```bash
python manage.py test
```

## Environment Variables

Common variables:

```env
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOW_ALL_ORIGINS=false
```

Database variables:

```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=pilah
DB_USER=pilah
DB_PASSWORD=pilah
DB_HOST=db
DB_PORT=5432
```

Auth and app variables:

```env
GOOGLE_CLIENT_ID=
PILAH_ALLOW_FAKE_GOOGLE_TOKEN=false
PILAH_PUBLIC_APP_URL=https://pilah.example.com
```

WhatsApp gateway variables:

```env
WHATSAPP_GATEWAY_URL=
WHATSAPP_GATEWAY_TOKEN=
WHATSAPP_GATEWAY_TIMEOUT=10
```

## Development Auth Tokens

When `PILAH_ALLOW_FAKE_GOOGLE_TOKEN=true`, local development can use fake Google tokens.

Pengelola:

```json
{
  "id_token": "dev:user@example.com:User Name"
}
```

SuperAdmin:

```json
{
  "id_token": "dev-superadmin:admin@example.com:Admin Name"
}
```

Use only real Google ID tokens in production.

## Role Flow

Pengelola utama flow:

1. Login with Google.
2. Complete profile through `PUT /api/v1/onboarding/profile`.
3. Register bank sampah through `POST /api/v1/onboarding/bank-sampah`.
4. Bank status becomes `pending`.
5. Pengelola is blocked from operational APIs until approval.
6. SuperAdmin approves through `POST /api/v1/superadmin/bank-sampah/:id/approve`.
7. Bank status becomes `active`.
8. Pengelola can access dashboard, CRUD, transactions, reports, settings, and team management.

Invited pengelola flow:

1. Pengelola utama creates an invite through `POST /api/v1/team/invite`.
2. Invited user logs in with Google.
3. Invited user completes profile.
4. Invited user accepts invite through `POST /api/v1/invites/accept`.
5. Invited user joins the active bank sampah and can use operational APIs.
6. Invited users cannot generate invite links unless they are the primary pengelola.

SuperAdmin flow:

1. Login as SuperAdmin or provision an account with the management command.
2. List registration requests with `GET /api/v1/superadmin/bank-sampah?status=pending`.
3. Approve or reject bank sampah registrations.
4. SuperAdmin cannot use pengelola operational APIs.

## API Groups

Authentication:

- `POST /api/v1/auth/google`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Onboarding and invites:

- `PUT /api/v1/onboarding/profile`
- `POST /api/v1/onboarding/bank-sampah`
- `POST /api/v1/invites/accept`

Bank sampah and team:

- `GET /api/v1/bank-sampah/me`
- `PUT /api/v1/bank-sampah/me`
- `GET /api/v1/team`
- `POST /api/v1/team/invite`

Nasabah:

- `GET /api/v1/nasabah`
- `POST /api/v1/nasabah`
- `GET /api/v1/nasabah/:id`
- `PUT /api/v1/nasabah/:id`
- `PATCH /api/v1/nasabah/:id/status`
- `GET /api/v1/nasabah/:id/saldo`

Jenis sampah:

- `GET /api/v1/jenis-sampah`
- `POST /api/v1/jenis-sampah`
- `PUT /api/v1/jenis-sampah/:id`
- `PATCH /api/v1/jenis-sampah/:id/status`

Transaksi:

- `GET /api/v1/transaksi`
- `POST /api/v1/transaksi`
- `GET /api/v1/transaksi/:id`
- `POST /api/v1/transaksi/:id/notify-wa`
- `GET /api/v1/transaksi/export`

Dashboard and settings:

- `GET /api/v1/dashboard/stats`
- `GET /api/v1/dashboard/recent-transactions`
- `GET /api/v1/pengaturan/wa-template`
- `PUT /api/v1/pengaturan/wa-template`

SuperAdmin:

- `GET /api/v1/superadmin/bank-sampah`
- `GET /api/v1/superadmin/bank-sampah/:id`
- `POST /api/v1/superadmin/bank-sampah/:id/approve`
- `POST /api/v1/superadmin/bank-sampah/:id/reject`

## Report Export

Export transaction reports:

```http
GET /api/v1/transaksi/export?periode=bulan_ini
```

Supported periods:

- `hari_ini`
- `minggu_ini`
- `bulan_ini`
- `bulan_lalu`
- `custom`, with `dari_tanggal` and `sampai_tanggal`

The export returns an `.xlsx` file with category, item, price, total weight, and Excel formulas for totals.

## WhatsApp Gateway

The backend renders the configured WhatsApp template and posts to `WHATSAPP_GATEWAY_URL` when configured.

Default outgoing JSON body:

```json
{
  "to": "+6281234567890",
  "message": "Rendered message"
}
```

If `WHATSAPP_GATEWAY_URL` is empty, the notification endpoint simulates success and updates `status_wa`.

## File Uploads

Bank sampah registration accepts multipart upload through `foto_kegiatan`.

Rules:

- Required
- Allowed extensions: `.jpg`, `.jpeg`, `.png`
- Maximum size: 5 MB

Local uploads are stored under `media/`. Docker persists uploads in the `media_data` volume.

## API Test Runner

Open:

```text
http://localhost:8000/api-test/
```

The runner executes the full API flow:

- Pengelola login
- Profile completion
- Bank registration
- Pending access block
- SuperAdmin approval
- Invite generation and acceptance
- Team checks
- CRUD flows
- Transaction and saldo update
- Report export
- WhatsApp notification
- Deactivation rules
- Logout

It produces a step-by-step report and can download the report as JSON.

## OpenAPI

Generate schema locally:

```bash
python manage.py spectacular --file openapi.yaml --validate
```

Served endpoints:

- `GET /api/schema/`
- `GET /api/docs/`

## Project Structure

```text
api/
  models.py          Domain models
  serializers.py     Validation and response shapes
  services.py        Business logic and integrations
  permissions.py     Role and bank-status gates
  views.py           API views and viewsets
  urls.py            API routing
  tests.py           Backend API tests
  templates/         API test runner page
config/
  settings.py        Django settings
  urls.py            Project routing
docker/
  entrypoint.sh      Container startup script
```

## Operational Commands

Create SuperAdmin:

```bash
python manage.py createsuperadmin \
  --email admin@example.com \
  --password password123 \
  --nama "Admin PILAH"
```

Run migrations:

```bash
python manage.py migrate
```

Collect static files:

```bash
python manage.py collectstatic --noinput
```

Run tests:

```bash
python manage.py test
```

## Notes

- This repository is backend-only.
- The included HTML page is an API test utility, not the product interface.
- Docker uses development credentials by default; change secrets before deployment.
- Production Google OAuth requires a real `GOOGLE_CLIENT_ID`.
- Production file storage can be moved from local filesystem to S3, Supabase Storage, or another Django storage backend.
