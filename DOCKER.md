# Local Docker Setup

Start the API and Postgres:

```bash
docker compose up --build
```

Open:

- API: http://localhost:8000/api/v1/
- API tester: http://localhost:8000/api-test/
- OpenAPI schema: http://localhost:8000/api/schema/
- Swagger UI: http://localhost:8000/api/docs/

Create or update a SuperAdmin:

```bash
docker compose exec web python manage.py createsuperadmin \
  --email admin@example.com \
  --password password123 \
  --nama "Admin PILAH"
```

Populate the local Docker database with deterministic E2E data:

```bash
docker compose exec web python manage.py seed_testing_data
```

The command is safe to rerun and preserves unrelated rows. It is guarded by
`DJANGO_DEBUG=true` for local use.

Run tests inside the container:

```bash
docker compose exec web python manage.py test
```

Reset local database and uploaded files:

```bash
docker compose down -v
```

The compose setup uses Postgres with local development credentials:

- database: `pilah`
- user: `pilah`
- password: `pilah`
- host from Django container: `db`

Docker Compose explicitly enables fake Google tokens for local development.
Keep that setting out of any public deployment; the backend rejects fake-token
mode when `DJANGO_DEBUG=false`.
