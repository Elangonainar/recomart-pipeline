# # from datetime import datetime
# # from airflow import DAG
# # from airflow.providers.standard.operators.python import PythonOperator
# # import sys

# # sys.path.append('/app')
# # from ingest import ingest_data

# # default_args = {
# #     'owner': 'airflow',
# #     'start_date': datetime(2026, 11, 1),
# # }

# # with DAG(
# #     'recomart_ingest_pipeline',
# #     default_args=default_args,
# #     schedule=None,
# #     catchup=False,
# # ) as dag:

# #     run_ingestion = PythonOperator(
# #         task_id='trigger_sqlite_ingestion',
# #         python_callable=ingest_data,
# #     )

# from datetime import datetime
# from airflow import DAG
# from airflow.providers.standard.operators.python import PythonOperator
# import sys

# sys.path.append('/app')
# from ingest import ingest_data
# from validation import validate_data

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

#     run_validation = PythonOperator(
#         task_id='validate_data',
#         python_callable=validate_data,
#     )

#     # Validation only runs if ingestion succeeds; later tasks (EDA, modeling)
#     # will be chained after run_validation the same way.
#     run_ingestion >> run_validation

from datetime import datetime
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
import sys

sys.path.append('/app')
from ingest import ingest_data
from validation import validate_data
from preparation import prepare_data  # change "preparation" if your file has a different name
from transformation import transform_data
from feature_store import materialize_feature_store
from train_models import main as train_models


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

    run_preparation = PythonOperator(
        task_id='prepare_data',
        python_callable=prepare_data,
    )

    run_transformation = PythonOperator(
        task_id='transform_features',
        python_callable=transform_data,
    )
    run_feature_store = PythonOperator(
        task_id='materialize_feature_store',
        python_callable=materialize_feature_store,
    )

    run_training = PythonOperator(
        task_id='train_models',
        python_callable=train_models,
    )

    # Each step only runs if the previous one succeeds
    run_ingestion >> run_validation >> run_preparation >> run_transformation >> run_feature_store >> run_training
