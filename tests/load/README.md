# Staging concurrency checks for PIL-443, PIL-444 and PIL-445

Subissues: [PIL-443](https://linear.app/pilah-2/issue/PIL-443) (baseline),
[PIL-444](https://linear.app/pilah-2/issue/PIL-444) (realistic load),
[PIL-445](https://linear.app/pilah-2/issue/PIL-445) (bursts),
[PIL-446](https://linear.app/pilah-2/issue/PIL-446) (actual clients), and
[PIL-447](https://linear.app/pilah-2/issue/PIL-447) (results).

Execution findings: [25–26 October 2026 evidence](https://linear.app/pilah-2/document/pil-393-staging-load-test-evidence-7086e4575a96).
The 10- and 20-user tiers missed customer-list, picker and Pengurus-history
targets. The first 30-user run stopped after a 15s history timeout; a full retry
completed without HTTP failures but again missed those three read targets
(p95 1.396s, 5.849s and 1.509s). Its row-level balance audit passed, but k6's
131 acknowledged writes did not match 132 database rows. Do not treat that run
as reconciled or repeat higher load until the mismatch and slow reads are
investigated in [PIL-448](https://linear.app/pilah-2/issue/PIL-448).

A virtual user repeatedly uses a session, including reading and typing pauses.
This is a closed workload: slower responses reduce completed work per minute.
Always compare throughput with latency. These are active users, not requests/sec.

| Total users | Pengurus | Nasabah |
|---|---|---|
| 10 | 7 | 3 |
| 20 | 14 | 6 |
| 30 | 21 | 9 |

## Prepare an isolated dataset

Use Python/backend dependencies, k6 **2.3.0**, and authenticated `flyctl`.
Download k6 from Grafana's official GitHub release and verify its release checksum.
Run the commands below from the backend repository. Use a fresh lowercase run ID.

The command refuses production, allows only local development or staging's Neon
database, creates a dedicated named bank, and never invokes global reset/flush.
It creates 21 Pengurus accounts, 9 Nasabah accounts, 1,000 memberships, and
10,000 historical setoran. The first nine memberships belong to Nasabah users.
Each baseline transaction is 1 kg at Rp 2,500, yielding Rp 25,000 per membership.
Historical prices are seeded through the existing price service.

On a normal deployment the management command ships with the backend. For an
unmerged validation run, warm `/healthz`, then upload only the management helper for initial seeding:

```bash
curl --fail https://pilah-be-staging.fly.dev/healthz
flyctl ssh sftp put --app pilah-be-staging api/management/commands/load_test_data.py /app/api/management/commands/load_test_data.py
flyctl ssh console --app pilah-be-staging -C 'python manage.py load_test_data seed --run-id=example-run --confirm=PIL-393-STAGING-ONLY --manifest=/tmp/pil393-accounts.json'
```

Confirm the staging DB host is distinct from production before seeding. Production
currently uses Cloud SQL; Fly staging uses Neon. Do not change either deployment's
capacity before measuring its baseline. Avoid concurrent deployments or UAT writes
to the synthetic bank. Unmerged helpers uploaded to a VM can disappear on stop/restart. The runner sends
its own local fixture and monitor source through SSH for reset/audit/telemetry, so
those actions survive restarts and use the checksummed source being tested. It
does not change deployment capacity or require a public testing endpoint.

The remote manifest is owner-only and contains passwords. Download it into a
private directory outside all repositories, then authenticate real sessions:

```bash
mkdir -m 700 /tmp/pil393-private
flyctl ssh sftp get --app pilah-be-staging /tmp/pil393-accounts.json /tmp/pil393-private/accounts.json
chmod 600 /tmp/pil393-private/accounts.json
python tests/load/run.py auth --accounts /tmp/pil393-private/accounts.json --run-id example-run --output /tmp/pil393-results
```

Authentication uses a 16-second pause and can resume from the saved tokens after
interruption. Do not authenticate twice concurrently. A 429 is a rate-limit result,
not proof of overload; investigate before retrying. Never enable fake Google tokens,
change the rate limit, or generate load against Google's login endpoints.

## Run and interpret

Pass the same account/run/output arguments for every action:

```bash
python tests/load/run.py smoke --accounts /tmp/pil393-private/accounts.json --run-id example-run --output /tmp/pil393-results
python tests/load/run.py matrix --accounts /tmp/pil393-private/accounts.json --run-id example-run --output /tmp/pil393-results
python tests/load/run.py burst --accounts /tmp/pil393-private/accounts.json --run-id example-run --output /tmp/pil393-results
```

Each trial first warms the read paths; these HTTP samples are tagged `warmup` and
excluded from latency thresholds. First-use/startup timings are separate evidence.
Every required measured action must have at least one sample; an empty percentile
cannot produce a passing result.

`smoke` measures one Pengurus and one Nasabah separately for one minute each.
`matrix` runs 10, 20, then 30 users twice each: a one-minute ramp and five minutes
steady, followed by a graceful stop. Ordinary pauses are 3–8 seconds; preparing a
setoran takes 15–30 seconds. One existing Pengurus VU measures permitted logins.
`burst` releases Pengurus saves at one common timestamp while Nasabah read. Both
separate-recipient and shared-recipient cases run three times per level. A latency-only
threshold failure still permits those bounded repetitions at the same level; it
blocks higher levels. Script, HTTP/business or integrity faults stop immediately. Actual
release offsets are recorded; this does not promise perfectly simultaneous arrivals.

Each trial resets only the fixture's transactions/balances, retaining users and
sessions. Output folders must be new, preventing accidental result overwrites.
Use `--users 10` (or 20/30) to repeat an investigated level in a new output directory.
No notification delivery endpoint is called. HTTP redirects are disabled.

Thresholds apply per action to the steady period: reads p95 ≤1 second; setoran and
login p95 ≤2 seconds; unexpected failures <1%; integrity faults zero. All HTTP or
business failures abort the current trial conservatively. Investigate before
escalating. A failed or untested level must never be reported as passing. Baseline
and burst percentiles with few samples are diagnostic, not strong statistical claims.

The post-run audit verifies persisted write counts against acknowledged creates,
item totals, balances, scope, and idempotency. Never reset after an integrity failure
until its evidence has been preserved. The audit fails closed; no result is a pass
without a successful audit. Reset/cleanup refuse unexpected users or memberships.

Each folder contains raw tagged samples, k6 summary/exit status, reconciliation,
source checksums, deployment snapshots, and CPU/memory/DB telemetry. Ramp, steady,
and drain samples are tagged separately. Count/minute for completed journeys is
steady journey count divided by five; requests/sec uses steady request count divided
by 300. Report p50/p95/p99 and sample counts per action. Do not pool trials.

The runner records host load averages alongside its logical CPU count to help
identify generator saturation. Record physical runner location/network separately;
its operating system/timezone does not establish its network region.

The staging monitor reads guest CPU/memory and PostgreSQL connections/lock waits
at 15-second intervals. A short lock may occur between samples. Missing/empty
telemetry is unavailable evidence, never zero utilization. Before/after Machine
configuration/events help identify restarts; snapshots alone are not CPU usage.
The monitor exits within seven minutes even if its SSH connection is interrupted.

## Actual client probes

Use **playwright-cli** for Pengurus web and **agent-device** for native Pengurus
and Nasabah. Native needs a matching staging Android build/device; responsive web
emulation does not verify native behavior. Nasabah web is unsupported.

```bash
python tests/load/run.py probe --users 10 --probe-role pengelola --probe-writes 1 --accounts /tmp/pil393-private/accounts.json --run-id example-run --output /tmp/pil393-probe-web
```

This reserves the last selected account of that role for the real client: Pengurus
index 6/13/20 or Nasabah index 23/26/29 in the manifest, for 10/20/30 respectively.
Run one actual client at a time. During the steady period, measure from click/tap to
visible data or saved confirmation for search, setoran, jadwal and riwayat; Nasabah
checks balance, jadwal and personal riwayat. Use 1 kg of the fixture waste type.
Stop at saved confirmation; do not send a WhatsApp receipt. Declare the expected actual-client
write count with `--probe-writes` (one in this example); Nasabah read-only probes use
zero. The runner adds it to acknowledged k6 creates when auditing persisted counts.

Record client build/revision, device/emulator and OS, viewport/browser, network,
runner location, UTC start/end, individual timings, and errors. Target ≤3 seconds
per observed action. A few samples do not establish client p95. Retain synthetic-only
screenshots/recordings and review usability with Tristan before closing PIL-446.

## Report and clean up

PIL-447's report should include each level and repeat, role mix, dataset, thresholds,
per-action samples/latency/failures, throughput, integrity, telemetry, actual-client
observations and evidence paths. Identify the highest passing level separately for
realistic activity and bursts. Link measured bottlenecks to fixes or follow-ups and
repeat affected tests. Note cold starts separately from warm capacity. Never infer
production capacity or capacity above 30 from these runs.

After preserving the evidence and completing all probes:

```bash
python tests/load/run.py audit --accounts /tmp/pil393-private/accounts.json --run-id example-run --output /tmp/pil393-results
python tests/load/run.py cleanup --accounts /tmp/pil393-private/accounts.json --run-id example-run --output /tmp/pil393-results
```

Remove the private manifests and test browser/device sessions after cleanup. Do not
commit credentials, raw artifacts, local databases, or temporary helper uploads.
For local validation, set DJANGO_DEBUG=true, PILAH_ENVIRONMENT=local and a disposable DB;
run the harness with that environment's Python interpreter and use the loopback API
URL. Local fixture actions use the same Python interpreter as the harness.

The representative Pengurus journey includes the real active-customer picker request
(`status=aktif&page_size=100`) and calendar dates. Dashboard bootstrap requests are
observed in actual-client probes, rather than repeated on every virtual journey.
Idempotency replay timings are tagged separately from new setoran creation.
