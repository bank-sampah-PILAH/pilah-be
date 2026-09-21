---
name: seed-database
description: Populate PILAH local or staging databases with the deterministic E2E fixture, and keep that fixture current after schema changes. Use when an agent needs demo rows, test accounts, seeded balances, transactions, approval-flow data, or E2E readiness.
argument-hint: "[local database or schema change]"
compatibility: Requires the pilah-be repository and its documented Django environment.
metadata:
  author: PILAH
  version: "1.0"
---

# Seed the PILAH E2E database

Use the public management command as the single fixture entry point. Read
`AGENTS.md` and the relevant model/API code first. Never flush the database or
delete unrelated rows for this task.

## Local development

Run migrations, then seed the deterministic fixture:

```bash
uv run --with-requirements requirements.txt python manage.py migrate --noinput
uv run --with-requirements requirements.txt python manage.py seed_testing_data
```

Local seeding requires `DJANGO_DEBUG=true` and uses the default demo emails
unless `PILAH_SEED_OPERATOR_EMAIL`, `PILAH_SEED_CUSTOMER_EMAIL`,
`PILAH_SEED_SUPERADMIN_EMAIL`, or `PILAH_SEED_PENDING_OPERATOR_EMAIL` is set.
The command is idempotent and preserves unrelated rows.

## Staging

Never enable fake Google authentication on staging or production. Configure the
four staging Google test-account emails in the GitHub `staging` environment and
run the confirmation-gated **Seed Staging Testing Data** workflow. The exact
confirmation is `SEED-PILAH-STAGING-DATA`; do not run this command against
production.

## After schema changes

When a backend change adds or changes a required model field:

1. Run the migration checks and update `seed_testing_data` defaults so the
   fixture remains valid.
2. Extend `api/test_seed_testing_data.py` for the observable fixture behavior.
3. Run the command twice and verify deterministic counts, balances,
   transactions, and approval-flow rows; check that an unrelated row survives.
4. Exercise the affected authenticated endpoint with a seeded role.

Only report “ready for E2E test” after migrations, seeding, rerun checks, and
the relevant endpoint verification succeed. Include the seeded roles and rows
in the handoff so the next agent knows which demo accounts are available.
