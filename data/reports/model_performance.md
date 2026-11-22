# Model Performance Report

MLflow tracking URI: `http://localhost:5000`  
Experiment: `recomart-recommendation`

| Model | rmse | mae | precision_at_5 | recall_at_5 | ranking_users | Run ID |
|---|---|---|---|---|---|---|
| baseline_global_mean | 1.0199 | 0.8445 | - | - | - | `9e156d6f0b0046cfb24bc2ecc48a33eb` |
| content_based | 1.3011 | 1.0317 | 0.0914 | 0.2357 | 35 | `a6199c426cca498da097e543cac014bc` |
| matrix_factorization_svd | 1.4138 | 1.0717 | 0.0743 | 0.2357 | 35 | `279b8afac38244c09332cff920cdb2a6` |

Time split: ratings up to 1730491709 (the 80% quantile of timestamps) train, later ratings test. Training rows and item features come from feature version 2, which only uses ratings up to the cutoff. Ranking metrics use top-5 recommendations and treat test ratings >= 4.0 as relevant.
