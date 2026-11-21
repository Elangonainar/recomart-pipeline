from datetime import datetime
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
import sys

sys.path.append('/app')
from ingest import ingest_data
from validation import validate_data
from preparation import prepare_data

default_args = {
    'owner': 'airflow',
    'start_date': datetime(2026, 11, 1),
}

with DAG(
    'recomart_ingest_pipeline',
    default_args=default_args,
    schedule=None,
    catchup=False,
) as dag:

    run_ingestion = PythonOperator(
        task_id='trigger_sqlite_ingestion',
        python_callable=ingest_data,
    )

    run_validation = PythonOperator(
        task_id='validate_ingested_data',
        python_callable=validate_data,
    )

    run_preparation = PythonOperator(
        task_id='prepare_and_eda',
        python_callable=prepare_data,
    )

    run_ingestion >> run_validation >> run_preparation