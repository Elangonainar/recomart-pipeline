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
   docker run -d -p 8080:8080 -v ./data:/app/data --name recomart-app recomart-single-container:latest
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
docker run -d -p 8080:8080 -v ./data:/app/data --name recomart-app recomart-single-container:latest

# Trigger DAG (ingest -> validation -> preparation)
docker exec recomart-app airflow dags trigger recomart_ingest_pipeline

# Check run status
docker exec recomart-app airflow dags list-runs recomart_ingest_pipeline --no-backfill -o table

# Validate task states
RUN_ID=$(docker exec recomart-app airflow dags list-runs recomart_ingest_pipeline --no-backfill -o json | tail -n 1 | python -c "import sys,json; print(json.loads(sys.stdin.read())[0]['run_id'])")
docker exec recomart-app airflow tasks states-for-dag-run recomart_ingest_pipeline "$RUN_ID"
```
