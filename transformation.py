"""Feature engineering and transformation for the RecoMart recommendation pipeline.

Reads the outputs of the preparation step (data/processed/*.csv), builds
features for recommendation algorithms and stores them in SQLite
(same database as the raw tables, schema in feature_schema.sql):

- user_feature_store  : demographics + activity frequency + average rating per user
- item_feature_store  : catalog features + popularity + average rating per item
- item_similarity     : top-K similar items (co-occurrence + adjusted cosine)

Also writes data/reports/feature_summary.json.

Every run fully refreshes the three tables inside one transaction, so the step
is safe to re-run and never leaves them half-updated.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd

DB_PATH = "data/recomart.db"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feature_schema.sql")

USERS_IN = "data/processed/users_prepared.csv"
ITEMS_IN = "data/processed/items_prepared.csv"
INTERACTIONS_IN = "data/processed/interactions_observed_prepared.csv"
SUMMARY_PATH = "data/reports/feature_summary.json"

SECONDS_PER_DAY = 86400
BAYES_PRIOR_WEIGHT = 5     # "virtual ratings" at the global mean used to shrink item averages
TOP_K_NEIGHBORS = 20       # neighbours stored per item
MIN_CO_OCCURRENCE = 2      # a pair needs at least this many common users to be scored
BLOCK_SIZE = 500           # items processed per block (limits memory use)

log = logging.getLogger(__name__)


def min_max(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    mn, mx = s.min(), s.max()
    if pd.isna(mn) or pd.isna(mx) or mn == mx:
        return pd.Series([0.0] * len(s), index=s.index)
    return (s - mn) / (mx - mn)


def require_columns(df: pd.DataFrame, cols: list, name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"{name} is missing columns {missing}. Re-run the preparation step.")


def build_user_features(users, interactions, global_mean, max_ts, computed_at) -> pd.DataFrame:
    require_columns(users, ["user_id", "gender_encoded", "occupation_encoded", "age_norm"], USERS_IN)

    stats = interactions.groupby("user_id").agg(
        interaction_count=("item_id", "size"),
        avg_rating=("rating", "mean"),
        rating_std=("rating", "std"),
        first_interaction_ts=("timestamp", "min"),
        last_interaction_ts=("timestamp", "max"),
    ).reset_index()

    span_days = (
        (stats["last_interaction_ts"] - stats["first_interaction_ts"]) / SECONDS_PER_DAY
    ).clip(lower=1.0)
    stats["activity_frequency"] = stats["interaction_count"] / span_days
    stats["days_since_last_interaction"] = (max_ts - stats["last_interaction_ts"]) / SECONDS_PER_DAY

    base = users[["user_id", "gender_encoded", "occupation_encoded", "age_norm"]]
    out = base.drop_duplicates(subset="user_id").merge(stats, on="user_id", how="left")

    # Users with no interactions (cold start) get neutral defaults
    out["interaction_count"] = out["interaction_count"].fillna(0).astype(int)
    out["activity_frequency"] = out["activity_frequency"].fillna(0.0)
    out["activity_norm"] = min_max(out["interaction_count"])
    out["avg_rating"] = out["avg_rating"].fillna(global_mean)
    out["rating_std"] = out["rating_std"].fillna(0.0)
    out["rating_bias"] = out["avg_rating"] - global_mean
    out["first_interaction_ts"] = out["first_interaction_ts"].round().astype("Int64")
    out["last_interaction_ts"] = out["last_interaction_ts"].round().astype("Int64")
    out["computed_at"] = computed_at

    return out[[
        "user_id", "gender_encoded", "occupation_encoded", "age_norm",
        "interaction_count", "activity_frequency", "activity_norm",
        "avg_rating", "rating_std", "rating_bias",
        "first_interaction_ts", "last_interaction_ts", "days_since_last_interaction",
        "computed_at",
    ]]


def build_item_features(items, interactions, global_mean, computed_at) -> pd.DataFrame:
    require_columns(items, ["item_id", "category_encoded", "price_norm", "catalog_rating_norm"], ITEMS_IN)

    stats = interactions.groupby("item_id").agg(
        interaction_count=("user_id", "size"),
        avg_rating=("rating", "mean"),
        rating_std=("rating", "std"),
    ).reset_index()

    base = items[["item_id", "category_encoded", "price_norm", "catalog_rating_norm"]]
    out = base.drop_duplicates(subset="item_id").merge(stats, on="item_id", how="left")

    # Items with no interactions (cold start) fall back to the global mean
    out["interaction_count"] = out["interaction_count"].fillna(0).astype(int)
    out["popularity_norm"] = min_max(out["interaction_count"])
    out["avg_rating"] = out["avg_rating"].fillna(global_mean)
    out["rating_std"] = out["rating_std"].fillna(0.0)
    out["bayesian_avg_rating"] = (
        BAYES_PRIOR_WEIGHT * global_mean + out["interaction_count"] * out["avg_rating"]
    ) / (BAYES_PRIOR_WEIGHT + out["interaction_count"])
    out["rating_bias"] = out["avg_rating"] - global_mean
    out["computed_at"] = computed_at

    return out[[
        "item_id", "category_encoded", "price_norm", "catalog_rating_norm",
        "interaction_count", "popularity_norm", "avg_rating", "rating_std",
        "bayesian_avg_rating", "rating_bias", "computed_at",
    ]]


def compute_item_similarity(
    interactions, computed_at, top_k=TOP_K_NEIGHBORS, min_co=MIN_CO_OCCURRENCE, block_size=BLOCK_SIZE
) -> pd.DataFrame:
    """Top-K neighbours per item using co-occurrence counts and adjusted cosine similarity.

    Ratings are centred on each user's mean (adjusted cosine), so a 4.0 from a harsh
    rater counts for more than a 4.0 from a generous one. Only pairs with at least
    `min_co` common users and a positive similarity are kept.
    """
    columns = ["item_id", "similar_item_id", "co_occurrence", "cosine_sim", "neighbor_rank", "computed_at"]

    u_codes, u_index = pd.factorize(interactions["user_id"])
    i_codes, i_index = pd.factorize(interactions["item_id"])
    i_index = np.asarray(i_index)
    n_users, n_items = len(u_index), len(i_index)

    k = min(top_k, n_items - 1)
    if k < 1:
        return pd.DataFrame(columns=columns)

    ratings = interactions["rating"].to_numpy(dtype=np.float64)
    user_mean = np.bincount(u_codes, weights=ratings, minlength=n_users) / np.bincount(u_codes, minlength=n_users)

    # Dense user x item matrices: centred ratings and a 0/1 "interacted" mask
    R = np.zeros((n_users, n_items), dtype=np.float32)
    B = np.zeros((n_users, n_items), dtype=np.float32)
    R[u_codes, i_codes] = ratings - user_mean[u_codes]
    B[u_codes, i_codes] = 1.0
    norms = np.sqrt((R ** 2).sum(axis=0))

    frames = []
    for start in range(0, n_items, block_size):
        end = min(start + block_size, n_items)

        co = B[:, start:end].T @ B                      # common users per item pair
        dot = R[:, start:end].T @ R
        denom = norms[start:end, None] * norms[None, :]
        sim = np.divide(dot, denom, out=np.zeros_like(dot), where=denom > 0)

        sim[(co < min_co) | (sim <= 0)] = -np.inf       # too little evidence / not similar
        rows = np.arange(end - start)
        sim[rows, np.arange(start, end)] = -np.inf      # an item is not its own neighbour

        top = np.argpartition(-sim, k - 1, axis=1)[:, :k]
        top_sim = np.take_along_axis(sim, top, axis=1)
        order = np.argsort(-top_sim, axis=1, kind="stable")
        top = np.take_along_axis(top, order, axis=1)
        top_sim = np.take_along_axis(top_sim, order, axis=1)
        top_co = np.take_along_axis(co, top, axis=1)

        r_idx, c_idx = np.nonzero(np.isfinite(top_sim))
        if len(r_idx) == 0:
            continue
        frames.append(pd.DataFrame({
            "item_id": i_index[start + r_idx],
            "similar_item_id": i_index[top[r_idx, c_idx]],
            "co_occurrence": top_co[r_idx, c_idx].astype(int),
            "cosine_sim": np.round(top_sim[r_idx, c_idx].astype(np.float64), 6),
            "neighbor_rank": c_idx + 1,
            "computed_at": computed_at,
        }))

    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)[columns]


def replace_table(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    """Delete all rows and insert `df` (part of the caller's transaction, no commit here)."""
    conn.execute(f"DELETE FROM {table}")
    if df.empty:
        return
    cols = list(df.columns)
    records = [
        tuple(None if pd.isna(v) else v for v in row)
        for row in df.astype(object).itertuples(index=False, name=None)
    ]
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        records,
    )


