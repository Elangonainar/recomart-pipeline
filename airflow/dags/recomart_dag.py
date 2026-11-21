# from datetime import datetime
# from airflow import DAG
# from airflow.providers.standard.operators.python import PythonOperator
# import sys

# sys.path.append('/app')
# from ingest import ingest_data

# default_args = {
#     'owner': 'airflow',
#     'start_date': datetime(2026, 11, 1),
# }

# with DAG(
#     'recomart_ingest_pipeline',
#     default_args=default_args,
#     schedule=None,
#     catchup=False,
# ) as dag:

#     run_ingestion = PythonOperator(
#         task_id='trigger_sqlite_ingestion',
#         python_callable=ingest_data,
#     )

from datetime import datetime
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
import sys

sys.path.append('/app')
from ingest import ingest_data
from validation import validate_data

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
        task_id='validate_data',
        python_callable=validate_data,
    )

    # Validation only runs if ingestion succeeds; later tasks (EDA, modeling)
    # will be chained after run_validation the same way.
    run_ingestion >> run_validation