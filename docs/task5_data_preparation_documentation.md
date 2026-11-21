# Task 5 Documentation - Data Preparation

## Objective
Prepare recommendation data for downstream feature engineering by cleaning interactions, handling missing user-item pairs, encoding categorical variables, normalizing numerics, and generating EDA artifacts.

## Input Sources
- SQLite tables from `data/recomart.db`:
  - `user_features`
  - `item_features`
  - `interactions`

## Processing Steps
1. **Interaction cleaning**
   - Sort interactions by timestamp.
   - Deduplicate on `(user_id, item_id)` keeping latest interaction.
   - Clip ratings into `[0.5, 5.0]`.
   - Convert Unix timestamp to datetime (`timestamp_dt`) and normalized value (`timestamp_norm`).

2. **Categorical encoding**
   - `gender` → `gender_encoded` (`F=0`, `M=1`, unknown `-1`)
   - `occupation` → `occupation_encoded` (category code)
   - `category` (items) → `category_encoded` (category code)

3. **Numeric normalization**
   - `age` → `age_norm` (min-max)
   - `price` → `price_norm` (min-max)
   - `item rating` → `catalog_rating_norm` (min-max)
   - `timestamp` → `timestamp_norm` (min-max)

4. **Missing user-item interaction handling**
   - Build complete user-item Cartesian set.
   - Left join observed interactions.
   - Impute missing ratings in priority order:
     1) user mean
     2) item mean
     3) global mean
   - Add flags:
     - `is_observed`
     - `is_imputed`

5. **EDA generation**
   - Rating histogram (`rating_distribution.png`)
   - Item popularity bar chart (`item_popularity.png`)
   - User-item sparsity heatmap (`interaction_sparsity_heatmap.png`)

## Outputs
- `data/processed/users_prepared.csv`
- `data/processed/items_prepared.csv`
- `data/processed/interactions_observed_prepared.csv`
- `data/processed/interactions_prepared.csv`
- `data/reports/eda/rating_distribution.png`
- `data/reports/eda/item_popularity.png`
- `data/reports/eda/interaction_sparsity_heatmap.png`
- `data/reports/preparation_summary.json`
- `logs/preparation.log`

## Run Commands
```bash
python ingest.py
python validation.py
python preparation.py
```

## Docker Validation Flow
- Airflow DAG `recomart_ingest_pipeline` executes:
  1. `trigger_sqlite_ingestion`
  2. `validate_ingested_data`
  3. `prepare_and_eda`

Validation checks:
- DAG run state = `success`
- All 3 task instances = `success`
- All Task 5 output files exist in mounted `data/` volume
