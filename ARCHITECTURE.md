# Library Search Architecture

## Purpose and scope

This program maintains a local copy of a selected III Vega library catalog and
provides semantic search over that copy. It has two independent runtime paths:

- a scheduled synchronization path that fetches catalog data, creates missing
  OpenAI embeddings, and updates SQLite; and
- an online request path in which Gunicorn serves a Flask application that
  embeds a user's query and searches the stored vectors.

Both paths use the `library_search` package and the same `items.db` file. Schema
changes are a separate operator action: normal synchronization and web requests
validate the schema version but never migrate it implicitly.

The application is a small monolith. There is no separate application server,
job queue, cache, or database service. External dependencies are Vega, OpenAI,
and the native sqliteai-vector extension.

## System context

### Database synchronization path

The installed cron entry runs `/home/reedbc1/scripts/sync_db.sh` at 08:00 and
16:00 each day. That wrapper changes to the repository directory and executes:

```bash
.venv/bin/python -m library_search sync
```

One synchronization run works as follows:

- The command-line boundary loads and validates `Settings`, including the
  database path, Vega parameters, concurrency and timeout values, embedding
  settings, log path, and `OPENAI_API_KEY`.
- `library_search.sync` starts one asyncio event loop for the complete run.
- One `VegaClient` and one reusable asynchronous HTTP client fetch all matching
  bibliographic pages. The client limits the actual HTTP operations with a
  semaphore and applies a finite timeout.
- Vega response parsers validate the response shape and create typed
  `BibliographicRecord` objects. The repository compares their IDs with `bibs`,
  inserting new IDs and deleting IDs no longer returned by Vega.
- The repository compares edition IDs referenced by `bibs` with `editions`.
  The Vega client fetches missing editions and parses them into typed
  `EditionRecord` objects; obsolete editions are removed.
- SQLite builds `records_new` from an inner join of `bibs` and `editions`, then
  swaps it into place as `records` within the write transaction. Readers do not
  observe a deliberately dropped table between commits.
- The repository compares `records` IDs with `embeddings`. It removes orphaned
  embeddings and prepares labeled text for records with no embedding.
- One reusable `AsyncOpenAI` client creates missing embeddings in configured
  batches. Every response is checked for exactly 1,536 finite numeric values
  before it is stored.
- sqliteai-vector converts the values to FLOAT32 BLOBs, initializes the vector
  metadata, and updates the quantized search representation.
- Each database stage owns its transaction and connection. Success commits,
  failure rolls back that stage, and the connection is always closed.

The ID-difference behavior intentionally preserves the pre-refactor semantics:
an existing catalog ID is considered unchanged. Metadata changes for an
existing ID do not update its stored row or regenerate its embedding.

### Flask behind Gunicorn path

The `simsearch.service` systemd unit runs
`/home/reedbc1/scripts/simsearch.sh`. The wrapper changes to the repository and
executes:

```bash
.venv/bin/gunicorn --config gunicorn.conf.py
```

`gunicorn.conf.py` tells Gunicorn to create the Flask application with
`library_search.web:create_app()`, bind to `0.0.0.0:8001`, and start four
synchronous workers.

The request path works as follows:

- `GET /` renders the search form. It does not access OpenAI or SQLite.
- `GET /search?query=...` reads the decoded query string at the Flask boundary.
  Missing, blank, or overlong input produces HTTP 400 without calling OpenAI.
- `library_search.search` trims the query, creates one query embedding with the
  synchronous OpenAI client, and validates its type, dimension, and values.
- A managed SQLite connection loads the packaged vector extension, applies a
  five-second busy timeout, and verifies that `PRAGMA user_version` is the
  current application schema version.
- sqliteai-vector scans the quantized `embeddings` data for the configured 100
  nearest neighbors. Their IDs are joined to `records` and ordered by ascending
  vector distance.
- Search converts each SQLite row to one dictionary containing the eight
  `records` fields. Vector distance is used for ordering but is not displayed.
- Flask renders the Jinja result template and returns the HTML response.
- A recognized application failure returns HTTP 503 and is logged; unexpected
  exception details are not returned to the browser.

The online path never contacts Vega and never changes catalog content. It does
run vector initialization/quantization SQL while preparing a search, so the
search connection is treated as a write-capable transaction.

## Package organization

The source is organized by responsibility under one domain package:

