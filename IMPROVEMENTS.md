# Application Cleanup and Refactoring Improvements

## 1. Purpose

This document proposes behavior-preserving cleanup and refactoring work for the
library semantic-search application. The goal is to make the existing program
safer to change, easier to understand, easier to operate, and more predictable
without adding user-facing capabilities.

The proposals cover validation, package structure, database hygiene, module
boundaries, dead-code removal, dependency management, testing, logging, and
repository naming. They do not implement any of those changes.

### Implementation status

Phases 1 through 4 were implemented on 2026-08-23. Phase 5 was completed on
2026-09-05: the GitHub repository, project distribution, checkout directory,
and deployment paths were renamed to `library-semantic-search`, while the
Python package remained `library_search`. The local `origin` remote uses the
renamed GitHub URL.

- Phase 1 added offline characterization tests and external-client fakes,
  tested SQLite backup/restore tooling and operator documentation, pinned
  direct dependencies and Ruff configuration, deterministic
  `make test`/`make check` commands, and the historical baseline in
  `docs/BASELINE.md`.
- Phase 2 moved maintained source into the `library_search` package, introduced
  typed and validated settings with absolute paths, added a Flask application
  factory, moved its templates/static assets into `library_search.web`, and
  changed Gunicorn and the installed host wrappers to package entry points.
- Phase 3 separated Vega, synchronization, embedding, search, database, models,
  errors, configuration, CLI, and web responsibilities. Database connections,
  transactions, HTTP/OpenAI clients, and the one outer asyncio event loop now
  have explicit owners. Input, remote response, embedding, schema, and request
  boundaries are validated.
- Phase 4 added transactional `PRAGMA user_version` migrations, rehearsed the
  legacy-table cleanup on a verified backup copy, migrated the live database to
  schema version 2, retained 20,326 rows in each active table and the two
  extension-owned vector tables, and removed obsolete root modules, the old
  Flask package, stale documentation, duplicate conversions, and unused code.

The live service was restarted after migration and returned HTTP 200 through
the new Gunicorn application-factory configuration. The complete offline gate
contains 35 passing tests. `ARCHITECTURE.md` describes the current state;
`docs/BASELINE.md` remains an intentionally historical pre-refactor snapshot.

## 2. Scope and non-goals

Normal application behavior should remain the same throughout this work:

- The same Vega catalog records are selected.
- Synchronization continues to maintain bibliographic, edition, record, and
  embedding data.
- `text-embedding-3-small` remains the embedding model.
- Search remains semantic nearest-neighbor search with up to 100 results.
- The current `/` and `/search` routes and rendered result information remain
  available.
- No filters, keyword search, pagination, accounts, new UI behavior, or other
  features are added.

Boundary validation and error handling may intentionally change how malformed
input or invalid external data fails. Such changes should reject bad data
clearly while preserving behavior for valid requests and records.

## 3. Recommended priorities

| Priority | Work | Reason |
| --- | --- | --- |
| P0 | Characterization tests, database backup procedure, and current-state inventory | Creates a safety net before moving code or deleting data. |
| P1 | Boundary validation, centralized configuration, and managed resource lifetimes | Prevents invalid data and hidden process state from spreading through the program. |
| P1 | Move the remaining Python modules into one application package | Establishes clear imports and module ownership before further splitting. |
| P1 | Replace ad hoc SQL and schema repair helpers with versioned migrations | Makes database changes repeatable and reviewable. |
| P2 | Remove verified legacy tables, dead scripts, unused functions, and duplicate logic | Reduces the amount of code and data that maintainers must reason about. |
| P2 | Separate synchronization, Vega access, embeddings, search, and database access | Makes tests smaller and failures easier to locate. |
| P2 | Clean up dependencies, logging, naming, typing, and documentation | Improves reproducibility and everyday maintenance. |
| P3 | Rename the repository and application package | Best done after the target module structure and terminology are settled. |

P0 work should land first. The other items should be delivered in small commits
that keep the application runnable rather than as one large rewrite.

## 4. Establish a safety net first

Refactoring without tests would make it difficult to distinguish cleanup from a
behavior regression. Begin with tests that record the behavior the application
has today.

### 4.1 Characterization tests

