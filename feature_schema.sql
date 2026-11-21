-- Feature store tables for the RecoMart recommendation pipeline.
-- These tables are derived: transformation.py fully refreshes them on every run.
-- (The raw tables user_features / item_features / interactions are defined in schema.sql.)

-- One row per user: demographics + behavioural features
CREATE TABLE IF NOT EXISTS user_feature_store (
    user_id                      INTEGER PRIMARY KEY,
    gender_encoded               INTEGER,
    occupation_encoded           INTEGER,
    age_norm                     REAL,
    interaction_count            INTEGER NOT NULL DEFAULT 0,
    activity_frequency           REAL,      -- interactions per active day
    activity_norm                REAL,      -- interaction_count, min-max scaled
    avg_rating                   REAL,
    rating_std                   REAL,
    rating_bias                  REAL,      -- avg_rating - global mean rating
    first_interaction_ts         INTEGER,
    last_interaction_ts          INTEGER,
    days_since_last_interaction  REAL,      -- relative to newest interaction in the data
    computed_at                  TEXT
);

-- One row per item: catalog features + popularity / rating features
CREATE TABLE IF NOT EXISTS item_feature_store (
    item_id                      INTEGER PRIMARY KEY,
    category_encoded             INTEGER,
    price_norm                   REAL,
    catalog_rating_norm          REAL,
    interaction_count            INTEGER NOT NULL DEFAULT 0,
    popularity_norm              REAL,      -- interaction_count, min-max scaled
    avg_rating                   REAL,
    rating_std                   REAL,
    bayesian_avg_rating          REAL,      -- avg_rating shrunk toward the global mean
    rating_bias                  REAL,      -- avg_rating - global mean rating
    computed_at                  TEXT
);

-- Top-K most similar items per item (item-item collaborative signal)
CREATE TABLE IF NOT EXISTS item_similarity (
    item_id          INTEGER NOT NULL,
    similar_item_id  INTEGER NOT NULL,
    co_occurrence    INTEGER NOT NULL,      -- number of users who interacted with both items
    cosine_sim       REAL    NOT NULL,      -- adjusted cosine (ratings centred per user)
    neighbor_rank    INTEGER NOT NULL,      -- 1 = most similar
    computed_at      TEXT,
    PRIMARY KEY (item_id, similar_item_id)
);

CREATE INDEX IF NOT EXISTS idx_item_similarity_rank
    ON item_similarity (item_id, neighbor_rank);