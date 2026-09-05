# Library Semantic Search

Library Semantic Search synchronizes a selected portion of an III Vega library
catalog into SQLite and provides natural-language similarity search through a
small Flask website.

Catalog records and their OpenAI embeddings are stored locally. At search time,
the application embeds the user's query and uses sqliteai-vector to find the
nearest catalog records. The project is intentionally focused: it provides
semantic search, not a replacement library catalog or a general-purpose search
platform.

## How it works

The application has two independently invoked paths that share `items.db`:

1. **Catalog synchronization** fetches bibliographic and edition data from
   Vega, updates the local relational tables, creates embeddings for new
   records with OpenAI, and updates the local vector index.
2. **Web search** accepts a query through Flask, creates one OpenAI query
   embedding, searches the stored vectors in SQLite, and renders the closest
   records as HTML.

Database schema changes are a separate, explicit operation. Normal web requests
and synchronization validate the schema version but never migrate it
automatically.

## Requirements

- Python 3.13
- An OpenAI API key for catalog synchronization and real searches
- Network access to OpenAI and the configured Vega API
- A platform supported by the native extension included with
  `sqliteai-vector`
- `make` for the convenience commands (optional)

The tested direct dependencies and Python range are declared in
[`pyproject.toml`](pyproject.toml).

## Installation

### Using uv

From the repository root:

```bash
uv sync --extra dev
```

This creates or synchronizes `.venv`, installs the application, installs its
runtime dependencies, and includes development tools such as Ruff.

Run commands through the managed environment with `uv run`:

```bash
uv run python -m library_search --help
```

### Using standard Python and pip

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

The editable installation means imports use the files in this checkout, so
source changes take effect the next time the application starts without
reinstalling the project.

## Configuration

Configuration is loaded from environment variables. When no explicit mapping is
provided by a caller, the application also loads an ignored `.env` file from the
project root.

At minimum, create `.env` with an OpenAI key:

```dotenv
OPENAI_API_KEY=replace-with-your-key
```

Do not commit `.env` or an API key.

The available settings are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_PATH` | `items.db` | SQLite database path. Relative paths resolve from the project root. |
| `LOG_PATH` | `history.log` | Synchronization log path. |
| `OPENAI_API_KEY` | none | Required for synchronization and real web searches. |
| `VEGA_BASE_URL` | `https://na2.iiivega.com/api` | Vega API root. |
| `VEGA_CUSTOMER_DOMAIN` | `slouc.na2.iiivega.com` | Customer domain sent in Vega headers. |
| `VEGA_SEARCH_TEXT` | `*` | Catalog search expression. |
| `VEGA_MATERIAL_TYPE_ID` | `1` | Selected Vega material type. |
| `VEGA_LOCATION_ID` | `59` | Selected Vega location. |
| `VEGA_LIMITER_ID` | `at_library` | Vega universal limiter. |
| `VEGA_PAGE_SIZE` | `100` | Bibliographic page and edition batch size. |
| `REQUEST_CONCURRENCY` | `5` | Maximum concurrent Vega requests. |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Vega request timeout in seconds. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Model used for record and query embeddings. |
| `EMBEDDING_DIMENSION` | `1536` | Required embedding dimension. |
| `EMBEDDING_BATCH_SIZE` | `100` | Catalog embedding batch size. |
| `SEARCH_RESULT_COUNT` | `100` | Number of nearest records returned. |
| `MAXIMUM_QUERY_LENGTH` | `1000` | Maximum accepted query length. |
| `LOG_LEVEL` | `INFO` | Synchronization logging level. |

Numeric settings must be positive, required text settings must not be blank,
and the model and dimension must remain compatible with the vectors already
stored in the database.

## Initial database setup

Apply the schema migrations before running either synchronization or web
search:

```bash
uv run python -m library_search migrate
```

With an activated conventional virtual environment, use:

```bash
python -m library_search migrate
```

The migration command creates the application tables for a fresh database or
applies pending migrations in order. Each migration is transactional and is
recorded in SQLite's `PRAGMA user_version`.

Inspect the resulting database with:

```bash
uv run python -m library_search database-info
```

The report includes the absolute database path, schema version, integrity
result, known tables, and application row counts.

## Synchronizing the catalog

After configuring `OPENAI_API_KEY` and applying migrations, run:

```bash
uv run python -m library_search sync
```

Synchronization:

- fetches matching bibliographic records from Vega;
- inserts new bibliographic IDs and deletes IDs no longer returned;
- fetches missing editions and removes obsolete editions;
- rebuilds the flattened `records` search table through a transactional swap;
- removes orphaned embeddings and creates embeddings for new records; and
- initializes and quantizes the sqliteai-vector search data.