Add focused tests for:

- Vega bibliographic-response parsing using saved JSON fixtures.
- Vega edition-response parsing, including missing optional fields and
  multi-valued authors, languages, subjects, and summaries.
- ID-difference calculations for inserts, deletions, and unchanged rows.
- Creation of the flattened embedding input text.
- SQL row-to-dictionary conversion.
- The `/` route, `/search` route with a mocked search service, template loading,
  and static-file loading.
- Database schema creation and migration against a temporary SQLite database.
- Embedding validation using fake OpenAI responses rather than live API calls.
- Search-result ordering using a small temporary vector database where the
  native extension is available.

Tests should not call Vega or OpenAI over the network. External responses and
clients should be fixtures or fakes so the suite is deterministic and free to
run.

### 4.2 Record a baseline

Before changing schema or synchronization logic, record:

- table schemas and `PRAGMA user_version`;
- row counts for application and legacy tables;
- null counts for fields assumed to be strings;
- duplicate IDs and IDs missing from related tables;
- the embedding model and expected dimension;
- representative search queries and their ordered result IDs;
- the commands currently used by systemd, cron, Flask, and Gunicorn.

This baseline is verification data, not a permanent feature. Avoid storing real
API keys or a copy of the large database in Git.

## 5. Validate at system boundaries

Internally, functions should be able to assume that inputs are valid. Validation
should occur where untrusted or loosely typed data first enters the program.

| Boundary | Validate | Preferred failure behavior |
| --- | --- | --- |
| Environment/configuration | Required `OPENAI_API_KEY`, database/log paths, positive page size, positive concurrency, non-empty Vega IDs, supported model/dimension pair | Fail once at startup with a specific configuration error. |
| Flask request | Query exists, is a string after Flask decoding, is trimmed, is not blank, and is below a documented maximum length | Return a clear HTTP 400 response without calling OpenAI. |
| Vega HTTP response | Successful status, JSON object shape, required IDs, lists/objects in expected locations, and sensible pagination values | Raise a Vega-specific parsing or protocol error that identifies the endpoint and field. |
| Parsed catalog record | Non-empty stable ID, usable edition ID, strings or explicitly normalized missing values | Reject or quarantine the record before SQL insertion; do not fail later during embedding concatenation. |
| OpenAI response | Embedding exists, contains finite numeric values, and has exactly 1,536 dimensions | Raise an embedding-specific error before storing or searching. |
| Database read/write | Expected schema version, required tables/columns, unique IDs, and parameterized values | Abort the current transaction with a database-specific error and preserve the previous committed state. |
| Command-line maintenance operation | Known command, explicit database path, and confirmation/backup for destructive operations | Refuse ambiguous or unsafe operations. |

Use small domain dataclasses or typed records for parsed bibliographic and
edition data instead of passing anonymous tuples between modules. This gives
validation one home and avoids relying on tuple position throughout the sync
pipeline.

Avoid a large validation framework unless it provides clear value. Standard
library dataclasses plus explicit parsing functions are sufficient for the
current application size.

## 6. Consolidate Python code into one application package

The Flask files now live in `flaskr`, but `sync_db.py`, `fetch_items.py`,
`embed.py`, and `query.py` remain at the repository root. Move maintained code
under one domain-named package so imports, configuration, and ownership are
clear.

A possible target structure is:

```text
catalog_search/
    __init__.py
    config.py
    db.py
    models.py
    vega.py
    sync.py
    embeddings.py
    search.py
    web/
        __init__.py
        routes.py
        templates/
            index.html
            results.html
        static/
            style.css
tests/
    fixtures/
    test_db.py
    test_sync.py
    test_vega.py
    test_search.py
    test_web.py
gunicorn.conf.py
pyproject.toml
```

The exact package name should be chosen with the repository rename. The main
seams are more important than the exact number of files:

- `config.py` owns settings and their validation.
- `db.py` owns connection creation, extension loading, transactions, schema
  checks, and migrations.
- `models.py` owns typed internal records.
- `vega.py` owns only Vega HTTP and response parsing.
- `sync.py` coordinates catalog synchronization without containing HTTP or raw
  connection setup.
