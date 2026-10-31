# PIL-442 customer-list security boundaries

This is a feature-scoped hardening record against [OWASP Top 10:2025](https://top10.owasp.org/2025/), not a claim that all PILAH application or deployment risks have been eliminated. The feature also uses the resource-consumption guidance in [OWASP API4:2023](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/).

## Request and response contract

- The existing JWT authentication, active Pengurus permission, and server-derived bank scope remain mandatory. A client-supplied bank identifier never changes that scope. Another bank's customer detail returns 404.
- `status` accepts `aktif`, `tidak_aktif`, `menunggu`, `ditolak`, and the existing explicit `semua` choice. Unknown status values return 422 instead of accidentally removing the status filter.
- `search` accepts at most 254 characters. It retains the existing rule that searches shorter than two characters are ignored. Null characters are rejected by serializer validation. `%`, `_`, and quotes remain literal search values through the parameterized ORM.
- `urutan` accepts at most 64 characters. Supported orders are `nomor`, `nama`, `terbaru`, `saldo_terbesar`, and `saldo_terkecil`. Empty or unknown values within that length safely fall back to `nomor`. The sort columns come from the fixed server map, never directly from caller text.
- Repeated `search`, `status`, `urutan`, `page`, or `page_size` parameters return 422. This avoids disagreement between components that choose the first or last repeated value.
- The existing pagination cap remains 100 customers per response. DRF's existing invalid-page handling remains in place; this change does not invent another pagination format.
- `NASABAH_LIST_RATE` defaults to `120/min`. Requests by the same user share the budget even when search, status, order, or page changes. List requests use the existing database-backed cache so the budget is shared across workers. Other customer actions retain their existing throttle behavior.
- Rate exhaustion returns 429 with `Retry-After`. DRF cache-based throttles are non-atomic and approximate; they are an overuse budget, not a DDoS/security boundary. Configure strict concurrent, IP, and volumetric limits at the edge/WAF as appropriate.
- Customer ViewSet responses, including authentication/permission/validation/throttle failures, carry `Cache-Control: private, no-store, max-age=0` and `Vary: Authorization`.
- List database failures, including authentication or shared throttle-cache database failures before the list method runs, return a generic retryable 503. SQL, credentials, and exception text are not sent to the caller. Other programming errors are not silently swallowed by a blanket exception handler.

## OWASP mapping

| Category | Feature protection and verification | Boundary / remaining responsibility |
| --- | --- | --- |
| A01 Broken Access Control | Existing active-Pengurus permission, real JWT authentication and bank-scoped queries; regressions cover forbidden roles, incomplete profiles, inactive/pending banks, disabled users, ignored bank overrides and foreign detail 404. | No claim about unrelated application endpoints. |
| A02 Security Misconfiguration | New private/no-store headers apply on successes and handled failures. Existing production JSON renderer and CSP middleware remain in place. | Deployment owners must keep debug/fake tokens off, restrict allowed hosts/CORS origins and maintain proxy/header configuration. |
| A03 Software Supply Chain Failures | Requirements are pinned and the existing scheduled pipeline runs dependency/secret checks; feature changes add no dependency. | This change is not a fresh supply-chain audit. Maintain dependency scanning, trusted actions/images and signed release provenance. |
| A04 Cryptographic Failures | Existing signed JWT verification stays enabled; no secret or customer contents are added to feature audit records. Private responses are marked no-store. | TLS, certificate validation, signing-key rotation, database/back-up encryption and key management remain infrastructure responsibilities. |
| A05 Injection | Existing ORM parameterization and fixed ordering map retained; inputs are bounded, duplicate keys rejected, and hostile sort/search strings tested. | Tests do not establish absence of injection in unrelated code. |
| A06 Insecure Design | Search/order bounds, existing page cap, shared per-user overuse budget, and explicit rejection behavior. | Quotas must be tuned to real traffic; edge controls are still required against sustained/concurrent abuse. |
| A07 Authentication Failures | Tests use actual JWT processing for absent, invalid, expired and disabled-user tokens; existing permission checks also require current eligible bank membership. | Login/session lifecycle and real Google OAuth flows are unchanged by this feature. |
| A08 Software or Data Integrity Failures | Sorting/filtering is a read operation; caller query values cannot modify balances, bank ownership, or sort expressions. Existing CI and migration checks remain in use. | Repository/release protections, artifact integrity and broader business write paths require separate review. |
| A09 Security Logging and Alerting Failures | Rejected list requests emit a fixed event, numeric response status, and authenticated actor UUID when available through `apps.nasabah.security`. Tests ensure no token, search value, customer profile or database exception is included. | Configure collection, retention and alerts for these events. Platform/reverse-proxy access logs may independently include full URLs: redact query strings there, especially customer search terms. This feature does not reconfigure the deployment's logging platform. |
| A10 Mishandling of Exceptional Conditions | Validation precedes the customer query; quota/cache/authentication/customer-query failures have explicit safe responses; database/cache outages fail closed instead of serving cached customer rows. | Application-wide error recovery and infrastructure availability remain outside this feature's scope. |

## TDD evidence and commands

The security RED commit introduced 11 endpoint tests and produced 20 failing assertions/subtests plus one database-failure error before implementation. GREEN adds the missing controls and extends coverage with pre-list cache/auth database failures and OpenAPI constraints. There are now 13 security tests, plus the 11 original ordering tests.

```text
python manage.py test apps.nasabah.test_list_security apps.nasabah.test_ordering
python manage.py test
ruff check .
ruff format --check .
mypy api apps config shared_kernel tests
python manage.py check
python manage.py makemigrations --check --dry-run
```

Use the application's supported local virtual environment. Tests run against their own test database, never the running seeded demo database. Authentication, bank isolation, cache headers, bounds, parameter pollution, SQL-literal handling, per-user quotas, retry headers, sanitized audit events, safe database failures and published OpenAPI constraints are all checked through the endpoint boundary.
