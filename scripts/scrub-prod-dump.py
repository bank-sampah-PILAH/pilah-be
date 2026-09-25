"""Scrub a pg_dump of prod into an anonymized migration-test fixture.

Usage:
    python3 scripts/scrub-prod-dump.py pilah-prod-<ts>.sql.gz db/fixtures/prod-anonymized.sql.gz

Only the COPY data blocks of sensitive tables are rewritten; DDL, constraints
and all other tables pass through byte-identical so the fixture still sits at
prod's real migration state. Fakes are deterministic (row ordinal based), so
re-runs diff cleanly.

Refresh runbook: when prod drifts past the fixture's django_migrations state,
take a fresh dump locally and re-run this script. The raw dump is gitignored
and must never be committed. The migration-prod workflow fails loudly if the
fixture goes stale.

Fail-closed: unknown columns in sensitive tables or malformed rows abort
instead of passing data through. New PII columns cannot silently leak.
"""

import argparse
import gzip
import re
import sys

COPY_RE = re.compile(r"^COPY public\.(\w+) \(([^)]+)\) FROM stdin;$")
NULL = "\\N"
# Cloud SQL artifacts that break restores on vanilla Postgres with
# ON_ERROR_STOP=1 (CI restores with no such roles present).
OWNER_RE = re.compile(r"^(?:GRANT|REVOKE)\b.*\bcloudsqlsuperuser\b|ALTER\b.*\bOWNER TO\b")

# Tables whose rows are dropped entirely (live secrets, zero migration signal).
TRUNCATE = {
    "django_session",
    "token_blacklist_outstandingtoken",
    "token_blacklist_blacklistedtoken",
}


def _unless_blank(make):
    """Rewrite only real values; keep NULLs and empty strings as they are."""

    def inner(n, value):
        return value if value in (NULL, "") else make(n, value)

    return inner


# ponytail: per-column lambdas; a mapping table is clearer than a class here.
SCRUB = {
    "users": {
        "password": lambda n, v: "!",  # Django unusable-password marker
        "last_login": lambda n, v: NULL,
        "google_id": _unless_blank(lambda n, v: f"anon-google-{n:02d}"),
        "email": lambda n, v: f"user{n:02d}@example.invalid",
        "nama": _unless_blank(lambda n, v: f"Pengguna Anonim {n}"),
        "no_hp": _unless_blank(lambda n, v: f"+628000000{n:02d}"),
        # Quasi-identifiers: real values must not survive, but null-ness is
        # kept so migrations touching these columns still see both shapes.
        "jenis_kelamin": _unless_blank(lambda n, v: "laki-laki" if n % 2 else "perempuan"),
        "tanggal_lahir": _unless_blank(lambda n, v: f"1990-01-{n:02d}"),
    },
    "bank_sampah": {
        "nama": lambda n, v: f"Bank Sampah Anonim {n}",
        "alamat": _unless_blank(lambda n, v: f"Jl. Contoh No. {n}"),
        "no_hp_pic": _unless_blank(lambda n, v: f"+6281000000{n}"),
        "wa_gateway_token": _unless_blank(lambda n, v: f"ANON-WA-TOKEN-{n}"),
        "invite_token": _unless_blank(lambda n, v: f"anon-invite-{n}"),
        # Storage paths may embed original names; media does not exist in CI.
        "foto_logo": lambda n, v: "",
        "foto_kegiatan": lambda n, v: "",
    },
}

# Columns verified to carry no PII or secrets. Any column outside SCRUB and
# SAFE aborts the run — new columns fail closed instead of passing through.
SAFE = {
    "users": {
        "is_superuser",
        "created_at",
        "updated_at",
        "id",
        "role",
        "is_profile_complete",
        "is_active",
        "is_staff",
        "bank_sampah_id",
        "is_primary_pengelola",
    },
    "bank_sampah": {
        "created_at",
        "updated_at",
        "id",
        "kota",  # city granularity, not identifying
        "wa_template",  # message-template config, not PII
        "status",
        "invite_token_expires",
        "is_active",
    },
}

# Low-cardinality fakes reuse the same words as real values, so absence
# checking cannot distinguish them; the DOB allowlist check below covers
# those columns instead.
UNTRACKED = {"jenis_kelamin"}

# wa_template passes through: message-template config, not PII.
# kota passes through: city name, not PII. Timestamps/IDs/FKs are preserved
# as-is to keep referential shape and migration edge cases intact.


