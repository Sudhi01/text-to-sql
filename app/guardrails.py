"""
Phase 2 - Enterprise Guardrail Middleware
Replaces the old string-based guardrails.py with:
  1. sqlparse AST-based validation (not just string matching)
  2. Automatic LIMIT injection
  3. Subquery depth check
  4. EXPLAIN-based row scan estimation + blocking
  5. Audit logging of every query (passed or blocked)
  6. Standardized response format
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import sqlparse
from sqlparse.sql import Statement, Where, Parenthesis
from sqlparse.tokens import Keyword, DDL, DML

from app.config import (ROW_LIMIT, MAX_SCAN_ROWS, MAX_SUBQUERY_DEPTH, FORBIDDEN_KEYWORDS)
from app.audit import log_query

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------

@dataclass
class GuardrailResult:
    passed: bool
    sql: str                        # possibly rewritten (LIMIT injected)
    blocked_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. sqlparse AST-based keyword check
# ---------------------------------------------------------------------------

def _check_forbidden_keywords_ast(sql: str) -> Optional[str]:
    """
    Use sqlparse token types to detect DDL/DML keywords.
    More reliable than string matching — won't be fooled by
    keywords inside column names or string literals.
    """
    parsed = sqlparse.parse(sql)
    if not parsed:
        return "Could not parse SQL"

    for statement in parsed:
        for token in statement.flatten():
            token_val = token.value.lower()
            # Block DDL (CREATE, DROP, ALTER etc.)
            if token.ttype is DDL:
                return f"DDL statement not allowed: {token.value}"
            # Block DML writes (INSERT, UPDATE, DELETE)
            if token.ttype is DML and token_val in ("insert", "update", "delete"):
                return f"Write operation not allowed: {token.value}"
            # Block additional forbidden keywords
            if token.ttype in (Keyword, DDL, DML) and token_val in FORBIDDEN_KEYWORDS:
                return f"Blocked keyword: {token.value}"

    return None


# ---------------------------------------------------------------------------
# 2. Must start with SELECT
# ---------------------------------------------------------------------------

def _check_select_only(sql: str) -> Optional[str]:
    clean = sql.strip().lstrip("(").strip().lower()
    if not clean.startswith("select"):
        return "Only SELECT queries are allowed"
    return None


# ---------------------------------------------------------------------------
# 3. Block multiple statements
# ---------------------------------------------------------------------------

def _check_single_statement(sql: str) -> Optional[str]:
    statements = [s for s in sqlparse.parse(sql) if s.get_type() is not None]
    if len(statements) > 1:
        return "Multiple SQL statements are not allowed"
    # Also catch semicolon-separated injection
    clean = sql.strip().rstrip(";")
    if ";" in clean:
        return "Multiple statements detected via semicolon injection"
    return None


# ---------------------------------------------------------------------------
# 4. Block comment injection
# ---------------------------------------------------------------------------

def _check_comments(sql: str) -> Optional[str]:
    if "--" in sql or "/*" in sql:
        return "SQL comments are not allowed"
    return None


# ---------------------------------------------------------------------------
# 5. Subquery depth check
# ---------------------------------------------------------------------------

def _subquery_depth(sql: str) -> int:
    """Count maximum nesting depth of subqueries via parenthesis counting."""
    max_depth = 0
    depth = 0
    for char in sql:
        if char == "(":
            depth += 1
            max_depth = max(max_depth, depth)
        elif char == ")":
            depth -= 1
    return max_depth


def _check_subquery_depth(sql: str) -> Optional[str]:
    depth = _subquery_depth(sql)
    if depth > MAX_SUBQUERY_DEPTH:
        return f"Subquery depth {depth} exceeds maximum allowed ({MAX_SUBQUERY_DEPTH})"
    return None


# ---------------------------------------------------------------------------
# 6. LIMIT injection
# ---------------------------------------------------------------------------

def _has_limit(sql: str) -> bool:
    return bool(re.search(r"\blimit\b", sql, re.IGNORECASE))


def _inject_limit(sql: str) -> str:
    """Add LIMIT if not already present. Strips trailing semicolon first."""
    sql = sql.rstrip(";").strip()
    if not _has_limit(sql):
        sql = f"{sql} LIMIT {ROW_LIMIT}"
    return sql


# ---------------------------------------------------------------------------
# 7. EXPLAIN-based row scan estimation
# ---------------------------------------------------------------------------

def _parse_explain_rows(explain_plan: List[str]) -> int:
    """
    Extract the maximum estimated row scan from a PostgreSQL EXPLAIN output.
    Looks for patterns like: (cost=... rows=1570 ...)
    Returns the highest rows= value found across all plan nodes.
    """
    max_rows = 0
    for line in explain_plan:
        matches = re.findall(r"rows=(\d+)", line)
        for m in matches:
            max_rows = max(max_rows, int(m))
    return max_rows


def check_explain_scan(explain_plan: List[str]) -> Optional[str]:
    """
    Parse EXPLAIN output and block query if estimated scan exceeds MAX_SCAN_ROWS.
    Call this AFTER running EXPLAIN but BEFORE running the actual query.
    """
    if not explain_plan:
        return None

    estimated_rows = _parse_explain_rows(explain_plan)
    if estimated_rows > MAX_SCAN_ROWS:
        return (
            f"Query estimated to scan {estimated_rows:,} rows "
            f"(limit: {MAX_SCAN_ROWS:,}). Query blocked."
        )
    return None


# ---------------------------------------------------------------------------
# 8. SQL syntax validation via sqlparse
# ---------------------------------------------------------------------------

def _check_syntax(sql: str) -> Optional[str]:
    """Basic syntax check — ensures sqlparse can parse it and finds a FROM clause."""
    try:
        parsed = sqlparse.parse(sql)
        if not parsed or not parsed[0].tokens:
            return "SQL could not be parsed"
        # Must have FROM
        flat = sql.strip().lower()
        if "from" not in flat:
            return "Invalid SQL: missing FROM clause"
    except Exception as e:
        return f"SQL parse error: {e}"
    return None


# ---------------------------------------------------------------------------
# 9. Central guardrail validator
# ---------------------------------------------------------------------------

def validate_sql(
    sql: str,
    question: str = "",
    explain_plan: Optional[List[str]] = None,
) -> GuardrailResult:
    """
    Run all guardrail checks in order. Returns GuardrailResult.

    Args:
        sql          : The SQL string to validate.
        question     : Original user question (for audit logging).
        explain_plan : EXPLAIN output lines (for scan estimation).
                       Pass this after fetching EXPLAIN but before executing.

    Checks run in order — first failure blocks the query:
        1. Empty SQL
        2. Single statement only
        3. Comment injection
        4. SELECT only
        5. AST-based forbidden keyword check
        6. Subquery depth
        7. Syntax validation
        8. EXPLAIN scan estimation (if explain_plan provided)

    Then rewrites:
        9. LIMIT injection (if no LIMIT present)
    """
    original_sql = sql

    # -- 1. Empty --
    if not sql or not sql.strip():
        reason = "Empty SQL"
        log_query(question, sql, blocked=True, reason=reason)
        return GuardrailResult(passed=False, sql=sql, blocked_reason=reason)

    sql = sql.strip().rstrip(";")

    # -- 2. Single statement --
    reason = _check_single_statement(sql)
    if reason:
        log_query(question, sql, blocked=True, reason=reason)
        return GuardrailResult(passed=False, sql=sql, blocked_reason=reason)

    # -- 3. Comment injection --
    reason = _check_comments(sql)
    if reason:
        log_query(question, sql, blocked=True, reason=reason)
        return GuardrailResult(passed=False, sql=sql, blocked_reason=reason)

    # -- 4. SELECT only --
    reason = _check_select_only(sql)
    if reason:
        log_query(question, sql, blocked=True, reason=reason)
        return GuardrailResult(passed=False, sql=sql, blocked_reason=reason)

    # -- 5. AST keyword check --
    reason = _check_forbidden_keywords_ast(sql)
    if reason:
        log_query(question, sql, blocked=True, reason=reason)
        return GuardrailResult(passed=False, sql=sql, blocked_reason=reason)

    # -- 6. Subquery depth --
    reason = _check_subquery_depth(sql)
    if reason:
        log_query(question, sql, blocked=True, reason=reason)
        return GuardrailResult(passed=False, sql=sql, blocked_reason=reason)

    # -- 7. Syntax --
    reason = _check_syntax(sql)
    if reason:
        log_query(question, sql, blocked=True, reason=reason)
        return GuardrailResult(passed=False, sql=sql, blocked_reason=reason)

    # -- 8. EXPLAIN scan estimation --
    warnings = []
    if explain_plan:
        reason = check_explain_scan(explain_plan)
        if reason:
            log_query(question, sql, blocked=True, reason=reason)
            return GuardrailResult(passed=False, sql=sql, blocked_reason=reason)

    # -- 9. LIMIT injection --
    if not _has_limit(sql):
        sql = _inject_limit(sql)
        warnings.append(f"LIMIT {ROW_LIMIT} automatically applied")

    log_query(question, sql, blocked=False, reason=None)
    return GuardrailResult(passed=True, sql=sql, warnings=warnings)