- `embeddings.py` owns embedding text construction and OpenAI embedding calls.
- `search.py` owns vector-index preparation and similarity queries.
- `web/` owns Flask creation, routes, templates, and static assets.

Use an application factory such as `create_app(settings=None)` instead of
constructing Flask and importing database/logging side effects at module import
time. Gunicorn can load the factory explicitly. Tests can then create isolated
applications with temporary settings.

Do not split every function into its own file. The purpose is to define stable
boundaries, not to maximize the module count.

## 7. Centralize configuration

Replace constants scattered through `fetch_items.py`, `sync_db.py`,
`flaskr/__init__.py`, and `gunicorn.conf.py` with a small typed settings object.
It should distinguish:

- filesystem paths: database and optional log file;
- Vega connection details: base URL, customer domain, material type, location,
  limiter, page size, and concurrency;
- embedding details: model and dimension;
- search details: result count;
- operational details: log level.

Defaults may preserve current behavior, while secrets remain environment-only.
Add an `.env.example` containing variable names and safe placeholder values, not
credentials. Make all entry points load configuration in the same way.

Using a resolved absolute database path prevents Flask, cron, and systemd from
silently opening different `items.db` files when their working directories
differ.

## 8. Clean up database schema and migrations

### 8.1 Replace manual migration helpers

`query.py` currently contains one-off table-copy, rename, deduplication, and
primary-key helpers. `sync_db.py` also performs an embedding-column migration at
runtime. Consolidate schema changes into ordered, idempotent migrations.

For this small project, a lightweight migration runner is enough:

- Store the schema version in `PRAGMA user_version`.
- Apply migrations in a transaction and in numeric order.
- Record the expected schema in source.
- Refuse to run against a newer unknown schema.
- Test every migration from its previous version and from a fresh database.
- Keep data synchronization separate from schema migration.

This removes the need for application startup to guess whether a table is
legacy based only on column names.

### 8.2 Remove legacy tables safely

The current local database contains:

- active application tables: `bibs`, `editions`, `records`, and `embeddings`;
- apparent migration leftovers: `bibs_legacy`, `editions_legacy`, and
  `embeddings_legacy`;
- sqliteai-vector-owned tables: `_sqliteai_vector` and
  `vector0_embeddings_embedding`.

The three legacy tables currently contain 21,828 rows each, while the active
tables contained 20,326 rows each at the last architecture inspection. The row
count difference means the legacy tables should not be dropped merely because
their names end in `_legacy`; they may contain an older snapshot not present in
the active catalog.

Use this removal procedure:

1. Stop the synchronization job and web workers so the file cannot change.
2. Make a timestamped backup outside the repository and verify that the backup
   opens successfully.
3. Run `PRAGMA integrity_check` on the source and backup.
4. Compare schemas, row counts, key sets, duplicate IDs, and representative rows
   between active and legacy tables.
5. Confirm that no maintained code or rollback procedure reads the legacy
   tables.
6. Add a versioned migration that drops only the verified legacy tables.
7. Re-run integrity, schema, count, sync, and representative-search checks.
8. Optionally run `VACUUM` during a maintenance window to reclaim disk space;
   dropping tables alone may not reduce the file size.
9. Retain the backup until the cleaned database has completed at least one
   successful sync and production verification cycle.

Do not manually delete `_sqliteai_vector` or
`vector0_embeddings_embedding`. They are owned by the vector extension and are
part of the active search index.

### 8.3 Make the target schema explicit

After validating existing data, standardize:

- primary keys on all identity tables, including `embeddings.id`;
- explicit column types and justified `NOT NULL` constraints;
- foreign-key intent between catalog IDs, even if derived tables are rebuilt;
- consistent naming, preferably Python and SQL `snake_case` at module
  boundaries;
- parameterized `IN` clauses that correctly handle zero, one, or many IDs;
- indexes required by joins and ID comparisons;
- a safe rebuild/swap strategy for `records` so readers do not observe a missing
  or half-built table.

Constraint changes should follow data validation. Adding constraints before
checking the current data could turn cleanup into an outage.

## 9. Remove dead and duplicate code

Review each candidate with tests and call-site searches before deletion.