```text
library_search/
    __init__.py
    __main__.py
    config.py
    db.py
    embeddings.py
    errors.py
    models.py
    search.py
    sync.py
    vega.py
    web/
        __init__.py
        static/
            style.css
        templates/
            index.html
            results.html
```

Dependencies point inward through explicit interfaces:

- `web` calls `search` and renders templates.
- `sync` coordinates `vega`, `embeddings`, and the repository in `db`.
- `search` calls `embeddings` validation and database/vector helpers.
- `vega` and `db` produce or consume the typed records in `models`.
- All runtime modules use `Settings` from `config` and expected exception types
  from `errors`.

Configuration loading, logging setup, network calls, and database connections
do not occur merely because a module is imported. They occur at executable or
service boundaries, which keeps unit tests isolated and avoids worker import
side effects.

## Repository file map

| Path | Responsibility |
| --- | --- |
| `library_search/__init__.py` | Marks the domain package and exposes package metadata. |
| `library_search/__main__.py` | CLI entry point for `sync`, `migrate`, and `database-info`. |
| `library_search/config.py` | Immutable typed settings, `.env` loading at boundaries, absolute path resolution, and configuration validation. |
| `library_search/errors.py` | Small application exception hierarchy for configuration, input, Vega, embeddings, persistence, migration, and search failures. |
| `library_search/models.py` | Immutable bibliographic, edition, embedding-input, and ID-change dataclasses passed between layers. |
| `library_search/vega.py` | Reusable asynchronous Vega HTTP client, concurrency control, finite timeouts, pagination, and response parsing. |
| `library_search/embeddings.py` | Catalog/query embedding calls and dimension/finite-number validation. |
| `library_search/db.py` | Vector-enabled SQLite connections, transaction context manager, schema definitions, versioned migrations, database inventory, ID diffs, and `CatalogRepository`. |
| `library_search/sync.py` | High-level asynchronous synchronization stages and executable logging setup. |
| `library_search/search.py` | Query validation, vector-index preparation, nearest-neighbor SQL, and result conversion. |
| `library_search/web/__init__.py` | Flask application factory and the `/` and `/search` routes. |
| `library_search/web/templates/` | Landing-page and result-page Jinja templates. |
| `library_search/web/static/style.css` | Browser styling served by Flask. |
| `gunicorn.conf.py` | Factory import, port 8001, four workers, and access-log configuration. |
| `pyproject.toml` | Project metadata, Python compatibility, exact direct dependencies, and Ruff configuration. |
| `requirements.txt` | Exact production dependencies used by the existing host workflow. |
| `Makefile` | Deterministic `test`, `lint`, and `check` commands. |
| `scripts/database_backup.py` | Verified SQLite backup, restore, and integrity-check CLI that refuses overwrites. |
| `tests/` | Offline unit, integration, migration, vector-extension, complete fake-client synchronization, Flask, and project-configuration tests. |
| `tests/fixtures/` | Representative Vega responses used without network access. |
| `docs/BASELINE.md` | Historical pre-refactor Phase 1 behavior and schema snapshot. |
| `docs/DATABASE_BACKUP.md` | Operator backup, restore, and recovery procedure. |
| `ARCHITECTURE.md` | Current system and code architecture. |
| `IMPROVEMENTS.md` | Cleanup plan and phase status; intentionally listed in `.gitignore` per local policy. |
| `.env` | Ignored local secrets and optional settings overrides. |
| `items.db` | Ignored runtime SQLite database shared by synchronization and search. |
| `history.log` | Ignored synchronization log file. |

The obsolete root modules `sync_db.py`, `fetch_items.py`, `embed.py`, and
`query.py` have been removed. Their maintained responsibilities now live in the
package. The old `flaskr` package and stale `README_OLD.md` have also been
removed. Deployment wrappers outside the repository now call the package entry
points directly; no compatibility modules remain.

## Configuration

`Settings.from_env()` resolves paths relative to the repository root, not the
process working directory. This prevents cron, systemd, Flask, and shell runs
from silently opening different database files.

