-- CREATE TABLE IF NOT EXISTS user_features (
--     user_id INTEGER PRIMARY KEY,
--     age INTEGER,
--     gender TEXT,
--     occupation TEXT,
--     zip_code TEXT,
--     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
-- );

-- CREATE TABLE IF NOT EXISTS item_features (
--     item_id INTEGER PRIMARY KEY,
--     title TEXT,
--     category TEXT,
--     price REAL,
--     rating REAL,
--     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
-- );

-- CREATE TABLE IF NOT EXISTS interactions (
--     interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
--     user_id INTEGER,
--     item_id INTEGER,
--     rating REAL,
--     timestamp INTEGER,
--     partition_date TEXT,
--     FOREIGN KEY (user_id) REFERENCES user_features(user_id),
--     FOREIGN KEY (item_id) REFERENCES item_features(item_id)
-- );
-- RecoMart schema
-- Safe to run on every ingestion: CREATE ... IF NOT EXISTS never alters existing tables,
-- so delete data/recomart.db once after changing any table definition below.

CREATE TABLE IF NOT EXISTS user_features (
    user_id     INTEGER PRIMARY KEY,
    age         INTEGER,
    gender      TEXT,
    occupation  TEXT,
    zip_code    TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS item_features (
    item_id     INTEGER PRIMARY KEY,
    title       TEXT,
    category    TEXT,
    price       REAL,
    rating      REAL,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interactions (
    interaction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    item_id         INTEGER NOT NULL,
    rating          REAL,
    timestamp       INTEGER NOT NULL,
    partition_date  TEXT,
    -- natural key: lets INSERT OR REPLACE detect re-loaded rows, so re-runs don't duplicate
    UNIQUE (user_id, item_id, timestamp),
    FOREIGN KEY (user_id) REFERENCES user_features(user_id),
    FOREIGN KEY (item_id) REFERENCES item_features(item_id)
);

-- Speeds up per-user / per-item lookups during EDA and feature engineering
CREATE INDEX IF NOT EXISTS idx_interactions_user ON interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_item ON interactions(item_id);