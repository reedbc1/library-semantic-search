# Database Backup and Restore Procedure

## Purpose

Use this procedure before database migrations, legacy-table removal, a manual
repair, or another operation that could make `items.db` difficult to recover.
The repository script uses SQLite's online backup API rather than copying a live
database byte-for-byte.

The script never overwrites an existing destination. This is intentional: a
restore must not silently destroy the current database.

## Prerequisites

- Run commands from the repository root with the project virtual environment.
- Choose a backup location outside the repository and on storage with enough
  free space for the approximately 591 MiB database.
- Stop the synchronization job before creating the maintenance backup.
- For the cleanest operational snapshot, stop the Gunicorn service as well;
  search currently invokes vector-index maintenance SQL.

The examples use `/srv/backups/library-search`. Replace it with an appropriate
absolute directory owned by the service operator.

## Verify the current database

```bash
.venv/bin/python -m scripts.database_backup verify items.db
```

Continue only when the JSON report says `"integrity_check": "ok"` and lists
the expected application and sqliteai-vector tables.

## Create and verify a backup

Use a unique, timestamped destination:

```bash
.venv/bin/python -m scripts.database_backup backup \
  items.db \
  /srv/backups/library-search/items-2026-08-23T1601.db
```

The backup command verifies the source, creates a consistent SQLite backup, and
verifies the result. Verify it again independently before destructive work:

```bash
.venv/bin/python -m scripts.database_backup verify \
  /srv/backups/library-search/items-2026-08-23T1601.db
```

Record the backup path in the maintenance notes. Do not store the database in
Git.

## Test the backup without replacing the live database

Restore to a new scratch filename:

```bash
.venv/bin/python -m scripts.database_backup restore \
  /srv/backups/library-search/items-2026-08-23T1601.db \
  /tmp/items-restore-test.db
```

Inspect counts using the SQLite CLI:

```bash
sqlite3 /tmp/items-restore-test.db \
  "SELECT 'bibs', COUNT(*) FROM bibs
   UNION ALL SELECT 'editions', COUNT(*) FROM editions
   UNION ALL SELECT 'records', COUNT(*) FROM records
   UNION ALL SELECT 'embeddings', COUNT(*) FROM embeddings;"
```

Remove the scratch restore only after verification. The backup itself should be
retained.

## Restore after a failure

1. Stop Gunicorn and every synchronization or maintenance process.
2. Verify the selected backup with the `verify` command.
3. Move the failed `items.db` to a uniquely named quarantine path on the same
   filesystem; do not delete it.
4. Restore the backup to the now-absent `items.db` path:

   ```bash
   .venv/bin/python -m scripts.database_backup restore \
     /srv/backups/library-search/items-2026-08-23T1601.db \
     items.db
   ```

5. Verify `items.db` and compare its schema and row counts with the maintenance
   baseline.
6. Start Gunicorn and run representative searches.
7. Start synchronization only after read-only verification succeeds.
8. Keep both the original backup and quarantined failed database until a full
   sync and operational verification have completed.

If `items.db` still exists, the restore command exits without changing it. This
guard is covered by the automated test suite.

## Automated procedure tests

`tests/test_database_backup.py` creates a temporary SQLite database and verifies
the complete backup, integrity-check, and restore round trip. It also verifies
that existing destinations and same-file backups are rejected.

Run it with the rest of Phase 1 checks:

```bash
make check
```
