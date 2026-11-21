-- Feature store tables for RecoMart (custom registry + versioned snapshots).
-- Created / validated by feature_store.py. Tables prefixed fs_ are the feature store;
-- user_feature_store / item_feature_store / item_similarity (feature_schema.sql) are the
-- "current" transformation output that each snapshot is taken from.

-- Registry: documentation of every feature (name, source, transformation)
CREATE TABLE IF NOT EXISTS fs_registry (
    entity          TEXT NOT NULL,          -- user | item | item_pair
    feature_name    TEXT NOT NULL,
    dtype           TEXT NOT NULL,
    description     TEXT NOT NULL,
    source          TEXT NOT NULL,          -- raw table.column(s) the feature is derived from
    transformation  TEXT NOT NULL,          -- how it is computed
    PRIMARY KEY (entity, feature_name)
);

-- One row per feature snapshot (version)
CREATE TABLE IF NOT EXISTS fs_versions (
    version_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT    NOT NULL,     -- UTC, fixed-width ISO format (sortable)
    data_cutoff_ts    INTEGER,              -- newest interaction timestamp included in this version
    data_hash         TEXT    NOT NULL,     -- SHA-256 of the feature values (skips duplicate versions)
    user_rows         INTEGER,
    item_rows         INTEGER,
    similarity_rows   INTEGER,
    parameters_json   TEXT,                 -- transformation parameters used for this version
    definitions_json  TEXT,                 -- registry definitions at the time of the snapshot
    description       TEXT,
    is_active         INTEGER NOT NULL DEFAULT 0   -- the version served to inference by default
);
-- at most one active version
CREATE UNIQUE INDEX IF NOT EXISTS idx_fs_versions_active ON fs_versions (is_active) WHERE is_active = 1;

-- Versioned feature values
CREATE TABLE IF NOT EXISTS fs_user_features (
    version_id                   INTEGER NOT NULL,
    user_id                      INTEGER NOT NULL,
    gender_encoded               INTEGER,
    occupation_encoded           INTEGER,
    age_norm                     REAL,
    interaction_count            INTEGER,
    activity_frequency           REAL,
    activity_norm                REAL,
    avg_rating                   REAL,
    rating_std                   REAL,
    rating_bias                  REAL,
    first_interaction_ts         INTEGER,
    last_interaction_ts          INTEGER,
    days_since_last_interaction  REAL,
    PRIMARY KEY (version_id, user_id)
);

CREATE TABLE IF NOT EXISTS fs_item_features (
    version_id           INTEGER NOT NULL,
    item_id              INTEGER NOT NULL,
    category_encoded     INTEGER,
    price_norm           REAL,
    catalog_rating_norm  REAL,
    interaction_count    INTEGER,
    popularity_norm      REAL,
    avg_rating           REAL,
    rating_std           REAL,
    bayesian_avg_rating  REAL,
    rating_bias          REAL,
    PRIMARY KEY (version_id, item_id)
);

CREATE TABLE IF NOT EXISTS fs_item_similarity (
    version_id       INTEGER NOT NULL,
    item_id          INTEGER NOT NULL,
    similar_item_id  INTEGER NOT NULL,
    co_occurrence    INTEGER,
    cosine_sim       REAL,
    neighbor_rank    INTEGER,
    PRIMARY KEY (version_id, item_id, similar_item_id)
);
CREATE INDEX IF NOT EXISTS idx_fs_item_similarity_rank
    ON fs_item_similarity (version_id, item_id, neighbor_rank);