Important environment variables and defaults are:

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_PATH` | `items.db` | SQLite file; relative values resolve under the project root. |
| `LOG_PATH` | `history.log` | Synchronization log path. |
| `OPENAI_API_KEY` | none | Required for synchronization and real web search. |
| `VEGA_BASE_URL` | `https://na2.iiivega.com/api` | Vega API root. |
| `VEGA_CUSTOMER_DOMAIN` | `slouc.na2.iiivega.com` | Vega customer and host headers. |
| `VEGA_SEARCH_TEXT` | `*` | Catalog search text. |
| `VEGA_MATERIAL_TYPE_ID` | `1` | Selected material type. |
| `VEGA_LOCATION_ID` | `59` | Selected location. |
| `VEGA_LIMITER_ID` | `at_library` | Vega universal limiter. |
| `VEGA_PAGE_SIZE` | `100` | Bibliographic page and edition batch size. |
| `REQUEST_CONCURRENCY` | `5` | Maximum concurrent Vega requests. |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Timeout for Vega HTTP operations. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Model used for records and queries. |
| `EMBEDDING_DIMENSION` | `1536` | Required stored and query vector dimension. |
| `EMBEDDING_BATCH_SIZE` | `100` | Number of concurrently requested record embeddings per batch. |
| `SEARCH_RESULT_COUNT` | `100` | Nearest neighbors returned to the template. |
| `MAXIMUM_QUERY_LENGTH` | `1000` | Largest accepted search query in characters. |
| `LOG_LEVEL` | `INFO` | Synchronization logging threshold. |

Numeric settings must be positive, log levels must be recognized, required
strings must be nonblank, and Vega's base URL must be HTTP(S). Secrets stay in
the environment and are not logged.

## Database model and migrations

### Application tables

The current schema is version 2 in `PRAGMA user_version`:

| Table | Columns | Role |
| --- | --- | --- |
| `bibs` | `id` PK, `title`, `publicationDate`, `coverUrl` nullable, `editionId` | Vega format-group fields and selected edition reference. |
| `editions` | `id` PK, `author`, `itemLanguage`, `subjects`, `summary` | Flattened metadata for fetched editions. |
| `records` | `id` PK, `title`, `author`, `publicationDate`, `itemLanguage`, `subjects`, `summary`, `coverUrl` nullable | Search/UI read model produced by joining `bibs` and `editions`. |
| `embeddings` | `id` PK, `embedding` BLOB | One FLOAT32 vector per searchable record. |

Fresh databases use explicit SQLite types, primary keys, and `NOT NULL`
constraints for required values. The migrated live database retained its
compatible pre-refactor table definitions, whose non-ID text columns have no
declared affinity or `NOT NULL` constraint; migration 1 validated the column
order, primary keys, and current required values rather than rebuilding four
large active tables. `coverUrl` remains logically nullable because the verified
live data contains 12 records without a cover. The relationships are not
declared as foreign keys because synchronization computes diffs in separate
stages and `records` is replaced as a derived read model.

### Extension-owned tables

`_sqliteai_vector` and `vector0_embeddings_embedding` are owned by
sqliteai-vector. Application migrations preserve them, and operators must not
edit or remove them as ordinary application tables.

### Version history

- Version 1 creates a constrained schema for a fresh database or safely adopts
  the compatible pre-refactor tables without rewriting them. It also normalizes
  the old `embeddings.BLOB` column form if encountered. Required table shape,
  primary keys, and current non-null data are checked before completion.
- Version 2 drops only the verified leftovers `bibs_legacy`,
  `editions_legacy`, and `embeddings_legacy`.

Each migration runs in its own `BEGIN IMMEDIATE` transaction. A failure rolls
back that migration and preserves the previous committed schema version. A
database newer than the code is rejected. Run migrations explicitly:

```bash
.venv/bin/python -m library_search migrate
```

Both synchronization and search call `require_current_schema`; neither tries to
repair a database during normal traffic.

### Live Phase 4 migration

On 2026-08-23 the live database was backed up, rehearsed on a copy, migrated to
version 2 with the service stopped, and then verified. It retained 20,326 rows
in each application table, preserved both vector tables, passed SQLite's
integrity check, and returned the source record first for an exact stored-vector
search. The migration intentionally did not run `VACUUM`; dropping tables does
not necessarily reduce the file size, and vacuuming a database this large needs
additional temporary disk space and a separate maintenance window.

## Validation and failure behavior

Validation occurs where loosely typed data enters a trusted layer:

- configuration errors fail before work begins;
- bad Flask query input returns HTTP 400 before an OpenAI call;
- Vega transport failures, non-object JSON, malformed pagination, missing IDs,
  and invalid nested field shapes become `VegaError` failures;
- typed records establish the representation passed into persistence;
- OpenAI embeddings must be a list or tuple of the configured number of finite
  numeric values;
- schema version, table order/columns, primary keys, and required stored values
  are checked during migrations; routine operation also checks schema version
  and table shape;
