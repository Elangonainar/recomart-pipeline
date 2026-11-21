"""Data preparation and EDA for RecoMart recommendation pipeline.

Outputs:
- data/processed/users_prepared.csv
- data/processed/items_prepared.csv
- data/processed/interactions_observed_prepared.csv
- data/processed/interactions_prepared.csv  (dense user-item matrix with imputed ratings)
- data/reports/eda/rating_distribution.png
- data/reports/eda/item_popularity.png
- data/reports/eda/interaction_sparsity_heatmap.png
- data/reports/preparation_summary.json
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import seaborn as sns
from matplotlib import pyplot as plt

DB_PATH = "data/recomart.db"
LOG_PATH = "logs/preparation.log"

USERS_OUT = "data/processed/users_prepared.csv"
ITEMS_OUT = "data/processed/items_prepared.csv"
INTERACTIONS_OBS_OUT = "data/processed/interactions_observed_prepared.csv"
INTERACTIONS_DENSE_OUT = "data/processed/interactions_prepared.csv"

EDA_DIR = "data/reports/eda"
RATING_PLOT = os.path.join(EDA_DIR, "rating_distribution.png")
POPULARITY_PLOT = os.path.join(EDA_DIR, "item_popularity.png")
SPARSITY_PLOT = os.path.join(EDA_DIR, "interaction_sparsity_heatmap.png")

SUMMARY_PATH = "data/reports/preparation_summary.json"


def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
    )


def min_max(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    mn, mx = s.min(), s.max()
    if pd.isna(mn) or pd.isna(mx) or mn == mx:
        return pd.Series([0.0] * len(s), index=s.index)
    return (s - mn) / (mx - mn)


def load_tables(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    users = pd.read_sql_query("SELECT * FROM user_features", conn)
    items = pd.read_sql_query("SELECT * FROM item_features", conn)
    interactions = pd.read_sql_query("SELECT * FROM interactions", conn)
    return users, items, interactions


def clean_and_preprocess(
    users: pd.DataFrame, items: pd.DataFrame, interactions: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    summary: dict = {}

    # ---- interactions cleaning ----
    interactions = interactions.copy()
    before_rows = len(interactions)

    # Keep latest interaction per (user, item)
    interactions = interactions.sort_values("timestamp").drop_duplicates(
        subset=["user_id", "item_id"], keep="last"
    )
    interactions["rating"] = interactions["rating"].astype(float).clip(0.5, 5.0)
    interactions["timestamp_dt"] = pd.to_datetime(
        interactions["timestamp"], unit="s", errors="coerce", utc=True
    )
    interactions["timestamp_norm"] = min_max(interactions["timestamp"])

    observed_rows = len(interactions)
    summary["interactions_raw_rows"] = int(before_rows)
    summary["interactions_after_dedup_rows"] = int(observed_rows)

    # ---- users preprocessing ----
    users = users.copy()
    users["gender_encoded"] = users["gender"].map({"F": 0, "M": 1}).fillna(-1).astype(int)
    users["occupation_encoded"] = users["occupation"].astype("category").cat.codes
    users["age_norm"] = min_max(users["age"]) if "age" in users.columns else 0.0

    # ---- items preprocessing ----
    items = items.copy()
    items["category_encoded"] = items["category"].astype("category").cat.codes
    items["price_norm"] = min_max(items["price"]) if "price" in items.columns else 0.0
    items["catalog_rating_norm"] = min_max(items["rating"]) if "rating" in items.columns else 0.0

    # ---- Handle missing user-item interactions ----
    # Build dense matrix using all user/item pairs, impute missing ratings
    user_ids = users[["user_id"]].drop_duplicates()
    item_ids = items[["item_id"]].drop_duplicates()
    user_ids["_k"] = 1
    item_ids["_k"] = 1

    dense = user_ids.merge(item_ids, on="_k").drop(columns="_k")
    dense = dense.merge(
        interactions[["user_id", "item_id", "rating", "timestamp", "timestamp_norm"]],
        on=["user_id", "item_id"],
        how="left",
    )

    dense["is_observed"] = dense["rating"].notna().astype(int)

    global_mean = float(interactions["rating"].mean())
    user_mean = interactions.groupby("user_id")["rating"].mean().rename("user_mean")
    item_mean = interactions.groupby("item_id")["rating"].mean().rename("item_mean")

    dense = dense.merge(user_mean, on="user_id", how="left")
    dense = dense.merge(item_mean, on="item_id", how="left")

    dense["rating_filled"] = (
        dense["rating"]
        .fillna(dense["user_mean"])
        .fillna(dense["item_mean"])
        .fillna(global_mean)
        .astype(float)
    )

    dense["is_imputed"] = (1 - dense["is_observed"]).astype(int)
    dense["timestamp"] = dense["timestamp"].fillna(interactions["timestamp"].median())
    dense["timestamp_norm"] = dense["timestamp_norm"].fillna(interactions["timestamp_norm"].median())

    total_pairs = len(dense)
    observed_pairs = int(dense["is_observed"].sum())
    missing_pairs = total_pairs - observed_pairs

    summary["users"] = int(len(users))
    summary["items"] = int(len(items))
    summary["all_user_item_pairs"] = int(total_pairs)
    summary["observed_pairs"] = int(observed_pairs)
    summary["missing_pairs_imputed"] = int(missing_pairs)
    summary["sparsity_before_imputation"] = round(1 - observed_pairs / total_pairs, 6)

    return users, items, interactions, dense, summary


def create_eda_plots(interactions: pd.DataFrame) -> None:
    os.makedirs(EDA_DIR, exist_ok=True)
    sns.set_theme(style="whitegrid")

    # 1) Rating distribution
    plt.figure(figsize=(8, 5))
    sns.histplot(interactions["rating"], bins=10, kde=True)
    plt.title("Interaction Rating Distribution")
    plt.xlabel("Rating")
    plt.ylabel("Frequency")
    plt.tight_layout()
    plt.savefig(RATING_PLOT)
    plt.close()

    # 2) Item popularity
    popularity = interactions.groupby("item_id").size().reset_index(name="interaction_count")
    popularity = popularity.sort_values("interaction_count", ascending=False)
    popularity["item_id"] = popularity["item_id"].astype(int)

    plt.figure(figsize=(10, 5))
    sns.barplot(data=popularity.head(15), x="item_id", y="interaction_count", color="steelblue")
    plt.title("Top 15 Items by Interaction Count")
    plt.xlabel("Item ID")
    plt.ylabel("Interaction Count")
    plt.tight_layout()
    plt.savefig(POPULARITY_PLOT)
    plt.close()

    # 3) Sparsity heatmap (observed interactions)
    pivot = interactions.assign(observed=1).pivot_table(
        index="user_id", columns="item_id", values="observed", fill_value=0
    )

    plt.figure(figsize=(12, 8))
    sns.heatmap(pivot, cmap="YlGnBu", cbar=True)
    plt.title("Observed Interaction Matrix (Sparsity Pattern)")
    plt.xlabel("Item ID")
    plt.ylabel("User ID")
    plt.tight_layout()
    plt.savefig(SPARSITY_PLOT)
    plt.close()


def save_outputs(
    users: pd.DataFrame,
    items: pd.DataFrame,
    interactions_observed: pd.DataFrame,
    interactions_dense: pd.DataFrame,
    summary: dict,
) -> None:
    os.makedirs("data/processed", exist_ok=True)
    os.makedirs("data/reports", exist_ok=True)

    users.to_csv(USERS_OUT, index=False)
    items.to_csv(ITEMS_OUT, index=False)
    interactions_observed.to_csv(INTERACTIONS_OBS_OUT, index=False)
    interactions_dense.to_csv(INTERACTIONS_DENSE_OUT, index=False)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outputs": {
            "users": USERS_OUT,
            "items": ITEMS_OUT,
            "interactions_observed": INTERACTIONS_OBS_OUT,
            "interactions_dense": INTERACTIONS_DENSE_OUT,
            "plots": [RATING_PLOT, POPULARITY_PLOT, SPARSITY_PLOT],
        },
        "summary": summary,
    }

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def prepare_data() -> dict:
    setup_logging()
    logging.info("Starting data preparation")

    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"{DB_PATH} not found. Run ingestion first.")

    conn = sqlite3.connect(DB_PATH)
    try:
        users, items, interactions = load_tables(conn)
    finally:
        conn.close()

    users_p, items_p, interactions_obs_p, interactions_dense_p, summary = clean_and_preprocess(
        users, items, interactions
    )

    create_eda_plots(interactions_obs_p)
    save_outputs(users_p, items_p, interactions_obs_p, interactions_dense_p, summary)

    logging.info("Data preparation completed successfully")
    logging.info("Summary: %s", summary)

    return summary


if __name__ == "__main__":
    prepare_data()
