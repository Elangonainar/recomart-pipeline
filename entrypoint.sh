#!/bin/bash
export AIRFLOW_HOME=/app/airflow
export AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=True

# Runs db migration, scheduler, dag-processor, and UI server on port 8080
exec airflow standalone
EOF
chmod +x entrypoint.sh
