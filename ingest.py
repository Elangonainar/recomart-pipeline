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

def ingest_data():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Initialize Schema
    with open("schema.sql", "r") as f:
        cursor.executescript(f.read())
    print("[INFO] SQLite schema initialized successfully.")

    # Clear child table first so the reload is idempotent on reruns
    cursor.executescript("DELETE FROM interactions; DELETE FROM user_features; DELETE FROM item_features;")

    # 1. Ingest User Features
    for file in glob.glob("data/raw/users/date=*/*.csv"):
        df = pd.read_csv(file)
        df.to_sql("user_features", conn, if_exists="append", index=False)
        print(f"[SUCCESS] Ingested user features from {file}")

    # 2. Ingest Item Features
    for file in glob.glob("data/raw/items/date=*/*.csv"):
        df = pd.read_csv(file)
        df.to_sql("item_features", conn, if_exists="append", index=False)
        print(f"[SUCCESS] Ingested item features from {file}")

    # 3. Ingest Interactions (MovieLens ratings.csv formatted)
    for file in glob.glob("data/raw/interactions/date=*/*.csv"):
        df = pd.read_csv(file)
        df.to_sql("interactions", conn, if_exists="append", index=False)
        print(f"[SUCCESS] Ingested interactions from {file}")

    conn.commit()
    conn.close()
    print("[INFO] Data ingestion completed successfully.")

if __name__ == "__main__":
    ingest_data()
