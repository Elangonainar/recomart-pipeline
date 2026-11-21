# Model Performance Report

MLflow tracking URI: `file:./mlruns`  
Experiment: `recomart-recommendation`

| Model | rmse | mae | precision_at_5 | recall_at_5 | ranking_users | Run ID |
|---|---|---|---|---|---|---|
| baseline_global_mean | 1.0199 | 0.8445 | - | - | - | `c3479aed58614cdf97996cf19190c5fd` |
| content_based | 1.3011 | 1.0317 | 0.0914 | 0.2357 | 35 | `a817d0af2b8746adad7a505a140d17f5` |
| matrix_factorization_svd | 1.4138 | 1.0717 | 0.0743 | 0.2357 | 35 | `11f0583f8d944af29808aaa7bc31a9ff` |

Split: 20% test, seed 42. Ranking metrics use top-5 recommendations and treat test ratings >= 4.0 as relevant.
