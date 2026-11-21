# import os
# import glob
# import sqlite3
# import pandas as pd

# DB_PATH = "data/recomart.db"

# def ingest_data():
#     os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()
    
#     # Initialize Schema
#     with open("schema.sql", "r") as f:
#         cursor.executescript(f.read())
#     print("[INFO] SQLite schema initialized successfully.")

#     # 1. Ingest User Features
#     for file in glob.glob("data/raw/users/date=*/*.csv"):
#         df = pd.read_csv(file)
#         df.to_sql("user_features", conn, if_exists="append", index=False)
#         print(f"[SUCCESS] Ingested user features from {file}")

#     # 2. Ingest Item Features
#     for file in glob.glob("data/raw/items/date=*/*.csv"):
#         df = pd.read_csv(file)
#         df.to_sql("item_features", conn, if_exists="append", index=False)
#         print(f"[SUCCESS] Ingested item features from {file}")

#     # 3. Ingest Interactions (MovieLens ratings.csv formatted)
#     for file in glob.glob("data/raw/interactions/date=*/*.csv"):
#         df = pd.read_csv(file)
#         df.to_sql("interactions", conn, if_exists="append", index=False)
#         print(f"[SUCCESS] Ingested interactions from {file}")

#     conn.commit()
#     conn.close()
#     print("[INFO] Data ingestion completed successfully.")

# if __name__ == "__main__":
#     ingest_data()


import os
import glob
import sqlite3
import pandas as pd

DB_PATH = "data/recomart.db"

SOURCES = [
    ("user_features", "data/raw/users/date=*/*.csv"),
    ("item_features", "data/raw/items/date=*/*.csv"),
    ("interactions",  "data/raw/interactions/date=*/*.csv"),  # MovieLens ratings format
]

def upsert_csv(conn, table, file):
    """Load a CSV into `table`. Rows that collide on the table's PRIMARY KEY /
    UNIQUE constraint replace the existing row instead of raising IntegrityError."""
    df = pd.read_csv(file)
    if df.empty:
        return 0
    cols = ", ".join(f'"{c}"' for c in df.columns)
    placeholders = ", ".join("?" * len(df.columns))
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})",
        df.itertuples(index=False, name=None),
    )
    return len(df)

def ingest_data():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        # Initialize Schema
        with open("schema.sql", "r") as f:
            conn.executescript(f.read())
        print("[INFO] SQLite schema initialized successfully.")

        # sorted() so later date partitions are loaded last and win on conflicts
        for table, pattern in SOURCES:
            for file in sorted(glob.glob(pattern)):
                n = upsert_csv(conn, table, file)
                print(f"[SUCCESS] Ingested {n} rows into {table} from {file}")

        conn.commit()
        print("[INFO] Data ingestion completed successfully.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    ingest_data()