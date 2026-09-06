# PILAH Backend Instructions

## Scope

- This repository is the `pilah-be` application submodule of the PILAH
  workspace.
- Keep backend implementation changes here, not in the workspace root or the
  mobile repository.
- Keep the canonical checkout on `main`; use `staging` as the default worktree
  baseline and pull request target unless the request explicitly names another
  branch.

## Development

- The backend uses Python 3.12, Django 6, and Django REST Framework.
- Prefer `uv` for local setup when available: `uv venv` followed by
  `uv pip install -r requirements.txt`; fall back to a virtual environment and
  `pip install -r requirements.txt` when `uv` is unavailable.
- Docker setup and environment variables are documented in `README.md`.

## Validation

- Run `uv run --with-requirements requirements.txt python manage.py test` when
  `uv` is available; otherwise run `python manage.py test`.
- The Docker equivalent is `docker compose exec web python manage.py test`.
- Do not commit `.env`, credentials, local databases, media, or generated
  runtime files.

## Delivery

- Use the local `.agents/skills/ship` skill with the global `ship` workflow for
  feature or fix branches in sibling `pilah-be-worktrees` directories.
- Use the local `.agents/skills/lgtm` skill with the global `lgtm` workflow for
  merge and cleanup.
