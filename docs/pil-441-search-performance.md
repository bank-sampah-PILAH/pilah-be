# PIL-441 search performance review

The search keeps case-insensitive substring matching across name, customer ID, phone, and email. Numeric text can appear in a name and alphabetic text can appear in an email, so query-shape routing would change existing behavior. Surrounding whitespace is trimmed before the two-character gate. Normalized searches longer than 100 characters return HTTP 422 with a search-field error; exactly 100 characters remains supported.

## PostgreSQL indexes

Migration `0028_nasabah_search_trigrams` adds `pg_trgm` and four GIN expression indexes on `UPPER(column::text)`, matching Django PostgreSQL `icontains`. It intentionally changes physical PostgreSQL indexes only; SQLite remains supported without PostgreSQL opclasses in model state. The migration is reversible, but leaves the potentially shared extension installed. `0029_merge_search_and_transaksi` joins the current staging migration branch.

Deployment runs `python manage.py check_search_prerequisites` before `migrate`. This check is read-only and fails early if pg_trgm is missing. Before deploying, a database owner or another authorized role must run `python manage.py check_search_prerequisites --install-extension` against each target database. No production role or table size has been inspected by this change. PostgreSQL documents pg_trgm as trusted, so installation privileges depend on the database and managed-provider configuration; do not assume every application role can install it.

The migration uses `atomic = False` and `CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY`. Concurrent builds permit customer writes but can wait for old transactions and still consume CPU, I/O, and storage. Do not put the migration inside an external transaction. If an unapplied build fails partway, inspect `pg_indexes` and `pg_index.indisvalid`; remove only this migration's partial indexes concurrently after checking their definitions, then rerun the migration. Never drop the shared extension during rollback.

The migration's `CREATE EXTENSION IF NOT EXISTS` is retained so Django can provision disposable test databases. In the deployment path the prerequisite check ensures the extension is already installed before migrations run. CI explicitly bootstraps its disposable database before applying migrations.

The two-character minimum is preserved for compatibility. Terms without an extractable trigram, including many two-character queries, can still scan. Pagination still executes a filtered count and a page query; cancelling the frontend HTTP request does not guarantee cancellation of an already executing Django/PostgreSQL query.

## Local EXPLAIN measurements

Measured with PostgreSQL 18 on Windows using one synthetic bank, first 102 and then 10,000 fictional rows. Production CI uses PostgreSQL 16, so these numbers are local evidence, not production predictions. Both COUNT and the first 20 rows use `EXPLAIN (ANALYZE, BUFFERS)`. Statistics were refreshed with ANALYZE. Single runs are illustrative and include cache effects; the planner may rightly choose a sequential scan for small or unselective sets.

| Rows | Search | Matches | Count before ms | Count after ms | Page before ms | Page after ms |
|---:|---|---:|---:|---:|---:|---:|
| 102 | `0012` | 1 | 0.106 | 0.112 | 0.191 | 0.16 |
| 102 | `12` | 102 | 0.191 | 0.212 | 0.088 | 0.168 |
| 102 | `00000123` | 0 | 0.131 | 0.134 | 0.122 | 0.166 |
| 10000 | `0012` | 111 | 7.245 | 0.106 | 0.888 | 1.646 |
| 10000 | `12` | 10000 | 6.497 | 5.096 | 0.064 | 0.087 |
| 10000 | `00000123` | 11 | 6.437 | 0.431 | 6.729 | 0.22 |

For `0012` at 10,000 rows the count improved, while the page query was slightly slower in this sample. No claim is made that every query is faster. The two-character `12` matches every synthetic phone number and remains a scan-heavy case.

## Requested 102-row query plans

Below are the actual JSON plans for `status=aktif&search=0012`, before and after indexes, including buffer and timing information.

### Before indexes count plan