- database writes use placeholders for values, including variable-size ID
  lists, and service-level context managers own commit/rollback/close behavior.

The sync command exits nonzero when an exception escapes. The web layer returns
503 for expected application failures and logs the causal stack on the host.
There is no automatic retry policy at present.

## Testing and verification

The test suite is network-free and does not require an API key. It uses saved
Vega fixtures, fake HTTP/OpenAI clients, temporary SQLite databases, and the
real locally installed sqliteai-vector extension.

Coverage includes:

- settings defaults, path resolution, and invalid environment values;
- Vega request parameters, parsing, pagination, invalid response shapes,
  client reuse, and concurrency;
- embedding input compatibility and response validation;
- schema creation/adoption, ordered migrations, legacy deletion, new-version
  refusal, migration/connection rollback behavior, parameterized repository
  operations, and vector search ordering;
- complete synchronization with fake external clients;
- query validation, result conversion, and managed search resources;
- Flask routes, templates, static files, HTTP 400, and HTTP 503 behavior;
- backup/restore integrity and refuse-overwrite safeguards;
- import sorting, project metadata, Flask factory discovery, and Gunicorn
  factory configuration.

Run the local gate with:

```bash
make check
```

## Operational assumptions

Correct operation assumes:

- Vega's unauthenticated endpoints, headers, and JSON structure remain
  compatible with the parser;
- configured Vega material, location, and limiter IDs retain their meanings;
- Vega IDs are stable and the first edition in the first material tab is the
  desired edition;
- OpenAI credentials have access and quota, and record/query vectors use the
  same model and dimension;
- the host's Python and packaged sqliteai-vector binary support extension
  loading;
- one authoritative sync job writes at a time;
- operators stop Gunicorn and sync jobs before schema maintenance;
- the systemd and cron wrappers outside the repository continue to point to
  `/home/reedbc1/Repos/fetchdvds` until the separate Phase 5 rename;
- backups are stored outside Git and retained until a post-migration sync and
  production verification cycle have succeeded.

## Known limitations

### Catalog freshness

- ID-based synchronization inserts and deletes but does not update an existing
  ID whose metadata changed upstream.
- Existing embeddings are not regenerated when upstream fields change under
  the same ID.
- Only the first edition from the first material tab is indexed.
- Multi-valued fields are flattened into comma-separated strings.
- The embedding input retains the historical `lanugage` label typo to avoid an
  unplanned full re-embedding during behavior-preserving refactoring.
- `records` is an inner join, so a bibliographic item without a stored edition
  is not searchable.

### Reliability and operation

- Synchronization uses transactions per stage, not a single transaction across
  all remote calls and database changes. A later-stage failure leaves earlier
  committed stages for the next run to reconcile.
- Vega and OpenAI calls have no retry/backoff policy.
- The web process has no health endpoint or richer operator-facing error page.
- Gunicorn workers and the scheduled synchronizer share one SQLite file. A busy
  timeout helps with short contention, but WAL mode is not currently enabled.
- Vector initialization and quantization are invoked for each search as well as
  after synchronization.
- `history.log` has no rotation configured in this repository.

### Search and exposure

- Search is semantic-only, fixed at 100 results, and has no pagination, filter,
  cache, or keyword fallback.
- Every valid search performs a paid external OpenAI request and occupies a
  synchronous Gunicorn worker while it waits.
- The application has no authentication, rate limiting, or request quota. Host
  firewall/reverse-proxy/tunnel policy controls exposure of port 8001.
- The result template does not expose similarity distance.

### Project state

- Exact direct dependencies are pinned, but transitive dependencies are not
  locked and there is no CI workflow.
- The distribution name and checkout directory still use `fetchdvds`; renaming
  them is Phase 5 and was intentionally excluded from phases 2–4.
- The migration backup made during Phase 4 is in `/tmp` and is not a durable
  long-term backup location. Operators should copy it to durable storage before
  relying on it for recovery.

## Safe change points

- Change Vega protocol details and parsing in `vega.py`, extending fixture-based
  tests before modifying sync orchestration.
- Add schema changes as ordered migrations in `db.py`; never restore import-time
  or request-time schema guessing.
- Treat any change to embedding text, model, or dimension as a controlled full
  index migration.
- Keep web request handling thin and place search behavior in `search.py`.
- Keep transaction ownership at operation boundaries and repository methods
  focused on persistence.
- Update both external host wrappers, systemd/cron references, configuration,
  and documentation together during the Phase 5 repository rename.
