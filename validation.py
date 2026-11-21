"""Data validation task for the RecoMart pipeline.

Reads data/recomart.db (read-only), runs quality checks, writes a JSON report to
data/reports/validation.json and raises ValueError if any CRITICAL check fails,
so downstream Airflow tasks (EDA, modeling) don't run on bad data.

Severity:
  critical -> task fails
  warning  -> logged and written to the report, task still succeeds
"""
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

DB_PATH = "data/recomart.db"
REPORT_PATH = "data/reports/validation.json"

# ---- Thresholds: adjust to match your dataset ----
RATING_MIN, RATING_MAX = 0.5, 5.0   # use 1.0 / 5.0 if ratings are whole stars only
AGE_MIN, AGE_MAX = 1, 110
NULL_WARN_FRACTION = 0.05           # warn if more than 5% of an optional column is NULL
ORPHAN_CRITICAL_FRACTION = 0.05     # orphan interactions above 5% fail the task

EXPECTED_COLUMNS = {
    "user_features": {"user_id", "age", "gender", "occupation", "zip_code"},
    "item_features": {"item_id", "title", "category", "price", "rating"},
    "interactions": {"user_id", "item_id", "rating", "timestamp", "partition_date"},
}

# NULL in these columns is a critical failure; other columns only warn above the threshold
REQUIRED_NOT_NULL = {
    "user_features": ["user_id"],
    "item_features": ["item_id", "title"],
    "interactions": ["user_id", "item_id", "rating", "timestamp"],
}

NUMERIC_COLUMNS = {
    "user_features": ["user_id", "age"],
    "item_features": ["item_id", "price", "rating"],
    "interactions": ["user_id", "item_id", "rating", "timestamp"],
}


class Report:
    def __init__(self):
        self.checks = []
        self.stats = {}

    def add(self, name, passed, severity, detail=""):
        status = "pass" if passed else ("fail" if severity == "critical" else "warn")
        self.checks.append(
            {"check": name, "status": status, "severity": severity, "detail": detail}
        )
        tag = {"pass": "PASS", "fail": "FAIL", "warn": "WARN"}[status]
        print(f"[{tag}] {name}" + (f" - {detail}" if detail else ""))

    @property
    def failures(self):
        return [c for c in self.checks if c["status"] == "fail"]

    @property
    def warnings(self):
        return [c for c in self.checks if c["status"] == "warn"]


def scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


def check_structure(conn, rpt):
    """Tables exist, expected columns are present, tables are not empty."""
    ok = True
    for table, expected in EXPECTED_COLUMNS.items():
        exists = scalar(
            conn,
            f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'",
        )
        if not exists:
            rpt.add(f"{table}: table exists", False, "critical", "table not found")
            ok = False
            continue

        actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        missing = expected - actual
        rpt.add(
            f"{table}: required columns present",
            not missing,
            "critical",
            f"missing: {sorted(missing)}" if missing else "",
        )

        n = scalar(conn, f"SELECT COUNT(*) FROM {table}")
        rpt.stats[f"{table}_rows"] = n
        rpt.add(f"{table}: not empty", n > 0, "critical", f"{n} rows")
        if missing or n == 0:
            ok = False
    return ok


