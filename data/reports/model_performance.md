# Model Performance Report

MLflow tracking URI: `http://localhost:5000`  
Experiment: `recomart-recommendation`

| Model | rmse | mae | precision_at_5 | recall_at_5 | ranking_users | Run ID |
|---|---|---|---|---|---|---|
| baseline_global_mean | 1.1451 | 0.9071 | - | - | - | `f68d19f7a9864fbfb08618a543d417cd` |
| content_based | 1.3590 | 1.0783 | 0.0788 | 0.2399 | 33 | `1cda690a6c884d48a616f9d5d5932607` |
| matrix_factorization_svd | 1.4213 | 1.1143 | 0.1273 | 0.3788 | 33 | `f1bbd887502d4491b915516f72f1ae67` |

Time split: ratings up to 1730491709 (the 80% quantile of timestamps) train, later ratings test. Training rows and item features come from feature version 2, which only uses ratings up to the cutoff. Ranking metrics use top-5 recommendations and treat test ratings >= 4.0 as relevant.
