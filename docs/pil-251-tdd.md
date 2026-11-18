# PIL-251 implementation and TDD evidence

Baseline: `origin/staging` at `d5a2ff9`. Branch: `feature/pil-251`.

## Implementation

- `User.role` remains the primary role. `User.roles` is a Django JSONField.
- Migration 0039 backfills existing accounts to `[role]`. New normal and bulk
  account creation also initialize that list.
- Assigned-role lists must contain valid, unique roles and include the primary
  role. Memberships require an assigned Nasabah role.
- Access and refresh tokens use the existing `role` claim for the session's
  active role. A missing claim falls back to the primary role. Explicit invalid
  claims and revoked assignments are rejected, including during authentication
  on endpoints without a role-specific permission class.
- Permissions and the existing role-dependent schedule/withdrawal query branches
  use the active claim without changing the account or another device's role.
- Team queries and membership eligibility use assigned roles. PostgreSQL uses
  JSON containment; SQLite uses array indexes over the bounded, unique role set.
- Existing account provisioning and test fixtures remain compatible.
- Profile role-switch UI, a switch endpoint, and second-role granting workflows
  remain outside this implementation. Existing membership registration accepts
  accounts that already have the required role; it does not grant that role.

## Demonstrated RED/GREEN cycles

Each RED test was executed and committed before its implementation. Each GREEN
implementation passed the new test and relevant regression tests before commit.

| Behavior | RED commit | Actual RED result | GREEN commit |
| --- | --- | --- | --- |
| JSON storage and single/dual-role persistence | `3bf9ebd` | `User has no field named 'roles'` | `d5bb9e7` |
| Existing-account migration | `38bc5c3` | `[] != ['nasabah']` | `955a058` |
| Dual-role Nasabah membership | `3358f62` | Membership validation rejected the dual-role account | `5047189` |
| Independent per-device permissions | `24543a5` | Pengurus permission remained true in Nasabah mode | `922741a` |
| Invalid claims on authenticated endpoints | `40f0dd8` | Seven malformed/unowned claims returned 200 instead of 401 | `5bce65b` |
| Refresh preserves active role and rejects revocation | `e8f8df1` | Refresh returned `pengelola` instead of `nasabah` | `a759c7f` |
| New refresh tokens contain the session role | `4cdd1c6` | Refresh token had no `role` claim | `1aff7ed` |
| Team membership uses assigned roles | `14bd7f1` | Dual-role manager with primary Nasabah was missing | `e8151c8` |
| Bank invitation eligibility | `5d96f9a` | Existing dual-role account received PermissionError | `6c45aca` |
| Assigned-role JSON validation | `5867b48` | Seven invalid lists/values saved without ValidationError | `c355713` |
| Existing admin provisioning | `3ea1bf2` | Primary-role validation rejected the existing promotion command | `6944b7b` |
| Bulk account creation | `e208ec1` | Stored roles were `[]` instead of `[primary_role]` | `de31667` |
| Existing membership linking | `2314759` | Matching membership remained unlinked | `f87622f` |
| Registration with an already assigned Nasabah role | `afec3b8` | Existing dual-role account received PermissionError | `27a6f5f` |

Additional regression tests added after GREEN cover existing-token revocation,
legacy refresh fallback, malformed refresh claims, removal of Nasabah while a
membership exists, withdrawal ownership, and exclusion of schedule drafts in
Nasabah mode. These are supplemental coverage, not claimed RED cycles.

## Validation

Tests use Django 6.0.8 from the existing sibling environment at
`../pil-246/.venv/Scripts/python.exe`. That environment was not modified. The
global Python lacked DRF, and installing a new environment could not reach the
package index; those setup failures are not counted as RED evidence.

Set `DJANGO_DEBUG=true` and a local-only `DJANGO_SECRET_KEY` before testing.
Local test keys and runtime database files are not committed.

- Authentication, Nasabah, bank-sampah and architecture regressions: **192 tests
  passed** on SQLite.
- Final feature, migration, architecture and query-scoping regressions: **20
  tests passed** on SQLite.
- Feature, migration and architecture tests: **18 tests passed** on an isolated
  local PostgreSQL 18.1 instance. CI remains configured for PostgreSQL 16; the
  local database was stopped after the run.
- Ruff lint and formatting, strict mypy with the CI Linux target, migration
  drift check, Django system checks, dependency consistency, and diff whitespace
  checks passed. Deploy checks passed at the configured ERROR threshold with
  warnings for existing schema/development settings.
- Full suite: **1,081 tests executed**, with **6 failures, 10 errors and 5
  skips**. Every remaining failure/error matched the unchanged staging baseline
  under the same Windows environment. The two supplemental query-scoping tests
  were added afterward and passed in the final 20-test regression run.

The unchanged staging baseline was exported separately and tested against the
same Windows environment. It reproduced the load-runner failures for POSIX-only
APIs and file modes, and deployment-workflow subprocess failures. Those checks
were not weakened or changed for this feature.
