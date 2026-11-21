# Model Performance Report

MLflow tracking URI: `sqlite:////tmp/recomart_mlflow_test.db`  
Experiment: `recomart-recommendation`

| Model | rmse | mae | precision_at_5 | recall_at_5 | ranking_users | Run ID |
|---|---|---|---|---|---|---|
| baseline_global_mean | 1.1451 | 0.9071 | - | - | - | `b141754baff64ba2a5d858c9f5c1802f` |
| content_based | 1.3590 | 1.0783 | 0.0788 | 0.2399 | 33 | `5292338ebbee471fb717b6df56b68c23` |
| matrix_factorization_svd | 1.4213 | 1.1143 | 0.1273 | 0.3788 | 33 | `726edd4e427a4258af93ac7bb6c447e2` |

Time split: ratings up to 1730491709 (the 80% quantile of timestamps) train, later ratings test. Training rows and item features come from feature version 2, which only uses ratings up to the cutoff. Ranking metrics use top-5 recommendations and treat test ratings >= 4.0 as relevant.
