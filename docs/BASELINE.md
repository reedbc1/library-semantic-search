# Phase 1 Behavior and Database Baseline

> Historical snapshot: this document intentionally describes the application
> before phases 2 through 4. On 2026-08-23 the maintained code moved into the
> `library_search` package and the live database migrated to schema version 2.
> The legacy tables listed below were removed after a verified backup and
> rehearsal; active table counts remained 20,326. See `ARCHITECTURE.md` for the
> current design and runtime commands.

## Snapshot metadata

This baseline was captured on 2026-08-23 before production refactoring began.
It describes local runtime state and current code behavior; it is not a promise
that catalog row counts remain fixed after later synchronization.

- Git commit before Phase 1 changes:
  `bbc7367847b6eb9059c4dfec6c654ee9e93837fc`
- Python: 3.13.5
- SQLite: 3.46.1
- `items.db` size: 619,704,320 bytes
- Database `PRAGMA user_version`: 0
- Database `PRAGMA quick_check`: `ok`

## Direct dependency versions

| Dependency | Version |
| --- | --- |
| Flask | 3.1.3 |
| Gunicorn | 25.3.0 |
| httpx | 0.28.1 |
| OpenAI Python | 2.30.0 |
| python-dotenv | 1.2.2 |
| sqliteai-vector | 0.9.93 |
| tqdm | 4.67.3 |
| Ruff (development) | 0.16.4 |

These exact versions are recorded in `pyproject.toml`; production dependencies
are also mirrored in `requirements.txt` for the current deployment workflow.

## Database schema

| Table | Definition at capture time |
| --- | --- |
| `bibs` | `CREATE TABLE "bibs"(id PRIMARY KEY, title, publicationDate, coverUrl, editionId)` |
| `editions` | `CREATE TABLE "editions"(id PRIMARY KEY, author, itemLanguage, subjects, summary)` |
| `records` | `CREATE TABLE records(id PRIMARY KEY, title, author, publicationDate, itemLanguage, subjects, summary, coverUrl)` |
| `embeddings` | `CREATE TABLE "embeddings"(id PRIMARY KEY, embedding BLOB)` |
| `bibs_legacy` | Legacy five-column bibliographic table without a primary key. |
| `editions_legacy` | Legacy five-column edition table without a primary key. |
| `embeddings_legacy` | Legacy `id`/`embedding` table without a primary key. |
| `_sqliteai_vector` | sqliteai-vector metadata table. |
| `vector0_embeddings_embedding` | sqliteai-vector quantized data table. |

## Counts and relationships

| Check | Captured value |
| --- | ---: |
| `bibs` rows | 20,326 |
| `editions` rows | 20,326 |
| `records` rows | 20,326 |
| `embeddings` rows | 20,326 |
| `bibs_legacy` rows | 21,828 |
| `editions_legacy` rows | 21,828 |
| `embeddings_legacy` rows | 21,828 |
| Duplicate IDs in each active table | 0 |
| Bibliographic rows without an edition | 0 |
| Records without an embedding | 0 |
| Embeddings without a record | 0 |

There were 12 null `coverUrl` values in both `bibs` and `records`. No other
stored application field was null. Every embedding BLOB was 6,144 bytes, which
is consistent with 1,536 FLOAT32 values.

## Representative application behavior

Phase 1 tests preserve these current behaviors:

- Vega format-group requests use search text `*`, material type ID `1`, location
  ID `59`, page size 100, and the requested year/page values.
- Bibliographic parsing selects the medium cover and first edition in the first
  material tab.
- Edition parsing flattens authors, languages, all `subj*` fields, and summary
  notes into comma-separated strings.
- Embedding text labels and order are title, author, publication date,
  `lanugage`, subjects, and summary. The misspelled label is deliberately
  characterized rather than corrected in Phase 1.
- Both record and query embeddings use `text-embedding-3-small`.
- Stored embedding values are stringified before `vector_as_f32` insertion.
- SQL results are mapped using the eight `records` columns; vector distance is
  not exposed in the rendered dictionary.
- `/` renders the packaged search template and `/static/style.css` is served.
- `/search` passes the decoded query directly to search and renders the current
  record fields.
- A missing `query` parameter currently defaults to the string `Flask`.
- Gunicorn loads `flaskr:app`, binds to `0.0.0.0:8001`, and uses four workers.

External-client behavior is tested with deterministic fakes. No Phase 1 test
calls Vega or OpenAI, and representative live search result IDs are not pinned
because the remote model and evolving catalog make them unsuitable deterministic
test fixtures.

## Deterministic verification commands

```bash
make test
make lint
make check
```

`make check` is the Phase 1 gate and runs linting followed by all unit and
characterization tests.