def transform_data() -> dict:
    for path in (USERS_IN, ITEMS_IN, INTERACTIONS_IN):
        if not os.path.exists(path):
            raise FileNotFoundError(f"{path} not found. Run the preparation step first.")

    users = pd.read_csv(USERS_IN)
    items = pd.read_csv(ITEMS_IN)
    interactions = pd.read_csv(INTERACTIONS_IN, usecols=["user_id", "item_id", "rating", "timestamp"])
    if interactions.empty:
        raise ValueError(f"{INTERACTIONS_IN} has no rows; nothing to build features from.")

    log.info("Building features from %d users, %d items, %d interactions",
             len(users), len(items), len(interactions))

    global_mean = float(interactions["rating"].mean())
    max_ts = float(interactions["timestamp"].max())
    computed_at = datetime.now(timezone.utc).isoformat()

    user_feats = build_user_features(users, interactions, global_mean, max_ts, computed_at)
    item_feats = build_item_features(items, interactions, global_mean, computed_at)
    similarity = compute_item_similarity(interactions, computed_at)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        replace_table(conn, "user_feature_store", user_feats)
        replace_table(conn, "item_feature_store", item_feats)
        replace_table(conn, "item_similarity", similarity)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    summary = {
        "generated_at": computed_at,
        "global_mean_rating": round(global_mean, 6),
        "user_feature_rows": int(len(user_feats)),
        "item_feature_rows": int(len(item_feats)),
        "item_similarity_rows": int(len(similarity)),
        "items_with_neighbors": int(similarity["item_id"].nunique()) if len(similarity) else 0,
        "parameters": {
            "bayes_prior_weight": BAYES_PRIOR_WEIGHT,
            "top_k_neighbors": TOP_K_NEIGHBORS,
            "min_co_occurrence": MIN_CO_OCCURRENCE,
        },
        "tables": ["user_feature_store", "item_feature_store", "item_similarity"],
    }
    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log.info("Feature transformation completed: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    transform_data()