```json
{
  "Plan": {
    "Node Type": "Aggregate",
    "Strategy": "Plain",
    "Partial Mode": "Simple",
    "Parallel Aware": false,
    "Async Capable": false,
    "Startup Cost": 6.58,
    "Total Cost": 6.59,
    "Plan Rows": 1,
    "Plan Width": 8,
    "Actual Startup Time": 0.096,
    "Actual Total Time": 0.096,
    "Actual Rows": 1.0,
    "Actual Loops": 1,
    "Disabled": false,
    "Shared Hit Blocks": 3,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0,
    "Plans": [
      {
        "Node Type": "Seq Scan",
        "Parent Relationship": "Outer",
        "Parallel Aware": false,
        "Async Capable": false,
        "Relation Name": "nasabah",
        "Alias": "nasabah",
        "Startup Cost": 0.0,
        "Total Cost": 6.57,
        "Plan Rows": 3,
        "Plan Width": 0,
        "Actual Startup Time": 0.019,
        "Actual Total Time": 0.094,
        "Actual Rows": 1.0,
        "Actual Loops": 1,
        "Disabled": false,
        "Filter": "(is_active AND (bank_sampah_id = 'd6f80793-89c9-4baf-a231-76c8ab3971d5'::uuid) AND ((status)::text = 'approved'::text) AND ((upper((nama)::text) ~~ '%0012%'::text) OR (upper((nomor)::text) ~~ '%0012%'::text) OR (upper((no_hp)::text) ~~ '%0012%'::text) OR (upper((email)::text) ~~ '%0012%'::text)))",
        "Rows Removed by Filter": 101,
        "Shared Hit Blocks": 3,
        "Shared Read Blocks": 0,
        "Shared Dirtied Blocks": 0,
        "Shared Written Blocks": 0,
        "Local Hit Blocks": 0,
        "Local Read Blocks": 0,
        "Local Dirtied Blocks": 0,
        "Local Written Blocks": 0,
        "Temp Read Blocks": 0,
        "Temp Written Blocks": 0
      }
    ]
  },
  "Planning": {
    "Shared Hit Blocks": 1,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0
  },
  "Planning Time": 0.103,
  "Triggers": [],
  "Execution Time": 0.106
}
```

### Before indexes page plan