| Candidate | Proposed cleanup |
| --- | --- |
| `embed.py` | Remove it after confirming no external job calls it. It duplicates production embedding logic and currently calls `get_collection` with the wrong signature. |
| `query.py` | Replace useful read-only diagnostics with explicit CLI commands; move schema changes into migrations; then remove the ad hoc script. |
| `flaskr.get_db`, `close_connection`, and `DATABASE` | Remove or make them the one real connection path. They are currently bypassed by search, so teardown does not close the active connection. |
| `fetch_items.get_lang` | Remove if language normalization remains out of scope. Keeping an unused partial mapping suggests behavior that does not exist. |
| `Config.pageLimit` | Remove or enforce it internally; it is currently unused. Removing it is the behavior-preserving option. |
| `sim_search`'s unused `res_json` | Remove the first conversion and convert rows exactly once at the web boundary. |
| `sql_to_json` debug `print` | Remove it or replace it with intentional debug logging. |
| `get_embeddings` database connection | Remove the unused connection and ensure the real caller owns resource cleanup. |
| Commented-out main-block experiments | Delete them after useful diagnostics have moved to tests or CLI commands. |
| `README_OLD.md` | Remove after any still-correct information is merged into maintained documentation. |

Also replace broad `except Exception` handling in author parsing with explicit
shape validation. Broad exception handling hides programming errors and makes
invalid remote data appear valid.

## 10. Make resource and async lifetimes explicit

### 10.1 SQLite

- Provide a context manager that opens the configured database, loads the
  vector extension, commits on success, rolls back on failure, and always
  closes.
- Keep transaction ownership at the service/operation level rather than
  committing inside low-level helper functions.
- Configure and document any foreign-key, WAL, and busy-timeout choices in one
  place.
- Do not create unused connections inside embedding helpers.

### 10.2 HTTP and OpenAI clients

- Create one reusable `httpx.AsyncClient` per sync operation instead of one per
  request.
- Ensure the semaphore covers the actual bibliographic HTTP request; it is
  currently released before that request begins.
- Use an explicit finite timeout rather than `timeout=None` so failed remote
  calls cannot hang forever.
- Inject Vega and OpenAI clients into services so tests can provide fakes.

### 10.3 Async orchestration

Make the synchronization entry point async and call `asyncio.run` once at the
outermost command. The current code repeatedly enters and exits event loops for
bibliographic fetching, edition batches, and embedding batches. One event loop
makes ownership clearer and allows client reuse without changing the sync's
functional result.

## 11. Clarify errors, transactions, and logging

Define a small exception hierarchy such as configuration, Vega protocol,
embedding, migration, and search errors. Add context at module boundaries while
preserving the original exception as the cause.

For synchronization:

- log the sync run ID, stage, elapsed time, and insert/delete/unchanged counts;
- roll back the current transaction on failure;
- exit nonzero so cron or systemd can detect failure;
- avoid catching an exception unless the code can add context or recover.

Configure logging only in executable entry points. Importing `sync_db.py` should
not call `load_dotenv`, `basicConfig`, or open `history.log`. Under systemd,
standard output/error may be preferable to a process-owned file; if a file is
kept, define rotation and ownership explicitly.

Avoid printing schema details during web requests. Logging should be deliberate,
structured enough to diagnose a stage, and free of API keys and full user query
contents unless retention has been consciously approved.

## 12. Improve naming and typing

Use consistent `snake_case` for Python variables and parameters:

- `date_from`, `date_to`, and `page_num` instead of mixed camel case;
- `search_text`, `page_size`, and `page_limit` in configuration;
- descriptive names instead of shadowing built-ins such as `id`.

Replace generic return annotations such as `tuple`, `list`, and `dict` with
precise types or dataclasses. Add return types to public functions. Prefer one
representation for record IDs and embedding values across modules.

Correcting the `lanugage` label embedded in catalog text is not a purely
cosmetic change: it changes embedding input and therefore requires a controlled
full embedding rebuild. Defer it until that rebuild is explicitly planned, even
though the source typo itself looks like routine cleanup.

## 13. Clean up dependency and development configuration

Move project metadata and tool configuration to `pyproject.toml`. Declare only
direct dependencies and use a lock or compiled requirements file for deployed
versions.

Current dependency cleanup candidates are:

