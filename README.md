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

1. **Add Sample Data:**
   Create date partition folders and drop your CSV files in place:
   ```bash
   mkdir -p data/raw/users/date=2026-11-01
   mkdir -p data/raw/items/date=2026-11-01
   mkdir -p data/raw/interactions/date=2026-11-01
   ```

2. **Build Docker Image:**
   ```bash
   docker build -t recomart-single-container:latest .
   ```

3. **Run Container:**
   ```bash
   docker run -d -p 8080:8080 -v $(pwd)/data:/app/data --name recomart-app recomart-single-container:latest
   ```

4. **Trigger Pipeline:**
   - Open browser at `http://localhost:8080` (Login: `admin` / `admin`).
   - Enable and trigger `recomart_ingest_pipeline`.