```json
{
  "Plan": {
    "Node Type": "Limit",
    "Parallel Aware": false,
    "Async Capable": false,
    "Startup Cost": 23.76,
    "Total Cost": 23.81,
    "Plan Rows": 20,
    "Plan Width": 236,
    "Actual Startup Time": 0.152,
    "Actual Total Time": 0.153,
    "Actual Rows": 1.0,
    "Actual Loops": 1,
    "Disabled": false,
    "Shared Hit Blocks": 5,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0,
    "Plans": [
      {
        "Node Type": "Sort",
        "Parent Relationship": "Outer",
        "Parallel Aware": false,
        "Async Capable": false,
        "Startup Cost": 23.76,
        "Total Cost": 23.83,
        "Plan Rows": 28,
        "Plan Width": 236,
        "Actual Startup Time": 0.151,
        "Actual Total Time": 0.152,
        "Actual Rows": 1.0,
        "Actual Loops": 1,
        "Disabled": false,
        "Sort Key": [
          "nasabah.nomor"
        ],
        "Sort Method": "quicksort",
        "Sort Space Used": 25,
        "Sort Space Type": "Memory",
        "Shared Hit Blocks": 5,
        "Shared Read Blocks": 0,
        "Shared Dirtied Blocks": 0,
        "Shared Written Blocks": 0,
        "Local Hit Blocks": 0,
        "Local Read Blocks": 0,
        "Local Dirtied Blocks": 0,
        "Local Written Blocks": 0,
        "Temp Read Blocks": 0,
        "Temp Written Blocks": 0,
        "Plans": [
          {
            "Node Type": "Nested Loop",
            "Parent Relationship": "Outer",
            "Parallel Aware": false,
            "Async Capable": false,
            "Join Type": "Left",
            "Startup Cost": 0.15,
            "Total Cost": 23.08,
            "Plan Rows": 28,
            "Plan Width": 236,
            "Actual Startup Time": 0.037,
            "Actual Total Time": 0.134,
            "Actual Rows": 1.0,
            "Actual Loops": 1,
            "Disabled": false,
            "Inner Unique": true,
            "Shared Hit Blocks": 5,
            "Shared Read Blocks": 0,
            "Shared Dirtied Blocks": 0,
            "Shared Written Blocks": 0,
            "Local Hit Blocks": 0,
            "Local Read Blocks": 0,
            "Local Dirtied Blocks": 0,
            "Local Written Blocks": 0,
            "Temp Read Blocks": 0,
            "Temp Written Blocks": 0,
            "Plans": [
              {
                "Node Type": "Seq Scan",
                "Parent Relationship": "Outer",
                "Parallel Aware": false,
                "Async Capable": false,
                "Relation Name": "nasabah",
                "Alias": "nasabah",
                "Startup Cost": 0.0,
                "Total Cost": 6.57,
                "Plan Rows": 3,
                "Plan Width": 178,
                "Actual Startup Time": 0.03,
                "Actual Total Time": 0.127,
                "Actual Rows": 1.0,
                "Actual Loops": 1,
                "Disabled": false,
                "Filter": "(is_active AND (bank_sampah_id = 'd6f80793-89c9-4baf-a231-76c8ab3971d5'::uuid) AND ((status)::text = 'approved'::text) AND ((upper((nama)::text) ~~ '%0012%'::text) OR (upper((nomor)::text) ~~ '%0012%'::text) OR (upper((no_hp)::text) ~~ '%0012%'::text) OR (upper((email)::text) ~~ '%0012%'::text)))",
                "Rows Removed by Filter": 101,
                "Shared Hit Blocks": 3,
                "Shared Read Blocks": 0,
                "Shared Dirtied Blocks": 0,
                "Shared Written Blocks": 0,
                "Local Hit Blocks": 0,
                "Local Read Blocks": 0,
                "Local Dirtied Blocks": 0,
                "Local Written Blocks": 0,
                "Temp Read Blocks": 0,
                "Temp Written Blocks": 0
              },
              {
                "Node Type": "Index Scan",
                "Parent Relationship": "Inner",
                "Parallel Aware": false,
                "Async Capable": false,
                "Scan Direction": "Forward",
                "Index Name": "saldo_nasabah_id_key",
                "Relation Name": "saldo",
                "Alias": "saldo",
                "Startup Cost": 0.15,
                "Total Cost": 5.5,
                "Plan Rows": 1,
                "Plan Width": 58,
                "Actual Startup Time": 0.005,
                "Actual Total Time": 0.005,
                "Actual Rows": 0.0,
                "Actual Loops": 1,
                "Disabled": false,
                "Index Cond": "(nasabah_id = nasabah.id)",
                "Rows Removed by Index Recheck": 0,
                "Index Searches": 1,
                "Shared Hit Blocks": 2,
                "Shared Read Blocks": 0,
                "Shared Dirtied Blocks": 0,
                "Shared Written Blocks": 0,
                "Local Hit Blocks": 0,
                "Local Read Blocks": 0,
                "Local Dirtied Blocks": 0,
                "Local Written Blocks": 0,
                "Temp Read Blocks": 0,
                "Temp Written Blocks": 0
              }
            ]
          }
        ]
      }
    ]
  },
  "Planning": {
    "Shared Hit Blocks": 132,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0
  },
  "Planning Time": 1.797,
  "Triggers": [],
  "Execution Time": 0.191
}
```

### After indexes count plan

