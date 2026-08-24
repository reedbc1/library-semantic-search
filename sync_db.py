######################################################################
# Imports
######################################################################

import asyncio
import importlib.resources
import json
import logging
import sqlite3
from datetime import datetime

import tqdm
import tqdm.asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

import fetch_items

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(encoding="utf-8", level=logging.INFO)
fh = logging.FileHandler('history.log')
logger.addHandler(fh)
logging.getLogger("httpx").setLevel(logging.WARNING)

######################################################################
# Initialize sqlite3
######################################################################

def create_con():
    # conect to database
    con = sqlite3.connect("items.db")
    cur = con.cursor()

    # load sqliteai-vector extention
    ext_path = importlib.resources.files("sqlite_vector.binaries") / "vector"

    con.enable_load_extension(True)
    con.load_extension(str(ext_path))
    con.enable_load_extension(False)
    
    return (con, cur)


def ensure_embeddings_table(con, cur):
    existing_table = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'"
    ).fetchone()

    if existing_table is None:
        cur.execute("CREATE TABLE embeddings(id, embedding BLOB)")
        con.commit()
        return

    columns = cur.execute("PRAGMA table_info(embeddings)").fetchall()
    column_names = {column[1] for column in columns}

    if "embedding" in column_names:
        return

    if "BLOB" in column_names:
        logger.info(
            "migrating legacy embeddings table schema from column 'BLOB' to 'embedding'..."
        )
        cur.execute("ALTER TABLE embeddings RENAME TO embeddings_legacy")
        cur.execute("CREATE TABLE embeddings(id, embedding BLOB)")
        cur.execute(
            "INSERT INTO embeddings(id, embedding) "
            "SELECT id, BLOB FROM embeddings_legacy"
        )
        cur.execute("DROP TABLE embeddings_legacy")
        con.commit()
        return

    raise sqlite3.OperationalError(
        "Could not find an 'embedding' column in table 'embeddings'."
    )

######################################################################
# Bibs
######################################################################

def bibs(con, cur):
    # create table if it doesn't exist
    cur.execute("CREATE TABLE IF NOT EXISTS bibs(id PRIMARY KEY, title, publicationDate, coverUrl, editionId)")

    # fetch bibs with API
    api_data, api_ids = asyncio.run(fetch_items.fetch_all_bibs())

    # generate diff with bib table (insert/delete/unchanged)
    res = cur.execute("SELECT id FROM bibs").fetchall()
    db_ids = {id[0] for id in res}

    to_insert = api_ids - db_ids
    to_delete = db_ids - api_ids
    unchanged = api_ids & db_ids

    # log diff
    logger.info("bibs diff:")
    logger.info(f"to_insert: {len(to_insert)}")
    logger.info(f"to_delete: {len(to_delete)}")
    logger.info(f"unchanged: {len(unchanged)}")

    # insert records
    records_to_insert = {record for record in api_data if record[0] in to_insert}
    cur.executemany("INSERT INTO bibs VALUES(?, ?, ?, ?, ?)", records_to_insert)
    con.commit()  # Remember to commit the transaction after executing INSERT.

    # delete records
    if len(to_delete) == 0:
        return
    elif len(to_delete) == 1:
        placeholders = "?,"
    else:
        placeholders = ','.join(['?' for _ in to_delete])

    query = f"DELETE FROM bibs WHERE id IN ({placeholders})"
    ids_to_delete = [id for id in to_delete]

    cur.execute(query, ids_to_delete)
    con.commit()

######################################################################
# Editions
######################################################################

def editions(con, cur):
    # create table if it doesn't exist
    cur.execute("CREATE TABLE IF NOT EXISTS editions(id PRIMARY KEY, author, itemLanguage, subjects, summary)")

    # use bib table to generate diff with editions table
    res = cur.execute("SELECT editionId FROM bibs").fetchall()
    bib_e_ids = {r[0] for r in res}

    res = cur.execute("SELECT id from editions").fetchall()
    edition_ids = {r[0] for r in res}

    to_insert = bib_e_ids - edition_ids
    to_delete = edition_ids - bib_e_ids
    unchanged = bib_e_ids & edition_ids

    # log diff
    logger.info("editions diff:")
    logger.info(f"to_insert: {len(to_insert)}")
    logger.info(f"to_delete: {len(to_delete)}")
    logger.info(f"unchanged: {len(unchanged)}")

    # delete records in editions table not in bib table
    placeholders = ','.join(['?' for _ in to_delete])
    query = f"DELETE FROM editions WHERE id IN ({placeholders})"
    ids_to_delete = [id for id in to_delete]

    cur.execute(query, ids_to_delete)
    con.commit()

    to_insert_list = list(to_insert)

    # fetch editions for new records and add to editions table
    for i in tqdm.tqdm(range(0, len(to_insert_list), 100)):

        if i + 99 <= len(to_insert_list):
            j = i + 99
        else:
            j = len(to_insert_list) 
        
        editions_slice = asyncio.run(fetch_items.fetch_all_editions(to_insert_list[i:j+1]))

        # insert records
        cur.executemany("INSERT INTO editions VALUES(?, ?, ?, ?, ?)", editions_slice)
        con.commit()

######################################################################
# Sync
######################################################################

def sync(con, cur, logger):
    logger.info(f"current time: {datetime.now()}")
    logger.info("starting sync...")
    logger.info("################################")
    bibs(con, cur)
    logger.info("################################")
    editions(con, cur)
    logger.info("################################")
    join_tables(con, cur)
    logger.info("################################")
    sync_embeddings(con, cur)
    logger.info("################################")
    logger.info("sync complete.")

