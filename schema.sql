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
-- Safe to run on every task: CREATE ... IF NOT EXISTS never alters existing tables,
-- so delete data/recomart.db once after changing an existing table definition.

-- =====================================================================
-- Raw tables (loaded by ingest.py)
-- =====================================================================

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

CREATE INDEX IF NOT EXISTS idx_interactions_user ON interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_item ON interactions(item_id);

-- =====================================================================
-- Engineered features (rebuilt in full by features.py on every run)
-- =====================================================================

-- One row per user: activity frequency, average rating, recency
CREATE TABLE IF NOT EXISTS feat_user_activity (
    user_id                      INTEGER PRIMARY KEY,
    n_interactions               INTEGER NOT NULL,   -- ratings given (activity volume)
    n_distinct_items             INTEGER NOT NULL,
    avg_rating                   REAL,               -- user's mean rating (rating bias)
    rating_std                   REAL,               -- 0 when the user has a single rating
    pct_high_ratings             REAL,               -- share of ratings >= HIGH_RATING_THRESHOLD
    first_interaction_ts         INTEGER,
    last_interaction_ts          INTEGER,
    active_days                  INTEGER,            -- distinct UTC days with at least one rating
    interactions_per_active_day  REAL,               -- activity frequency
    activity_span_days           REAL,               -- last - first interaction, in days
    recency_days                 REAL,               -- days between last interaction and newest one in the data
    computed_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- One row per item: popularity and rating statistics
CREATE TABLE IF NOT EXISTS feat_item_stats (
    item_id               INTEGER PRIMARY KEY,
    n_interactions        INTEGER NOT NULL,          -- popularity
    n_users               INTEGER NOT NULL,
    avg_rating            REAL,                      -- raw mean rating
    bayesian_avg_rating   REAL,                      -- mean shrunk toward global mean (stable for rarely rated items)
    rating_std            REAL,
    pct_high_ratings      REAL,
    popularity_rank       INTEGER,                   -- 1 = most rated
    first_interaction_ts  INTEGER,
    last_interaction_ts   INTEGER,
    computed_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Top-K most similar items per item (item-item collaborative filtering signal)
CREATE TABLE IF NOT EXISTS feat_item_similarity (
    item_id              INTEGER NOT NULL,
    similar_item_id      INTEGER NOT NULL,
    neighbor_rank        INTEGER NOT NULL,           -- 1 = most similar
    co_occurrence_count  INTEGER NOT NULL,           -- users who rated both items
    jaccard              REAL,                       -- co / (n_a + n_b - co)
    cosine_sim           REAL,                       -- cosine of the two items' rating vectors
    computed_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (item_id, similar_item_id)
);