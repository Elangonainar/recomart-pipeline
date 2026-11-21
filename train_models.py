import json
import math
import os

import mlflow
import numpy as np
import pandas as pd

INTERACTIONS_PATH = "data/processed/interactions_observed_prepared.csv"
ITEMS_PATH = "data/processed/items_prepared.csv"
REPORT_DIR = "data/reports"
EXPERIMENT_NAME = "recomart-recommendation"
DEFAULT_TRACKING_URI = "http://localhost:5000"
SEED = 42
TEST_FRACTION = 0.2
TOP_K = 5
RELEVANT_RATING = 4.0
MF_PARAMS = {"n_factors": 8, "learning_rate": 0.01, "reg": 0.05, "epochs": 200}


def load_data():
    interactions = pd.read_csv(INTERACTIONS_PATH)[["user_id", "item_id", "rating"]]
    items = pd.read_csv(ITEMS_PATH)
    return interactions, items


def split_interactions(interactions):
    rng = np.random.default_rng(SEED)
    order = rng.permutation(len(interactions))
    n_test = int(round(len(interactions) * TEST_FRACTION))
    test = interactions.iloc[order[:n_test]].reset_index(drop=True)
    train = interactions.iloc[order[n_test:]].reset_index(drop=True)
    return train, test


def build_item_similarity(items):
    categories = pd.get_dummies(items["category"], prefix="cat", dtype=float)
    features = pd.concat(
        [categories, items[["price_norm", "catalog_rating_norm"]].astype(float)], axis=1
    ).to_numpy()
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    features = features / np.where(norms == 0, 1, norms)
    similarity = np.clip(features @ features.T, 0, None)
    item_index = {item_id: pos for pos, item_id in enumerate(items["item_id"])}
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


def write_report(results, tracking_uri):
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
        f"Split: {TEST_FRACTION:.0%} test, seed {SEED}. Ranking metrics use top-{TOP_K} "
        f"recommendations and treat test ratings >= {RELEVANT_RATING} as relevant.",
    ]
    with open(os.path.join(REPORT_DIR, "model_performance.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    interactions, items = load_data()
    train, test = split_interactions(interactions)
    catalog_ids = items["item_id"].tolist()
    item_index, item_similarity = build_item_similarity(items)

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
            "split_seed": SEED,
            "test_fraction": TEST_FRACTION,
        }
        with mlflow.start_run(run_name=name) as run:
            mlflow.log_params(params)
            mlflow.log_metrics(metrics)
            mlflow.set_tag("model", name)
            run_id = run.info.run_id
        results.append({"model": name, "run_id": run_id, "params": params, "metrics": metrics})
        print(f"{name}: {metrics} run_id={run_id}")

    write_report(results, tracking_uri)


if __name__ == "__main__":
    main()
