#!/bin/bash
export AIRFLOW_HOME=/app/airflow

# Initialize Airflow Metadata DB
airflow db migrate

# Create default Airflow admin user
airflow users create     --username admin     --firstname Admin     --lastname User     --role Admin     --email admin@recomart.com     --password admin || true

# Start Airflow scheduler in background and webserver in foreground
airflow scheduler &
exec airflow webserver --port 8080
