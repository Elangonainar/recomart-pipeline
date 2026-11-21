"""Custom feature store for the RecoMart recommendation pipeline.

A small, dependency-free alternative to Feast built on the project's SQLite database:

- Registry  : every feature's name, type, source and transformation (FEATURES below,
              synced into the fs_registry table)
- Versions  : each materialisation snapshots the current transformation output
              (user_feature_store, item_feature_store, item_similarity) into versioned
              fs_* tables. Identical data never creates a new version (content hash).
- Retrieval : the same feature sets serve training (pin a version, or ask "as of" a
              time) and inference (active version by default), so features are
              identical in both places.

Typical use
-----------
    fs = FeatureStore()
    fs.materialize()                                              # pipeline step
    train = fs.get_training_dataset("rating_prediction_v1", version=3)
    feats = fs.get_inference_features("rating_prediction_v1", [7, 7], [50, 51])

CLI:  python feature_store.py [materialize | versions | docs [path]]
"""

import hashlib
import json
import logging
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import pandas as pd

DB_PATH = "data/recomart.db"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feature_store_schema.sql")
TRANSFORM_SUMMARY_PATH = "data/reports/feature_summary.json"

RETAIN_VERSIONS = 10    # newest versions kept (the active version is always kept)
FETCH_CHUNK = 500       # ids per IN (...) query
TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Registry: feature definitions (the single source of truth for documentation)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Feature:
    entity: str          # user | item | item_pair
    name: str
    dtype: str
    description: str
    source: str          # raw table.column(s) the feature comes from
    transformation: str  # how it is computed


FEATURES = [
    # ---- user ----
    Feature("user", "gender_encoded", "INTEGER", "Gender as a number",
            "user_features.gender", "F -> 0, M -> 1, anything else or missing -> -1 (preparation step)"),
    Feature("user", "occupation_encoded", "INTEGER", "Occupation as a category code",
            "user_features.occupation", "pandas category codes, alphabetical order of distinct occupations (preparation step)"),
    Feature("user", "age_norm", "REAL", "Age scaled to 0-1",
            "user_features.age", "min-max scaling across users; 0 if constant (preparation step)"),
    Feature("user", "interaction_count", "INTEGER", "Number of ratings the user has given",
            "interactions.user_id", "count of observed interactions after de-duplicating (user, item) and keeping the latest"),
    Feature("user", "activity_frequency", "REAL", "Interactions per active day",
            "interactions.timestamp", "interaction_count / max(1, days between first and last interaction)"),
    Feature("user", "activity_norm", "REAL", "Activity level scaled to 0-1",
            "interactions.user_id", "min-max scaling of interaction_count across users"),
    Feature("user", "avg_rating", "REAL", "Average rating the user gives",
            "interactions.rating", "mean of the user's ratings (clipped 0.5-5.0); global mean if the user has none"),
    Feature("user", "rating_std", "REAL", "Spread of the user's ratings",
            "interactions.rating", "sample standard deviation of the user's ratings; 0 with fewer than 2 ratings"),
    Feature("user", "rating_bias", "REAL", "How generous (+) or harsh (-) the user is",
            "interactions.rating", "avg_rating minus the global mean rating"),
    Feature("user", "first_interaction_ts", "INTEGER", "Time of the user's first rating (Unix seconds)",
            "interactions.timestamp", "minimum timestamp; NULL if no interactions"),
    Feature("user", "last_interaction_ts", "INTEGER", "Time of the user's latest rating (Unix seconds)",
            "interactions.timestamp", "maximum timestamp; NULL if no interactions"),
    Feature("user", "days_since_last_interaction", "REAL", "Recency of the user's last rating",
            "interactions.timestamp", "(newest timestamp in the dataset - last_interaction_ts) / 86400; NULL if no interactions"),
    # ---- item ----
    Feature("item", "category_encoded", "INTEGER", "Item category as a category code",
            "item_features.category", "pandas category codes, alphabetical order of distinct categories (preparation step)"),
    Feature("item", "price_norm", "REAL", "Price scaled to 0-1",
            "item_features.price", "min-max scaling across items; 0 if constant (preparation step)"),
    Feature("item", "catalog_rating_norm", "REAL", "Catalog rating scaled to 0-1",
            "item_features.rating", "min-max scaling across items; 0 if constant (preparation step)"),
    Feature("item", "interaction_count", "INTEGER", "Number of ratings the item has received",
            "interactions.item_id", "count of observed interactions after de-duplication"),
    Feature("item", "popularity_norm", "REAL", "Popularity scaled to 0-1",
            "interactions.item_id", "min-max scaling of interaction_count across items"),
    Feature("item", "avg_rating", "REAL", "Average rating the item receives",
            "interactions.rating", "mean of ratings received; global mean if the item has none"),
    Feature("item", "rating_std", "REAL", "Spread of ratings the item receives",
            "interactions.rating", "sample standard deviation; 0 with fewer than 2 ratings"),
    Feature("item", "bayesian_avg_rating", "REAL", "Average rating shrunk toward the global mean",
            "interactions.rating", "(5 x global_mean + n x avg_rating) / (5 + n), n = interaction_count"),
    Feature("item", "rating_bias", "REAL", "Item quality relative to the average item",
            "interactions.rating", "avg_rating minus the global mean rating"),
    # ---- item_pair (item-item similarity) ----
    Feature("item_pair", "co_occurrence", "INTEGER", "Users who interacted with both items",
            "interactions.user_id, interactions.item_id", "count of common users for the item pair"),
    Feature("item_pair", "cosine_sim", "REAL", "Adjusted cosine similarity between two items",
            "interactions.rating, interactions.user_id", "cosine of per-user-mean-centred rating vectors; kept only if co_occurrence >= 2 and > 0"),
    Feature("item_pair", "neighbor_rank", "INTEGER", "Rank of the neighbour (1 = most similar)",
            "derived from cosine_sim", "top-20 neighbours per item ordered by cosine_sim"),
]

