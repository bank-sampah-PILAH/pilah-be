# Nasabah and pencairan integration

This integration branch targets `staging`. The feature PRs stay separate:

- #34: PIL-225 home
- #33: PIL-226 profile
- #37: PIL-227 history contract
- #38: PIL-228 navigation role contract
- #19: PIL-176 pencairan

Review the feature PRs independently. This PR combines their snapshots to test
the final result; merging it early would also deliver all five features.
Coordinate the feature merges first, then refresh this integration branch
against `staging` and re-run CI before merging the remaining integration fixes.
The second migration-producing feature to land may temporarily create multiple
leaves, so do not deploy that intermediate state; deliver the merge migration
with the combined rollout. Do not delete or rename migrations already applied
in another environment.

`0016_merge_pencairan_and_nasabah_features` joins the pencairan leaf with
`0015_merge_nasabah_and_staging`. It has no schema or data operations. Existing
nasabah and pencairan migration names remain intact.

`IsActivePengelolaOrNasabah` delegates customer reads to `IsActiveNasabah`.
It therefore rejects inactive customer accounts without requiring a completed
profile or active bank membership. Querysets still restrict customer reads to
their own pencairan. The manager branch retains `IsActivePengelola` checks.
Staging's `IsNasabah` remains a distinct complete-profile permission used by
registration; the duplicate role-only class from pencairan is removed.

Transaction detail and export include withdrawal debits and use the shared
`bulatkan_rupiah` helper. Deposit price/weight validation and per-item rounding
from staging remain intact. Withdrawal snapshots retain the original balance,
including historical fractions, while the resulting balance is whole rupiah.

Validate with `python manage.py makemigrations --check --dry-run`,
`python manage.py migrate --noinput`, `python manage.py test`, `ruff check .`,
`ruff format --check .`, and `mypy api config`. CI repeats validation against
PostgreSQL. The overlap tests check the single migration leaf and both branches
of the shared read permission; the existing suites check account isolation,
withdrawal balance updates, and deposit/withdrawal history.
