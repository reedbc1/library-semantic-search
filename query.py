import sqlite3

import sync_db

con = sqlite3.connect("items.db")
cur = con.cursor()

# Delete all from tables
def del_rows():
    cur.execute("DELETE FROM bibs WHERE 1=1;")
    cur.execute("DELETE FROM editions WHERE 1=1;")
    cur.execute("DELETE FROM embeddings WHERE 1=1")
    con.commit()
    print("All records deleted.")

# Select count of table
def select_count():
    b_count = cur.execute("SELECT COUNT(*) from bibs;").fetchone()
    e_count = cur.execute("SELECT COUNT(*) from editions;").fetchone()
    r_count = cur.execute("SELECT COUNT(*) FROM records;").fetchone()
    em_count = cur.execute("SELECT COUNT(id) FROM embeddings").fetchone()
    print(f"bib count: {b_count}\neditions count: {e_count}")
    print(f"records count: {r_count}")
    print(f"embeddings count: {em_count}")

def select(table):
    res = cur.execute(f"SELECT COUNT(DISTINCT id) FROM {table} GROUP BY id HAVING COUNT(id)>1")
    return res.fetchall()

def distinct_tables(table_name: str):
    # cur.execute("CREATE TEMP TABLE temp_ids AS SELECT DISTINCT id FROM embeddings;")

    cur.execute(f"CREATE TABLE new_table as SELECT DISTINCT * FROM {table_name};")
    cur.execute(f"DROP TABLE {table_name};")

    cur.execute(f"CREATE TABLE {table_name} AS SELECT DISTINCT * FROM new_table;")
    cur.execute("DROP TABLE new_table;")
    
    con.commit()

def remove_dup_em():
    ids_to_remove = cur.execute("SELECT id, count(id) FROM embeddings group by id having count(id) > 1;").fetchall()
    print(ids_to_remove)
    list_to_remove = [item[0] for item in ids_to_remove]
    tup_to_remove = tuple(list_to_remove)
    print(tup_to_remove)
    cur.execute(f"DELETE FROM embeddings WHERE id IN {tup_to_remove};")
    con.commit()

def add_primary_keys():
    cur.execute("DROP TABLE IF EXISTS embeddings2")
    cur.execute("CREATE TABLE embeddings2(id PRIMARY KEY, embedding BLOB);")
    cur.execute("INSERT INTO embeddings2 SELECT id, embedding FROM embeddings;")
    con.commit()
    return cur.execute("SELECT * FROM embeddings2").fetchall()

def rename_tables():
    cur.execute("DROP TABLE IF EXISTS embeddings_legacy")
    cur.execute("ALTER TABLE embeddings RENAME TO embeddings_legacy;")
    cur.execute("ALTER TABLE embeddings2 RENAME TO embeddings;")
    con.commit()

def add_primary_key_bibs():
    query = """
    DROP TABLE IF EXISTS bibs2;
    CREATE TABLE bibs2(id PRIMARY KEY, title, publicationDate, coverUrl, editionId);
    INSERT INTO bibs2 SELECT * from bibs;

    DROP TABLE IF EXISTS bibs_legacy;
    ALTER TABLE bibs RENAME TO bibs_legacy;
    ALTER TABLE bibs2 RENAME TO bibs;
    """
    cur.executescript(query)
    con.commit()

def add_primary_key_editions():
    query = """
    DROP TABLE IF EXISTS editions2;
    CREATE TABLE editions2(id PRIMARY KEY, author, itemLanguage, subjects, summary);
    INSERT INTO editions2 SELECT * from editions;

    DROP TABLE IF EXISTS editions_legacy;
    ALTER TABLE editions RENAME TO editions_legacy;
    ALTER TABLE editions2 RENAME TO editions;
    """
    cur.executescript(query)
    con.commit()

def table_info(table_name):
    res = cur.execute(f"PRAGMA table_info({table_name})").fetchall()
    print(res)

if __name__ == "__main__":
    # add_primary_key_editions()
    # res = cur.execute("SELECT * FROM editions limit 10;").fetchall()
    # print(res)
    # select_count()
    # res = cur.execute("pragma table_info(editions)").fetchall()
    # print(res)

    res = cur.execute("select itemLanguage, count(itemLanguage) from editions group by itemLanguage;")
    fetched_res = res.fetchall()
    print(fetched_res)
