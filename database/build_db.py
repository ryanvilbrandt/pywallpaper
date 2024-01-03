import sqlite3
from sqlite3 import Cursor


def open_db():
    db = sqlite3.connect("database/main.db")
    cur = db.cursor()
    return db, cur


def drop_tables(cur: Cursor):
    print("Dropping all tables in database...")

    sql = """
        DROP TABLE IF EXISTS images;
    """
    cur.executescript(sql)

    tables = get_all_tables(cur)
    if tables:
        raise Exception(f"Some tables were not deleted: {tables}")


def run_ddl(cur: Cursor, ddl_filepath: str):
    with open(ddl_filepath) as f:
        cur.executescript(f.read())


def get_all_tables(cur):
    sql = "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    return cur.execute(sql).fetchall()


def show_tables(cur):
    for row in get_all_tables(cur):
        print(row[0])


def build_db():
    db, cur = open_db()
    # drop_tables(cur)
    run_ddl(cur, "database/tables.ddl")
    db.commit()
    show_tables(cur)
    db.close()
