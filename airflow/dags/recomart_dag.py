from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
import sys

sys.path.append('/app')
from ingest import ingest_data

default_args = {
    'owner': 'airflow',
    'start_date': datetime(2026, 11, 1),
}

with DAG(
    'recomart_ingest_pipeline',
    default_args=default_args,
    schedule_interval=None,
    catchup=False,
) as dag:

    run_ingestion = PythonOperator(
        task_id='trigger_sqlite_ingestion',
        python_callable=ingest_data,
    )