def check_nulls(conn, rpt):
    for table, expected in EXPECTED_COLUMNS.items():
        total = rpt.stats[f"{table}_rows"]
        for col in sorted(expected):
            nulls = scalar(conn, f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL")
            detail = f"{nulls} NULLs ({nulls / total:.1%})" if nulls else ""
            if col in REQUIRED_NOT_NULL[table]:
                rpt.add(f"{table}.{col}: no NULLs", nulls == 0, "critical", detail)
            else:
                rpt.add(
                    f"{table}.{col}: NULLs <= {NULL_WARN_FRACTION:.0%}",
                    nulls / total <= NULL_WARN_FRACTION,
                    "warning",
                    detail,
                )


def check_types(conn, rpt):
    """Numeric columns must hold numbers (SQLite lets text slip into numeric columns)."""
    for table, cols in NUMERIC_COLUMNS.items():
        for col in cols:
            bad = scalar(
                conn,
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE typeof({col}) NOT IN ('integer', 'real', 'null')",
            )
            rpt.add(
                f"{table}.{col}: numeric values only",
                bad == 0,
                "critical",
                f"{bad} non-numeric values" if bad else "",
            )


def check_range(conn, rpt, table, col, lo, hi, severity):
    conds = []
    if lo is not None:
        conds.append(f"{col} < {lo}")
    if hi is not None:
        conds.append(f"{col} > {hi}")
    cond = " OR ".join(conds)
    bad = scalar(
        conn, f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND ({cond})"
    )
    rpt.add(
        f"{table}.{col}: within [{lo}, {hi}]",
        bad == 0,
        severity,
        f"{bad} rows out of range" if bad else "",
    )


def check_ranges(conn, rpt):
    check_range(conn, rpt, "interactions", "rating", RATING_MIN, RATING_MAX, "critical")
    check_range(conn, rpt, "interactions", "timestamp", 1, None, "critical")
    check_range(conn, rpt, "user_features", "age", AGE_MIN, AGE_MAX, "warning")
    check_range(conn, rpt, "item_features", "price", 0, None, "critical")
    check_range(conn, rpt, "item_features", "rating", 0, RATING_MAX, "warning")

    # Timestamps in the future (also catches milliseconds stored instead of seconds)
    future = scalar(
        conn,
        f"SELECT COUNT(*) FROM interactions WHERE timestamp > {int(time.time()) + 86400}",
    )
    rpt.add(
        "interactions.timestamp: not in the future",
        future == 0,
        "warning",
        f"{future} rows in the future" if future else "",
    )


def check_duplicates(conn, rpt):
    # (user_id, item_id, timestamp) is UNIQUE in the schema, so check the looser pair
    repeats = scalar(
        conn,
        "SELECT COUNT(*) FROM ("
        "SELECT 1 FROM interactions GROUP BY user_id, item_id HAVING COUNT(*) > 1)",
    )
    rpt.add(
        "interactions: one rating per (user, item)",
        repeats == 0,
        "warning",
        f"{repeats} user-item pairs rated more than once" if repeats else "",
    )


def check_orphans(conn, rpt):
    """Foreign keys are not enforced by SQLite, so check them here."""
    total = rpt.stats["interactions_rows"]
    for col, parent in (("user_id", "user_features"), ("item_id", "item_features")):
        orphans = scalar(
            conn,
            f"SELECT COUNT(*) FROM interactions "
            f"WHERE {col} NOT IN (SELECT {col} FROM {parent})",
        )
        frac = orphans / total
        severity = "critical" if frac > ORPHAN_CRITICAL_FRACTION else "warning"
        rpt.add(
            f"interactions.{col}: exists in {parent}",
            orphans == 0,
            severity,
            f"{orphans} orphan rows ({frac:.1%})" if orphans else "",
        )


def collect_stats(conn, rpt):
    users = rpt.stats["user_features_rows"]
    items = rpt.stats["item_features_rows"]
    inter = rpt.stats["interactions_rows"]
    rpt.stats["sparsity"] = round(1 - inter / (users * items), 6)
    rpt.stats["avg_interactions_per_user"] = round(inter / users, 2)
    rpt.stats["users_without_interactions"] = scalar(
        conn,
        "SELECT COUNT(*) FROM user_features "
        "WHERE user_id NOT IN (SELECT DISTINCT user_id FROM interactions)",
    )
    rpt.stats["items_without_interactions"] = scalar(
        conn,
        "SELECT COUNT(*) FROM item_features "
        "WHERE item_id NOT IN (SELECT DISTINCT item_id FROM interactions)",
    )
    rpt.stats["partitions_loaded"] = scalar(
        conn, "SELECT COUNT(DISTINCT partition_date) FROM interactions"
    )


def validate_data():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"{DB_PATH} not found - did the ingest task run?")

    rpt = Report()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)  # read-only
    try:
        print("[INFO] Starting data validation...")
        if check_structure(conn, rpt):  # later checks need the tables and columns
            check_nulls(conn, rpt)
            check_types(conn, rpt)
            check_ranges(conn, rpt)
            check_duplicates(conn, rpt)
            check_orphans(conn, rpt)
            collect_stats(conn, rpt)
    finally:
        conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": DB_PATH,
        "passed": not rpt.failures,
        "critical_failures": len(rpt.failures),
        "warnings": len(rpt.warnings),
        "stats": rpt.stats,
        "checks": rpt.checks,
    }
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"[INFO] Stats: {rpt.stats}")
    print(
        f"[INFO] Validation finished: {len(rpt.failures)} critical failures, "
        f"{len(rpt.warnings)} warnings. Report: {REPORT_PATH}"
    )

    if rpt.failures:
        names = "; ".join(c["check"] for c in rpt.failures)
        raise ValueError(f"Data validation failed: {names}")

    return {"passed": True, "warnings": len(rpt.warnings)}


if __name__ == "__main__":
    validate_data()