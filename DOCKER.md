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