######################################################################
# Joining Tables
######################################################################

def join_tables(con, cur):
    logger.info("creating records table...")
    # drop pre-existing table
    cur.execute("DROP TABLE IF EXISTS records")
    cur.execute("CREATE TABLE records(id PRIMARY KEY, title, author, publicationDate, itemLanguage, subjects, summary, coverUrl)")
    
    # join bibs and editions on editionId = id
    query: str = """
    INSERT INTO records 
    SELECT 
        b.id, 
        b.title, 
        e.author, 
        b.publicationDate, 
        e.itemLanguage, 
        e.subjects, 
        e.summary, 
        b.coverUrl 
    FROM bibs b 
    INNER JOIN editions e 
    ON e.id = b.editionId;
    """

    cur.execute(query)
    con.commit()
    logger.info("records table created.")

######################################################################
# Embeddings
######################################################################

# get text to put into embeddings model
def get_collection(con, cur, to_insert) -> list:
    ensure_embeddings_table(con, cur)

    query = f"""
    SELECT
        id,
        title,
        author,
        publicationDate,
        itemLanguage,
        subjects,
        summary
    FROM records r
    WHERE id IN {tuple(to_insert)};
    """
    
    cur.execute(query)
    records = cur.fetchall()
    logger.info("query completed.")

    field_names = ["title: ", ", author: ", ", publication date: ", ", lanugage: ", ", subjects: ", ", summary: "]
    collection = []

    for r in records:
        id = r[0]
        text = ""

        for i in range(len(field_names)):
            text += field_names[i] + r[i+1]

        collection.append((id, text))

    return collection

# create embeddings for individual record
async def create_embedding(client, id: str, text: str):
    response = await client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    embedding = response.data[0].embedding
    return (id, str(embedding))

# get embeddings for all records
async def get_embeddings(col):
    con, cur = create_con()
    client = AsyncOpenAI()
    logger.info("creating embeddings...")
    coroutines = [create_embedding(client, *record) for record in col]
    embeddings = await tqdm.asyncio.tqdm.gather(*coroutines)
    return embeddings

# generate embeddings and put into table
def embeddings_table(con, cur, embeddings):
    ensure_embeddings_table(con, cur)
    cur.executemany(
        "INSERT INTO embeddings(id, embedding) VALUES(?, vector_as_f32(?))",
        embeddings,
    )
    con.commit()

# putting it all together
def sync_embeddings(con, cur):
    logger.info("starting sync_embeddings")
    
    # selects records where id is not in embeddings
    alt_query = "SELECT id FROM embeddings;"
    res1 = cur.execute(alt_query).fetchall()
    em_ids = {item[0] for item in res1}
    res2 = cur.execute("SELECT id FROM records").fetchall()
    r_ids = {item[0] for item in res2}

    to_insert = r_ids - em_ids
    to_delete = em_ids - r_ids
    unchanged = em_ids & r_ids

    logger.info("embeddings diff:")
    logger.info(f"to insert: {len(to_insert)}")
    logger.info(f"to delete: {len(to_delete)}")
    logger.info(f"unchanged: {len(unchanged)}")

    # delete embeddings
    cur.execute(f"DELETE FROM embeddings WHERE id IN {tuple(to_delete)}")
    con.commit()

    # insert embeddings
    col = get_collection(con, cur, to_insert)

    for i in range(0, len(col), 100):
        if i + 99 > len(col):
            j = len(col)
        else:
            j = i + 99
    
        embeddings = asyncio.run(get_embeddings(col[i:j+1]))
        embeddings_table(con, cur, embeddings)
    logger.info("embeddings table updated.")

######################################################################
# Similarity Search
######################################################################

# embed query
def embed_query(query: str):
    client = OpenAI()
    response = client.embeddings.create(
        input=query,
        model="text-embedding-3-small"
    )
    embedding = response.data[0].embedding
    return embedding

# cosine similarity search
def sim_search(con, cur, user_query: str):
    ensure_embeddings_table(con, cur)
    q_embed = embed_query(user_query)
    q_json = json.dumps(q_embed)

    # initialize vector
    cur.execute("SELECT vector_init('embeddings', 'embedding', 'type=FLOAT32,dimension=1536');")

    # quantize vector
    cur.execute("SELECT vector_quantize('embeddings', 'embedding');")

    # create temporary table of nearest n neighbors
    cur.execute("DROP TABLE IF EXISTS nearest_neighbors")

    query = """
    CREATE TEMP TABLE IF NOT EXISTS nearest_neighbors AS
    SELECT e.id, v.distance FROM embeddings AS e
    JOIN vector_quantize_scan('embeddings', 'embedding', vector_as_f32(?), 100) AS v
    ON e.rowid = v.rowid;
    """

    cur.execute(query, (q_json,))
    
    # inner join temporary table to records table
    query = """
    SELECT r.*, n.distance FROM records AS r
    INNER JOIN nearest_neighbors AS n
    ON r.id = n.id
    ORDER BY n.distance;
    """

    res = cur.execute(query).fetchall()
    res_json = sql_to_json(con, cur, res)

    # output results
    return res

def sql_to_json(con, cur, results):
    col_names = cur.execute("PRAGMA table_info(records);").fetchall()
    col_names = [tup[1] for tup in col_names]
    print(col_names)
    records = []
    for tup in results:
        record = {}
        for i in range(len(col_names)):
            record[col_names[i]] = tup[i]
        records.append(record)
    return records

if __name__ == "__main__":
    con, cur = create_con()
    sync(con, cur, logger)