- add `tqdm`, which is imported directly but not declared;
- remove the third-party `asyncio` package because modern Python includes it;
- remove `requests` and `sqlalchemy` if call-site searches confirm they are
  unused;
- define and document the supported Python version;
- pin or lock Flask, Gunicorn, httpx, OpenAI, python-dotenv, sqliteai-vector, and
  tqdm to tested versions.

Configure Ruff in `pyproject.toml` for import sorting and linting. Add pytest for
tests and consider a type checker after annotations are made meaningful. A small
CI workflow should run syntax checks, Ruff, and tests without requiring secrets
or external network access.

Generated caches such as `__pycache__` and `.ruff_cache` should remain ignored
and should not be treated as application artifacts.

## 14. Rename the repository and package

`fetchdvds` no longer accurately describes a semantic search application whose
current catalog filter targets print books. Possible names include:

- `library-semantic-search` — describes the user-visible purpose without tying
  the project to one vendor;
- `vega-library-search` — makes the III Vega integration explicit;
- `catalog-semantic-search` — describes the reusable technical role;
- `wr-library-search` — appropriate only if the application is intentionally
  specific to the current library.

Choose whether the project is library-specific and whether Vega is a permanent
part of its identity before selecting a name. A neutral recommendation is
`library-semantic-search` for the repository and `library_search` for the Python
package.

Perform the repository rename after moving modules into the chosen package so
deployment paths only need to be updated once. The rename checklist includes:

- remote repository name and clone URL;
- local checkout directory;
- Python package/import paths and Gunicorn `wsgi_app`;
- systemd unit working directory and launch script;
- cron commands and log paths;
- Cloudflare or reverse-proxy configuration, if present;
- documentation and developer commands;
- CI, backup, and monitoring paths.

The SQLite filename can remain `items.db` during this refactor to avoid mixing a
data-file migration into a repository rename.

## 15. Suggested implementation sequence

### Phase 1: Safety and reproducibility

1. Add characterization tests and external-client fakes.
2. Document and test the database backup/restore procedure.
3. Add `pyproject.toml`, exact direct dependencies, Ruff configuration, and a
   deterministic test command.
4. Capture current schema and representative behavior as a baseline.

### Phase 2: Package and configuration boundaries

1. Choose the domain package name.
2. Move maintained modules under it without changing function behavior.
3. Add typed settings and resolved paths.
4. Introduce a Flask application factory and update Gunicorn.
5. Keep temporary compatibility entry points only if external jobs need a
   transition period.

### Phase 3: Persistence and service boundaries

1. Introduce managed database connections and transaction ownership.
2. Parameterize all SQL values and centralize schema definitions.
3. Separate Vega, sync, embedding, and search responsibilities.
4. Run synchronization under one async entry point with reusable clients.
5. Add boundary validation and specific exceptions.

### Phase 4: Schema and dead-code cleanup

1. Add and test schema-version migrations.
2. Validate and remove legacy tables using the safe procedure above.
3. Verify the vector extension's internal tables and rebuild behavior.
4. Remove `embed.py`, replace/remove `query.py`, and delete unused functions and
   duplicate conversions.
5. Remove unused dependencies and stale documentation.

### Phase 5: Operational rename

1. Rename the repository and final Python package.
2. Update Gunicorn, systemd, cron, working-directory, and remote-repository
   references.
3. Run a full sync and representative web searches in the renamed deployment.

## 16. Completion criteria

The cleanup effort is complete when:

- valid user requests and representative searches retain expected behavior;
- all maintained Python code lives under one clearly named package;
- configuration is typed, validated once, and free of hidden working-directory
  assumptions;
- Vega, OpenAI, Flask, and SQLite boundaries validate external data;
- database schema changes are versioned and tested;
- verified migration leftovers are removed while extension-owned tables remain
  intact;
- all connections and clients have explicit owners and lifetimes;
- synchronization uses parameterized SQL and predictable transactions;
- stale scripts, unused functions, duplicate work, and unused dependencies are
  gone;
- imports have no logging, `.env`, network, or database side effects;
- tests, linting, and dependency installation are reproducible;
- systemd, cron, Gunicorn, and documentation reference the final package and
  repository names;
- no new product functionality was introduced as part of the refactor.
