# PIL-540: switch active role

## Design and contract

Built on PIL-251 (`4166875`), which is not yet in staging at implementation
time. This branch starts from staging and fast-forwards to that dependency.

`POST /api/v1/auth/switch-role` accepts `{"role": "nasabah"}` with bearer
authentication. The serializer validates the payload; `AuthService.switch_role`
checks current assignments before reusing the session response builder. It
does not write the account's primary role or assigned roles.

Success returns the existing login response shape: a fresh access/refresh
pair, token metadata, user data, and `next_step` for the selected role.
Both tokens carry the selected role. Missing/invalid input returns 422;
unowned roles return 403 with `code: role_not_owned`; invalid authentication
returns 401. Same-role requests issue fresh pairs. Existing tokens remain
valid subject to expiry, role ownership, and existing authentication rules.

PIL-251 already preserves and validates refresh roles. `/auth/me` now reports
the token's role and corresponding state, so reloading the session does not
show the primary role instead. Routing reuses `AuthService.user_state`, the
implementation behind `user_state_hint`, with an optional active-role argument.

## Actual TDD evidence

1. `0afdd6d` RED: owned-role switch returned 404 instead of 200.
   `a606659` GREEN: endpoint/service/token claims passed; 20 focused tests
   (including architecture and multi-role regressions) passed.
   Automatic approval review rejected the initial intermediate GREEN commit
   because ownership validation was missing. Before committing implementation,
   an additional ownership regression failed with 200 instead of 403; the
   ownership check was added and passed. That test was included in the GREEN
   commit, not presented as a separate committed RED cycle.
2. `5790ced` RED: response user role was pengelola instead of nasabah.
   `d065501` GREEN: selected-role user response and register_nasabah routing;
   31 focused tests passed.
3. `cce075b` RED: auth/me reported pengelola after switching to nasabah.
   `f60d8ca` GREEN: auth/me follows the token role; 32 focused tests passed.

Supplemental regressions exercise existing behavior rather than claim new
RED cycles: repeated refresh and independent devices, round-trip/same-role
switching, malformed payloads, invalid/expired/tampered/inactive authentication,
real endpoint permissions, existing membership routing, role revocation, and
untrusted identity/role fields. Their initial permission test lacked a Nasabah
membership; the fixture was corrected without changing production permissions.

## Validation

Used the existing Python environment at `../pil-246/.venv/Scripts/python.exe`
with `DJANGO_DEBUG=true`; no dependencies or credentials were modified.

- All 12 switch-role tests pass.
- Ruff lint and formatting pass.
- Strict mypy passes for all 273 checked source files.
- Migration drift check reports no changes.
- 220 tests passed across `apps.authentication`, `apps.bank_sampah`,
  `apps.nasabah`, `tests.test_multirole_scoping`, and `tests.test_architecture`.
- Full `manage.py test --noinput`: 1,121 tests in 224 seconds, with 9 failures,
  11 errors, and 10 skips. This first run used the development-generated secret;
  subprocess production-settings checks require an explicit test secret.
- Reran the failing modules with a temporary random `DJANGO_SECRET_KEY`:
  53 tests, 6 failures and 10 errors. Running the identical selection on an
  unchanged export of dependency commit `4166875` produced the same failure
  names and counts. The remaining failures concern POSIX file modes/APIs
  (`O_NOFOLLOW`, `getloadavg`) and deployment shell/subprocess checks on Windows.
  No tests were weakened or skipped to conceal failures.

The full suite remains a Linux CI validation requirement; this implementation
has not been pushed or submitted as a PR.

## OWASP hardening

Controls follow the [OWASP REST Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
and [Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).
They are concrete endpoint protections, not a claim of OWASP certification.

| Threat | Added prevention | Verified behavior |
| --- | --- | --- |
| Sensitive token responses stored by HTTP caches | `never_cache` on switch dispatch | Success and 401/403/422 responses include `Cache-Control: no-store`; 429 also checked. |
| Unexpected properties and mass-assignment attempts | Serializer permits only `role` | Supplied identity, roles, admin flag, bank ID, or expiry cause 422 before issuance. |
| Automated switching/token issuance abuse | Shared `auth_rate_limit` cache and account-keyed DRF scope | Ten requests/minute; eleventh returns 429 and Retry-After, despite token or forwarded-IP changes; another account retains its allowance. |
| Missing security evidence or log injection/credential exposure | Dedicated security logger for successful/denied switches | Only account UUID and validated role on success; denial omits untrusted role; no JWTs, email, or raw injected input. |
| Stale authorization or partially persisted token issuance | Reload active account under row lock and validate current roles within a transaction | Revoked roles denied before issuance; disabled/deleted accounts rejected; token-build failure rolls back outstanding token and produces no success event. |

The strict field policy deliberately changes spoofed payloads from ignored
extra fields to 422. A recognized but unowned role submitted alone still
returns the acceptance-criteria-required 403.

Rate limiting uses the existing shared database cache and is scoped to the
account, so devices share an abuse allowance while retaining separate active
roles. DRF's cache throttling is best-effort under concurrency; it is not a
hard distributed quota or a replacement for infrastructure request limits.
Row-lock concurrency requires PostgreSQL in production; SQLite local tests
verify stale reads and transaction rollback, not PostgreSQL lock scheduling.

### Additional demonstrated RED/GREEN cycles

| RED commit and observed failure | GREEN commit | Focused result |
| --- | --- | --- |
| `3b9c324`: no-store absent | `23818f4` | 16 passed |
| `3b888b2`: unexpected fields accepted with 200 | `c609b3b` | 17 passed |
| `ebe301f`: eleventh request accepted with 200 | `6d6b2ca` | 36 passed |
| `92e91fd`: no security log events emitted | `6aa87dc` | 19 passed |
| `2facfd9`: stale revoked role accepted | `e7f87ed` | 35 passed |

Supplemental disabled/deleted-account and token-rollback cases exercise the
last protection without claiming additional RED cycles. Strict typing required
an explicit cast for the third-party serializer return type and concrete
throttle-type assertions; neither changes runtime behavior.

Final focused run: **245 tests passed** across authentication, bank, Nasabah,
multi-role scoping, architecture, and identity regressions. Ruff lint/format,
strict mypy (273 source files), and migration drift checks pass.

Final full-suite run with a temporary explicit test secret: **1,128 tests**
in 219 seconds, with **6 failures, 10 errors, and 10 skips**. The failing test
names exactly match the unchanged PIL-251 Windows baseline described above;
no new failing test names were introduced by these protections. All 19
switch-role tests pass. Linux CI remains necessary for a full green gate.