# Where each entity's current values live, where the versioned copy goes, and its key
ENTITIES = {
    "user": {"source": "user_feature_store", "table": "fs_user_features", "keys": ["user_id"]},
    "item": {"source": "item_feature_store", "table": "fs_item_features", "keys": ["item_id"]},
    "item_pair": {"source": "item_similarity", "table": "fs_item_similarity",
                  "keys": ["item_id", "similar_item_id"]},
}

# Named groups of features a model uses. Training and inference both ask for a set by
# name, which is what keeps the two consistent.
FEATURE_SETS = {
    "rating_prediction_v1": {
        "description": "Baseline user/item features for rating prediction and ranking",
        "user": ["gender_encoded", "occupation_encoded", "age_norm", "interaction_count",
                 "activity_frequency", "avg_rating", "rating_bias"],
        "item": ["category_encoded", "price_norm", "popularity_norm", "avg_rating",
                 "bayesian_avg_rating"],
    },
}


def features_for(entity: str) -> list:
    return [f.name for f in FEATURES if f.entity == entity]


def _check_feature_sets() -> None:
    for set_name, spec in FEATURE_SETS.items():
        for entity in ("user", "item"):
            bad = [n for n in spec[entity] if n not in features_for(entity)]
            if bad:
                raise ValueError(f"Feature set '{set_name}' uses unregistered {entity} features: {bad}")


_check_feature_sets()


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime(TS_FORMAT)


def _to_utc_str(ts) -> str:
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.strftime(TS_FORMAT)


