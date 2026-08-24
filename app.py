import sqlite3

from flask import Flask, g, render_template, request

import sync_db

app = Flask(__name__)

DATABASE = '/items.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.route("/")
def index():
    return render_template('index.html')

@app.route("/search")
def search():
    con, cur = sync_db.create_con()
    query = request.args.get("query", "Flask")
    results = sync_db.sim_search(con, cur, user_query=query)
    results = sync_db.sql_to_json(con, cur, results)
    return render_template('results.html', results=results)
