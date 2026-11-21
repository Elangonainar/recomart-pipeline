#!/bin/bash
set -e

export AIRFLOW_HOME=/app/airflow
export AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=True

# Runs MLflow tracking server in the background, then db migration, scheduler, dag-processor, and UI server on port 8080
mlflow server --host 0.0.0.0 --port 5000 \
  --backend-store-uri sqlite:////app/data/mlflow.db \
  --default-artifact-root /app/data/mlartifacts &

exec airflow standalone
