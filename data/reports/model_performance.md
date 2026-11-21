# Model Performance Report

MLflow tracking URI: `http://localhost:5000`  
Experiment: `recomart-recommendation`

| Model | rmse | mae | precision_at_5 | recall_at_5 | ranking_users | Run ID |
|---|---|---|---|---|---|---|
| baseline_global_mean | 1.0199 | 0.8445 | - | - | - | `c566665fb0b843dcacb0091be494f2ca` |
| content_based | 1.3011 | 1.0317 | 0.0914 | 0.2357 | 35 | `25a93c925e014a549ded0f2d98483a52` |
| matrix_factorization_svd | 1.4138 | 1.0717 | 0.0743 | 0.2357 | 35 | `acf08842cf2a480ebbec2e8392a60b40` |

Split: 20% test, seed 42. Ranking metrics use top-5 recommendations and treat test ratings >= 4.0 as relevant.
