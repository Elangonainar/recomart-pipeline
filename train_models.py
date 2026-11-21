import json
import math
import os

import mlflow
import numpy as np
import pandas as pd

from feature_store import FeatureStore
from transformation import transform_data

INTERACTIONS_PATH = "data/processed/interactions_observed_prepared.csv"
ITEMS_PATH = "data/processed/items_prepared.csv"
REPORT_DIR = "data/reports"
EXPERIMENT_NAME = "recomart-recommendation"
DEFAULT_TRACKING_URI = "http://localhost:5000"
FEATURE_SET = "rating_prediction_v1"
ITEM_FEATURES = ["category_encoded", "price_norm", "catalog_rating_norm"]
SEED = 42
TRAIN_QUANTILE = 0.8  # the first 80% of ratings (by time) train; the rest test
TOP_K = 5
RELEVANT_RATING = 4.0
MF_PARAMS = {"n_factors": 8, "learning_rate": 0.01, "reg": 0.05, "epochs": 200}


def time_split(interactions):
    """Cutoff at the TRAIN_QUANTILE timestamp. Train = ratings up to it, test = ratings after it."""
    cutoff = float(interactions["timestamp"].quantile(TRAIN_QUANTILE))
    test = interactions[interactions["timestamp"] > cutoff].reset_index(drop=True)
    return cutoff, test


def materialize_train_window(cutoff):
    """Build a feature version from ratings up to the cutoff only, without making it active.

    Serving tables are rebuilt from all data afterwards, so the store's active version
    and the database state match what the DAG produced before training.
    """
    transform_data(cutoff_ts=cutoff)
    try:
        result = FeatureStore().materialize(
            description=f"training window: ratings up to {cutoff:.0f}", activate=False)
    finally:
        transform_data()
    return result["version_id"]


def build_item_similarity(item_features):
    categories = pd.get_dummies(item_features["category_encoded"], prefix="cat", dtype=float)
    features = pd.concat(
        [categories, item_features[["price_norm", "catalog_rating_norm"]].astype(float)], axis=1
    ).to_numpy()
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    features = features / np.where(norms == 0, 1, norms)
    similarity = np.clip(features @ features.T, 0, None)
    item_index = {item_id: pos for pos, item_id in enumerate(item_features["item_id"])}
    return item_index, similarity


class GlobalMeanModel:
    def __init__(self, train):
        self.mu = float(train["rating"].mean())

    def predict(self, user_id, item_id):
        return self.mu


class ContentBasedModel:
    """Predicts a rating as a similarity-weighted average of the user's training ratings."""

    def __init__(self, train, item_index, item_similarity):
        self.item_index = item_index
        self.item_similarity = item_similarity
        self.global_mean = float(train["rating"].mean())
        self.user_ratings = {
            user_id: dict(zip(group["item_id"], group["rating"]))
            for user_id, group in train.groupby("user_id")
        }

    def user_mean(self, user_id):
        ratings = self.user_ratings.get(user_id)
        return float(np.mean(list(ratings.values()))) if ratings else self.global_mean

    def predict(self, user_id, item_id):
        ratings = self.user_ratings.get(user_id)
        if not ratings or item_id not in self.item_index:
            return self.user_mean(user_id)
        i = self.item_index[item_id]
        numerator = denominator = 0.0
        for rated_item, rating in ratings.items():
            if rated_item not in self.item_index:
                continue
            similarity = self.item_similarity[i, self.item_index[rated_item]]
            numerator += similarity * rating
            denominator += similarity
        return numerator / denominator if denominator > 0 else self.user_mean(user_id)


class MatrixFactorization:
    """Biased matrix factorization (SVD-style) trained with SGD."""

    def __init__(self, train, n_factors, learning_rate, reg, epochs, seed):
        self.user_index = {u: i for i, u in enumerate(sorted(train["user_id"].unique()))}
        self.item_index = {m: i for i, m in enumerate(sorted(train["item_id"].unique()))}
        self.mu = float(train["rating"].mean())
        self.low = float(train["rating"].min())
        self.high = float(train["rating"].max())

        rng = np.random.default_rng(seed)
        self.P = rng.normal(0, 0.1, (len(self.user_index), n_factors))
        self.Q = rng.normal(0, 0.1, (len(self.item_index), n_factors))
        self.bu = np.zeros(len(self.user_index))
        self.bi = np.zeros(len(self.item_index))

        users = train["user_id"].map(self.user_index).to_numpy()
        items = train["item_id"].map(self.item_index).to_numpy()
        ratings = train["rating"].to_numpy(float)
        for _ in range(epochs):
            for n in rng.permutation(len(ratings)):
                u, i = users[n], items[n]
                pu = self.P[u].copy()
                qi = self.Q[i].copy()
                error = ratings[n] - (self.mu + self.bu[u] + self.bi[i] + pu @ qi)
                self.bu[u] += learning_rate * (error - reg * self.bu[u])
                self.bi[i] += learning_rate * (error - reg * self.bi[i])
                self.P[u] += learning_rate * (error * qi - reg * pu)
                self.Q[i] += learning_rate * (error * pu - reg * qi)

    def predict(self, user_id, item_id):
        u = self.user_index.get(user_id)
        i = self.item_index.get(item_id)
        prediction = self.mu
        if u is not None:
            prediction += self.bu[u]
        if i is not None:
            prediction += self.bi[i]
        if u is not None and i is not None:
            prediction += self.P[u] @ self.Q[i]
        return float(np.clip(prediction, self.low, self.high))