```json
{
  "Plan": {
    "Node Type": "Aggregate",
    "Strategy": "Plain",
    "Partial Mode": "Simple",
    "Parallel Aware": false,
    "Async Capable": false,
    "Startup Cost": 6.58,
    "Total Cost": 6.58,
    "Plan Rows": 1,
    "Plan Width": 8,
    "Actual Startup Time": 0.099,
    "Actual Total Time": 0.1,
    "Actual Rows": 1.0,
    "Actual Loops": 1,
    "Disabled": false,
    "Shared Hit Blocks": 3,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0,
    "Plans": [
      {
        "Node Type": "Seq Scan",
        "Parent Relationship": "Outer",
        "Parallel Aware": false,
        "Async Capable": false,
        "Relation Name": "nasabah",
        "Alias": "nasabah",
        "Startup Cost": 0.0,
        "Total Cost": 6.57,
        "Plan Rows": 2,
        "Plan Width": 0,
        "Actual Startup Time": 0.021,
        "Actual Total Time": 0.097,
        "Actual Rows": 1.0,
        "Actual Loops": 1,
        "Disabled": false,
        "Filter": "(is_active AND (bank_sampah_id = 'd6f80793-89c9-4baf-a231-76c8ab3971d5'::uuid) AND ((status)::text = 'approved'::text) AND ((upper((nama)::text) ~~ '%0012%'::text) OR (upper((nomor)::text) ~~ '%0012%'::text) OR (upper((no_hp)::text) ~~ '%0012%'::text) OR (upper((email)::text) ~~ '%0012%'::text)))",
        "Rows Removed by Filter": 101,
        "Shared Hit Blocks": 3,
        "Shared Read Blocks": 0,
        "Shared Dirtied Blocks": 0,
        "Shared Written Blocks": 0,
        "Local Hit Blocks": 0,
        "Local Read Blocks": 0,
        "Local Dirtied Blocks": 0,
        "Local Written Blocks": 0,
        "Temp Read Blocks": 0,
        "Temp Written Blocks": 0
      }
    ]
  },
  "Planning": {
    "Shared Hit Blocks": 5,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0
  },
  "Planning Time": 0.201,
  "Triggers": [],
  "Execution Time": 0.112
}
```

### After indexes page plan