The first synchronization can make many Vega and OpenAI requests. It may take
substantial time and incur OpenAI API costs. The current ID-based behavior does
not refresh metadata or embeddings for IDs already present in the database.

Only one synchronization process should write the database at a time.

## Running the web application

For local development with Flask:

```bash
uv run flask --app 'library_search.web:create_app()' run --debug
```

For the project’s Gunicorn configuration:

```bash
uv run gunicorn --config gunicorn.conf.py
```

Gunicorn creates the app with `library_search.web:create_app()`, starts four
synchronous workers, and listens on `0.0.0.0:8001`.

The browser routes are:

| Route | Behavior |
| --- | --- |
| `GET /` | Renders the search form without contacting OpenAI or SQLite. |
| `GET /search?query=...` | Validates the query, performs semantic search, and renders the closest records. |

Missing, blank, or overlong queries return HTTP 400. Expected application
failures return HTTP 503 without exposing internal exception details.

## Command-line interface

The package's [`__main__.py`](library_search/__main__.py) registers these
subcommands:

```text
python -m library_search sync
python -m library_search migrate
python -m library_search database-info
```

View the generated help with:

```bash
uv run python -m library_search --help
```

## Testing and linting

Run the complete offline verification gate:

```bash
make check
```

Or run the underlying commands directly:

```bash
uv run ruff check .
uv run python -m unittest discover -s tests -v
```

The tests do not contact Vega or OpenAI. They use saved Vega fixtures, fake
external clients, temporary SQLite databases, and the real installed vector
extension. Coverage includes configuration, parsing, synchronization,
embeddings, migrations, transaction behavior, vector ordering, Flask routes,
backup/restore behavior, and packaging configuration.

## Database backup and maintenance

Before a migration, manual repair, or other potentially destructive database
operation, follow [`docs/DATABASE_BACKUP.md`](docs/DATABASE_BACKUP.md).

The backup utility verifies SQLite integrity and refuses to overwrite an
existing destination:

```bash
uv run python -m scripts.database_backup verify items.db

uv run python -m scripts.database_backup backup \
  items.db \
  /absolute/backup/path/items-backup.db
```

Application data lives in `bibs`, `editions`, `records`, and `embeddings`.
Tables named `_sqliteai_vector` and `vector0_embeddings_embedding` belong to the
vector extension and must not be manually removed.

`items.db`, `.env`, and runtime logs are intentionally ignored by Git.

## Raspberry Pi deployment

The current Raspberry Pi deployment uses two host-level wrappers outside this
repository:

- `simsearch.service` invokes `/home/reedbc1/scripts/simsearch.sh`, which starts
  Gunicorn from `/home/reedbc1/Repos/library-semantic-search`.
- The installed cron entry invokes `/home/reedbc1/scripts/sync_db.sh` at 08:00
  and 16:00, and that wrapper runs `python -m library_search sync` from the same
  checkout.

The deployment therefore follows the branch currently checked out in that
working tree. Restart the service after switching branches or changing loaded
Python code.

## Repository layout

```text
library-semantic-search/
├── library_search/
│   ├── __main__.py       # Command-line entry point
│   ├── config.py         # Typed environment-backed settings
│   ├── db.py             # SQLite access, migrations, and repository
│   ├── embeddings.py     # OpenAI embedding calls and validation
│   ├── errors.py         # Application exception hierarchy
│   ├── models.py         # Typed records passed between layers
│   ├── search.py         # Query validation and vector search
│   ├── sync.py           # Synchronization orchestration
│   ├── vega.py           # Vega HTTP client and response parsing
│   └── web/              # Flask factory, templates, and static assets
├── scripts/
│   └── database_backup.py
├── tests/
├── docs/
├── ARCHITECTURE.md
├── gunicorn.conf.py
├── Makefile
├── pyproject.toml
└── requirements.txt
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the detailed system design, data
model, configuration boundaries, assumptions, and limitations. The historical
pre-refactor snapshot is preserved in
[`docs/BASELINE.md`](docs/BASELINE.md).

## Current limitations

- Existing IDs are treated as unchanged, even when their upstream metadata
  changes.
- Search is semantic-only and returns a fixed number of results.
- Every valid search makes an OpenAI API request.
- Vega and OpenAI operations do not currently have retry/backoff policies.
- The web application has no built-in authentication, rate limiting, or usage
  quota.
- Gunicorn and synchronization share one SQLite file; SQLite busy-timeout
  handling reduces brief contention, but WAL mode is not enabled.
- Direct dependencies are pinned, but transitive dependencies are not locked.

Changes to the embedding model, dimension, or catalog embedding text require a
controlled full embedding rebuild; changing only the configuration would make
stored and query vectors incompatible.
