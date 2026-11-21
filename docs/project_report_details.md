# RecoMart Project Report Details

## Project Title

RecoMart Lightweight Data Pipeline: a containerized recommendation pipeline with ingestion, validation, preparation, feature store, and model training.

## Team Member Details

| Name   | ID          |
|--------|-------------|
| Elango | 2025NS04019 |
|--------|-------------|
|        |             |
|--------|-------------|
|        |             |
|--------|-------------|
|        |             |
|--------|-------------|

## Problem Statement

RecoMart collects user, item, and rating data as daily CSV drops. It needs a repeatable pipeline that loads this data into a database, checks its quality, prepares it for modelling, and trains recommendation models with results that can be tracked and reproduced.

## Objectives

- Ingest partitioned CSVs (`date=YYYY-MM-DD/`) into SQLite, idempotently.
- Validate the data and prepare it: deduplicate ratings, encode categories, normalize numeric fields, and produce EDA plots.
- Build a feature store with versioned features and point-in-time-safe training sets.
- Train and compare a baseline, a content-based recommender, and a matrix factorization model, logging everything to MLflow.
- Version the data and pipeline with DVC, and orchestrate it with Airflow in one Docker container.

## Methodology / Pipeline

1. **Ingest:** `ingest.py` loads users, items, and interactions into SQLite (`data/recomart.db`).
2. **Validate:** `validation.py` writes `data/reports/validation.json`.
3. **Prepare:** `preparation.py` cleans the data, encodes and normalizes features, and writes the processed CSVs and EDA plots.
4. **Transform and feature store:** `transformation.py` and `feature_store.py` build versioned features.
5. **Train:** `train_models.py` uses a time-based split. The cutoff is the 80th percentile of rating timestamps, and features come only from the training window, to avoid label leakage.
6. **Track:** MLflow records parameters, metrics, and run IDs.
7. **Orchestrate:** Airflow DAG `recomart_ingest_pipeline`; DVC tracks the stages.

## Implementation Details

- **Stack:** Python, SQLite, pandas, scikit-learn-style models, DVC, Airflow, MLflow, Docker.
- **Key files:** `schema.sql`, `ingest.py`, `validation.py`, `preparation.py`, `transformation.py`, `feature_store.py`, `train_models.py`, `airflow/dags/recomart_dag.py`, `dvc.yaml`, `Dockerfile`.
- **Data versioning:** data stays in git; DVC outputs that git tracks use `cache: false`.

## Results and Output Screenshots

Latest run (time-based split, 334 train / 84 test ratings):

| Model | RMSE | MAE | Precision@5 | Recall@5 |
|---|---|---|---|---|
| baseline_global_mean | 1.145 | 0.907 | – | – |
| content_based | 1.359 | 1.078 | 0.079 | 0.240 |
| matrix_factorization_svd | 1.421 | 1.114 | 0.127 | 0.379 |

Neither model beats the baseline on RMSE. The dataset is small (500 ratings on one day), so these numbers are noisy.

Screenshots to capture:

- EDA plots in `data/reports/eda/` (rating distribution, item popularity, sparsity heatmap).
- The Airflow DAG graph and a successful run.
- The MLflow UI at `http://localhost:5000`, showing the three runs.

## Conclusion and Future Scope

The pipeline runs end to end from ingestion to MLflow tracking, and the time-based split removes the leakage from the earlier random-split setup. The models don't yet beat the baseline.

Future work:

- Use the feature store's user features in the models.
- Test on more data, with multiple daily partitions.
- Tune the matrix factorization model.
- Fix the DVC ordering between `feature_store` and `train`.
- Verify the Airflow DAG and Docker image with the latest code.