def fail(message):
    print(f"scrub-prod-dump: error: {message}", file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser(description="Anonymize a prod pg_dump for migration tests.")
    parser.add_argument("input", help="raw prod dump (.sql.gz), never committed")
    parser.add_argument("output", help="anonymized fixture to write (.sql.gz)")
    args = parser.parse_args()

    opener = gzip.open if args.input.endswith(".gz") else open
    with opener(args.input, "rt", encoding="utf-8") as f:
        lines = f.read().splitlines()

    out = []
    counts_in = {}
    counts_out = {}
    ordinals = {}
    originals = set()
    current = None
    columns = []
    skipping = None

    for line in lines:
        if OWNER_RE.match(line):
            continue
        if skipping is not None:
            if line == "\\.":
                skipping = None
            else:
                counts_in[skipping] += 1
            continue
        match = COPY_RE.match(line)
        if match:
            table = match.group(1)
            columns = [c.strip() for c in match.group(2).split(",")]
            current = table
            counts_in.setdefault(table, 0)
            counts_out.setdefault(table, 0)
            ordinals.setdefault(table, 0)
            out.append(line)
            if table in TRUNCATE:
                out.append("\\.")
                skipping = table
                current = None
            elif table in SCRUB:
                missing = [c for c in SCRUB[table] if c not in columns]
                if missing:
                    return fail(f"header for {table} missing columns: {missing}")
                unknown = [c for c in columns if c not in SCRUB[table] and c not in SAFE[table]]
                if unknown:
                    return fail(
                        f"header for {table} has unclassified columns: {unknown} "
                        "(refusing to pass through)"
                    )
            continue
        if current is not None:
            if line == "\\.":
                current = None
                out.append(line)
                continue
            table = current
            counts_in[table] += 1
            if table in SCRUB:
                ordinals[table] += 1
                n = ordinals[table]
                fields = line.split("\t")
                if len(fields) != len(columns):
                    return fail(f"{table} row has {len(fields)} fields, expected {len(columns)}")
                index = {c: i for i, c in enumerate(columns)}
                for col, make in SCRUB[table].items():
                    old = fields[index[col]]
                    new = make(n, old)
                    if new != old and old not in (NULL, "") and col not in UNTRACKED:
                        originals.add(old)
                    fields[index[col]] = new
                line = "\t".join(fields)
            counts_out[table] += 1
            out.append(line)
        else:
            out.append(line)

    text = "\n".join(out) + "\n"

    for table, total in counts_in.items():
        if table in TRUNCATE:
            if counts_out[table] != 0:
                return fail(f"{table} should be truncated")
        elif counts_out[table] != total:
            return fail(f"{table} row count changed {total} -> {counts_out[table]}")
    leaked = [v for v in originals if v and v in text]
    if leaked:
        return fail(f"{len(leaked)} original value(s) survived scrubbing")
    for email in set(re.findall(r"\S+@\S+", text)):
        if not email.endswith("@example.invalid"):
            return fail(f"non-anonymized email in output: {email[:40]}")
    for phone in set(re.findall(r"\+62\d+", text)):
        if not (phone.startswith("+628000000") or phone.startswith("+6281000000")):
            return fail(f"non-anonymized phone in output: {phone[:20]}")
    # DOB fakes share no vocabulary with real values to check by absence
    # (any YYYY-MM-DD could theoretically collide), so assert positively:
    # every emitted birth date is one the script itself generated.
    users_block = re.search(
        r"^COPY public\.users \(([^)]+)\) FROM stdin;\n(.*?)^\\\.$",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if users_block and "tanggal_lahir" in SCRUB["users"]:
        header = [c.strip() for c in users_block.group(1).split(",")]
        dob_idx = header.index("tanggal_lahir")
        for row in users_block.group(2).splitlines():
            dob = row.split("\t")[dob_idx]
            if dob != NULL and not re.fullmatch(r"1990-01-\d{2}", dob):
                return fail("non-anonymized birth date in output")
    for marker in ("eyJ", ".eJx"):
        if marker in text:
            return fail(f"token/session blob marker in output: {marker}")

    opener = gzip.open if args.output.endswith(".gz") else open
    with opener(args.output, "wt", encoding="utf-8") as f:
        f.write(text)

    for table in sorted(counts_in):
        print(f"{table}: {counts_in[table]} -> {counts_out[table]}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
