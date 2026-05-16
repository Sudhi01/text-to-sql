"""
Phase 2 - Guardrail Configuration
All guardrail rules in one place — easy to tune without touching logic.
"""

# Maximum rows a query is allowed to return
ROW_LIMIT = 1000

# Maximum estimated rows a query is allowed to SCAN (from EXPLAIN)
MAX_SCAN_ROWS = 100_000

# Maximum depth of nested subqueries allowed
MAX_SUBQUERY_DEPTH = 3

# Keywords that must never appear in a query
FORBIDDEN_KEYWORDS = [
    "drop", "delete", "insert", "update", "alter",
    "create", "truncate", "grant", "revoke", "execute",
    "exec", "xp_", "sp_",
]

# Audit log file path
AUDIT_LOG_PATH = "audit.log"