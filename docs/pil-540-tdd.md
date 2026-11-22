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