```json
{
  "Plan": {
    "Node Type": "Limit",
    "Parallel Aware": false,
    "Async Capable": false,
    "Startup Cost": 19.29,
    "Total Cost": 19.34,
    "Plan Rows": 18,
    "Plan Width": 236,
    "Actual Startup Time": 0.126,
    "Actual Total Time": 0.126,
    "Actual Rows": 1.0,
    "Actual Loops": 1,
    "Disabled": false,
    "Shared Hit Blocks": 5,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0,
    "Plans": [
      {
        "Node Type": "Sort",
        "Parent Relationship": "Outer",
        "Parallel Aware": false,
        "Async Capable": false,
        "Startup Cost": 19.29,
        "Total Cost": 19.34,
        "Plan Rows": 18,
        "Plan Width": 236,
        "Actual Startup Time": 0.125,
        "Actual Total Time": 0.126,
        "Actual Rows": 1.0,
        "Actual Loops": 1,
        "Disabled": false,
        "Sort Key": [
          "nasabah.nomor"
        ],
        "Sort Method": "quicksort",
        "Sort Space Used": 25,
        "Sort Space Type": "Memory",
        "Shared Hit Blocks": 5,
        "Shared Read Blocks": 0,
        "Shared Dirtied Blocks": 0,
        "Shared Written Blocks": 0,
        "Local Hit Blocks": 0,
        "Local Read Blocks": 0,
        "Local Dirtied Blocks": 0,
        "Local Written Blocks": 0,
        "Temp Read Blocks": 0,
        "Temp Written Blocks": 0,
        "Plans": [
          {
            "Node Type": "Nested Loop",
            "Parent Relationship": "Outer",
            "Parallel Aware": false,
            "Async Capable": false,
            "Join Type": "Left",
            "Startup Cost": 0.15,
            "Total Cost": 18.92,
            "Plan Rows": 18,
            "Plan Width": 236,
            "Actual Startup Time": 0.035,
            "Actual Total Time": 0.12,
            "Actual Rows": 1.0,
            "Actual Loops": 1,
            "Disabled": false,
            "Inner Unique": true,
            "Shared Hit Blocks": 5,
            "Shared Read Blocks": 0,
            "Shared Dirtied Blocks": 0,
            "Shared Written Blocks": 0,
            "Local Hit Blocks": 0,
            "Local Read Blocks": 0,
            "Local Dirtied Blocks": 0,
            "Local Written Blocks": 0,
            "Temp Read Blocks": 0,
            "Temp Written Blocks": 0,
            "Plans": [
              {
                "Node Type": "Seq Scan",
                "Parent Relationship": "Outer",
                "Parallel Aware": false,
                "Async Capable": false,
                "Relation Name": "nasabah",
                "Alias": "nasabah",
                "Startup Cost": 0.0,
                "Total Cost": 6.57,
                "Plan Rows": 2,
                "Plan Width": 178,
                "Actual Startup Time": 0.028,
                "Actual Total Time": 0.112,
                "Actual Rows": 1.0,
                "Actual Loops": 1,
                "Disabled": false,
                "Filter": "(is_active AND (bank_sampah_id = 'd6f80793-89c9-4baf-a231-76c8ab3971d5'::uuid) AND ((status)::text = 'approved'::text) AND ((upper((nama)::text) ~~ '%0012%'::text) OR (upper((nomor)::text) ~~ '%0012%'::text) OR (upper((no_hp)::text) ~~ '%0012%'::text) OR (upper((email)::text) ~~ '%0012%'::text)))",
                "Rows Removed by Filter": 101,
                "Shared Hit Blocks": 3,
                "Shared Read Blocks": 0,
                "Shared Dirtied Blocks": 0,
                "Shared Written Blocks": 0,
                "Local Hit Blocks": 0,
                "Local Read Blocks": 0,
                "Local Dirtied Blocks": 0,
                "Local Written Blocks": 0,
                "Temp Read Blocks": 0,
                "Temp Written Blocks": 0
              },
              {
                "Node Type": "Index Scan",
                "Parent Relationship": "Inner",
                "Parallel Aware": false,
                "Async Capable": false,
                "Scan Direction": "Forward",
                "Index Name": "saldo_nasabah_id_key",
                "Relation Name": "saldo",
                "Alias": "saldo",
                "Startup Cost": 0.15,
                "Total Cost": 6.17,
                "Plan Rows": 1,
                "Plan Width": 58,
                "Actual Startup Time": 0.005,
                "Actual Total Time": 0.005,
                "Actual Rows": 0.0,
                "Actual Loops": 1,
                "Disabled": false,
                "Index Cond": "(nasabah_id = nasabah.id)",
                "Rows Removed by Index Recheck": 0,
                "Index Searches": 1,
                "Shared Hit Blocks": 2,
                "Shared Read Blocks": 0,
                "Shared Dirtied Blocks": 0,
                "Shared Written Blocks": 0,
                "Local Hit Blocks": 0,
                "Local Read Blocks": 0,
                "Local Dirtied Blocks": 0,
                "Local Written Blocks": 0,
                "Temp Read Blocks": 0,
                "Temp Written Blocks": 0
              }
            ]
          }
        ]
      }
    ]
  },
  "Planning": {
    "Shared Hit Blocks": 75,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0
  },
  "Planning Time": 0.421,
  "Triggers": [],
  "Execution Time": 0.16
}
```

## Larger selective count plan

This plan shows actual index selection for the 10,000-row `0012` count; indexes are not forced.

