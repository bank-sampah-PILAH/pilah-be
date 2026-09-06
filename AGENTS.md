# PILAH Backend Instructions

## Scope

- This repository is the `pilah-be` application submodule of the PILAH
  workspace.
- Keep backend implementation changes here, not in the workspace root or the
  mobile repository.
- Use `main` as the baseline and pull request target.

## Development

- The backend uses Python 3.12, Django 6, and Django REST Framework.
- Direct local setup uses a virtual environment and `pip install -r
  requirements.txt`.
- Docker setup and environment variables are documented in `README.md`.

## Validation

- Run `python manage.py test` for direct local validation.
- The Docker equivalent is `docker compose exec web python manage.py test`.
- Do not commit `.env`, credentials, local databases, media, or generated
  runtime files.

## Delivery

- Use the local `.agents/skills/ship` skill with the global `ship` workflow for
  feature or fix branches in sibling `pilah-be-worktrees` directories.
- Use the local `.agents/skills/lgtm` skill with the global `lgtm` workflow for
  merge and cleanup.