def evaluate(model, train, test, catalog_ids, ranking):
    predictions = np.array([model.predict(u, i) for u, i in zip(test["user_id"], test["item_id"])])
    errors = predictions - test["rating"].to_numpy(float)
    metrics = {
        "rmse": math.sqrt(float(np.mean(errors**2))),
        "mae": float(np.mean(np.abs(errors))),
    }
    if not ranking:
        return metrics

    seen = train.groupby("user_id")["item_id"].apply(set).to_dict()
    precisions, recalls = [], []
    for user_id, group in test.groupby("user_id"):
        relevant = set(group.loc[group["rating"] >= RELEVANT_RATING, "item_id"])
        if not relevant:
            continue
        candidates = [item for item in catalog_ids if item not in seen.get(user_id, set())]
        top = sorted(candidates, key=lambda item: model.predict(user_id, item), reverse=True)[:TOP_K]
        hits = len(relevant.intersection(top))
        precisions.append(hits / TOP_K)
        recalls.append(hits / len(relevant))
    metrics[f"precision_at_{TOP_K}"] = float(np.mean(precisions))
    metrics[f"recall_at_{TOP_K}"] = float(np.mean(recalls))
    metrics["ranking_users"] = len(precisions)
    return metrics


def write_report(results, tracking_uri, split_description):
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "model_runs.json"), "w") as f:
        json.dump({"tracking_uri": tracking_uri, "experiment": EXPERIMENT_NAME, "runs": results}, f, indent=2)

    metric_names = list(dict.fromkeys(k for r in results for k in r["metrics"]))
    lines = [
        "# Model Performance Report",
        "",
        f"MLflow tracking URI: `{tracking_uri}`  ",
        f"Experiment: `{EXPERIMENT_NAME}`",
        "",
        "| Model | " + " | ".join(metric_names) + " | Run ID |",
        "|---|" + "---|" * (len(metric_names) + 1),
    ]
    for result in results:
        values = [
            f"{result['metrics'][m]:.4f}" if isinstance(result["metrics"].get(m), float) else str(result["metrics"].get(m, "-"))
            for m in metric_names
        ]
        lines.append(f"| {result['model']} | " + " | ".join(values) + f" | `{result['run_id']}` |")
    lines += [
        "",
        f"{split_description} Ranking metrics use top-{TOP_K} "
        f"recommendations and treat test ratings >= {RELEVANT_RATING} as relevant.",
    ]
    with open(os.path.join(REPORT_DIR, "model_performance.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    interactions = pd.read_csv(INTERACTIONS_PATH)
    cutoff, test = time_split(interactions)
    version = materialize_train_window(cutoff)

    store = FeatureStore()
    train = store.get_training_dataset(FEATURE_SET, version=version)
    # Keep the same rows as the split: the latest rating per pair, and only if it is before the cutoff.
    train = train.merge(
        interactions.loc[interactions["timestamp"] <= cutoff, ["user_id", "item_id", "timestamp"]],
        on=["user_id", "item_id", "timestamp"], how="inner")
    catalog_ids = pd.read_csv(ITEMS_PATH)["item_id"].tolist()
    item_features = store.get_entity_features("item", catalog_ids, features=ITEM_FEATURES, version=version)
    item_index, item_similarity = build_item_similarity(item_features)
    split_description = (
        f"Time split: ratings up to {cutoff:.0f} (the {TRAIN_QUANTILE:.0%} quantile of timestamps) train, "
        f"later ratings test. Training rows and item features come from feature version {version}, "
        f"which only uses ratings up to the cutoff."
    )

    candidates = [
        ("baseline_global_mean", GlobalMeanModel(train), {}, False),
        ("content_based", ContentBasedModel(train, item_index, item_similarity), {"top_k": TOP_K}, True),
        ("matrix_factorization_svd", MatrixFactorization(train, seed=SEED, **MF_PARAMS), MF_PARAMS, True),
    ]

    results = []
    for name, model, model_params, ranking in candidates:
        metrics = evaluate(model, train, test, catalog_ids, ranking)
        params = {
            **model_params,
            "train_rows": len(train),
            "test_rows": len(test),
            "split": "time",
            "train_quantile": TRAIN_QUANTILE,
            "train_cutoff_ts": cutoff,
            "feature_set": FEATURE_SET,
            "feature_version": version,
        }
        with mlflow.start_run(run_name=name) as run:
            mlflow.log_params(params)
            mlflow.log_metrics(metrics)
            mlflow.set_tag("model", name)
            run_id = run.info.run_id
        results.append({"model": name, "run_id": run_id, "params": params, "metrics": metrics})
        print(f"{name}: {metrics} run_id={run_id}")

    write_report(results, tracking_uri, split_description)


if __name__ == "__main__":
    main()