```json
{
  "Plan": {
    "Node Type": "Aggregate",
    "Strategy": "Plain",
    "Partial Mode": "Simple",
    "Parallel Aware": false,
    "Async Capable": false,
    "Startup Cost": 343.54,
    "Total Cost": 343.55,
    "Plan Rows": 1,
    "Plan Width": 8,
    "Actual Startup Time": 0.091,
    "Actual Total Time": 0.092,
    "Actual Rows": 1.0,
    "Actual Loops": 1,
    "Disabled": false,
    "Shared Hit Blocks": 26,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0,
    "Plans": [
      {
        "Node Type": "Bitmap Heap Scan",
        "Parent Relationship": "Outer",
        "Parallel Aware": false,
        "Async Capable": false,
        "Relation Name": "nasabah",
        "Alias": "nasabah",
        "Startup Cost": 87.18,
        "Total Cost": 343.04,
        "Plan Rows": 203,
        "Plan Width": 0,
        "Actual Startup Time": 0.044,
        "Actual Total Time": 0.086,
        "Actual Rows": 111.0,
        "Actual Loops": 1,
        "Disabled": false,
        "Recheck Cond": "((upper((nama)::text) ~~ '%0012%'::text) OR (upper((nomor)::text) ~~ '%0012%'::text) OR (upper((no_hp)::text) ~~ '%0012%'::text) OR (upper((email)::text) ~~ '%0012%'::text))",
        "Rows Removed by Index Recheck": 1,
        "Filter": "(is_active AND (bank_sampah_id = 'd6f80793-89c9-4baf-a231-76c8ab3971d5'::uuid) AND ((status)::text = 'approved'::text))",
        "Rows Removed by Filter": 0,
        "Exact Heap Blocks": 6,
        "Lossy Heap Blocks": 0,
        "Shared Hit Blocks": 26,
        "Shared Read Blocks": 0,
        "Shared Dirtied Blocks": 0,
        "Shared Written Blocks": 0,
        "Local Hit Blocks": 0,
        "Local Read Blocks": 0,
        "Local Dirtied Blocks": 0,
        "Local Written Blocks": 0,
        "Temp Read Blocks": 0,
        "Temp Written Blocks": 0,
        "Plans": [
          {
            "Node Type": "BitmapOr",
            "Parent Relationship": "Outer",
            "Parallel Aware": false,
            "Async Capable": false,
            "Startup Cost": 87.18,
            "Total Cost": 87.18,
            "Plan Rows": 204,
            "Plan Width": 0,
            "Actual Startup Time": 0.032,
            "Actual Total Time": 0.032,
            "Actual Rows": 0.0,
            "Actual Loops": 1,
            "Disabled": false,
            "Shared Hit Blocks": 20,
            "Shared Read Blocks": 0,
            "Shared Dirtied Blocks": 0,
            "Shared Written Blocks": 0,
            "Local Hit Blocks": 0,
            "Local Read Blocks": 0,
            "Local Dirtied Blocks": 0,
            "Local Written Blocks": 0,
            "Temp Read Blocks": 0,
            "Temp Written Blocks": 0,
            "Plans": [
              {
                "Node Type": "Bitmap Index Scan",
                "Parent Relationship": "Member",
                "Parallel Aware": false,
                "Async Capable": false,
                "Index Name": "nasabah_nama_trgm_idx",
                "Startup Cost": 0.0,
                "Total Cost": 21.49,
                "Plan Rows": 1,
                "Plan Width": 0,
                "Actual Startup Time": 0.004,
                "Actual Total Time": 0.004,
                "Actual Rows": 0.0,
                "Actual Loops": 1,
                "Disabled": false,
                "Index Cond": "(upper((nama)::text) ~~ '%0012%'::text)",
                "Index Searches": 1,
                "Shared Hit Blocks": 5,
                "Shared Read Blocks": 0,
                "Shared Dirtied Blocks": 0,
                "Shared Written Blocks": 0,
                "Local Hit Blocks": 0,
                "Local Read Blocks": 0,
                "Local Dirtied Blocks": 0,
                "Local Written Blocks": 0,
                "Temp Read Blocks": 0,
                "Temp Written Blocks": 0
              },
              {
                "Node Type": "Bitmap Index Scan",
                "Parent Relationship": "Member",
                "Parallel Aware": false,
                "Async Capable": false,
                "Index Name": "nasabah_nomor_trgm_idx",
                "Startup Cost": 0.0,
                "Total Cost": 22.0,
                "Plan Rows": 101,
                "Plan Width": 0,
                "Actual Startup Time": 0.014,
                "Actual Total Time": 0.014,
                "Actual Rows": 112.0,
                "Actual Loops": 1,
                "Disabled": false,
                "Index Cond": "(upper((nomor)::text) ~~ '%0012%'::text)",
                "Index Searches": 1,
                "Shared Hit Blocks": 5,
                "Shared Read Blocks": 0,
                "Shared Dirtied Blocks": 0,
                "Shared Written Blocks": 0,
                "Local Hit Blocks": 0,
                "Local Read Blocks": 0,
                "Local Dirtied Blocks": 0,
                "Local Written Blocks": 0,
                "Temp Read Blocks": 0,
                "Temp Written Blocks": 0
              },
              {
                "Node Type": "Bitmap Index Scan",
                "Parent Relationship": "Member",
                "Parallel Aware": false,
                "Async Capable": false,
                "Index Name": "nasabah_no_hp_trgm_idx",
                "Startup Cost": 0.0,
                "Total Cost": 22.0,
                "Plan Rows": 101,
                "Plan Width": 0,
                "Actual Startup Time": 0.012,
                "Actual Total Time": 0.012,
                "Actual Rows": 112.0,
                "Actual Loops": 1,
                "Disabled": false,
                "Index Cond": "(upper((no_hp)::text) ~~ '%0012%'::text)",
                "Index Searches": 1,
                "Shared Hit Blocks": 5,
                "Shared Read Blocks": 0,
                "Shared Dirtied Blocks": 0,
                "Shared Written Blocks": 0,
                "Local Hit Blocks": 0,
                "Local Read Blocks": 0,
                "Local Dirtied Blocks": 0,
                "Local Written Blocks": 0,
                "Temp Read Blocks": 0,
                "Temp Written Blocks": 0
              },
              {
                "Node Type": "Bitmap Index Scan",
                "Parent Relationship": "Member",
                "Parallel Aware": false,
                "Async Capable": false,
                "Index Name": "nasabah_email_trgm_idx",
                "Startup Cost": 0.0,
                "Total Cost": 21.49,
                "Plan Rows": 1,
                "Plan Width": 0,
                "Actual Startup Time": 0.002,
                "Actual Total Time": 0.002,
                "Actual Rows": 0.0,
                "Actual Loops": 1,
                "Disabled": false,
                "Index Cond": "(upper((email)::text) ~~ '%0012%'::text)",
                "Index Searches": 1,
                "Shared Hit Blocks": 5,
                "Shared Read Blocks": 0,
                "Shared Dirtied Blocks": 0,
                "Shared Written Blocks": 0,
                "Local Hit Blocks": 0,
                "Local Read Blocks": 0,
                "Local Dirtied Blocks": 0,
                "Local Written Blocks": 0,
                "Temp Read Blocks": 0,
                "Temp Written Blocks": 0
              }
            ]
          }
        ]
      }
    ]
  },
  "Planning": {
    "Shared Hit Blocks": 5,
    "Shared Read Blocks": 0,
    "Shared Dirtied Blocks": 0,
    "Shared Written Blocks": 0,
    "Local Hit Blocks": 0,
    "Local Read Blocks": 0,
    "Local Dirtied Blocks": 0,
    "Local Written Blocks": 0,
    "Temp Read Blocks": 0,
    "Temp Written Blocks": 0
  },
  "Planning Time": 0.129,
  "Triggers": [],
  "Execution Time": 0.106
}
```

## Review follow-up and test evidence

The following incremental cycles were recorded locally. No after-the-fact test is claimed as a RED cycle.

| Behavior | RED commit and observed failure | GREEN commit |
|---|---|---|
| Reject 101-character search | `55e4e37`: HTTP 200 instead of 422 | `d08074a` |
| Non-atomic concurrent index migration | `8befad3`: migration.atomic was True | `5bf8d4a` |
| Missing-extension deployment preflight | `aa661af`: command missing instead of actionable pg_trgm bootstrap error | `53eb9f2` |

The first preflight attempt (`f8cddd5`) also had an unrelated database-mock teardown error. It was corrected before implementation; only the clean failure at `aa661af` is the demonstrated RED evidence.

Regression tests additionally cover the 100-character accepted boundary, read-only installed-extension checks, explicit bootstrap, permission failure instructions, and SQLite no-op behavior. The migration assertions now use `_assert_trigram_indexes()` rather than calling a test method as a helper.

References: [PostgreSQL pg_trgm privileges](https://www.postgresql.org/docs/current/pgtrgm.html), [concurrent index behavior](https://www.postgresql.org/docs/current/sql-createindex.html).
