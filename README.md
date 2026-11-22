# RecoMart Lightweight Data Pipeline

A self-contained, containerized data pipeline for **RecoMart** utilizing SQLite, MovieLens interaction logs, partitioned CSV files (`date=YYYY-MM-DD/`), DVC versioning, and Apache Airflow.

## Project Structure
```text
recomart-pipeline/
├── data/
│   └── raw/              # Place your partitioned CSVs here
├── airflow/              # Airflow metadata & DAGs
├── schema.sql            # SQLite database schema
├── ingest.py             # Python ingestion script
├── entrypoint.sh         # Airflow bootstrap script
├── Dockerfile            # Single container definition
├── requirements.txt      # Python packages
└── dvc.yaml              # DVC pipeline stages
```

## Quick Start

   Created date partition folders and CSV files in place:
   ```bash
   ./data/raw/users/date=2026-11-01
   ./data/raw/items/date=2026-11-01
   ./data/raw/interactions/date=2026-11-01
   ```
1. **clone the repository:**
   clone the repository to your local and flow the below steps.
   
2. **Build Docker Image:**
   ```bash
   docker build -t recomart-single-container:latest .
   ```

3. **Run Container:**
   ```bash
   docker run -d -p 8080:8080 -p 5000:5000 -v ./data:/app/data --name recomart-app recomart-single-container:latest
   ```

4. **check the docker is up by running below command you should see recomart-app with status Up:**
   ```bash
    docker ps
   ```

5. **Trigger Pipeline:**
   - Open browser at `http://localhost:8080` (Login: `admin` / `admin`).
   - Enable and trigger `recomart_ingest_pipeline`.

6. **read raw data tables**
   - sqlite3 data/recomart.db 
   - List all tables: Type .tables and press Enter.
   - View table schema: Type .schema user_features (or any other table name).
   - Run a query: Type a standard SQL query ending with a semicolon, e.g., SELECT * FROM user_features LIMIT 5;
   - Exit the CLI: Type .exit and press Enter.

## Data Preparation (Task 5) - Completed

Implemented file: `preparation.py`

What it does:
- Cleans interactions (deduplicates user-item ratings, rating clipping)
- Handles missing user-item interactions by creating dense user-item pairs and imputing ratings
- Encodes categorical attributes:
   - `users.gender -> gender_encoded`
   - `users.occupation -> occupation_encoded`
   - `items.category -> category_encoded`
- Normalizes numerical attributes:
   - `users.age -> age_norm`
   - `items.price -> price_norm`
   - `items.rating -> catalog_rating_norm`
   - `interactions.timestamp -> timestamp_norm`
- Generates EDA plots for rating distribution, item popularity, and sparsity heatmap

### Task 5 Outputs
- `data/processed/users_prepared.csv`
- `data/processed/items_prepared.csv`
- `data/processed/interactions_observed_prepared.csv`
- `data/processed/interactions_prepared.csv`
- `data/reports/eda/rating_distribution.png`
- `data/reports/eda/item_popularity.png`
- `data/reports/eda/interaction_sparsity_heatmap.png`
- `data/reports/preparation_summary.json`

### Run Task 5 Locally
```bash
python ingest.py
python validation.py
python preparation.py
```

### Validate Task 5 in Docker
```bash
docker rm -f recomart-app || true
docker build -t recomart-single-container:latest .
docker run -d -p 8080:8080 -p 5000:5000 -v ./data:/app/data --name recomart-app recomart-single-container:latest

# Trigger DAG (ingest -> validation -> preparation)
docker exec recomart-app airflow dags trigger recomart_ingest_pipeline

# Check run status
docker exec recomart-app airflow dags list-runs recomart_ingest_pipeline --no-backfill -o table

# Validate task states
RUN_ID=$(docker exec recomart-app airflow dags list-runs recomart_ingest_pipeline --no-backfill -o json | tail -n 1 | python -c "import sys,json; print(json.loads(sys.stdin.read())[0]['run_id'])")
docker exec recomart-app airflow tasks states-for-dag-run recomart_ingest_pipeline "$RUN_ID"
```

## Model Training and Evaluation (Task 6)

Implemented file: `train_models.py`

What it does:
- Reads ratings from the feature store and splits them by time: the first 80% of ratings (by timestamp) train, the rest test
- Builds a training-window feature version from ratings up to the cutoff only (inactive, so serving keeps using the full-data version). Training rows and item features come from that version; test rows are the later ratings from `data/processed/interactions_observed_prepared.csv`. A user-item pair is never in both sets.
- Trains and evaluates three models:
   - `baseline_global_mean`: predicts the training mean rating
   - `content_based`: predicts a rating as a similarity-weighted average of the user's training ratings, using item category, price, and catalog rating from the feature store
   - `matrix_factorization_svd`: biased matrix factorization trained with SGD (uses user and item IDs and ratings only)
- Logs parameters (including the cutoff and feature version), metrics, and run IDs to MLflow (experiment `recomart-recommendation`)

Metrics: RMSE and MAE for all models; Precision@5 and Recall@5 for the two recommenders (test ratings >= 4 count as relevant).

### Outputs
- `train_models.py`
- `data/reports/model_performance.md`: comparison table with run IDs
- `data/reports/model_runs.json`: run IDs, parameters, and metrics

### Run Task 6 in Docker
The MLflow tracking server starts with the container on port 5000 (`-p 5000:5000`); its data is stored in `data/mlflow.db` and `data/mlartifacts/`.

```bash
docker exec recomart-app python train_models.py
```

Open the MLflow UI at `http://localhost:5000`.

### Run Task 6 Locally
Start an MLflow server, then run the script against it:
```bash
mlflow server --host 127.0.0.1 --port 5000 --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlartifacts &
MLFLOW_TRACKING_URI=http://localhost:5000 python train_models.py
```
