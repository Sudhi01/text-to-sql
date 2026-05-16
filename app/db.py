"""
db.py — Unified Execution Layer
Phase 1 + Phase 2 + Phase 3 integrated
"""

import time
import psycopg2
from sqlalchemy import create_engine

from guardrails import validate_sql, check_explain_scan
from audit import log_query

# ---------------------------------------------------------------------------
# DB config
# ---------------------------------------------------------------------------

DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": 5432,
}

# ---------------------------------------------------------------------------
# SQLAlchemy engine — Phase 1 schema extractor
# ---------------------------------------------------------------------------

engine = create_engine(
    f"postgresql+psycopg2://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
    f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
)

# ---------------------------------------------------------------------------
# Main query runner — Phase 2
# ---------------------------------------------------------------------------

def run_query(sql: str, question: str = "") -> dict:
    conn = None
    cur = None

    # Step 1: Guardrail check + LIMIT injection (no DB needed)
    pre_check = validate_sql(sql, question=question)
    if not pre_check.passed:
        return {
            "status": "blocked",
            "sql": sql,
            "data": [],
            "row_count": 0,
            "execution_time": 0,
            "explain_plan": [],
            "guardrail": {
                "passed": False,
                "blocked_reason": pre_check.blocked_reason,
                "warnings": [],
            },
        }

    safe_sql = pre_check.sql

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # Step 2: Fetch EXPLAIN plan
        cur.execute(f"EXPLAIN {safe_sql}")
        explain_plan = [row[0] for row in cur.fetchall()]

        # Step 3: EXPLAIN scan check — block heavy queries
        scan_block = check_explain_scan(explain_plan)
        if scan_block:
            log_query(question, safe_sql, blocked=True, reason=scan_block)
            return {
                "status": "blocked",
                "sql": safe_sql,
                "data": [],
                "row_count": 0,
                "execution_time": 0,
                "explain_plan": explain_plan,
                "guardrail": {
                    "passed": False,
                    "blocked_reason": scan_block,
                    "warnings": [],
                },
            }

        # Step 4: Execute in read-only transaction
        start = time.time()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(safe_sql)

        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        cur.execute("ROLLBACK")

        execution_time = round(time.time() - start, 4)

        log_query(
            question, safe_sql,
            blocked=False,
            execution_time=execution_time,
            row_count=len(rows),
        )

        return {
            "status": "success",
            "sql": safe_sql,
            "data": [dict(zip(cols, row)) for row in rows],
            "row_count": len(rows),
            "execution_time": execution_time,
            "explain_plan": explain_plan,
            "guardrail": {
                "passed": True,
                "blocked_reason": None,
                "warnings": pre_check.warnings,
            },
        }

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        log_query(question, safe_sql, blocked=False, reason=str(e))
        return {
            "status": "error",
            "sql": safe_sql,
            "data": [],
            "row_count": 0,
            "execution_time": 0,
            "explain_plan": [],
            "guardrail": {
                "passed": True,
                "blocked_reason": None,
                "warnings": pre_check.warnings,
            },
            "error": str(e),
        }

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Phase 3 execute_fn — used by run_quality_checks() for multi-query validation
# ---------------------------------------------------------------------------

def execute_fn(sql: str) -> dict:
    result = run_query(sql)
    return {
        "status": result.get("status"),
        "row_count": result.get("row_count", 0),
        "sample_data": result.get("data", [])[:5],
    }