# --------------------------------------------------------------------------- #
# Feature store
# --------------------------------------------------------------------------- #
class FeatureStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    # ---- setup -------------------------------------------------------------
    def _connect(self):
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"{self.db_path} not found. Run the pipeline first.")
        return closing(sqlite3.connect(self.db_path))

    def init(self) -> None:
        """Create the fs_* tables, check them against the registry, sync the registry."""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
            self._check_schema(conn)
            conn.execute("DELETE FROM fs_registry")
            conn.executemany(
                "INSERT INTO fs_registry (entity, feature_name, dtype, description, source, transformation) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(f.entity, f.name, f.dtype, f.description, f.source, f.transformation) for f in FEATURES],
            )
            conn.commit()

    @staticmethod
    def _check_schema(conn) -> None:
        for entity, spec in ENTITIES.items():
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({spec['table']})")}
            want = {"version_id", *spec["keys"], *features_for(entity)}
            if have != want:
                raise RuntimeError(
                    f"{spec['table']} does not match the registry. "
                    f"Missing columns: {sorted(want - have)}; unregistered columns: {sorted(have - want)}."
                )

    # ---- materialisation ---------------------------------------------------
    def _read_source(self, conn, entity: str) -> pd.DataFrame:
        spec = ENTITIES[entity]
        have = [r[1] for r in conn.execute(f"PRAGMA table_info({spec['source']})")]
        if not have:
            raise RuntimeError(f"Source table {spec['source']} not found. Run the transformation step first.")
        need = spec["keys"] + features_for(entity)
        missing = [c for c in need if c not in have]
        if missing:
            raise RuntimeError(f"{spec['source']} is missing registered columns {missing}.")
        extra = [c for c in have if c not in need and c != "computed_at"]
        if extra:
            log.warning("%s has unregistered columns %s (not versioned)", spec["source"], extra)
        return pd.read_sql_query(f"SELECT {', '.join(need)} FROM {spec['source']}", conn)

    @staticmethod
    def _content_hash(frames: dict) -> str:
        h = hashlib.sha256()
        for entity in sorted(frames):
            df = frames[entity].sort_values(ENTITIES[entity]["keys"]).reset_index(drop=True)
            df = df[sorted(df.columns)]
            h.update(entity.encode())
            h.update(",".join(df.columns).encode())
            h.update(pd.util.hash_pandas_object(df, index=False).values.tobytes())
        return h.hexdigest()

    @staticmethod
    def _transform_parameters():
        try:
            with open(TRANSFORM_SUMMARY_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("parameters")
        except (OSError, ValueError):
            return None

    def _prune(self, conn) -> int:
        keep = [r[0] for r in conn.execute(
            "SELECT version_id FROM fs_versions ORDER BY version_id DESC LIMIT ?", (RETAIN_VERSIONS,))]
        active = conn.execute("SELECT version_id FROM fs_versions WHERE is_active = 1").fetchone()
        if active and active[0] not in keep:
            keep.append(active[0])
        marks = ",".join("?" * len(keep))
        removed = conn.execute(
            f"SELECT COUNT(*) FROM fs_versions WHERE version_id NOT IN ({marks})", keep).fetchone()[0]
        for table in ("fs_user_features", "fs_item_features", "fs_item_similarity", "fs_versions"):
            conn.execute(f"DELETE FROM {table} WHERE version_id NOT IN ({marks})", keep)
        return removed

    def materialize(self, description: str = None, activate: bool = True) -> dict:
        """Snapshot the current transformation output as a new feature version.

        Does nothing if the values are identical to the newest version. Runs in one
        transaction: a failure leaves the store exactly as it was.
        """
        self.init()
        with closing(sqlite3.connect(self.db_path)) as conn:
            frames = {e: self._read_source(conn, e) for e in ENTITIES}
            if frames["user"].empty or frames["item"].empty:
                raise RuntimeError("Transformation output is empty; nothing to materialise.")

            data_hash = self._content_hash(frames)
            latest = conn.execute(
                "SELECT version_id, data_hash FROM fs_versions ORDER BY version_id DESC LIMIT 1").fetchone()
            if latest and latest[1] == data_hash:
                log.info("Features unchanged since version %d; no new version created", latest[0])
                return {"version_id": int(latest[0]), "created": False,
                        "rows": {e: int(len(df)) for e, df in frames.items()}}

            cutoff = frames["user"]["last_interaction_ts"].max()
            cutoff = None if pd.isna(cutoff) else int(cutoff)
            params = self._transform_parameters()
            try:
                if activate:
                    conn.execute("UPDATE fs_versions SET is_active = 0 WHERE is_active = 1")
                cur = conn.execute(
                    "INSERT INTO fs_versions (created_at, data_cutoff_ts, data_hash, user_rows, item_rows, "
                    "similarity_rows, parameters_json, definitions_json, description, is_active) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (_now_str(), cutoff, data_hash, len(frames["user"]), len(frames["item"]),
                     len(frames["item_pair"]), json.dumps(params) if params else None,
                     json.dumps([asdict(f) for f in FEATURES]), description, 1 if activate else 0),
                )
                version_id = cur.lastrowid
                for entity, spec in ENTITIES.items():
                    cols = ", ".join(spec["keys"] + features_for(entity))
                    conn.execute(
                        f"INSERT INTO {spec['table']} (version_id, {cols}) "
                        f"SELECT ?, {cols} FROM {spec['source']}", (version_id,))
                pruned = self._prune(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        log.info("Created feature version %d (%d users, %d items, %d similarity rows); pruned %d old version(s)",
                 version_id, len(frames["user"]), len(frames["item"]), len(frames["item_pair"]), pruned)
        return {"version_id": int(version_id), "created": True, "active": bool(activate),
                "data_cutoff_ts": cutoff, "pruned_versions": int(pruned),
                "rows": {e: int(len(df)) for e, df in frames.items()}}

    # ---- versions ----------------------------------------------------------
    def list_versions(self) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query(
                "SELECT version_id, created_at, data_cutoff_ts, user_rows, item_rows, similarity_rows, "
                "is_active, substr(data_hash, 1, 12) AS data_hash, description "
                "FROM fs_versions ORDER BY version_id", conn)

    def set_active_version(self, version: int) -> None:
        """Promote (or roll back to) a version for default / inference retrieval."""
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM fs_versions WHERE version_id = ?", (version,)).fetchone() is None:
                raise ValueError(f"Version {version} does not exist.")
            try:
                conn.execute("UPDATE fs_versions SET is_active = 0 WHERE is_active = 1")
                conn.execute("UPDATE fs_versions SET is_active = 1 WHERE version_id = ?", (version,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def resolve_version(self, conn, version=None, as_of=None) -> int:
        """version (pinned) > as_of (newest version created at or before that time) > active."""
        if version is not None and as_of is not None:
            raise ValueError("Pass either version or as_of, not both.")
        try:
            if version is not None:
                row = conn.execute("SELECT version_id FROM fs_versions WHERE version_id = ?", (int(version),)).fetchone()
                if row is None:
                    known = [r[0] for r in conn.execute("SELECT version_id FROM fs_versions ORDER BY version_id")]
                    raise ValueError(f"Version {version} does not exist. Available: {known}")
            elif as_of is not None:
                row = conn.execute("SELECT MAX(version_id) FROM fs_versions WHERE created_at <= ?",
                                   (_to_utc_str(as_of),)).fetchone()
                if row is None or row[0] is None:
                    raise ValueError(f"No feature version existed at or before {as_of}.")
            else:
                row = conn.execute("SELECT version_id FROM fs_versions WHERE is_active = 1").fetchone()
                if row is None:
                    raise ValueError("No active feature version. Run materialize() or set_active_version().")
        except sqlite3.OperationalError as exc:
            raise RuntimeError("Feature store is not initialised. Run materialize() first.") from exc
        return int(row[0])

    # ---- retrieval ---------------------------------------------------------
    @staticmethod
    def _validate_features(entity: str, features) -> list:
        known = features_for(entity)
        if features is None:
            return known
        bad = [f for f in features if f not in known]
        if bad:
            raise ValueError(f"Unknown {entity} feature(s) {bad}. Registered: {known}")
        return list(features)

    @staticmethod
    def _feature_set(name: str) -> dict:
        if name not in FEATURE_SETS:
            raise ValueError(f"Unknown feature set '{name}'. Available: {sorted(FEATURE_SETS)}")
        return FEATURE_SETS[name]

    @staticmethod
    def _fetch(conn, entity: str, ids, feats: list, version: int) -> pd.DataFrame:
        spec = ENTITIES[entity]
        key = spec["keys"][0]
        unique = list(dict.fromkeys(int(i) for i in ids))
        cols = ", ".join([key] + feats)
        frames = []
        for i in range(0, len(unique), FETCH_CHUNK):
            chunk = unique[i:i + FETCH_CHUNK]
            marks = ",".join("?" * len(chunk))
            frames.append(pd.read_sql_query(
                f"SELECT {cols} FROM {spec['table']} WHERE version_id = ? AND {key} IN ({marks})",
                conn, params=[version, *chunk]))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=[key] + feats)
        df[key] = df[key].astype("int64")
        return df

    def get_entity_features(self, entity: str, ids, features=None, version=None, as_of=None) -> pd.DataFrame:
        """Feature lookup for users or items: one row per requested id, in order.

        Unknown ids come back with NaN features (cold start). Uses the active version
        unless `version` or `as_of` is given. The version used is in `feature_version`.
        """
        if entity not in ("user", "item"):
            raise ValueError("entity must be 'user' or 'item' (use get_similar_items for item pairs).")
        feats = self._validate_features(entity, features)
        key = ENTITIES[entity]["keys"][0]
        ids = list(ids)
        with self._connect() as conn:
            v = self.resolve_version(conn, version, as_of)
            found = self._fetch(conn, entity, ids, feats, v)
        out = pd.DataFrame({key: pd.Series(ids, dtype="int64")}).merge(found, on=key, how="left")
        out["feature_version"] = v
        return out

    def get_similar_items(self, item_ids, top_k: int = 10, version=None, as_of=None) -> pd.DataFrame:
        """Top-k most similar items for each item id (co-occurrence + adjusted cosine)."""
        ids = list(dict.fromkeys(int(i) for i in item_ids))
        with self._connect() as conn:
            v = self.resolve_version(conn, version, as_of)
            frames = []
            for i in range(0, len(ids), FETCH_CHUNK):
                chunk = ids[i:i + FETCH_CHUNK]
                marks = ",".join("?" * len(chunk))
                frames.append(pd.read_sql_query(
                    f"SELECT item_id, similar_item_id, co_occurrence, cosine_sim, neighbor_rank "
                    f"FROM fs_item_similarity WHERE version_id = ? AND neighbor_rank <= ? "
                    f"AND item_id IN ({marks}) ORDER BY item_id, neighbor_rank",
                    conn, params=[v, int(top_k), *chunk]))
        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        out["feature_version"] = v
        return out

    def _attach_features(self, conn, pairs: pd.DataFrame, feature_set: str, version: int) -> pd.DataFrame:
        spec = self._feature_set(feature_set)
        users = self._fetch(conn, "user", pairs["user_id"], spec["user"], version)
        items = self._fetch(conn, "item", pairs["item_id"], spec["item"], version)
        users = users.rename(columns={c: f"user_{c}" for c in spec["user"]})
        items = items.rename(columns={c: f"item_{c}" for c in spec["item"]})
        return pairs.merge(users, on="user_id", how="left").merge(items, on="item_id", how="left")

    def get_training_dataset(self, feature_set: str, version=None, as_of=None) -> pd.DataFrame:
        """Labelled rows (user, item, rating, timestamp) joined with a feature version.

        Pin `version` for reproducible training. Only interactions up to the version's
        data cut-off are returned, so the same version always yields the same rows even
        after new data is ingested. Columns: user_*/item_* features, `feature_version`.
        """
        with self._connect() as conn:
            v = self.resolve_version(conn, version, as_of)
            cutoff = conn.execute("SELECT data_cutoff_ts FROM fs_versions WHERE version_id = ?", (v,)).fetchone()[0]
            sql = "SELECT user_id, item_id, rating, timestamp FROM interactions"
            params = []
            if cutoff is not None:
                sql += " WHERE timestamp <= ?"
                params.append(int(cutoff))
            inter = pd.read_sql_query(sql, conn, params=params)
            # same rule as the preparation step: keep the latest rating per (user, item)
            inter = (inter.sort_values("timestamp", kind="stable")
                     .drop_duplicates(subset=["user_id", "item_id"], keep="last")
                     .reset_index(drop=True))
            out = self._attach_features(conn, inter, feature_set, v)
        out["feature_version"] = v
        return out

    def get_inference_features(self, feature_set: str, user_ids, item_ids, version=None, as_of=None) -> pd.DataFrame:
        """Features for (user, candidate item) pairs at serving time. Active version by default.

        `user_ids[i]` is paired with `item_ids[i]`. Same columns as the training dataset
        (minus label columns), so a model sees identical features in both places.
        """
        user_ids, item_ids = list(user_ids), list(item_ids)
        if len(user_ids) != len(item_ids):
            raise ValueError("user_ids and item_ids must have the same length (they are paired).")
        pairs = pd.DataFrame({"user_id": pd.Series(user_ids, dtype="int64"),
                              "item_id": pd.Series(item_ids, dtype="int64")})
        with self._connect() as conn:
            v = self.resolve_version(conn, version, as_of)
            out = self._attach_features(conn, pairs, feature_set, v)
        out["feature_version"] = v
        return out


# --------------------------------------------------------------------------- #
# Pipeline entry point + documentation generator
# --------------------------------------------------------------------------- #
def materialize_feature_store() -> dict:
    """Airflow task: snapshot the latest transformation output as a feature version."""
    return FeatureStore().materialize()


def generate_metadata_doc(path: str = "feature_metadata.md") -> str:
    """Write the feature metadata documentation straight from the registry, so it cannot drift."""
    def table(entity):
        lines = ["| Feature | Type | Description | Source | Transformation |", "|---|---|---|---|---|"]
        for f in FEATURES:
            if f.entity == entity:
                lines.append(f"| `{f.name}` | {f.dtype} | {f.description} | `{f.source}` | {f.transformation} |")
        return "\n".join(lines)

    sets = []
    for name, spec in FEATURE_SETS.items():
        sets.append(f"### `{name}`\n{spec['description']}\n\n"
                    f"- user features (prefixed `user_`): {', '.join('`' + c + '`' for c in spec['user'])}\n"
                    f"- item features (prefixed `item_`): {', '.join('`' + c + '`' for c in spec['item'])}")

    doc = f"""# Feature Store: Metadata Documentation

*Generated from the registry in `feature_store.py` (`python feature_store.py docs`). Do not edit by hand.*

## 1. Architecture

```
raw tables ──> preparation ──> transformation ──> materialize ──> fs_* (versioned) ──> training / inference
(user_features,  (encode,        (user_feature_store,  (snapshot,      fs_registry            get_training_dataset()
 item_features,   normalise)      item_feature_store,   new version     fs_versions            get_inference_features()
 interactions)                    item_similarity)      if changed)                            get_entity_features()
```

| Table | Purpose |
|---|---|
| `fs_registry` | One row per feature: name, type, source, transformation (section 4) |
| `fs_versions` | One row per snapshot: creation time, data cut-off, content hash, row counts, transformation parameters, active flag |
| `fs_user_features`, `fs_item_features`, `fs_item_similarity` | Feature values, keyed by `(version_id, entity id)` |

`user_feature_store`, `item_feature_store` and `item_similarity` (from `transformation.py`) hold only the **latest**
values and are overwritten every run. The `fs_*` tables keep the history.

## 2. Versioning

- **Creating versions:** the `materialize_feature_store` pipeline task copies the latest transformation output into the `fs_*`
  tables under a new, ever-increasing `version_id`. If the values are identical to the newest version (same SHA-256 content hash),
  no new version is created, so re-running the pipeline is safe.
- **Immutability:** a version's values never change after creation.
- **Active version:** exactly one version is *active*. Inference reads it by default; `set_active_version(n)` promotes or rolls back.
  A new version becomes active automatically.
- **Retention:** the newest {RETAIN_VERSIONS} versions are kept, plus the active one.
- **Lineage:** each version records the transformation parameters and the registry definitions used to build it.

## 3. Retrieval

| Use case | Call | Version used |
|---|---|---|
| Training | `get_training_dataset(feature_set, version=N)` | pinned `N` (reproducible) |
| Training "as of" a date | `get_training_dataset(feature_set, as_of="2026-11-21T10:00:00")` | newest version created at or before that time |
| Inference (candidate scoring) | `get_inference_features(feature_set, user_ids, item_ids)` | active version |
| Single lookup | `get_entity_features("user", [7, 8], features=[...])` | active, or pinned / as-of |
| Neighbours | `get_similar_items(item_ids, top_k=10)` | active, or pinned / as-of |

- Every result has a `feature_version` column, so the version used can be logged next to model output.
- Training and inference use the **same feature set** and the same code path, so column names and values match.
- `get_training_dataset` only returns interactions up to the version's data cut-off, so a pinned version always returns the same rows.
- Unknown users or items return NaN features (cold start); they are never dropped silently.

## 4. Feature registry

### User features (`fs_user_features`, key `user_id`)
{table('user')}

### Item features (`fs_item_features`, key `item_id`)
{table('item')}

### Item-pair features (`fs_item_similarity`, key `item_id` + `similar_item_id`)
{table('item_pair')}

## 5. Feature sets

{chr(10).join(sets)}

## 6. Known limitations

- **Label leakage:** features such as `avg_rating` are computed from all ratings up to the cut-off, including the rating being
  predicted. For honest evaluation, split by time or hold out interactions and build the version only from the training part.
- **Single database file:** retrieval reads SQLite directly, which suits this project. A multi-server deployment would need a
  networked store (for example Feast with Redis).
- **Late-arriving data:** an interaction with an old timestamp ingested after a version was created would appear in that
  version's training dataset (the cut-off filters by timestamp, not by ingestion time).
"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    command = sys.argv[1] if len(sys.argv) > 1 else "materialize"
    if command == "materialize":
        print(json.dumps(materialize_feature_store(), indent=2))
    elif command == "versions":
        print(FeatureStore().list_versions().to_string(index=False))
    elif command == "docs":
        print("Wrote", generate_metadata_doc(sys.argv[2] if len(sys.argv) > 2 else "feature_metadata.md"))
    else:
        sys.exit("Usage: python feature_store.py [materialize | versions | docs [path]]")